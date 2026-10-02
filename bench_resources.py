"""Windows 进程树实测：私有提交内存、工作集、空闲 CPU 和文档切换延迟。"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow

ROOT = Path(__file__).resolve().parent
KERNEL = ctypes.windll.kernel32
KERNEL.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
KERNEL.OpenProcess.restype = ctypes.c_void_p


class ProcessEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                ('executable', wintypes.WCHAR * 260)]


class MemoryCounters(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('peak_working', 'working', 'peak_paged', 'paged',
                                          'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]


def process_snapshot():
    handle = KERNEL.CreateToolhelp32Snapshot(2, 0)
    entry = ProcessEntry(size=ctypes.sizeof(ProcessEntry))
    all_processes = {}
    try:
        exists = KERNEL.Process32FirstW(ctypes.c_void_p(handle), ctypes.byref(entry))
        while exists:
            all_processes[entry.pid] = (entry.parent, entry.executable)
            exists = KERNEL.Process32NextW(ctypes.c_void_p(handle), ctypes.byref(entry))
    finally:
        KERNEL.CloseHandle(ctypes.c_void_p(handle))
    descendants = {os.getpid()}
    while True:
        expanded = descendants | {pid for pid, (parent, _) in all_processes.items() if parent in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    result = {}
    for pid in descendants:
        handle = KERNEL.OpenProcess(0x410, False, pid)
        if not handle:
            continue
        try:
            counters = MemoryCounters(size=ctypes.sizeof(MemoryCounters))
            if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle), ctypes.byref(counters), counters.size):
                continue
            created, exited, kernel, user = [wintypes.FILETIME() for _ in range(4)]
            KERNEL.GetProcessTimes(ctypes.c_void_p(handle), *[ctypes.byref(item) for item in (created, exited, kernel, user)])
            ticks = sum((item.dwHighDateTime << 32) | item.dwLowDateTime for item in (kernel, user))
            result[pid] = {'name': all_processes.get(pid, (0, 'python.exe'))[1], 'private': counters.private,
                           'working': counters.working, 'cpu_seconds': ticks / 10_000_000}
        finally:
            KERNEL.CloseHandle(ctypes.c_void_p(handle))
    return result


def pump(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(.01)


def wait(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'Editor timed out'
        pump(.05)


def sample(window, name):
    # editorReady only means the editor API exists; formulas still render afterward.
    # Wait for two low-CPU intervals before measuring steady idle, up to 30 seconds.
    quiet = 0
    deadline = time.monotonic() + 30
    while quiet < 2 and time.monotonic() < deadline:
        previous = process_snapshot()
        started = time.monotonic()
        pump(2)
        current = process_snapshot()
        used = sum(max(0, info['cpu_seconds'] - previous.get(pid, info)['cpu_seconds']) for pid, info in current.items())
        quiet = quiet + 1 if used / (time.monotonic() - started) / os.cpu_count() < .003 else 0
    before = process_snapshot()
    start = time.monotonic()
    pump(4)
    elapsed = time.monotonic() - start
    after = process_snapshot()
    cpu = sum(max(0, info['cpu_seconds'] - before.get(pid, info)['cpu_seconds']) for pid, info in after.items())
    result = {'case': name, 'documents': len(window._tab_list), 'processes': len(after),
              'renderer_processes': len({tab.view.page().renderProcessPid() for tab in window._tab_list
                                        if tab.view.page().renderProcessPid()}),
              'private_mib': round(sum(info['private'] for info in after.values()) / 1024 ** 2, 1),
              'working_set_mib': round(sum(info['working'] for info in after.values()) / 1024 ** 2, 1),
              'idle_cpu_percent': round(cpu / elapsed / os.cpu_count() * 100, 3)}
    result['process_memory'] = [{'name': info['name'], 'private_mib': round(info['private'] / 1024 ** 2, 1)}
                                for info in after.values()]
    diagnostics = []
    window.current_tab().view.page().runJavaScript("JSON.stringify({nodes:document.querySelectorAll('*').length,heap:performance.memory && performance.memory.usedJSHeapSize,mode:window.__vditor && window.__vditor.getCurrentMode()})", diagnostics.append)
    wait(lambda: bool(diagnostics))
    result['page'] = json.loads(diagnostics[0])
    result['tabs'] = [{'initialized': getattr(tab, 'initialized', True), 'edited': getattr(tab, 'ever_edited', False),
                       'parked': getattr(tab, 'parked', False), 'visible': tab.view.page().isVisible()}
                      for tab in window._tab_list]
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def run(label):
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='resources-', dir=ROOT / 'tmp') as scratch:
        assert Path(scratch).resolve().is_relative_to(ROOT / 'tmp')
        os.environ['MDVIEW_DATA_DIR'] = str(Path(scratch) / 'profile')
        app = QApplication(sys.argv)
        app.setOrganizationName('MarkdownViewResourceBench')
        app.setApplicationName('MarkdownViewResourceBench')
        QSettings().setValue('appearance/sidebarVisible', True)
        source = (ROOT / '02_建模方法_SCI精简重构版.md').read_text(encoding='utf-8')
        files = []
        for index in range(8):
            path = Path(scratch) / ('资源样本 ' + str(index + 1) + '.md')
            path.write_text('# 资源样本' + str(index + 1) + '\n\n' + source, encoding='utf-8')
            files.append(path)
        start = time.monotonic()
        window = MainWindow(startup_file=str(files[0]))
        window.resize(1100, 760)
        window.show()
        try:
            wait(lambda: window.current_tab().ready)
            ready_ms = round((time.monotonic() - start) * 1000)
            results = [sample(window, 'one_document')]
            for path in files[1:]:
                window.open_file(str(path))
            wait(lambda: window.current_tab().ready)
            results.append(sample(window, 'eight_documents_open'))
            start = time.monotonic()
            window.tabs.setCurrentIndex(0)
            wait(lambda: window.current_tab().ready)
            response = []
            window.current_tab().view.page().runJavaScript('window.currentMarkdown()', response.append)
            wait(lambda: bool(response))
            switch_ms = round((time.monotonic() - start) * 1000)
            assert '资源样本1' in response[0]
            for index in range(8):
                window.tabs.setCurrentIndex(index)
                wait(lambda: window.current_tab().ready)
                pump(.15)
            results.append(sample(window, 'eight_documents_all_visited'))
            window.tabs.setCurrentIndex(0)
            for index in range(7, 0, -1):
                window.close_tab(index)
            results.append(sample(window, 'seven_documents_closed'))
            output = {'label': label, 'logical_processors': os.cpu_count(), 'document_bytes': len(source.encode('utf-8')),
                      'editor_ready_ms': ready_ms, 'switch_ms': switch_ms, 'samples': results}
            directory = ROOT / 'tmp' / 'resource-benchmark'
            directory.mkdir(exist_ok=True)
            (directory / (label + '.json')).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            print('RESOURCE_BENCHMARK: COMPLETED', flush=True)
        finally:
            for tab in window._tab_list:
                tab.dirty = False
            window.close()
            pump(.3)
            QSettings().clear()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='before')
    run(parser.parse_args().label)
