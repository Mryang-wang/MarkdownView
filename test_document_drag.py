"""向真实侧栏行发送 Qt 输入事件，验证排序、分离和取消，不点击其他应用。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.single_instance import SingleInstance
from main import open_in_running_window

ROOT = Path(__file__).resolve().parent
(ROOT / 'tmp').mkdir(exist_ok=True)
scratch = tempfile.TemporaryDirectory(prefix='document-drag-', dir=ROOT / 'tmp')
assert Path(scratch.name).resolve().is_relative_to(ROOT / 'tmp')
os.environ['MDVIEW_DATA_DIR'] = scratch.name
app = QApplication(sys.argv)
app.setOrganizationName('MarkdownViewDragTest')
app.setApplicationName('MarkdownViewDragTest')
settings = QSettings()
settings.setValue('appearance/sidebarVisible', True)
settings.setValue('appearance/theme', 'light')
win = MainWindow(create_initial_tab=False)
win.setGeometry(60, 60, 920, 700)
files = [Path(scratch.name) / name for name in ('拖出 文档.md', '保留 文档.md', '第三个 文档.md')]
for index, path in enumerate(files):
    path.write_text('# 拖拽文档' + str(index + 1) + '\n', encoding='utf-8')
tabs = [win.open_file(str(path)) for path in files]
win.show()
instance = SingleInstance(app)
assert instance.start_or_forward([])
instance.set_handler(lambda paths: open_in_running_window(win, paths))
app.aboutToQuit.connect(instance.close)
launches = []
failures = []
finished = False
started = time.monotonic()


def check(name, condition):
    print(('PASS' if condition else 'FAIL') + ' - ' + name, flush=True)
    if not condition:
        failures.append(name)


def later(callback, delay=150):
    def checked():
        if finished:
            return
        try:
            callback()
        except Exception as error:
            check(repr(error), False)
            finish()
    QTimer.singleShot(delay, checked)


def send_mouse(widget, kind, position, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton):
    event = QMouseEvent(kind, QPointF(widget.mapFromGlobal(position)), QPointF(position),
                        button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def begin_drag(row, destination, after, escape=False):
    win.document_list.setCurrentRow(row)
    receiver = win.document_list.itemWidget(win.document_list.item(row))
    start = receiver.mapToGlobal(receiver.rect().center())
    send_mouse(receiver, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    later(lambda: send_mouse(receiver, QEvent.Type.MouseMove, start + QPoint(0, 16)), 50)
    later(lambda: send_mouse(receiver, QEvent.Type.MouseMove, destination), 100)
    if escape:
        later(lambda: QApplication.sendEvent(win.document_list,
              QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)), 150)
    later(lambda: send_mouse(receiver, QEvent.Type.MouseButtonRelease, destination,
                            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton), 220)
    later(after, 400)


def initial():
    win.tabs.setCurrentWidget(tabs[0].view)
    if not tabs[0].ready:
        if time.monotonic() - started > 20:
            check('Editors initialized', False)
            return finish()
        return later(initial)
    tabs[0].js('window.__setEditorValue(window.currentMarkdown()+"\\n尚未保存的拖拽内容\\n");')
    later(start_reorder, 300)


def start_reorder():
    check('Edited document is dirty before dragging', tabs[0].dirty)
    rect = win.document_list.visualItemRect(win.document_list.item(2))
    destination = win.document_list.viewport().mapToGlobal(rect.center())
    begin_drag(0, destination, reordered)


def reordered():
    check('Sidebar drag reorders documents without creating another window',
          len(win._detached_windows) == 0 and win._tab_list[-1] is tabs[0])
    check('Sidebar order matches editor ownership after sorting',
          all(win.document_list.itemWidget(win.document_list.item(i)).tab is tab for i, tab in enumerate(win._tab_list)))
    inside = win.tabs.mapToGlobal(win.tabs.rect().center())
    begin_drag(win.tabs.indexOf(tabs[0].view), inside, inside_cancelled)


def inside_cancelled():
    check('Dropping inside the editor does not detach a document', len(win._detached_windows) == 0)
    outside = win.frameGeometry().topRight() + QPoint(100, 200)
    begin_drag(win.tabs.indexOf(tabs[0].view), outside, detached)


def detached():
    check('Releasing a document outside the window creates exactly one second window', len(win._detached_windows) == 1)
    child = next(iter(win._detached_windows), None)
    if child is None:
        return finish()
    check('Dragging transfers the existing editor and dirty state',
          child.current_tab() is tabs[0] and tabs[0].window is child and tabs[0].dirty and len(win._tab_list) == 2)
    tabs[0].view.page().runJavaScript('window.currentMarkdown()', content_verified)


def content_verified(content):
    check('Unsaved text remains intact in the detached window', '尚未保存的拖拽内容' in content)
    child = next(iter(win._detached_windows))
    pasted = []
    original_clipboard, original_paste = QApplication.clipboard, child._paste_clipboard_image
    try:
        QApplication.clipboard = staticmethod(lambda: SimpleNamespace(mimeData=lambda: SimpleNamespace(hasImage=lambda: True)))
        child._paste_clipboard_image = pasted.append
        QApplication.sendEvent(tabs[0].view.focusProxy(), QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier))
        check('Screenshot paste routes to the detached document', pasted == [tabs[0]])
    finally:
        QApplication.clipboard, child._paste_clipboard_image = original_clipboard, original_paste
    check('New-window menu/shortcut removed; detachment comes from dragging',
          all('独立窗口' not in action.text() for action in win._file_menu.actions()))
    outside = win.frameGeometry().bottomRight() + QPoint(100, -80)
    begin_drag(0, outside, cancelled, escape=True)


def cancelled():
    check('Esc cancels an outside drag without creating a third window',
          len(win._detached_windows) == 1 and len(win._tab_list) == 2)
    check('Drag preview is removed after release or cancellation', win.document_list._drag_preview is None)
    child = next(iter(win._detached_windows))
    QApplication.sendEvent(child, QEvent(QEvent.Type.WindowActivate))
    path = Path(scratch.name) / '外部新打开 文档.md'
    path.write_text('# 独立窗口接收外部请求\n', encoding='utf-8')
    launch_external(path, lambda: routed_to_child(child, path))


def launch_external(path, after):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen([sys.executable, str(ROOT / 'main.py'), str(path)],
                               env=dict(os.environ), startupinfo=startup)
    launches.append(process)
    deadline = time.monotonic() + 15
    def received():
        if process.poll() is None and time.monotonic() < deadline:
            return later(received, 50)
        check('External launcher hands off its file and exits successfully', process.poll() == 0)
        later(after, 300)
    later(received, 50)


def routed_to_child(child, path):
    check('External open uses the last active detached window without a third window',
          len(win._detached_windows) == 1 and len(child._tab_list) == 2 and child.current_tab().filepath == str(path))
    win.close()
    check('Original window can close while a detached document remains open', win._closed and not child._closed)
    launch_external(path, lambda: after_parent_closed(child))


def after_parent_closed(child):
    check('Requests still reach the surviving detached window after the original closes',
          len(child._tab_list) == 2 and not child._closed)
    finish()


def finish():
    global finished
    if finished:
        return
    finished = True
    for process in launches:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    for window in [*win._detached_windows, win]:
        for tab in window._tab_list:
            tab.dirty = False
        window.close()
    settings.clear()
    instance.close()
    print('DOCUMENT_DRAG:', 'PASSED' if not failures else 'FAILED ' + repr(failures), flush=True)
    app.exit(1 if failures else 0)


later(initial, 500)
QTimer.singleShot(30000, lambda: (check('Drag test completed within timeout', False), finish()) if not finished else None)
code = app.exec()
scratch.cleanup()
sys.exit(code)
