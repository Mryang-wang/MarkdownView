"""Hold a real SSE response open: the UI must show it before any chunk commits."""
import json
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.translation import TranslationConfig, save_config
from app.translation_markdown import ProtectedMarkdown
from test_translation import wait


class Provider(BaseHTTPRequestHandler):
    gates = None
    requests = []

    def log_message(self, *_): pass

    def do_POST(self):
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        payload = json.loads(body['messages'][-1]['content'])
        self.requests.append(payload)
        gates = self.gates
        text = payload['text']
        if payload['target_language'] == 'English':
            text = text.replace('你好', 'Hello').replace('世界', 'world')
        else:
            text = text.replace('Hello', '你好').replace('world', '世界')
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
        try:
            ends = [min(150, len(text)), max(150, len(text) - 20), len(text)] if gates else [len(text)]
            offset = 0
            for index, end in enumerate(ends):
                for start in range(offset, end, 13):
                    data = {'choices': [{'delta': {'content': text[start:min(start + 13, end)]}}]}
                    self.wfile.write(('data: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode())
                    self.wfile.flush()
                offset = end
                if gates and index < 2:
                    assert gates[index].wait(20), 'test did not release stream'
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass


def run():
    doc = ProtectedMarkdown('# Hello **world** $x^2$ `code`\n\n![image](a.png)\n')
    for cut in range(len(doc.encoded) + 1):
        preview = doc.preview(doc.encoded[:cut])
        assert doc.source.startswith(preview), (cut, preview)
        assert '@' not in preview, (cut, preview)
    assert doc.preview(doc.encoded) == doc.source
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewStreamingTest'); app.setApplicationName('isolated')
        QSettings().clear()
        source = '# Hello world\n\n' + 'Hello world. ' * 320 + '\n\n$x^2$ and `code`.\n'
        path = root / 'source.md'; path.write_text(source, encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        save_config(TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'Streaming fixture', 'fake-key', chunk_size=8000))
        win = MainWindow(startup_file=str(path)); win.resize(1260, 850); win.show()
        all_gates = []

        def ev(code):
            values = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((()=>{' + code + '})())', lambda value: (values.append(value), loop.quit()))
            QTimer.singleShot(5000, loop.quit); loop.exec()
            assert values and values[0], code
            return json.loads(values[0])

        def held():
            Provider.gates = [threading.Event(), threading.Event()]; all_gates.extend(Provider.gates)
            return Provider.gates

        try:
            wait(lambda: win.current_tab().ready); QTest.qWait(200)
            before = ev('return currentMarkdown();')
            gates = held(); win.open_translation(win.current_tab(), 'full')
            wait(lambda: getattr(win.current_tab(), 'translation', None) and win.current_tab().translation.job is not None)
            controller = win.current_tab().translation
            wait(lambda: ev('return !!document.querySelector(".translation-live .translation-stream")?.textContent.includes("你好");'))
            assert controller.job.state == 'running' and not controller.job.parts
            first = ev('window.__live=document.querySelector(".translation-live .translation-stream"); window.__original=document.querySelector(".translation-original"); window.__mathCalls=0; const math=Vditor.mathRender; Vditor.mathRender=function(...args){window.__mathCalls++;return math.apply(this,args);};return window.__live.textContent;')
            assert '@@' not in first
            gates[0].set()
            wait(lambda: ev('return (document.querySelector(".translation-live .translation-stream")?.textContent.length || 0)>1200;'))
            assert not controller.job.parts and controller.job.state == 'running'
            assert ev('return window.__live===document.querySelector(".translation-live .translation-stream") && window.__original===document.querySelector(".translation-original") && window.__mathCalls===0;')
            assert ev('return document.querySelector(".translation-live .translation-stream").textContent;').startswith(first)
            output = Path('tmp/translation-streaming'); output.mkdir(parents=True, exist_ok=True)
            win.grab().save(str(output / 'live-full.png'))
            gates[1].set(); wait(lambda: controller.job.state == 'complete'); QTest.qWait(200)
            assert ev('return !document.querySelector(".translation-live") && !!document.querySelector(".translation-rendered h1");')
            assert ev('return currentMarkdown();') == before and not win.current_tab().dirty
            # Unchanged translations remain visible during a manual update. A newer
            # edit cancels the old stream and waits for another explicit update.
            before = before.replace('Hello world.', 'Hello changed world.', 1)
            ev('window.__setEditorValue(' + json.dumps(before) + ');return true;')
            wait(lambda: controller.source_stale)
            gates = held(); previous = controller.job; controller.action('update', {})
            wait(lambda: controller.job is not previous)
            wait(lambda: ev('return !!document.querySelector(".translation-live");'))
            assert controller.job.document.changed_units == 1
            assert ev('return document.querySelector(".translation-article").textContent;').count('你好 世界') > 100
            count = len(Provider.requests)
            before = before.replace('Hello changed world.', 'Hello newest world.', 1)
            ev('window.__setEditorValue(' + json.dumps(before) + ');return true;')
            wait(lambda: controller.job.state == 'cancelled' and controller.source_stale)
            QTest.qWait(150); assert len(Provider.requests) == count
            for gate in gates: gate.set()
            Provider.gates = None; previous = controller.job; controller.action('update', {})
            wait(lambda: controller.job is not previous and controller.job.state == 'complete'); QTest.qWait(200)
            assert 'newest' in controller.job.result and 'changed' not in controller.job.result
            # Cancel discards unvalidated live text; resume does not duplicate it.
            gates = held(); controller.action('reset', {}); controller.action('start', {})
            wait(lambda: ev('return !!document.querySelector(".translation-live");'))
            controller.action('cancel', {}); QTest.qWait(200)
            assert ev('return !document.querySelector(".translation-live") && document.querySelector(".translation-article").textContent.includes("待更新");')
            assert not controller.job.result
            for gate in gates: gate.set()
            Provider.gates = None; controller.action('start', {}); wait(lambda: controller.job.state == 'complete'); QTest.qWait(200)
            # The target dropdown changes the actual request after a Chinese result.
            controller.open({'full': before, 'selection': '你好，世界。'}, 'selection')
            wait(lambda: controller.job.state == 'complete'); QTest.qWait(200)
            count = len(Provider.requests)
            ev('const s=document.querySelector(".translation-panel [data-translation-language=target]");s.value="English";s.dispatchEvent(new Event("change"));const b=document.querySelector(".translation-actions .primary");b.click();b.click();return true;')
            wait(lambda: len(Provider.requests) > count and controller.job and controller.job.state == 'complete'); QTest.qWait(200)
            assert Provider.requests[-1]['target_language'] == 'English'
            assert len(Provider.requests) == count + 1
            assert ev('return document.querySelector(".translation-result").textContent;').strip() == 'Hello，world。'
            assert QSettings().value('translation/target') == 'English'
            # The selection rail also grows before commit.
            gates = held(); controller.open({'full': before, 'selection': '你好 世界。' * 80}, 'selection')
            wait(lambda: ev('return document.querySelector(".translation-result").textContent.includes("Hello");'))
            assert not controller.job.parts
            first = ev('return document.querySelector(".translation-result").textContent;')
            gates[0].set(); wait(lambda: len(ev('return document.querySelector(".translation-result").textContent;')) > len(first))
            assert not controller.job.parts
            old_job = controller.job; Provider.gates = None
            ev('const s=document.querySelector(".translation-panel [data-translation-language=target]");s.value="简体中文";s.dispatchEvent(new Event("change"));document.querySelector(".translation-actions .primary").click();return true;')
            wait(lambda: controller.job and controller.job is not old_job and controller.job.state == 'complete')
            assert old_job.state == 'cancelled' and Provider.requests[-1]['target_language'] == '简体中文'
            gates[1].set(); QTest.qWait(200)
            assert controller.job.result == '你好 世界。' * 80
            assert ev('return currentMarkdown();') == before and path.read_text(encoding='utf-8') == source
            assert not ev('return window.__err;')
            print('PASS partial-token boundaries, live full/selection before commit, >1200 characters, stable DOM/no repeated math, cancel/retry, language dropdown/request/persistence, and original preservation')
        finally:
            for gate in all_gates: gate.set()
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(100); QSettings().clear(); server.shutdown(); server.server_close()


if __name__ == '__main__': run()
