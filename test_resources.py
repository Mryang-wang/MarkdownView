"""Resource policy regression: lazy loading, cache restoration and edit safety."""
import json
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow, READING_EDITOR_CACHE
from bench_resources import pump, wait

ROOT = Path(__file__).resolve().parent


def run():
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='resource-tests-', dir=ROOT / 'tmp') as directory:
        root = Path(directory)
        assert root.resolve().is_relative_to(ROOT / 'tmp')
        os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication(sys.argv)
        app.setOrganizationName('MarkdownViewResourceTest')
        app.setApplicationName('MarkdownViewResourceTest')
        settings = QSettings()
        settings.setValue('files/autoSave', False)
        settings.setValue('appearance/theme', 'light')
        settings.setValue('appearance/sidebarVisible', True)
        image = QImage(24, 24, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(str(root / 'image.png'))
        content = '# Resource document\n\nResource paragraph.\n\n![image](image.png)\n\n'
        content += '\n\n'.join('Paragraph %d: \\(x+y\\) and **bold**.' % i for i in range(110))
        paths = [root / ('文档 ' + str(i + 1) + '.md') for i in range(8)]
        for i, path in enumerate(paths):
            path.write_text('# Document %d\n\n' % i + content, encoding='utf-8')
        # Use a plain editing fixture so asynchronous math/image rendering does
        # not add unrelated DOM snapshots to the undo stack being tested.
        paths[1].write_text('# Edit history\n\nResource paragraph.\n', encoding='utf-8')
        window = MainWindow(startup_file=str(paths[0]))
        window.resize(1100, 760)
        window.show()

        def evaluate(tab, code):
            values = []
            tab.view.page().runJavaScript('JSON.stringify((function(){' + code + '})())', values.append)
            wait(lambda: bool(values), 15)
            assert values[0] is not None, code
            return json.loads(values[0])

        def select(tab):
            tab.window.tabs.setCurrentWidget(tab.view)
            wait(lambda: tab.ready)
            pump(.25)

        try:
            first = window.current_tab()
            wait(lambda: first.ready)
            pump(1)
            assert not first.ever_edited and not first.dirty
            wait(lambda: evaluate(first, 'return document.querySelectorAll(".katex").length;') > 100, 25)
            state = evaluate(first, 'return {math:document.querySelectorAll(".katex").length, image:document.querySelector("#vditor img").naturalWidth};')
            assert state['math'] > 100 and state['image'] == 24, state
            print('PASS - Formula and relative image rendering stay intact', flush=True)

            tabs = [first] + [window.open_file(str(path)) for path in paths[1:]]
            wait(lambda: tabs[-1].ready)
            assert sum(tab.initialized for tab in tabs) == 2
            assert [tab.filepath for tab in tabs] == list(map(str, paths))
            assert [window.document_list.item(i).text() for i in range(8)] == [p.name for p in paths]
            window._persist_session()
            session = json.loads((window.store.root / 'workspace.json').read_text(encoding='utf-8'))['session']
            assert sorted(record['path'] for record in session['documents']) == sorted(map(str, paths))
            print('PASS - Batch open initializes only the selected editor and retains every path', flush=True)

            select(first)
            window.set_page_zoom(1.2)
            evaluate(first, 'document.querySelector("[data-mode=sv]").click();document.querySelector("[data-type=outline]").click();window.restorePosition(650);return true;')
            pump(.4)
            first_state = evaluate(first, 'return window.readingStateForCache();')
            assert first_state['mode'] == 'sv' and first_state['outline'] and first_state['scroll'] >= 600, first_state
            first_status = first.document_status
            assert first_status[0] > 0 and first_status[2] == 'sv'

            edited = tabs[1]
            select(edited)
            evaluate(edited, '''var p=Array.from(document.querySelectorAll('.vditor-ir p')).find(p=>p.textContent==='Resource paragraph.');
                var r=document.createRange();r.selectNodeContents(p);var s=getSelection();s.removeAllRanges();s.addRange(r);
                window.applyUnderline();return true;''')
            wait(lambda: edited.dirty and edited.ever_edited)
            edited_pid = edited.view.page().renderProcessPid()
            wait(lambda: bool(window.store.drafts()))
            for tab in tabs[2:]:
                select(tab)
            wait(lambda: first.parked, 20)
            pump(2)
            assert len(window._loaded_tabs()) <= READING_EDITOR_CACHE
            assert edited.ready and not edited.parked and edited.view.page().renderProcessPid() == edited_pid
            print('PASS - Old reading pages release renderers; dirty editors and drafts survive', flush=True)

            paths[0].write_text('external replacement', encoding='utf-8')
            select(first)
            restored = evaluate(first, 'return {value:window.currentMarkdown(),state:window.readingStateForCache()};')
            assert 'Resource paragraph.' in restored['value'] and 'external replacement' not in restored['value']
            assert restored['state']['mode'] == 'sv' and restored['state']['outline']
            assert restored['state']['scroll'] >= 600, restored['state']
            assert not first.dirty and not first.ever_edited
            wait(lambda: first.document_status == first_status)
            assert window.editor_status.counter.text() == '字数 %d' % first_status[0]
            assert window.editor_status.mode.text() == '源代码'
            assert first.zoom_factor == 1.2 and window.editor_status.zoom.text() == '120%'
            assert evaluate(first, 'return getComputedStyle(document.querySelector(".vditor-sv")).zoom;') == '1.2'
            print('PASS - Cached source, editing mode, outline and scroll restore without rereading changed files', flush=True)

            select(edited)
            saved = evaluate(edited, 'return window.currentMarkdown();')
            assert '<u>' in saved
            window.save_file(edited, saved)
            wait(lambda: not edited.dirty)
            for tab in tabs[2:]:
                select(tab)
            pump(2)
            assert not edited.parked and edited.view.page().renderProcessPid() == edited_pid
            select(edited)
            rect = evaluate(edited, 'var b=document.querySelector("button[data-type=undo]");var r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,button:b.outerHTML};')
            # Vditor may retain an additional cursor/DOM snapshot after saving;
            # verify that the original editing action is still undoable.
            for _ in range(3):
                QTest.mouseClick(edited.view.focusProxy(), Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier, QPoint(round(rect['x']), round(rect['y'])))
                pump(.3)
                undone = evaluate(edited, 'return window.currentMarkdown();')
                if '<u>' not in undone:
                    break
            assert '<u>' not in undone and 'Resource paragraph.' in undone
            assert '<u>' in paths[1].read_text(encoding='utf-8')
            print('PASS - Saved editors retain undo history after cache pressure', flush=True)

            closed = window.new_tab(filepath=str(root / 'unused.md'))
            assert not closed.initialized
            window.close_tab(window.tabs.indexOf(closed.view))
            pump(.3)
            assert not closed.initialized
            print('PASS - Closing a pending document does not start an unused renderer', flush=True)

            select(edited)
            window.detach_tab(window.tabs.indexOf(edited.view), QPoint(180, 120))
            child = edited.window
            assert child.current_tab() is edited and edited.dirty
            for tab in tabs[2:]:
                select(tab)
            pump(2)
            assert not edited.parked and edited.view.page().renderProcessPid() == edited_pid
            print('PASS - Active detached editors remain protected across windows', flush=True)
            print('RESOURCE_POLICY: PASSED', flush=True)
        finally:
            for owner in list(window.store.windows):
                for tab in owner._tab_list:
                    tab.dirty = False
                owner.close()
            pump(.3)
            settings.clear()


if __name__ == '__main__':
    run()
