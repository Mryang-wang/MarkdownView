"""Real WebEngine regression: rail, bilingual reader, cancellation and themed dialogs."""
import json
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.translation import TranslationConfig, save_config
from app.translation_dialog import PromptDialog, TranslationSettingsDialog
from app.workspace_dialogs import PreferencesDialog, NavigateDialog, TemplateDialog
from app.recovery_dialog import RecoveryDialog
from test_translation import Provider, wait


def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewTranslationUITest'); app.setApplicationName('isolated')
        QSettings().clear()
        image = QImage(60, 30, QImage.Format.Format_RGB32); image.fill(QColor('#879a7c')); image.save(str(root / 'image.png'))
        source = '# Hello world\n\nHello **world** and $x^2$.\n\n> Hello world\n\n- Hello\n- world\n\n| Hello | world |\n| --- | --- |\n| Hello | world |\n\n```python\nprint("Hello world")\n```\n\n$$x^2+y^2=z^2$$\n\n![Hello](image.png)\n\nHello [world][ref]\n\n[ref]: https://example.org/\n'
        file = root / 'reading.md'; file.write_text(source, encoding='utf8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start(); Provider.mode = 'json'; Provider.requests = []; Provider.fail_at = 0
        save_config(TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'Local test fixture', 'test-key', chunk_size=1000))
        win = MainWindow(startup_file=str(file)); win.resize(1260, 850); win.show()
        output = Path('tmp/translation-ui'); output.mkdir(parents=True, exist_ok=True)

        def ev(code, tab=None):
            values = []; loop = QEventLoop(); tab = tab or win.current_tab()
            tab.view.page().runJavaScript('JSON.stringify((()=>{' + code + '})())', lambda v:(values.append(v), loop.quit()))
            QTimer.singleShot(6000, loop.quit); loop.exec()
            assert values and values[0], code
            return json.loads(values[0])

        def settled():
            wait(lambda: getattr(win.current_tab(), 'translation', None) and win.current_tab().translation.job is not None)
            controller = win.current_tab().translation
            wait(lambda: controller.job.state != 'running', 40); controller.refresh(); QTest.qWait(300)
            assert controller.job.state == 'complete', controller.job.error
            return controller

        try:
            wait(lambda: win.current_tab().ready); QTest.qWait(250)
            tab = win.current_tab(); before = ev('return currentMarkdown();')
            ev('''const n = Array.from(document.querySelectorAll('.vditor-ir strong')).find(n=>n.textContent==='world');
               const r=document.createRange();r.selectNodeContents(n);getSelection().removeAllRanges();getSelection().addRange(r);
               window.requestTranslation(); return true;''')
            controller = settled()
            assert controller.mode == 'selection' and '**world**' in controller.snapshot['selection']
            assert ev('return !document.getElementById("mdv-translation-panel").hidden && document.getElementById("mdv-translation-reader").hidden;')
            assert ev('return document.querySelector(".translation-result").textContent;').strip() == '世界'
            assert not any(isinstance(w, QDialog) and w.isVisible() for w in app.topLevelWidgets())
            assert ev('return currentMarkdown();') == before and not tab.dirty
            win.grab().save(str(output / 'selection-light.png'))
            # A different selection updates the same rail rather than retaining stale text.
            ev('''const n=document.querySelector('.vditor-ir h1');const r=document.createRange();r.selectNodeContents(n);
               getSelection().removeAllRanges();getSelection().addRange(r);window.requestTranslation();return true;''')
            QTest.qWait(100); controller = settled(); assert 'Hello' in controller.snapshot['selection']
            win.open_translation(tab, 'full'); QTest.qWait(100); controller = settled()
            assert ev('return !document.getElementById("mdv-translation-reader").hidden && !document.getElementById("vditor").inert && document.documentElement.classList.contains("mdv-translation-editing");')
            assert ev('return document.querySelectorAll(".translation-pair").length;') >= 8
            assert ev('return parseFloat(getComputedStyle(document.querySelector(".translation-pair")).marginBottom) >= 12;')
            assert ev('return document.querySelector(".translation-rendered h1").textContent;') == '你好 世界'
            assert ev('return document.querySelectorAll(".translation-rendered table").length;') == 1
            assert ev('return document.querySelectorAll(".translation-original .katex").length;') >= 2
            assert ev('return Array.from(document.querySelectorAll(".translation-original img")).every(n=>n.complete && n.naturalWidth>0);')
            assert ev('return currentMarkdown();') == before and not tab.dirty
            assert file.read_text(encoding='utf8') == source
            win.grab().save(str(output / 'immersive-light.png'))
            ev('document.querySelector(".translation-view").value="translated";document.querySelector(".translation-view").onchange();return true;')
            assert ev('return getComputedStyle(document.querySelector(".translation-original")).display;') == 'none'
            # Tab isolation and cancellation/resume leave the source untouched.
            other = win.new_tab(); wait(lambda: other.ready)
            assert ev('return document.getElementById("mdv-translation-reader").hidden;')
            win.tabs.setCurrentWidget(tab.view); assert ev('return !document.getElementById("mdv-translation-reader").hidden;')
            Provider.mode = 'slow'; controller.action('reset', {}); controller.action('start', {})
            wait(lambda: controller.job.state == 'running'); controller.action('exit', {}); QTest.qWait(100)
            assert controller.job.state == 'cancelled'
            assert ev('return document.getElementById("mdv-translation-reader").hidden && !document.getElementById("vditor").inert;')
            Provider.mode = 'json'; win.open_translation(tab, 'full'); QTest.qWait(100); controller.action('start', {}); settled()
            assert ev('return currentMarkdown();') == before
            # A later request can fail; a resume retains validated chunks and alignment.
            Provider.requests = []; Provider.fail_at = 2
            controller.open({'full': before * 6, 'selection': ''}, 'full')
            wait(lambda: controller.job.state == 'failed'); assert controller.job.parts
            completed = list(controller.job.parts); Provider.fail_at = 0
            controller.action('start', {}); settled()
            assert controller.job.parts[:len(completed)] == completed
            assert ev('return document.querySelectorAll(".translation-rendered h1").length;') == 6
            win.open_translation(tab, 'full'); QTest.qWait(100); settled()
            ev('window.showReview(true);return true;'); assert ev('return document.getElementById("mdv-translation-panel").hidden;')
            # Finished hidden readers can be discarded by the existing editor cache.
            ev('window.showReview(false);return true;')
            for index in range(6):
                extra = root / f'cache-{index}.md'; extra.write_text('# Cache\n', encoding='utf8')
                cache_tab = win.open_file(str(extra)); wait(lambda: cache_tab.ready); QTest.qWait(40)
            win._trim_reading_editors(); wait(lambda: tab.parked)
            win.tabs.setCurrentWidget(tab.view); wait(lambda: tab.ready); QTest.qWait(100)
            win.open_translation(tab, 'full'); QTest.qWait(100)
            assert ev('return document.querySelector(".translation-rendered h1").textContent;') == '你好 世界'
            win.toggle_theme(); QTest.qWait(150); win.grab().save(str(output / 'immersive-dark.png'))
            win.resize(780, 650); QTest.qWait(150)
            assert ev('return document.querySelector(".translation-panel").getBoundingClientRect().right <= innerWidth;')
            win.grab().save(str(output / 'immersive-narrow.png'))
            win.set_language('en'); QTest.qWait(150)
            assert ev('return document.querySelector(".translation-reader-bar strong").textContent;') == 'Full-document translation'
            assert ev('return document.querySelector(".translation-rendered h1").textContent;') == '你好 世界'
            win.grab().save(str(output / 'immersive-english.png'))
            win.resize(1260, 850)
            for theme in ('dark', 'light'):
                if win._theme != theme: win.toggle_theme()
                dialogs = [TranslationSettingsDialog(win, theme), PromptDialog(win, 'Test', 'Translate to {target_language}', theme),
                           PreferencesDialog(win), NavigateDialog(win, 'commands'), TemplateDialog(win), RecoveryDialog(win, [])]
                for i, dialog in enumerate(dialogs):
                    dialog.show(); QTest.qWait(70)
                    assert dialog.property('appChrome') and dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
                    assert dialog.frameGeometry().height() <= dialog.screen().availableGeometry().height()
                    if i < 3: dialog.grab().save(str(output / f'dialog-{theme}-{i}.png'))
                    dialog.close(); dialog.deleteLater()
                for i, dialog in enumerate((QMessageBox(win), QInputDialog(win), QFileDialog(win))):
                    dialog.setWindowTitle('Test'); dialog.show(); QTest.qWait(50)
                    assert 'border-radius: 7px' in dialog.styleSheet()
                    dialog.grab().save(str(output / f'common-{theme}-{i}.png')); dialog.close(); dialog.deleteLater()
            print('PASS selection rail, no workbench, updated selection, bilingual blocks/math/table/images, source preservation, tabs, cancel/resume, themes, responsive layout, locales and dialog chrome')
        finally:
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(120); QSettings().clear(); server.shutdown(); server.server_close()


if __name__ == '__main__': run()
