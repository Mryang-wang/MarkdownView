"""Local translation memory, manual updates, bounded context and cache invalidation."""
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
from app.translation import TranslationConfig, save_config, load_config
from app.translation_memory import IncrementalMarkdown
from test_translation import Provider, wait


def translated(document):
    return ''.join(document.restore(c.text.replace('Hello', '你好'), c) for c in document.chunks)


def run():
    for source in ('# Hello\n\nHello **world**. Hello next!\n\n```py\nHello\n```\n\n$x^2$\n',
                   'Hello there. ' * 3000, '\n    Hello\n\nworld', '你好。世界！再见？\n', 'Hello.' + '\n' * 3000):
        doc = IncrementalMarkdown(source, 1000)
        assert ''.join(doc.restore(c.text, c) for c in doc.chunks) == source
        assert all(len(c.text) <= 1000 for c in doc.chunks)
    source = ' '.join(f'Hello sentence {n}.' for n in range(400))
    first = IncrementalMarkdown(source, 1000); translated(first)
    changed = IncrementalMarkdown(source.replace('Hello sentence 5.', 'Hello changed sentence 5.'), 1000, first)
    assert changed.changed_units == 1 and changed.reused_units == 399
    assert translated(changed) == changed.source.replace('Hello', '你好')
    removed = IncrementalMarkdown(changed.source.replace('Hello sentence 6. ', ''), 1000, changed)
    assert removed.changed_units == 0 and removed.reused_units == 399
    assert translated(removed) == removed.source.replace('Hello', '你好')
    inserted = IncrementalMarkdown(removed.source.replace('Hello sentence 7.', 'Hello new sentence. Hello sentence 7.'), 1000, removed)
    assert inserted.changed_units == 1
    translated(inserted)
    code = IncrementalMarkdown('Hello.\n\n```py\na=1\n```\n'); translated(code)
    code_edit = IncrementalMarkdown('Hello.\n\n```py\na=2\n```\n', previous=code)
    assert code_edit.changed_units == 0 and translated(code_edit).endswith('a=2\n```\n')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewIncrementalTest'); app.setApplicationName('isolated')
        QSettings().clear()
        source = '# Hello\n\n' + '\n\n'.join(f'Hello sentence {n}. Hello context {n}.' for n in range(30)) + '\n'
        path = root / 'source.md'; path.write_text(source, encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        Provider.mode = 'json'; Provider.requests = []; Provider.fail_at = 0
        save_config(TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'Memory fixture', 'fake-key'))
        win = MainWindow(startup_file=str(path)); win.resize(1460, 850); win.show()

        def ev(code):
            values = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((()=>{' + code + '})())', lambda value: (values.append(value), loop.quit()))
            QTimer.singleShot(5000, loop.quit); loop.exec()
            assert values and values[0], code
            return json.loads(values[0])

        def update():
            previous = controller.job
            ev('Array.from(document.querySelectorAll(".translation-reader-bar button")).find(b=>b.textContent==="更新改动").click();return true;')
            wait(lambda: controller.job is not previous)
            wait(lambda: controller.job.state != 'running'); QTest.qWait(150)
            assert controller.job.state == 'complete', controller.job.error

        def edit(text):
            ev('window.__setEditorValue(' + json.dumps(text) + ');return true;')
            wait(lambda: controller.source_stale); QTest.qWait(150)

        try:
            wait(lambda: win.current_tab().ready); QTest.qWait(200)
            win.open_translation(win.current_tab(), 'full')
            wait(lambda: getattr(win.current_tab(), 'translation', None) and win.current_tab().translation.job is not None)
            controller = win.current_tab().translation
            wait(lambda: controller.job.state == 'complete'); QTest.qWait(200)
            assert ev('return !document.getElementById("vditor").inert && document.querySelector(".translation-reader").getBoundingClientRect().left >= document.querySelector("#vditor").getBoundingClientRect().right-2;')
            assert ev('window.setReadOnly(true);return document.querySelector(".vditor-ir pre").getAttribute("contenteditable")==="false";')
            assert ev('window.setReadOnly(false);return document.querySelector(".vditor-ir pre").getAttribute("contenteditable")==="true";')
            assert ev('const v=document.querySelector(".translation-view");v.value="bilingual";v.onchange();window.setReadOnly(false);return document.getElementById("vditor").inert && document.querySelector(".vditor-ir pre").getAttribute("contenteditable")==="false";')
            ev('const v=document.querySelector(".translation-view");v.value="edit";v.onchange();return true;')
            initial = controller.job.result; initial_requests = list(Provider.requests)
            original = ev('return currentMarkdown();')
            # A burst of edits, and waiting longer than a debounce interval, sends nothing.
            count = len(Provider.requests)
            for word in ('changed', 'changed again', 'final change'):
                edit(original.replace('Hello sentence 5.', 'Hello ' + word + ' sentence 5.'))
            QTest.qWait(2200); assert len(Provider.requests) == count
            assert controller.job.result == initial
            update()
            assert len(Provider.requests) == count + 1
            assert controller.job.document.changed_units == 1
            request = Provider.requests[-1]; payload = json.loads(request['messages'][-1]['content'])
            assert 'final change sentence 5.' in payload['text'] and 'sentence 20.' not in payload['text']
            assert 'context 4.' in payload['context_before'] and 'context 5.' in payload['context_after']
            assert len(payload['context_before']) <= 240 and len(payload['context_after']) <= 240
            assert controller.job.result == initial.replace('你好 sentence 5.', '你好 final change sentence 5.')
            # No-op and deletion are entirely local.
            count = len(Provider.requests); update(); assert len(Provider.requests) == count
            current = ev('return currentMarkdown();')
            edit(current.replace('Hello sentence 7. ', '')); update(); assert len(Provider.requests) == count
            assert '你好 sentence 7.' not in controller.job.result
            # Adding text requests only that new sentence.
            current = ev('return currentMarkdown();')
            edit(current.replace('Hello sentence 9.', 'Hello added sentence. Hello sentence 9.')); update()
            assert len(Provider.requests) == count + 1 and controller.job.document.changed_units == 1
            # Clearing and restoring the document retains memory without translating.
            current = ev('return currentMarkdown();'); count = len(Provider.requests)
            edit(''); controller.action('update', {}); wait(lambda: controller.job is None); QTest.qWait(150)
            assert ev('return !Array.from(document.querySelectorAll(".translation-reader-bar button")).find(b=>b.textContent==="更新改动").disabled;')
            edit(current); update(); assert len(Provider.requests) == count
            # A service/model change cannot reuse old translations.
            config = load_config(); config.model = 'Different fixture'; save_config(config)
            count = len(Provider.requests); update()
            assert len(Provider.requests) > count and controller.job.document.reused_units == 0
            # Target dropdown beside the document invalidates Chinese memory.
            count = len(Provider.requests)
            ev('const s=document.querySelector(".translation-reader-bar [data-translation-language=target]");s.value="English";s.dispatchEvent(new Event("change"));document.querySelector("[data-translation-action=toggle]").click();return true;')
            wait(lambda: len(Provider.requests) > count and controller.job and controller.job.state == 'complete'); QTest.qWait(150)
            assert json.loads(Provider.requests[-1]['messages'][-1]['content'])['target_language'] == 'English'
            assert controller.job.document.reused_units == 0
            assert path.read_text(encoding='utf-8') == source and win.current_tab().dirty
            assert not ev('return window.__err;')
            output = Path('tmp/translation-incremental'); output.mkdir(parents=True, exist_ok=True)
            win.grab().save(str(output / 'side-by-side.png'))
            sizes = {'initial_request_count': len(initial_requests), 'initial_request_characters': sum(len(json.dumps(r, ensure_ascii=False)) for r in initial_requests),
                     'single_edit_request_count': 1, 'single_edit_request_characters': len(json.dumps(request, ensure_ascii=False)),
                     'note': 'Local fixture; character counts are not provider token usage.'}
            (output / 'request-sizes.json').write_text(json.dumps(sizes, indent=2), encoding='utf-8')
            print('PASS sentence cache/format/long text, edit/delete/insert, code-only changes, manual-only requests, bounded context, no-op reuse, model/language invalidation, side-by-side editing, and unsaved original preservation')
        finally:
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(100); QSettings().clear(); server.shutdown(); server.server_close()


if __name__ == '__main__': run()
