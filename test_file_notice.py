"""Unavailable-file navigation, read failures and protection against accidental writes."""
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        os.environ['MDVIEW_DATA_DIR'] = str(base / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewFileNoticeTest')
        app.setApplicationName('MarkdownViewFileNoticeTest')
        settings = QSettings()
        settings.clear()
        settings.setValue('appearance/sidebarVisible', True)
        source = base / '文档.md'
        source.write_text('# Keep my edits\n\nOriginal.', encoding='utf-8')
        python_file = base / 'example.py'
        python_file.write_text('raise RuntimeError("Do not execute")\n', encoding='utf-8')
        broken = base / '损坏.md'
        broken.write_bytes(b'\xff\xfeinvalid')
        binary = base / 'binary.txt'
        binary.write_bytes(b'hello\x00world')
        missing = base / '消失.md'
        missing.write_text('Will disappear', encoding='utf-8')
        win = MainWindow(startup_file=str(source))
        win.resize(1080, 760)
        win.show()
        windows = [win]

        def wait(predicate):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if predicate():
                    return
                QTest.qWait(25)
            raise AssertionError('Timed out')

        def js(tab, code):
            result = []
            tab.view.page().runJavaScript('JSON.stringify((function(){' + code + '})())', result.append)
            wait(lambda: bool(result))
            return json.loads(result[0])

        try:
            wait(lambda: win.current_tab().ready)
            original = win.current_tab()
            js(original, "window.setContent('# Unsaved content');window.notifyEdited();return true;")
            wait(lambda: original.dirty)
            win.open_project_folder(str(base))
            QTest.qWait(150)
            tree = win.project_explorer.tree
            index = win.project_explorer.model.index(str(python_file))
            tree.scrollTo(index)
            QTest.qWait(60)
            with patch('app.main_window.QMessageBox.warning') as warning:
                QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier, tree.visualRect(index).center())
                QTest.qWait(150)
                warning.assert_not_called()
            blocked = win.current_tab()
            assert blocked.filepath == str(python_file) and blocked.file_error == 'type'
            assert not blocked.initialized and not blocked.ready and not blocked.dirty
            assert blocked.file_notice.isVisible()
            assert blocked.file_notice.title.text() == '无法读取该类型文件'
            assert not blocked.file_notice.retry_button.isVisible()
            assert win.editor_status.mode.text() == '无法预览'
            assert not win.editor_status.counter.isVisible() and not win.editor_status.zoom.isVisible()
            assert all(not action.isEnabled() for action in win._document_actions)
            win.open_file(str(python_file))
            assert win.current_tab() is blocked and win.tabs.count() == 2
            previous_bytes = python_file.read_bytes()
            with patch('app.main_window.QFileDialog.getSaveFileName') as save_dialog:
                QTest.keyClick(blocked.file_notice, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
                win.save_file(blocked, '')
                win.export_docx(blocked, '')
                win.export_pdf(blocked)
                blocked.js('window.requestSave()')
                win.set_dirty(blocked, True)
                save_dialog.assert_not_called()
            assert not blocked.dirty and not blocked.pending_commands and python_file.read_bytes() == previous_bytes
            assert original.dirty and js(original, 'return window.currentMarkdown();').startswith('# Unsaved content')
            title = blocked.file_notice.title
            title_pos = title.mapTo(blocked.view, title.rect().center())
            assert blocked.view.childAt(title_pos) is title, (blocked.view.childAt(title_pos), title.geometry(), blocked.file_notice.geometry())
            win.grab().save(str(Path('tmp/file-notice-light.png').resolve()))
            win.toggle_theme()
            QTest.qWait(100)
            win.grab().save(str(Path('tmp/file-notice-dark.png').resolve()))
            win.set_language('en')
            assert blocked.file_notice.title.text() == 'Cannot read this file type'
            assert blocked.file_notice.filename.text() == python_file.name
            assert win.editor_status.mode.text() == 'Preview unavailable'
            win.resize(480, 360)
            QTest.qWait(100)
            assert win.size().width() == 480 and win.size().height() == 360
            assert blocked.file_notice.close_button.isVisible()
            assert blocked.file_notice.geometry() == blocked.view.rect(), (blocked.file_notice.geometry(), blocked.view.rect(), blocked.view.layout(), blocked.file_notice.parent())
            long_path = base / ('long_file_name_' * 10 + '.py')
            long_path.write_text('pass', encoding='utf-8')
            long_tab = win.open_file(str(long_path))
            QTest.qWait(100)
            assert win.width() == 480 and long_tab.file_notice.width() == long_tab.view.width()
            assert long_tab.file_notice.filename.width() <= long_tab.file_notice.width()
            win.close_tab(win.tabs.currentIndex())
            win.resize(1080, 760)
            win.set_language('zh_CN')
            win.open_file(str(source))
            assert win.current_tab() is original
            assert all(action.isEnabled() for action in win._document_actions)
            assert win.editor_status.counter.isVisible()
            print('PASS - Native notice, duplicate open, disabled editing, unchanged files and original unsaved text', flush=True)

            # Corrupt encoding and binary content must never become blank editable files.
            for path in (broken, binary):
                tab = win.open_file(str(path))
                wait(lambda: tab.file_error == 'encoding')
                assert tab.file_notice.isVisible() and not tab.ready
                before = path.read_bytes()
                win.save_file(tab, '')
                assert path.read_bytes() == before
                assert not tab.dirty and not tab.pending_commands
            retry_tab = win.open_file(str(broken))
            broken.write_text('# 已修复\n\n正常文本。', encoding='utf-8')
            QTest.mouseClick(retry_tab.file_notice.retry_button, Qt.MouseButton.LeftButton)
            wait(lambda: retry_tab.ready and not retry_tab.file_error)
            assert not retry_tab.file_notice.isVisible()
            assert '已修复' in js(retry_tab, 'return window.currentMarkdown();')
            vanished = win.open_file(str(missing))
            missing.unlink()  # Race between choosing a file and loading its editor.
            wait(lambda: vanished.file_error == 'read')
            missing.write_text('# Restored file', encoding='utf-8')
            QTest.mouseClick(vanished.file_notice.retry_button, Qt.MouseButton.LeftButton)
            wait(lambda: vanished.ready and not vanished.file_error)
            assert 'Restored file' in js(vanished, 'return window.currentMarkdown();')
            print('PASS - Encoding/binary failures, missing-file race and retry recovery without overwrites', flush=True)

            win.open_file(str(python_file))
            win.detach_tab(win.tabs.currentIndex())
            detached = blocked.window
            windows.append(detached)
            QTest.qWait(220)
            assert detached is not win and detached.current_tab() is blocked
            assert blocked.file_notice.isVisible() and not blocked.initialized
            assert all(not action.isEnabled() for action in detached._document_actions)
            QTest.mouseClick(blocked.file_notice.close_button, Qt.MouseButton.LeftButton)
            assert blocked not in detached._tab_list
            assert detached.tabs.count() == 1 and not detached.current_tab().filepath
            detached.close()
            # Unsupported files survive ordinary session restoration as notices.
            restored_notice = win.open_file(str(python_file))
            original.dirty = False
            win.close()
            win.store.initial_session = win.store.state['session']
            restored = MainWindow(restore_session=True)
            windows.append(restored)
            restored.show()
            QTest.qWait(150)
            assert restored.current_tab().filepath == str(python_file)
            assert restored.current_tab().file_error == 'type'
            assert not restored.current_tab().initialized
            print('PASS - Themes, languages, minimum size, detachment, close and session restoration', flush=True)
        finally:
            for window in windows:
                for tab in window._tab_list:
                    tab.dirty = False
                if not window._closed:
                    window.close()
            QTest.qWait(150)
            settings.clear()


if __name__ == '__main__':
    run()
