"""真实多进程回归：连续/并发打开、中文路径、重复文档、恢复窗口和崩溃重启。"""
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from PySide6.QtCore import QCoreApplication

from installer.verify_release import DebugClient, wait_until

ROOT = Path(__file__).resolve().parent
USER32 = ctypes.windll.user32


def window_handles(pid):
    handles = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(handle, _):
        owner = ctypes.c_ulong()
        USER32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(owner))
        title = ctypes.create_unicode_buffer(256)
        USER32.GetWindowTextW(ctypes.c_void_p(handle), title, len(title))
        if owner.value == pid and title.value == 'MarkdownView':
            handles.append(handle)
        return True

    USER32.EnumWindows(callback(visit), 0)
    return handles


def run(command):
    application = QCoreApplication(sys.argv)
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='instance-', dir=ROOT / 'tmp') as scratch:
        directory = Path(scratch)
        assert directory.resolve().is_relative_to(ROOT / 'tmp')
        files = [directory / name for name in ('第一个 文档.md', '第二个 文档.md', '第三个 文档.markdown', '第四个 文档.md')]
        for index, document in enumerate(files):
            document.write_text('# 实例测试文档' + str(index + 1) + '\n', encoding='utf-8')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        environment = dict(os.environ, MDVIEW_DATA_DIR=str(directory / 'profile'),
                           QTWEBENGINE_REMOTE_DEBUGGING='127.0.0.1:' + str(port))
        if len(command) == 1:
            windows = environment.get('SystemRoot', r'C:\Windows')
            environment['PATH'] = os.pathsep.join([str(Path(windows) / 'System32'), windows])
            for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
                environment.pop(name, None)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        processes, clients = [], {}
        log = (directory / 'application.log').open('w', encoding='utf-8')

        def launch(*paths):
            process = subprocess.Popen([*command, *map(str, paths)], cwd=ROOT, env=environment,
                                       startupinfo=startup, stdout=log, stderr=log)
            processes.append(process)
            return process

        def pages():
            try:
                with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/json', timeout=.3) as response:
                    return [page for page in json.load(response) if page.get('type') == 'page' and 'index.html' in page.get('url', '')]
            except OSError:
                return []

        def page_contents():
            values = []
            for page in pages():
                if page['id'] not in clients:
                    clients[page['id']] = DebugClient(page['webSocketDebuggerUrl'])
                values.append(clients[page['id']].evaluate(
                    'return window.__editorReady && window.currentMarkdown ? window.currentMarkdown() : "";'))
            return values

        def session_paths():
            try:
                state = json.loads((directory / 'profile' / 'workspace.json').read_text(encoding='utf-8'))
                return {record['path'] for record in state.get('session', {}).get('documents', [])}
            except (OSError, ValueError):
                return set()

        def verify_open_files(expected):
            # Background files intentionally have no rendered page until selected.
            wait_until(lambda: session_paths() == set(map(str, expected)))
            for document in expected:
                secondary_finished(launch(document))
                heading = document.read_text(encoding='utf-8').strip()
                wait_until(lambda: any(heading in text for text in page_contents()))

        def secondary_finished(process):
            wait_until(lambda: process.poll() is not None, 15)
            assert process.returncode == 0, 'Secondary launch failed: ' + (directory / 'application.log').read_text(encoding='utf-8')

        def application_pid():
            # Windows venv 的 python.exe 是启动器，实际 Qt 窗口属于它的子进程。
            return int((directory / 'profile' / 'instance.lock').read_text(encoding='utf-8').splitlines()[0])

        def terminate_application(pid):
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(1, False, pid)
            assert handle
            try:
                assert kernel.TerminateProcess(ctypes.c_void_p(handle), 1)
            finally:
                kernel.CloseHandle(ctypes.c_void_p(handle))

        def close_application(process):
            pid = application_pid()
            for handle in window_handles(pid):
                USER32.PostMessageW(ctypes.c_void_p(handle), 0x0010, 0, 0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                terminate_application(pid)
                process.wait(timeout=5)

        try:
            primary = launch(files[0])
            wait_until(lambda: any('实例测试文档1' in text for text in page_contents()), 30)
            assert len(window_handles(application_pid())) == 1
            first = next(iter(clients.values()))
            first.evaluate('window.__setEditorValue(window.currentMarkdown()+"\\n未保存的内容必须保留\\n");return true;')
            wait_until(lambda: '未保存的内容必须保留' in first.evaluate('return window.currentMarkdown();'))

            secondary_finished(launch(files[1]))
            wait_until(lambda: len(pages()) == 2 and any('实例测试文档2' in text for text in page_contents()))
            assert len(window_handles(application_pid())) == 1
            assert '未保存的内容必须保留' in first.evaluate('return window.currentMarkdown();')
            assert '未保存的内容必须保留' not in files[0].read_text(encoding='utf-8')
            print('PASS - Second OS launch opens in the same window and preserves unsaved edits', flush=True)

            secondary_finished(launch(str(files[0]).swapcase()))
            assert len(pages()) == 2 and len(window_handles(application_pid())) == 1
            assert '未保存的内容必须保留' in first.evaluate('return window.currentMarkdown();')
            print('PASS - Reopening the same file focuses its existing editor without reloading it', flush=True)

            concurrent = [launch(files[2]), launch(files[3])]
            for process in concurrent:
                secondary_finished(process)
            verify_open_files(files)
            assert len(window_handles(application_pid())) == 1
            print('PASS - Concurrent launch requests all reach one existing window', flush=True)

            handle = window_handles(application_pid())[0]
            USER32.ShowWindow(ctypes.c_void_p(handle), 6)
            wait_until(lambda: bool(USER32.IsIconic(ctypes.c_void_p(handle))))
            secondary_finished(launch())
            wait_until(lambda: not USER32.IsIconic(ctypes.c_void_p(handle)))
            assert session_paths() == set(map(str, files)) and len(window_handles(application_pid())) == 1
            print('PASS - Launching again restores a minimized window without adding a document', flush=True)

            for client in clients.values():
                client.evaluate('window.markClean();return true;')
                client.socket.close()
            clients.clear()
            time.sleep(.15)
            close_application(primary)
            assert primary.poll() == 0
            assert not (directory / 'profile' / 'instance.lock').exists()

            # 在冷启动期间同时请求多个路径，覆盖抢占锁和启动请求排队。
            attempts = [launch(files[0]), launch(files[1], files[2])]
            verify_open_files(files[:3])
            wait_until(lambda: sum(process.poll() is None for process in attempts) == 1)
            primary = next(process for process in attempts if process.poll() is None)
            assert len(window_handles(application_pid())) == 1
            assert all(process.poll() in (None, 0) for process in attempts)
            print('PASS - Simultaneous cold starts create one process and retain every file argument', flush=True)

            for client in clients.values():
                client.socket.close()
            clients.clear()
            terminate_application(application_pid())
            primary.wait(timeout=5)
            primary = launch(files[3])
            wait_until(lambda: len(pages()) == 1 and any('实例测试文档4' in text for text in page_contents()), 30)
            assert len(window_handles(application_pid())) == 1
            print('PASS - Crash recovery clears the stale process lock and permits a fresh launch', flush=True)
            print('SINGLE_INSTANCE: PASSED', flush=True)
        except Exception:
            log.flush()
            print((directory / 'application.log').read_text(encoding='utf-8'), flush=True)
            raise
        finally:
            for client in clients.values():
                try:
                    client.evaluate('window.markClean();return true;')
                    client.socket.close()
                except (AssertionError, RuntimeError):
                    pass
            for process in processes:
                if process.poll() is None:
                    close_application(process)
            log.close()


if __name__ == '__main__':
    run([str(Path(sys.argv[1]).resolve())] if len(sys.argv) > 1 else [sys.executable, str(ROOT / 'main.py')])
