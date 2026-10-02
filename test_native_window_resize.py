"""Windows resize integration: real SC_SIZE loop, no global mouse/key injection.

Only the test HWND receives queued mouse messages. WM_SIZING proposals are
constrained to deterministic rectangles so tests do not depend on the user's
cursor location or screen scaling. This verifies the native path, not visual FPS.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
import threading

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow

USER32 = ctypes.WinDLL('user32', use_last_error=True) if os.name == 'nt' else None
if USER32:
    USER32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    USER32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]


class NativeWindow(MainWindow):
    target = None
    cancel_resize = False

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if self.target is not None:
            if msg.message == 0x112 and (msg.wParam & 0xFFF0) == 0xF000:
                self.commands.append(msg.wParam & 0xF)
            elif msg.message == 0x231:  # WM_ENTERSIZEMOVE
                self.started += 1
                if self.cancel_resize:
                    USER32.PostMessageW(msg.hWnd, 0x100, 0x1B, 0)  # Esc, only this HWND
                else:
                    point = wintypes.POINT()
                    USER32.GetCursorPos(ctypes.byref(point))
                    point.x += 30
                    USER32.ScreenToClient(msg.hWnd, ctypes.byref(point))
                    position = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
                    USER32.PostMessageW(msg.hWnd, 0x200, 1, position)
                    USER32.PostMessageW(msg.hWnd, 0x202, 0, position)
            elif msg.message == 0x214:  # WM_SIZING; constrain the OS proposal in the test
                self.sizing.append(msg.wParam)
                rect = wintypes.RECT.from_address(msg.lParam)
                rect.left, rect.top, rect.right, rect.bottom = self.target
                return True, 1
            elif msg.message == 0x232:  # WM_EXITSIZEMOVE
                self.finished += 1
        return super().nativeEvent(event_type, message)


def run():
    if not USER32:
        print('SKIP - Windows-only native resize integration')
        return
    with tempfile.TemporaryDirectory() as directory:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(directory) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewNativeResizeTest')
        app.setApplicationName('MarkdownViewNativeResizeTest')
        source = Path(directory) / 'resize.md'
        source.write_text('# 原生缩放\n\n' + '\n\n'.join('第%d段，保留正文、$x^2$ 公式和阅读位置。' % i for i in range(50)), encoding='utf-8')
        win = NativeWindow(startup_file=str(source))
        original = QRect(130, 110, 950, 650)
        win.setGeometry(original)
        win.show()

        def js(code):
            result = []; loop = QEventLoop()
            win.view.page().runJavaScript(code, lambda value: (result.append(value), loop.quit()))
            QTimer.singleShot(6000, loop.quit); loop.exec()
            assert result, 'Editor did not respond'
            return result[0]

        try:
            for _ in range(100):
                QTest.qWait(100)
                if win.current_tab().ready:
                    break
            assert win.current_tab().ready
            QTest.qWait(250)
            body = js('window.currentMarkdown()')
            js("document.querySelector('.vditor-ir pre').scrollTop=300")
            left, right, top, bottom = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
            codes = {left: 1, right: 2, top: 3, top|left: 4, top|right: 5, bottom: 6, bottom|left: 7, bottom|right: 8}
            for grip, edges in win._resize_handles.items():
                win.setGeometry(original); QTest.qWait(60)
                rect = wintypes.RECT()
                hwnd = int(win.winId())
                assert USER32.GetWindowRect(hwnd, ctypes.byref(rect))
                expected = [rect.left, rect.top, rect.right, rect.bottom]
                for i, edge in enumerate((left, top, right, bottom)):
                    if edges & edge:
                        expected[i] += -40 if i < 2 else 40
                win.target = expected
                win.commands = []; win.sizing = []; win.started = win.finished = 0
                point = QPoint(2, 2)
                if edges & right: point.setX(grip.width()-2)
                if edges & bottom: point.setY(grip.height()-2)
                # A hung native loop cannot hold up the test or another app.
                watchdog = threading.Timer(5, lambda: USER32.PostMessageW(hwnd, 0x100, 0x1B, 0))
                watchdog.start()
                try:
                    QTest.mousePress(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
                    for _ in range(50):
                        QTest.qWait(20)
                        if win.finished:
                            break
                finally:
                    watchdog.cancel()
                assert win.commands == [codes[edges]], (edges, win.commands)
                assert win.started == win.finished == 1 and win.sizing, (edges, win.started, win.finished)
                assert all(code == codes[edges] for code in win.sizing)
                assert USER32.GetWindowRect(hwnd, ctypes.byref(rect))
                assert [rect.left, rect.top, rect.right, rect.bottom] == expected, (edges, expected, rect)
                assert not win._resize_timer.isActive() and not win._resize_drag_edges
                assert win._resize_pending_geometry is None and QWidget.mouseGrabber() is None
                settled = win.geometry(); QTest.qWait(80)
                assert win.geometry() == settled, 'Delayed fallback geometry overwrote native size'
                win.target = None
                print('PASS - Native Windows resize direction', codes[edges], 'commits without timer or mouse capture', flush=True)
            # Escape lets Windows cancel without any pending Python geometry.
            win.setGeometry(original); QTest.qWait(100)
            win.target = [0, 0, 1, 1]; win.cancel_resize = True
            win.commands = []; win.sizing = []; win.started = win.finished = 0
            grip = next(g for g,e in win._resize_handles.items() if e == right)
            QTest.mousePress(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2,20))
            QTest.qWait(180)
            assert win.finished == 1 and win.geometry() == original
            win.target = None
            assert js('window.currentMarkdown()') == body and not win.current_tab().dirty
            assert js("document.querySelector('.vditor-ir pre').scrollTop") > 200
            win.grab().save(str(Path('tmp/native-resize-final.png').resolve()))
            print('PASS - Native cancellation, document content and reading position', flush=True)
            print('NATIVE_RESIZE: PASSED', flush=True)
        finally:
            win.target = None
            win.current_tab().dirty = False
            win.close(); QTest.qWait(100)


if __name__ == '__main__':
    run()
