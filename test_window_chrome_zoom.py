"""Check painted resize edges and real page-zoom shortcuts in the Qt window."""
import json
import os
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(folder) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewChromeZoomTest')
        app.setApplicationName('MarkdownViewChromeZoomTest')
        settings = QSettings()
        settings.setValue('appearance/theme', 'light')
        settings.setValue('appearance/sidebarVisible', True)
        settings.setValue('appearance/language', 'zh_CN')
        source = Path(folder) / 'zoom.md'
        source.write_text('# 页面缩放\n\n你好 world。\n\n' + '\n\n'.join(
            '第%d段，公式 $x^2$ 与文字。' % i for i in range(40)), encoding='utf-8')
        win = MainWindow(startup_file=str(source))
        win.setGeometry(110, 80, 1080, 720)
        win.show()

        def wait(predicate):
            until = time.monotonic() + 10
            while time.monotonic() < until:
                if predicate():
                    return
                QTest.qWait(25)
            raise AssertionError('Timed out')

        def js(code, window=win):
            result = []
            window.view.page().runJavaScript('JSON.stringify((function(){' + code + '})())', result.append)
            wait(lambda: bool(result))
            assert result[0] is not None, code
            return json.loads(result[0])

        def key(key, modifiers=Qt.KeyboardModifier.ControlModifier, window=win):
            window.activateWindow()
            window.view.setFocus()
            QTest.qWait(40)
            QTest.keyClick(window.view.focusProxy(), key, modifiers)
            QTest.qWait(120)

        def wheel(delta, modifiers=Qt.KeyboardModifier.ControlModifier):
            proxy = win.view.focusProxy()
            point = QPoint(240, 220)
            event = QWheelEvent(QPointF(point), QPointF(proxy.mapToGlobal(point)), QPoint(),
                                QPoint(0, delta), Qt.MouseButton.NoButton, modifiers,
                                Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(proxy, event)
            QTest.qWait(100)

        def edges():
            # Allow WebEngine's compositor to finish maximize/theme transitions;
            # pixels on a maximized edge belong to the editor rather than grips.
            QTest.qWait(350)
            workspace = win.centralWidget()
            pixels = workspace.grab().toImage()
            dpr = pixels.devicePixelRatio()
            def color(x, y):
                return pixels.pixelColor(int(x * dpr), int(y * dpr)).name()
            canvas, panel = ('#20201e', '#181816') if win._theme == 'dark' else ('#ffffff', '#f5f5f2')
            left = panel if win.sidebar.isVisible() else canvas
            width, height = workspace.width(), workspace.height()
            # Left, lower-left corner, sidebar bottom, lower-right and right.
            for x, y, expected in ((1, height // 2, left), (1, height - 2, left),
                                   (80, height - 2, left), (width - 2, height - 2, canvas),
                                   (width - 2, height // 2, canvas)):
                if color(x, y) != expected:
                    win.grab().save(str(Path('tmp/chrome-failed.png').resolve()))
                assert color(x, y) == expected, (x, y, color(x, y), expected)
            assert win.view.page().backgroundColor().name() == canvas

        try:
            wait(lambda: win.current_tab().ready and win.current_tab().document_status[0] > 0)
            QTest.qWait(250)
            first = win.current_tab()
            original = js('return window.currentMarkdown();')
            frame = win.geometry()
            base_width = js('return innerWidth;')
            for theme in ('light', 'dark'):
                for visible in (True, False, True):
                    win._sidebar_action.setChecked(visible)
                    edges()
                    win.resize(win.width() + 13, win.height() + 7)
                    edges()
                win.showMaximized(); edges()
                win.showNormal(); edges()
                win.grab().save(str(Path('tmp/chrome-' + theme + '.png').resolve()))
                win.toggle_theme(); QTest.qWait(120)
            win.setGeometry(frame); QTest.qWait(100)
            print('PASS - Light/dark resize edges blend with each surface, with sidebar visible/hidden and maximized', flush=True)

            key(Qt.Key.Key_Equal)
            assert round(win.current_tab().zoom_factor * 100) == 110 and win.editor_status.zoom.text() == '110%'
            key(Qt.Key.Key_Plus)
            assert round(win.current_tab().zoom_factor * 100) == 120
            assert js('return innerWidth;') == base_width
            assert win.view.zoomFactor() == 1.0
            key(Qt.Key.Key_Minus)
            assert round(win.current_tab().zoom_factor * 100) == 110
            key(Qt.Key.Key_0)
            assert win.current_tab().zoom_factor == 1.0 and win.editor_status.zoom.text() == '100%'
            assert win.geometry() == frame, 'Page reset changed the outer window size'
            wheel(60); assert win.current_tab().zoom_factor == 1.0
            wheel(60); assert round(win.current_tab().zoom_factor * 100) == 110
            wheel(-120); assert win.current_tab().zoom_factor == 1.0
            wheel(-120, Qt.KeyboardModifier.NoModifier)
            assert win.current_tab().zoom_factor == 1.0, 'Ordinary scrolling changed zoom'
            win.set_page_zoom(1.5)
            assert '150%' in win.editor_status.zoom.toolTip() and 'Ctrl+0' in win.editor_status.zoom.toolTip()
            QTest.mouseClick(win.editor_status.zoom, Qt.MouseButton.LeftButton)
            assert win.current_tab().zoom_factor == 1.0
            for factor, expected in ((.1, .5), (9, 3.0)):
                win.set_page_zoom(factor)
                assert win.current_tab().zoom_factor == expected
            key(Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier)
            assert win.current_tab().zoom_factor == 1.0
            print('PASS - Ctrl +/-/0, numpad reset, Ctrl+wheel, percentage button and safe zoom limits', flush=True)

            # Source/rich text, search input and fullscreen must honor Ctrl+0.
            for mode in ('sv', 'wysiwyg', 'ir'):
                js("document.querySelector('[data-mode=" + mode + "]').click();return true;")
                QTest.qWait(180)
                win.set_page_zoom(1.4)
                key(Qt.Key.Key_0)
                assert win.current_tab().zoom_factor == 1.0, mode
            js('window.openFind(false);return true;')
            win.set_page_zoom(1.3)
            key(Qt.Key.Key_0)
            assert win.current_tab().zoom_factor == 1.0
            key(Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
            js('window.toggleFullscreen();return true;'); QTest.qWait(180)
            win.set_page_zoom(1.6)
            key(Qt.Key.Key_0)
            assert win.isFullScreen() and win.current_tab().zoom_factor == 1.0
            edges()
            js('window.toggleFullscreen();return true;'); QTest.qWait(180)

            win.set_page_zoom(1.2)
            second = win.new_tab(); wait(lambda: second.ready)
            assert win.editor_status.zoom.text() == '100%'
            win.tabs.setCurrentWidget(first.view)
            assert win.editor_status.zoom.text() == '120%'
            win.detach_tab(win.tabs.indexOf(first.view)); QTest.qWait(220)
            child = first.window
            assert child.editor_status.zoom.text() == '120%'
            key(Qt.Key.Key_0, window=child)
            assert child.current_tab().zoom_factor == 1.0 and win.current_tab().zoom_factor == 1.0
            win.set_language('en')
            assert child.editor_status.zoom.toolTip().startswith('Page zoom: 100%')
            assert any(a.text() == 'Reset zoom to 100%' for a in child.actions())
            assert js('return window.currentMarkdown();', child) == original and not first.dirty
            assert not js('return window.__err;', child)
            win.set_language('zh_CN')
            child.grab().save(str(Path('tmp/zoom-final.png').resolve()))
            print('PASS - Editor modes, fullscreen, tab switching, detach, language and document preservation', flush=True)
        finally:
            for window in list(win.store.windows):
                if not window._closed:
                    for tab in window._tab_list:
                        tab.dirty = False
                    window.close()
            QTest.qWait(100)


if __name__ == '__main__':
    run()
