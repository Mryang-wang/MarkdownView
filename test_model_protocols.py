"""Exercise all three wire protocols with real Qt HTTP, including stream failures."""
import json
import socket
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from app.translation import ChatRequest, TranslationConfig
from app.translation_markdown import TranslationJob


class Provider(BaseHTTPRequestHandler):
    mode = 'normal'
    requests = []
    fail_at = 0

    def log_message(self, *_): pass

    def do_POST(self):
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        protocol = {'/v1/chat/completions': 'chat', '/v1/responses': 'responses', '/v1/messages': 'anthropic'}[self.path]
        type(self).requests.append((protocol, body, dict(self.headers)))
        mode = self.mode
        if self.fail_at and len(self.requests) == self.fail_at: mode = 'error'
        if mode == 'error':
            self.send_response(429); self.end_headers(); self.wfile.write(b'secret never to be displayed'); return
        conversation = body['input' if protocol == 'responses' else 'messages']
        raw = conversation[-1]['content']; text = json.loads(raw)['text'] if raw.startswith('{') else raw
        text = text.replace('Hello', '你好').replace('world', '世界')
        if protocol == 'chat':
            final = {'choices': [{'message': {'content': text}, 'finish_reason': 'length' if mode == 'truncated' else 'stop'}]}
        elif protocol == 'responses':
            final = {'status': 'incomplete' if mode == 'truncated' else 'completed', 'error': None,
                     'incomplete_details': {'reason': 'max_output_tokens'} if mode == 'truncated' else None,
                     'output': [{'type': 'reasoning', 'summary': []}, {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
            if mode == 'refusal': final['output'][1]['content'] = [{'type': 'refusal', 'refusal': 'not a translation'}]
        else:
            final = {'type': 'message', 'content': [{'type': 'thinking', 'thinking': 'hidden'}, {'type': 'text', 'text': text}],
                     'stop_reason': 'max_tokens' if mode == 'truncated' else 'refusal' if mode == 'refusal' else 'end_turn'}
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if body['stream'] else 'application/json'); self.end_headers()
        try:
            if not body['stream']:
                self.wfile.write(json.dumps(final, ensure_ascii=False).encode()); return
            if protocol == 'anthropic':
                self.event({'type': 'message_start', 'message': {'content': [], 'stop_reason': None}})
                self.event({'type': 'ping'})
                self.event({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}})
                self.event({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'hidden'}})
                self.event({'type': 'content_block_stop', 'index': 0})
                self.event({'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}})
            for start in range(0, len(text), 47):
                piece = text[start:start + 47]
                if protocol == 'chat': self.event({'choices': [{'delta': {'content': piece}}]})
                elif protocol == 'responses': self.event({'type': 'response.output_text.delta', 'delta': piece})
                else: self.event({'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': piece}})
                if mode == 'slow': time.sleep(.05)
            if mode == 'incomplete': return
            if protocol == 'chat':
                self.event({'choices': [{'delta': {}, 'finish_reason': final['choices'][0]['finish_reason']}]})
                self.wfile.write(b'data: [DONE]\n\n')
            elif protocol == 'responses':
                self.event({'type': 'response.output_text.done', 'text': text})
                self.event({'type': 'response.incomplete' if mode == 'truncated' else 'response.completed', 'response': final}, trailing=False)
            else:
                self.event({'type': 'content_block_stop', 'index': 1})
                self.event({'type': 'message_delta', 'delta': {'stop_reason': final['stop_reason']}})
                self.event({'type': 'message_stop'}, trailing=False)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass

    def event(self, data, trailing=True):
        payload = ('event: ' + data.get('type', 'chunk') + '\r\ndata: ' + json.dumps(data, ensure_ascii=False) + ('\r\n\r\n' if trailing else '')).encode()
        # Split a UTF-8 codepoint without turning the fixture into thousands of tiny writes.
        offset = payload.find('你'.encode())
        split = offset + 1 if offset >= 0 else min(7, len(payload))
        self.wfile.write(payload[:split]); self.wfile.write(payload[split:])
        self.wfile.flush()


def wait(predicate, seconds=15):
    end = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < end, 'timeout'
        QTest.qWait(5)


def run():
    app = QCoreApplication([]); app.setOrganizationName('MarkdownViewProtocolTest'); app.setApplicationName('isolated')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'fixture', 'fake-key', chunk_size=1000)
    try:
        for protocol, route in (('chat', '/chat/completions'), ('responses', '/responses'), ('anthropic', '/messages')):
            for endpoint in ('http://203.0.113.8:8080', 'http://example.com/v1', 'https://example.com/v1/chat/completions/'):
                config = replace(base, endpoint=endpoint, protocol=protocol); assert config.url().endswith('/v1' + route); config.validate()
            for prefix in ('', '/api/v2'):
                config = replace(base, endpoint='http://example.com' + prefix + '/responses', protocol=protocol)
                assert config.url() == 'http://example.com' + prefix + route
            config = replace(base, protocol=protocol)
            for stream in (False, True):
                Provider.mode = 'normal'
                request = ChatRequest(); output = []; errors = []; deltas = []
                request.succeeded.connect(output.append); request.failed.connect(errors.append); request.delta.connect(deltas.append)
                request.start(replace(config, stream=stream), [{'role': 'system', 'content': 'Translation instructions'}, {'role': 'user', 'content': 'Hello world'}])
                wait(lambda: output or errors)
                assert output == ['你好 世界'] and not errors, (protocol, stream, errors, output)
                assert ''.join(deltas) == '你好 世界', (protocol, stream, deltas)
                _, payload, raw_headers = Provider.requests[-1]; headers = {k.lower(): v for k, v in raw_headers.items()}
                if protocol == 'anthropic':
                    assert headers['x-api-key'] == 'fake-key' and headers['anthropic-version'] == '2023-06-01'
                    assert 'authorization' not in headers and payload['max_tokens'] == 8192 and payload['system'] == 'Translation instructions'
                else: assert headers['authorization'] == 'Bearer fake-key'
                if protocol == 'responses': assert payload['instructions'] == 'Translation instructions' and payload['store'] is False and 'messages' not in payload
                if protocol != 'chat': assert all(m['role'] != 'system' for m in payload.get('input', payload.get('messages', [])))
                request.deleteLater()
                for mode in ('truncated', 'error', 'incomplete') + (('refusal',) if protocol != 'chat' else ()):
                    if mode == 'incomplete' and not stream: continue
                    Provider.mode = mode; request = ChatRequest(); done = []; errors = []
                    request.succeeded.connect(done.append); request.failed.connect(errors.append)
                    request.start(replace(config, stream=stream), [{'role': 'user', 'content': 'Hello world'}]); wait(lambda: done or errors)
                    assert errors and not done and 'secret' not in errors[0], (protocol, mode, stream, done, errors)
                    request.deleteLater()
            # Format protection, retry and cancellation are independent of the wire format.
            Provider.mode = 'normal'; Provider.requests = []; Provider.fail_at = 2
            source = ('# Hello world\n\nHello **world** $x^2$ and `code`.\n\n' * 20)
            job = TranslationJob(config, source, 'English', '中文', prompt='Technical {target_language}')
            job.start(); wait(lambda: job.state == 'failed'); assert job.parts
            before = list(job.parts); Provider.fail_at = 0; job.start(); wait(lambda: job.state != 'running', 45)
            assert job.state == 'complete', (protocol, job.state, job.error, len(job.parts), len(job.document.chunks))
            assert job.parts[:len(before)] == before and job.result == source.replace('Hello', '你好').replace('world', '世界')
            Provider.mode = 'slow'; interrupted = TranslationJob(config, source, 'English', '中文')
            interrupted.start(); wait(lambda: interrupted.request.reply is not None); interrupted.cancel(); QTest.qWait(70)
            assert interrupted.state == 'cancelled' and interrupted.request.reply is None
            job.deleteLater(); interrupted.deleteLater()
            print('PASS protocol ' + protocol, flush=True)
        print('PASS 3 protocols: URLs, auth, request shapes, SSE/JSON, UTF-8, final events, truncation/errors, retry, cancellation, and Markdown protection')
    finally:
        server.shutdown(); server.server_close()


if __name__ == '__main__': run()
