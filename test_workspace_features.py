"""Real Qt/WebEngine integration for the new local workflow and translation UI."""
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.translation import TranslationConfig, save_config
from app.translation_dialog import PromptDialog, load_prompts
from app.workspace_dialogs import CompareDialog, NavigateDialog, PreferencesDialog, TemplateDialog
from test_translation import Provider, wait


def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewWorkspaceFeatureTest'); app.setApplicationName('isolated')
        QSettings().clear()
        file = root / 'source.md'; file.write_text('# Hello\n\nHello **world** and $x^2$.\n\n- [ ] task\n', encoding='utf8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start(); Provider.mode = 'json'
        save_config(TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'fixture', 'test-key'))
        win = MainWindow(startup_file=str(file)); win.resize(1100, 780); win.show()
        output = Path('tmp/new-features'); output.mkdir(parents=True, exist_ok=True)

        def ev(code, tab=None):
            result = []; loop = QEventLoop(); tab = tab or win.current_tab()
            tab.view.page().runJavaScript('JSON.stringify((function(){try{' + code + '}catch(e){return {testError:String(e)};}})())', lambda v:(result.append(v), loop.quit()))
            QTimer.singleShot(8000, loop.quit); loop.exec()
            assert result and result[0], code
            data = json.loads(result[0]); assert not isinstance(data, dict) or 'testError' not in data, data
            return data

        try:
            wait(lambda: win.current_tab().ready); QTest.qWait(300)
            original = ev('return window.currentMarkdown();')
            win.features.set_readonly(True)
            assert ev('return window.mdvReadOnly && document.querySelector(".vditor-ir pre").contentEditable === "false";')
            ev("window.insertSnippet('UNWANTED'); return true;")
            assert ev('return window.currentMarkdown();') == original
            win.features.set_readonly(False)
            win.features.set_lightweight(True); QTest.qWait(150)
            assert ev('return window.mdvLightweight && document.querySelector(".vditor-sv").getBoundingClientRect().height > 0;')
            win.features.set_lightweight(False); QTest.qWait(150)
            win.features.set_focus(True); assert not win.sidebar.isVisible()
            assert ev('return document.documentElement.classList.contains("mdv-focus");')
            win.features.set_focus(False)
            prefs = PreferencesDialog(win); prefs.fields['size'].setValue(18); prefs.fields['line'].setValue(2.1); prefs._save()
            win.features.apply(win.current_tab()); QTest.qWait(50)
            assert ev('return getComputedStyle(document.querySelector(".vditor-ir pre")).fontSize;') == '18px'
            prefs.show(); QTest.qWait(80); prefs.grab().save(str(output / 'reading-settings.png')); prefs.close()
            template = TemplateDialog(win); template.name.setText('My template'); template.body.setPlainText('# Plan\n\n{date}'); template._save()
            assert 'My template' in [template.selector.itemData(i) for i in range(template.selector.count())]
            assert '{date}' not in template.content(); template.close()
            prompt = PromptDialog(win, '我的专业提示词', 'Use exact engineering terminology in {target_language}.', 'light'); prompt._save()
            assert 'engineering' in load_prompts()['我的专业提示词']; prompt.close()
            win.open_project_folder(str(root))
            nav = NavigateDialog(win, 'search'); nav.query.setText('Hello'); nav.debounce.stop(); nav.search()
            wait(lambda: not nav.poll.isActive()); assert nav.results.count() == 2
            nav.grab().save(str(output / 'search.png'))
            nav.results.setCurrentRow(1); nav._open(); QTest.qWait(150)
            assert 'Hello' in ev('return getSelection().toString();'), ev('return document.querySelector(".vditor-sv").innerHTML.slice(0,2200);')
            nav.close()
            commands = NavigateDialog(win, 'commands'); commands.query.setText('翻译'); commands.debounce.stop(); commands.search()
            assert commands.results.count() >= 2; commands.close()
            for mode in ('sv', 'wysiwyg', 'ir'):
                ev("document.querySelector('[data-mode=" + mode + "]').click(); return true;"); QTest.qWait(200)
                # Select the text inside bold markup to check partial selection fidelity.
                selected = ev('''var root=Array.from(document.querySelectorAll('#vditor [contenteditable=true]')).find(e=>e.getBoundingClientRect().height>0);
                    var walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),node;
                    while(walk.nextNode()){if(walk.currentNode.nodeValue.indexOf('world')>=0){node=walk.currentNode;break;}}
                    var at=node.nodeValue.indexOf('world'),range=document.createRange();range.setStart(node,at);range.setEnd(node,at+5);
                    getSelection().removeAllRanges();getSelection().addRange(range);return window.translationSource();''')
                assert 'world' in selected['selection'], (mode, selected)
                if mode != 'sv': assert '**world**' in selected['selection'], (mode, selected, ev('return getSelection().anchorNode.parentElement.parentElement.outerHTML;'))
            source_tab = win.current_tab()
            before = ev('return window.currentMarkdown();')
            QTest.keyClick(win.view.focusProxy(), Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            wait(lambda: getattr(source_tab, 'translation', None) is not None)
            translator = source_tab.translation; assert translator.mode == 'selection'
            wait(lambda: translator.job and translator.job.state != 'running')
            translator.options['prompt'] = '我的专业提示词'
            win.open_translation(source_tab, 'full'); QTest.qWait(150)
            wait(lambda: translator.job.state != 'running', 30); translator.refresh()
            assert translator.job.state == 'complete', translator.job.error
            assert ev('return window.currentMarkdown();', source_tab) == before
            assert 'engineering' in Provider.requests[-1]['messages'][0]['content']
            win.grab().save(str(output / 'translation-complete.png'))
            translator.action('open', {}); new_tab = win.current_tab(); wait(lambda: new_tab.ready)
            assert new_tab is not source_tab and new_tab.dirty and not new_tab.filepath
            assert '你好' in ev('return window.currentMarkdown();')
            assert file.read_text(encoding='utf8').startswith('# Hello')
            translator.action('exit', {}); QTest.qWait(50)
            win.tabs.setCurrentWidget(source_tab.view)
            source_tab.scroll_position = 125
            win.close_tab(win._tab_list.index(source_tab)); assert win.features.closed_documents
            win.features.reopen(); wait(lambda: win.current_tab().ready)
            assert win.current_tab().filepath == str(file)
            source_tab = win.current_tab()
            win.features.snapshot(str(file), 'old snapshot')
            assert win.features.history_store().entries(str(file))
            disk = '# External\n'; file.write_text(disk, encoding='utf8'); QTest.qWait(200); win.features.check_external()
            assert source_tab.external_changed and source_tab.autosave_paused
            with patch.object(CompareDialog, 'exec', lambda dialog: (setattr(dialog, 'choice', 'keep'), QDialog.DialogCode.Accepted)[1]):
                win.features.compare_external(source_tab, before)
            assert source_tab.dirty and not source_tab.external_changed and file.read_text(encoding='utf8') == disk
            assert any(entry.read_text(encoding='utf8') == disk for entry in win.features.history_store().entries(str(file)))
            # Image insertion compression and file moves retain local assets.
            image = QImage(3000, 2000, QImage.Format.Format_RGB32); image.fill(QColor('#56886e'))
            image_path = root / 'large.bmp'; image.save(str(image_path), 'BMP')
            QSettings().setValue('images/compress', True); QSettings().setValue('images/maxEdge', 800)
            stored = win._store_image(source_tab, image_path.read_bytes(), 'large.bmp')
            from urllib.parse import unquote
            stored_path = root / unquote(stored['path']); assert stored_path.stat().st_size < image_path.stat().st_size
            assert max(QImage(str(stored_path)).size().width(), QImage(str(stored_path)).size().height()) <= 800
            moving = root / 'move.md'; moving.write_text('![x](' + stored['path'] + ')', encoding='utf8')
            target = root / 'moved'; target.mkdir(); win.features.move_file(str(moving), str(target / 'move.md'))
            assert not moving.exists() and (target / 'move.md').exists() and list((target / 'images').iterdir())
            moving = root / 'move.mdown'; moving.write_text('![asset]\n\n[asset]: ' + stored['path'], encoding='utf8')
            win.features.move_file(str(moving), str(target / 'move.mdown'))
            from app.document_services import image_references
            references = image_references((target / 'move.mdown').read_text(encoding='utf8'), str(target))
            assert not moving.exists() and len(references) == 1 and references[0]['status'] == 'local', references
            try: win.features.safe_child(str(root), '../escape.md')
            except ValueError: pass
            else: raise AssertionError('path traversal accepted')
            win.toggle_theme(); QTest.qWait(100)
            win.open_translation(source_tab, 'full'); QTest.qWait(250)
            win.grab().save(str(output / 'translation-dark.png'))
            win.set_language('en')
            QTest.qWait(150)
            assert ev('return document.querySelector(".translation-reader-bar strong").textContent;') == 'Full-document translation'
            win.grab().save(str(output / 'translation-english.png'))
            print('PASS modes, preferences, templates, prompts, search, commands, translation selection/full, original preservation, new document, reopen, external conflict, history, image compression and move')
        finally:
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(100); QSettings().clear(); server.shutdown(); server.server_close()


if __name__ == '__main__': run()
