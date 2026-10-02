"""真实弹窗交互：主题、取消、放弃、保存以及另存为取消时保护文档。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow  # noqa: E402
from app.unsaved_dialog import UnsavedChangesDialog  # noqa: E402


def run():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(directory) / 'profile')
        app = QApplication(sys.argv)
        app.setOrganizationName('MarkdownViewDialogTest')
        app.setApplicationName('MarkdownViewDialogTest')
        settings = QSettings()
        settings.setValue('appearance/theme', 'light')
        source = Path(directory) / '设计笔记.md'
        source.write_text('Original content.', encoding='utf-8')
        window = MainWindow(startup_file=str(source))
        window.resize(1080, 740)
        window.show()
        errors = []

        def ready():
            for _ in range(100):
                QTest.qWait(100)
                if window.current_tab().ready:
                    return
            raise AssertionError('Editor did not become ready')

        def edit(content):
            tab = window.current_tab()
            tab.js('window.__setEditorValue(' + json.dumps(content) + ');')
            QTest.qWait(200)
            window.set_dirty(tab, True)
            return tab

        def respond(action, screenshot=None):
            def choose():
                dialog = QApplication.activeModalWidget()
                try:
                    assert isinstance(dialog, UnsavedChangesDialog), type(dialog)
                    assert dialog.save_button.isDefault()
                    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
                    assert dialog.name_label.toolTip() == window.current_tab().display_name()
                    for label in (dialog.name_label, dialog.path_label):
                        if label.fontMetrics().horizontalAdvance(label.toolTip()) > label.width():
                            assert '\u2026' in label.text(), label.text()
                    if screenshot:
                        assert dialog.grab().save(str(Path(screenshot).resolve()))
                    if action == 'escape':
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
                    elif action == 'cancel_enter':
                        dialog.cancel_button.setFocus()
                        QTest.keyClick(dialog.cancel_button, Qt.Key.Key_Return)
                    elif action == 'enter':
                        QTest.keyClick(dialog, Qt.Key.Key_Return)
                    else:
                        QTest.mouseClick(getattr(dialog, action + '_button'), Qt.MouseButton.LeftButton)
                except Exception as error:
                    errors.append(error)
                    if dialog:
                        dialog.reject()
            QTimer.singleShot(80, choose)

        try:
            ready()
            tab = edit('Unsaved content.')
            for theme in ('light', 'dark'):
                if window._theme != theme:
                    window.toggle_theme()
                respond('cancel', 'screenshot_unsaved_dialog_' + theme + '.png')
                window.close_tab(0)
                assert not errors, errors
                assert window.current_tab() is tab and tab.dirty
                assert source.read_text(encoding='utf-8') == 'Original content.'
            for action in ('escape', 'close', 'cancel_enter'):
                respond(action)
                window.close_tab(0)
                assert not errors, errors
                assert window.current_tab() is tab and tab.dirty
            print('PASS - Light/dark Chinese dialogs; Cancel, Escape and × keep the document open', flush=True)

            geometry = window.geometry()
            window.resize(480, 650)
            original_path = tab.filepath
            tab.filepath = str(Path(directory) / ('很长的文档名称' * 24 + '.md'))
            respond('close')
            window.close_tab(0)
            assert not errors, errors
            assert tab in window._tab_list and tab.dirty and not window._resize_drag_edges
            tab.filepath = original_path
            window.setGeometry(geometry)
            print('PASS - Long filenames are elided; dialog controls work in a narrow parent window', flush=True)

            respond('discard')
            window.close_tab(0)
            assert not errors, errors
            assert tab not in window._tab_list
            assert source.read_text(encoding='utf-8') == 'Original content.'
            print('PASS - Discard closes the document without changing the saved file', flush=True)

            window.open_file(str(source))
            ready()
            tab = edit('Saved by the new dialog.')
            respond('save')
            window.close_tab(window._tab_list.index(tab))
            QTest.qWait(500)
            assert not errors, errors
            assert source.read_text(encoding='utf-8').strip() == 'Saved by the new dialog.'
            assert tab not in window._tab_list
            print('PASS - Save writes the content before closing the document', flush=True)

            ready()
            unnamed = edit('Keep this unnamed draft.')
            with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
                respond('enter')
                window.close_tab(window._tab_list.index(unnamed))
                QTest.qWait(300)
            assert not errors, errors
            assert unnamed in window._tab_list and unnamed.dirty
            assert not unnamed.close_after_save and not unnamed.quit_after_save
            print('PASS - Enter saves by default; canceling Save As keeps an unnamed draft open', flush=True)

            respond('cancel')
            assert not window.close()
            assert not errors, errors
            assert window.isVisible() and unnamed.dirty and not window._closed
            respond('discard')
            assert window.close()
            assert not errors, errors
            assert window._closed
            print('PASS - The same dialog protects unsaved changes when exiting the entire window', flush=True)
        finally:
            for tab in window._tab_list:
                tab.dirty = False
            window.close()
            settings.clear()
            app.processEvents()
        print('UNSAVED_DIALOG: PASSED', flush=True)


if __name__ == '__main__':
    run()
