"""Local provider protocol, Markdown protection, credentials and cancellation checks."""
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from app.translation import ChatRequest, TranslationConfig, protect_key, load_config, save_config
from app.translation_markdown import ProtectedMarkdown, TranslationJob


class Provider(BaseHTTPRequestHandler):
    mode = "stream"
    requests = []
    fail_at = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).requests.append(data)
        mode = type(self).mode
        if type(self).fail_at and len(type(self).requests) == type(self).fail_at:
            mode = 'unauthorized'
        if mode == 'unauthorized':
            self.send_response(401); self.end_headers(); return
        if mode == 'redirect':
            self.send_response(302); self.send_header('Location', '/secret'); self.end_headers(); return
        message = data['messages'][-1]['content']
        text = json.loads(message)['text'] if message.startswith('{') else 'OK'
        text = text.replace('Hello', '你好').replace('world', '世界')
        if mode == 'corrupt':
            text = 'lost all tokens'
        reason = 'length' if mode == 'truncated' else 'stop'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if mode == 'json' else 'text/event-stream')
        self.end_headers()
        try:
            if mode == 'json':
                self.wfile.write(json.dumps({'choices': [{'message': {'content': text}, 'finish_reason': reason}]}).encode())
                return
            for offset in range(0, len(text), 30):
                body = ('data: ' + json.dumps({'choices': [{'delta': {'content': text[offset:offset+30]}}]}, ensure_ascii=False) + '\n\n').encode()
                # Deliberately split in the middle of UTF-8 sequences and SSE lines.
                for pos in range(0, len(body), 7):
                    self.wfile.write(body[pos:pos+7])
                self.wfile.flush()
                if mode == 'slow':
                    time.sleep(.2)
            if mode != 'incomplete':
                self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': reason}]}) + '\n\ndata: [DONE]\n\n').encode())
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def wait(predicate, timeout=40):
    start = time.monotonic()
    while not predicate():
        assert time.monotonic() - start < timeout, 'timed out'
        QTest.qWait(10)


def run():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName('MarkdownViewTranslationTests')
    app.setApplicationName('isolated')
    settings = QSettings(); settings.clear()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    config = TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'test-model', 'fake-test-key', chunk_size=1000)
    source = '# Hello world\n\n**Hello** `world` [Hello](https://example.org/a_(b))\n\n![pic](images/a.png)\n\n$$x^2$$\n\n```python\nprint("world")\n```\n'
    try:
        protected = ProtectedMarkdown(source, 1000)
        assert ''.join(protected.restore(c.text, c) for c in protected.chunks) == source
        assert 'https://' not in protected.encoded and 'print(' not in protected.encoded
        for sample in ('```\nHello\n```', '---\ntitle: Hello\n---\n\nHello\n', '\n    Hello\n\nworld', 'Hello there. ' * 2000, '你好。' * 3000):
            doc = ProtectedMarkdown(sample, 1000)
            assert ''.join(doc.restore(c.text, c) for c in doc.chunks) == sample
            assert all(len(c.text) <= 1000 for c in doc.chunks)
        job = TranslationJob(config, source * 20, 'auto', '中文', prompt='Technical translation')
        ticks = []
        timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(1)
        job.start(); wait(lambda: job.state != 'running')
        assert job.state == 'complete', job.error
        assert job.result == (source.replace('Hello', '你好').replace('world\n', '世界\n').replace('world\n\n', '世界\n\n')) * 20, job.result[:300]
        assert ticks and len(Provider.requests) > 1
        assert 'Technical translation' in Provider.requests[0]['messages'][0]['content']
        for request in Provider.requests:
            assert 'https://example' not in request['messages'][-1]['content']
        timer.stop()
        for mode, expected in [('json', 'complete'), ('corrupt', 'failed'), ('truncated', 'failed'), ('incomplete', 'failed'), ('unauthorized', 'failed'), ('redirect', 'failed')]:
            Provider.mode = mode
            current = TranslationJob(config, source, 'auto', 'English')
            current.start(); wait(lambda: current.state != 'running')
            assert current.state == expected, (mode, current.state, current.error)
        Provider.mode = 'slow'
        cancelled = TranslationJob(config, source * 50, 'auto', '中文')
        cancelled.start(); QTest.qWait(60); cancelled.cancel()
        assert cancelled.state == 'cancelled' and cancelled.request.reply is None
        Provider.mode = 'json'; cancelled.start(); wait(lambda: cancelled.state != 'running')
        assert cancelled.state == 'complete', cancelled.error
        Provider.requests.clear(); Provider.fail_at = 2
        resumed = TranslationJob(config, source * 10, 'auto', '中文')
        resumed.start(); wait(lambda: resumed.state != 'running')
        assert resumed.state == 'failed' and 0 < len(resumed.parts) < len(resumed.document.chunks), (resumed.state, len(resumed.parts), len(resumed.document.chunks), len(Provider.requests), resumed.error)
        retained = resumed.result
        first_input = Provider.requests[0]['messages'][-1]['content']
        Provider.fail_at = 0; resumed.start(); wait(lambda: resumed.state != 'running')
        assert resumed.state == 'complete' and resumed.result.startswith(retained)
        assert sum(r['messages'][-1]['content'] == first_input for r in Provider.requests) == 1
        Provider.mode = 'slow'
        expired = TranslationJob(config, source * 3, 'auto', '中文')
        expired.start(); wait(lambda: expired.request.reply is not None)
        expired.request.timer.start(40)
        wait(lambda: expired.state != 'running')
        assert expired.state == 'failed' and expired.request.reply is None and '超时' in expired.error
        cipher = protect_key('fake-secret'); assert 'fake-secret' not in cipher and protect_key(cipher, True) == 'fake-secret'
        config.remember = True; save_config(config)
        assert config.key not in str(settings.value('translation/config')) + str(settings.value('translation/key'))
        delattr(app, '_translation_key'); assert load_config().key == config.key
        config.remember = False; save_config(config); assert not settings.contains('translation/key')
        assert load_config().key == config.key
        delattr(app, '_translation_key'); assert not load_config().key
        for url in ('ftp://example.com', 'https://user:password@example.com', 'https://example.com?key=x', 'not a url'):
            try:
                TranslationConfig(url, 'model').validate()
            except ValueError:
                pass
            else:
                raise AssertionError(url)
        print('PASS translation protection, SSE/JSON, failure, partial-result retry, cancellation, timeout, async heartbeat and DPAPI')
    finally:
        settings.clear(); server.shutdown(); server.server_close()


if __name__ == '__main__':
    run()
