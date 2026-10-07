"""Shared language dropdowns: request values, custom languages and manual starts."""
import json
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.translation import TranslationConfig, save_config
from test_translation import Provider, wait


def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewTranslationLanguagesTest'); app.setApplicationName('isolated')
        QSettings().clear()
        source = '# Hello world\n\nHello world. The formula is $x^2$.\n'
        path = root / 'source.md'; path.write_text(source, encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        Provider.mode = 'json'; Provider.requests = []; Provider.fail_at = 0
        save_config(TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'Language UI fixture', 'fake-key'))
        win = MainWindow(startup_file=str(path)); win.resize(1400, 850); win.show()
        output = Path('tmp/translation-languages'); output.mkdir(parents=True, exist_ok=True)

        def ev(code):
            result = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((()=>{' + code + '})())', lambda v: (result.append(v), loop.quit()))
            QTimer.singleShot(5000, loop.quit); loop.exec()
            assert result and result[0], code
            return json.loads(result[0])

        def choose(surface, role, value):
            selector = f'{surface} [data-translation-language={role}]'
            ev('const s=document.querySelector(' + json.dumps(selector) + ');s.value=' + json.dumps(value) + ';s.dispatchEvent(new Event("change"));return true;')
            QTest.qWait(80)

        def start(full=False):
            selector = '[data-translation-action=toggle]' if full else '.translation-actions .primary'
            ev('document.querySelector(' + json.dumps(selector) + ').click();return true;')
            wait(lambda: controller.job and controller.job.state == 'complete'); QTest.qWait(120)
            return json.loads(Provider.requests[-1]['messages'][-1]['content'])

        try:
            wait(lambda: win.current_tab().ready); QTest.qWait(150)
            win.open_translation(win.current_tab(), 'full')
            wait(lambda: getattr(win.current_tab(), 'translation', None) and win.current_tab().translation.job)
            controller = win.current_tab().translation
            wait(lambda: controller.job.state == 'complete')
            before = ev('return currentMarkdown();')
            controller.open({'full': before, 'selection': 'Hello world.'}, 'selection')
            wait(lambda: controller.job.state == 'complete'); QTest.qWait(150)
            options = ev('return Array.from(document.querySelectorAll("[data-translation-language]")).map(s=>({role:s.dataset.translationLanguage,values:Array.from(s.options).map(o=>o.value)}));')
            assert len(options) == 4
            for role, count in (('source', 32), ('target', 31)):
                a, b = [o['values'] for o in options if o['role'] == role]
                assert a == b and len(a) == count and len(set(a)) == count
                assert ('auto detect' in a) == (role == 'source')
            assert not ev('return !!document.querySelector("[data-target-language],.translation-language-shortcuts,datalist#mdv-translation-languages");')
            count = len(Provider.requests)
            choose('.translation-panel', 'target', 'English')
            assert controller.job is None and len(Provider.requests) == count
            assert ev('return document.querySelector(".translation-reader-bar [data-translation-language=target]").value;') == 'English'
            payload = start(); assert payload['target_language'] == 'English' and payload['source_language'] == 'auto detect'
            win.grab().save(str(output / 'selection-light.png'))
            win.open_translation(win.current_tab(), 'full'); wait(lambda: controller.job and controller.job.state == 'complete'); QTest.qWait(150)
            count = len(Provider.requests)
            choose('.translation-reader-bar', 'source', 'Français')
            choose('.translation-reader-bar', 'target', 'Deutsch')
            assert len(Provider.requests) == count
            assert ev('return document.querySelector(".translation-panel [data-translation-language=source]").value;') == 'Français'
            payload = start(True); assert payload['source_language'] == 'Français' and payload['target_language'] == 'Deutsch'
            win.grab().save(str(output / 'full-light.png'))
            # A custom choice is mirrored and survives native settings refresh.
            for role, value in (('source', 'Latin'), ('target', 'Esperanto')):
                choose('.translation-reader-bar', role, '__custom__')
                ev('const s=document.querySelector(".translation-reader-bar [data-translation-language=' + role + ']");const i=s.parentElement.querySelector("input");i.value=' + json.dumps(value) + ';i.dispatchEvent(new Event("change"));return true;')
                QTest.qWait(50)
            controller.send('settings', controller.settings()); QTest.qWait(100)
            assert ev('return Array.from(document.querySelectorAll("[data-translation-language=target]")).every(s=>s.value==="__custom__"&&s.parentElement.querySelector("input").value==="Esperanto"&&!s.parentElement.querySelector("input").hidden);')
            payload = start(True); assert payload['source_language'] == 'Latin' and payload['target_language'] == 'Esperanto'
            assert QSettings().value('translation/target') == 'Esperanto'
            # Language changes stop an active request but do not start a new one.
            Provider.mode = 'slow'; controller.action('start', {})
            wait(lambda: controller.job.state == 'running' and controller.job.request.reply is not None)
            old_job = controller.job; count = len(Provider.requests)
            choose('.translation-reader-bar', 'target', '日本語'); QTest.qWait(250)
            assert old_job.state == 'cancelled' and controller.job is None
            assert len(Provider.requests) <= count + 1
            # Selecting a built-in language hides old custom inputs on both surfaces.
            choose('.translation-reader-bar', 'source', 'auto detect')
            Provider.mode = 'json'; payload = start(True)
            assert payload['source_language'] == 'auto detect' and payload['target_language'] == '日本語'
            assert ev('return Array.from(document.querySelectorAll(".translation-field input")).every(i=>i.hidden);')
            win.set_language('en'); QTest.qWait(120)
            assert ev('return document.querySelector(".translation-reader-bar [data-translation-language=target]").selectedOptions[0].textContent;') == 'Japanese'
            win.grab().save(str(output / 'full-english.png'))
            win.set_language('zh_CN'); win.toggle_theme(); QTest.qWait(150)
            win.grab().save(str(output / 'full-dark.png'))
            win.resize(780, 650); QTest.qWait(150)
            assert ev('return Array.from(document.querySelectorAll(".translation-reader-bar [data-translation-language]")).every(s=>{const r=s.getBoundingClientRect();return r.width>50&&r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;});')
            win.grab().save(str(output / 'full-narrow.png'))
            assert not ev('return window.__err;') and ev('return currentMarkdown();') == before
            assert path.read_text(encoding='utf-8') == source and not win.current_tab().dirty
            print('PASS shared 30-language dropdowns, no duplicated target shortcuts, auto/custom languages, actual request values, manual starts, cancellation, persistence, locales/themes/responsive layout and source preservation')
        finally:
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(100); QSettings().clear(); server.shutdown(); server.server_close()


if __name__ == '__main__': run()
