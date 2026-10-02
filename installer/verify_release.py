"""验证真实打包 EXE：带空格的中文文件、离线渲染、新格式、保存和内置 Pandoc。"""
import base64
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtWebSockets import QWebSocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.exporter import export_docx  # noqa: E402


def wait_until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError('Timed out waiting for the packaged application')


class DebugClient:
    def __init__(self, url):
        self.socket = QWebSocket()
        self.responses = {}
        self.next_id = 0
        self.socket.textMessageReceived.connect(self.received)
        self.socket.open(QUrl(url))
        wait_until(self.socket.isValid)

    def received(self, message):
        data = json.loads(message)
        if 'id' in data:
            self.responses[data['id']] = data

    def call(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        self.socket.sendTextMessage(json.dumps({'id': request_id, 'method': method, 'params': params or {}}))
        wait_until(lambda: request_id in self.responses)
        response = self.responses.pop(request_id)
        assert 'error' not in response, response
        return response['result']

    def evaluate(self, code):
        data = self.call('Runtime.evaluate', {
            'expression': 'JSON.stringify((function(){' + code + '})())', 'returnByValue': True})
        assert 'exceptionDetails' not in data, data
        return json.loads(data['result']['value'])


def close_process(process):
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(handle, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(owner))
        if owner.value == process.pid:
            user32.PostMessageW(ctypes.c_void_p(handle), 0x0010, 0, 0)
        return True
    user32.EnumWindows(callback_type(visit), 0)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)


def run(executable):
    application = QCoreApplication(sys.argv)
    directory = ROOT / 'tmp' / 'release-smoke'
    directory.mkdir(parents=True, exist_ok=True)
    document = directory / '中文文件 带空格.md'
    content = ('# 安装包启动成功\n\n<u>单横线</u>，'
               '<u style="text-decoration-style: double">双横线</u>，'
               '<u style="text-decoration-style: wavy">波浪线</u>，'
               '<u style="text-decoration-style: dashed">虚线</u>，'
               '<u style="text-decoration-style: dotted">点线</u>。\n\n'
               '<mark style="background-color: #bfdbfe; color: #272724">彩色高亮</mark>。\n\n'
               '离线公式：\\(x^2 + y^2 = z^2\\)。\n')
    document.write_text(content, encoding='utf-8')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    environment = dict(os.environ, MDVIEW_DATA_DIR=str(directory / 'profile'),
                       QTWEBENGINE_REMOTE_DEBUGGING='127.0.0.1:' + str(port))
    # 使用只有系统目录的 PATH，证明 EXE 不借用开发环境中的 Python/Qt/DLL。
    windows_dir = environment.get('SystemRoot', r'C:\Windows')
    environment['PATH'] = os.pathsep.join([str(Path(windows_dir) / 'System32'), windows_dir])
    for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        environment.pop(name, None)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    client = None
    with (directory / 'application.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(executable), str(document)], cwd=directory, env=environment,
                                   startupinfo=startup, stdout=log, stderr=log)
        try:
            targets = []
            def find_page():
                assert process.poll() is None, 'Packaged application exited early'
                try:
                    with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/json', timeout=.5) as response:
                        pages = json.load(response)
                    targets[:] = [page for page in pages if page.get('type') == 'page' and 'index.html' in page.get('url', '')]
                except OSError:
                    return False
                return bool(targets)
            wait_until(find_page, 30)
            client = DebugClient(targets[0]['webSocketDebuggerUrl'])
            wait_until(lambda: client.evaluate('return !!window.__editorReady && !!window.currentMarkdown && window.currentMarkdown().includes("安装包启动成功");'))
            # editorReady precedes asynchronous KaTeX loading; this is especially
            # visible while the installer compiler is using CPU in parallel.
            wait_until(lambda: client.evaluate(
                'return !!window.__err || !!document.querySelector(".katex, .katex-error");'), 30)
            state = client.evaluate('''
              window.refreshInlineFormats();var lines={};
              CSS.highlights.forEach((h,n)=>{if(n.startsWith('mdv-underline'))lines[n]=Array.from(h).map(r=>r.toString()).join('').replace(/\u200b/g,'');});
              return {error:window.__err,lines:lines,formula:document.querySelectorAll('.katex').length,
                formulaErrors:document.querySelectorAll('.katex-error').length,
                styles:document.querySelectorAll('#mdv-underline-options button').length,
                colors:document.querySelectorAll('#mdv-highlight-presets button').length};
            ''')
            assert not state['error'] and state['formula'] > 0 and not state['formulaErrors'], state
            assert state['styles'] == 5 and state['colors'] == 6, state
            for style, text in [('solid', '单横线'), ('double', '双横线'), ('wavy', '波浪线'), ('dashed', '虚线'), ('dotted', '点线')]:
                name = 'mdv-underline' if style == 'solid' else 'mdv-underline-' + style
                assert state['lines'][name] == text, state
            print('PASS - Frozen EXE opens a Chinese path with spaces and renders formulas and all five line styles', flush=True)
            assert client.evaluate('''
              return document.documentElement.dataset.nativeStatusbar === "true"
                && getComputedStyle(document.getElementById("editor-statusbar")).display === "none"
                && typeof window.bridge.reportEditorStatus === "function"
                && typeof window.showStatsDialog === "function"
                && typeof window.addReviewComment === "function"
                && typeof window.setLanguage === "function";
            '''), 'Current footer bridge, review or language assets missing from frozen application'
            print('PASS - Packaged editor includes the native footer bridge, comments and language controls', flush=True)
            screenshot = client.call('Page.captureScreenshot', {'format': 'png'})
            (directory / 'packaged-editor.png').write_bytes(base64.b64decode(screenshot['data']))
            client.evaluate('window.__setEditorValue(window.currentMarkdown()+"\\n打包保存验证\\n");return true;')
            wait_until(lambda: client.evaluate('return window.currentMarkdown().includes("打包保存验证");'))
            client.evaluate('window.requestSave();return true;')
            wait_until(lambda: '打包保存验证' in document.read_text(encoding='utf-8'))
            client.evaluate('window.markClean();return true;')
            print('PASS - Packaged application saves Markdown through its native Python bridge', flush=True)

            bundled_pandoc = executable.parent / '_internal' / 'pandoc.exe'
            assert bundled_pandoc.is_file()
            word = directory / '内置导出验证.docx'
            with patch('app.exporter.find_pandoc', return_value=str(bundled_pandoc)):
                export_docx(content, str(word), str(directory))
            with zipfile.ZipFile(word) as archive:
                xml = ET.fromstring(archive.read('word/document.xml'))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
                  'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}
            values = {node.get('{' + ns['w'] + '}val') for node in xml.findall('.//w:u', ns)}
            assert {'single', 'double', 'wave', 'dash', 'dotted'}.issubset(values), values
            assert xml.find('.//m:oMath', ns) is not None
            print('PASS - Bundled Pandoc exports editable Word underline styles and native equations', flush=True)
        finally:
            if client:
                client.socket.close()
            if process.poll() is None:
                close_process(process)
    print('PACKAGED_RELEASE: PASSED', flush=True)


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
