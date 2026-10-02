"""Native footer regression: resize while the renderer is busy, and tab ownership."""
import json
import os
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow, WORKSPACE_FOOTER_HEIGHT


def run():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(directory) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewFooterTest')
        app.setApplicationName('MarkdownViewFooterTest')
        settings = QSettings()
        settings.setValue('appearance/theme', 'light')
        settings.setValue('appearance/language', 'zh_CN')
        settings.setValue('appearance/sidebarVisible', True)
        source = Path(directory) / 'alignment.md'
        source.write_text('# 对齐\n\n你好 world。\n\n' + '\n\n'.join(
            '第%d段，公式 $x^2$ 与正文。' % i for i in range(50)), encoding='utf-8')
        win = MainWindow(startup_file=str(source))
        win.resize(1100, 720)
        win.show()

        def wait(predicate, timeout=8):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if predicate():
                    return
                QTest.qWait(20)
            raise AssertionError('Timed out')

        def js(code, tab=None):
            result = []
            (tab or win.current_tab()).view.page().runJavaScript(
                'JSON.stringify((function(){' + code + '})())', result.append)
            wait(lambda: bool(result))
            assert result[0] is not None, code
            return json.loads(result[0])

        def check_alignment(window):
            footer = window.editor_status
            bottom = window.centralWidget().mapTo(window, QPoint(0, window.centralWidget().height())).y()
            bottom -= window.centralWidget().layout().contentsMargins().bottom()
            assert footer.mapTo(window, QPoint(0, footer.height())).y() == bottom
            assert footer.height() == WORKSPACE_FOOTER_HEIGHT
            assert window.view.mapTo(window, QPoint(0, window.view.height())).y() == footer.mapTo(window, QPoint()).y()
            if window.sidebar.isVisible():
                theme = window._theme_button
                theme_center = theme.mapTo(window, theme.rect().center()).y()
                for widget in (footer.counter, footer.mode, footer.format):
                    if widget.isVisible():
                        center = widget.mapTo(window, widget.rect().center()).y()
                        assert abs(center - theme_center) <= 1, (center, theme_center)
                        assert widget.font().pixelSize() == theme.font().pixelSize() == 11
            assert footer.counter.width() >= footer.counter.sizeHint().width()

        try:
            wait(lambda: win.current_tab().ready and win.current_tab().document_status[0] > 0)
            QTest.qWait(250)
            first = win.current_tab()
            before = js('return window.currentMarkdown();')
            total = first.document_status[0]
            assert win.editor_status.counter.text() == f'字数 {total}'
            assert js("return getComputedStyle(document.getElementById('editor-statusbar')).display;") == 'none'
            assert js("return document.getElementById('vditor').getBoundingClientRect().bottom === innerHeight;")
            check_alignment(win)
            # The actual painted separator belongs to Qt, including dark mode.
            for expected in ('#e7e7e2', '#333330'):
                pixels = win.editor_status.grab().toImage()
                assert pixels.pixelColor(pixels.width() // 2, 0).name() == expected
                check_alignment(win)
                win.toggle_theme(); QTest.qWait(100)

            # Delay only this test renderer. Qt must keep its footer/line aligned
            # through every size change, without waiting for a browser frame.
            rendered = []
            first.view.page().runJavaScript(
                'var until=performance.now()+2200; while(performance.now()<until){}; true;', rendered.append)
            QTest.qWait(60)
            checked = 0
            for i in range(18):
                assert not rendered, 'Resize probe must run before the renderer catches up'
                win.setGeometry(90 + i * 2, 70 + i, 980 + (i % 6) * 30, 600 + (i % 7) * 16)
                QTest.qWait(12)
                check_alignment(win)
                checked += 1
            win.grab().save(str(Path('tmp/footer-during-resize.png').resolve()))
            wait(lambda: bool(rendered))
            assert js('return window.currentMarkdown();') == before and not first.dirty
            print('PASS - Footer and separator aligned during %d resizes with busy renderer' % checked, flush=True)

            second = win.new_tab()
            wait(lambda: second.ready)
            js("window.setContent('one two three');return true;")
            wait(lambda: second.document_status[0] == 3)
            assert win.editor_status.counter.text() == '字数 3'
            win.tabs.setCurrentWidget(first.view)
            assert win.editor_status.counter.text() == f'字数 {total}'
            js("window.setContent('one two three four');return true;", second)
            wait(lambda: second.document_status[0] == 4)
            assert win.editor_status.counter.text() == f'字数 {total}', 'Background editor changed active footer'
            win.detach_tab(win.tabs.indexOf(second.view))
            child = second.window
            QTest.qWait(220)
            assert child.editor_status.counter.text() == '字数 4'
            check_alignment(child)
            win.set_language('en')
            assert win.editor_status.counter.text() == f'Words {total}'
            assert child.editor_status.counter.text() == 'Words 4'
            assert win.editor_status.mode.text() == 'Instant rendering'
            js("document.querySelector('[data-mode=sv]').click();return true;")
            wait(lambda: win.editor_status.mode.text() == 'Source')
            win.set_language('zh_CN')
            assert win.editor_status.mode.text() == '源代码'
            print('PASS - Active/background/detached document counts, modes and languages', flush=True)

            child.close(); QTest.qWait(100)
            win.resize(480, 360); QTest.qWait(100)
            check_alignment(win)
            assert win.width() == 480 and not win.editor_status.mode.isVisible() and not win.editor_status.format.isVisible()
            win._sidebar_action.setChecked(False); QTest.qWait(100)
            check_alignment(win)
            win.resize(1100, 720); QTest.qWait(100)
            js('window.toggleFullscreen();return true;'); QTest.qWait(250)
            assert win.isFullScreen()
            check_alignment(win)
            assert js("return document.getElementById('vditor').getBoundingClientRect().bottom === innerHeight;")
            js('window.toggleFullscreen();return true;'); QTest.qWait(250)
            win._sidebar_action.setChecked(True)
            check_alignment(win)
            win.grab().save(str(Path('tmp/footer-aligned.png').resolve()))
            assert not js('return window.__err;')
            print('PASS - Narrow window, hidden sidebar, fullscreen, content preservation', flush=True)
        finally:
            for window in list(win.store.windows):
                if not window._closed:
                    for tab in window._tab_list:
                        tab.dirty = False
                    window.close()
            QTest.qWait(100)


if __name__ == '__main__':
    run()
