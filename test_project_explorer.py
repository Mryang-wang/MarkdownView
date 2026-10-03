"""Project navigation through real Qt mouse/keyboard events and filesystem changes."""
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        os.environ['MDVIEW_DATA_DIR'] = str(base / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewProjectTest')
        app.setApplicationName('MarkdownViewProjectTest')
        settings = QSettings()
        settings.clear()
        settings.setValue('appearance/theme', 'light')
        settings.setValue('appearance/sidebarVisible', True)
        settings.setValue('files/restoreSession', True)
        root = base / '项目 示例'
        nested = root / '章节'
        nested.mkdir(parents=True)
        (root / '图片').mkdir()
        (root / 'README.md').write_text('# 项目概览\n\n项目说明。', encoding='utf-8')
        (root / 'notes.txt').write_text('项目笔记', encoding='utf-8')
        (root / 'image.png').write_bytes(b'\x89PNG\xff')
        (root / '.hidden.md').write_text('# Hidden', encoding='utf-8')
        nested_file = nested / '设计说明.MD'
        nested_file.write_text('# 设计说明\n\n嵌套文档。', encoding='utf-8')
        empty = base / '空项目'
        empty.mkdir()
        win = MainWindow()
        win.resize(1080, 760)
        win.show()
        windows = [win]

        def wait(predicate):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if predicate():
                    return
                QTest.qWait(30)
            raise AssertionError('Timed out')

        def click_file(path):
            explorer = win.project_explorer
            index = explorer.model.index(str(path))
            assert index.isValid(), path
            explorer.tree.scrollTo(index)
            QTest.qWait(60)
            rect = explorer.tree.visualRect(index)
            assert rect.isValid(), path
            QTest.mouseClick(explorer.tree.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, rect.center())
            QTest.qWait(120)

        try:
            wait(lambda: win.current_tab().ready)
            with patch('app.main_window.QFileDialog.getExistingDirectory', return_value=str(root)):
                QTest.mouseClick(win._sidebar_buttons['project'], Qt.MouseButton.LeftButton)
            explorer = win.project_explorer
            tree = explorer.tree
            wait(lambda: explorer.count.text() == '文件 4 · 文件夹 2')
            assert win.tabs.count() == 1 and not win.current_tab().filepath
            assert explorer.root_path == str(root)
            assert explorer.isVisible() and win._close_project_action.isEnabled()
            model = explorer.model
            nested_index = model.index(str(nested))
            assert not tree.isExpanded(nested_index)
            assert model.rowCount(nested_index) == 0, 'Collapsed folder was eagerly traversed'
            assert model.isDir(model.index(0, 0, tree.rootIndex())), 'Folders must sort before files'
            click_file(nested)
            wait(lambda: tree.isExpanded(nested_index) and model.rowCount(nested_index) == 1)
            click_file(nested_file)
            wait(lambda: win.current_tab().ready and win.current_tab().filepath == str(nested_file))
            assert len([w for w in win.store.windows if not w._closed]) == 1
            count = win.tabs.count()
            click_file(nested_file)
            assert win.tabs.count() == count
            click_file(root / 'image.png')
            assert win.tabs.count() == count + 1
            assert win.current_tab().file_error == 'type'
            assert win.current_tab().file_notice.isVisible()
            tree.setCurrentIndex(model.index(str(root / 'notes.txt')))
            QTest.keyClick(tree, Qt.Key.Key_Return)
            wait(lambda: win.current_tab().ready and win.current_tab().filepath == str(root / 'notes.txt'))
            # Branch arrow and folder label each toggle once; keyboard arrows also work.
            nested_index = model.index(str(nested))
            tree.scrollTo(nested_index)
            rect = tree.visualRect(nested_index)
            arrow = QPoint(rect.left() - tree.indentation() // 2, rect.center().y())
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, arrow)
            assert not tree.isExpanded(nested_index)
            tree.setCurrentIndex(nested_index)
            QTest.keyClick(tree, Qt.Key.Key_Right)
            assert tree.isExpanded(nested_index)
            QTest.keyClick(tree, Qt.Key.Key_Left)
            assert not tree.isExpanded(nested_index)
            QTest.keyClick(tree, Qt.Key.Key_Return)
            assert tree.isExpanded(nested_index)
            QTest.mouseClick(explorer.collapse_button, Qt.MouseButton.LeftButton)
            assert not tree.isExpanded(nested_index)
            print('PASS - Folder dialog, lazy loading, tree mouse/keyboard navigation and document reuse', flush=True)

            created = root / '新增.md'
            created.write_text('# 新增', encoding='utf-8')
            wait(lambda: explorer.count.text() == '文件 5 · 文件夹 2')
            renamed = root / '改名.md'
            created.rename(renamed)
            wait(lambda: any(model.fileName(model.index(i, 0, tree.rootIndex())) == renamed.name
                             for i in range(model.rowCount(tree.rootIndex()))))
            renamed.unlink()
            wait(lambda: explorer.count.text() == '文件 4 · 文件夹 2')
            added_folder = root / '新增文件夹'
            added_folder.mkdir()
            wait(lambda: explorer.count.text() == '文件 4 · 文件夹 3')
            added_folder.rmdir()
            wait(lambda: explorer.count.text() == '文件 4 · 文件夹 2')
            print('PASS - External creation, rename and deletion automatically update the tree and count', flush=True)

            win.open_file(str(nested_file))
            QTest.qWait(120)
            assert tree.currentIndex() == model.index(str(nested_file))
            assert tree.isExpanded(model.index(str(nested)))
            win.grab().save(str(Path('tmp/project-explorer-light.png').resolve()))
            win.toggle_theme()
            QTest.qWait(150)
            win.grab().save(str(Path('tmp/project-explorer-dark.png').resolve()))
            assert explorer.model.muted.name() == '#9b9b93'
            win.set_language('en')
            assert explorer.count.text() == 'Files 4 · Folders 2'
            assert explorer.collapse_button.toolTip() == 'Collapse all folders'
            assert win._sidebar_buttons['project'].text() == 'Open folder'
            assert model.fileName(model.index(str(nested_file))) == nested_file.name
            win.set_language('zh_CN')
            win.resize(600, 420)
            QTest.qWait(120)
            assert win._theme_button.geometry().bottom() <= win.sidebar.height()
            assert explorer.tree.height() > 0
            win.grab().save(str(Path('tmp/project-explorer-small.png').resolve()))
            win.resize(480, 360)
            QTest.qWait(100)
            assert win.height() == 360 and explorer.tree.height() > 0
            win._sidebar_action.setChecked(False)
            assert not explorer.isVisible()
            win._sidebar_action.setChecked(True)
            assert explorer.isVisible()
            win.resize(1080, 760)
            win.toggle_theme()
            # Project changes must never discard edited documents.
            tab = win.current_tab()
            tab.dirty = True
            win.open_project_folder(str(empty))
            wait(lambda: explorer.count.text() == '文件 0 · 文件夹 0')
            assert tab in win._tab_list and tab.dirty
            empty.rmdir()
            wait(lambda: explorer.count.text() == '文件夹已被移动或删除')
            assert not explorer.tree.isVisible()
            QTest.mouseClick(explorer.close_button, Qt.MouseButton.LeftButton)
            assert explorer.model is None and not explorer.isVisible()
            assert tab in win._tab_list and tab.dirty
            assert not win._close_project_action.isEnabled()
            tab.dirty = False
            print('PASS - Active file reveal, themes, translation, small layout and safe folder switching', flush=True)

            with patch('app.main_window.QFileDialog.getExistingDirectory', return_value=str(root)):
                win.activateWindow()
                win.view.setFocus()
                QTest.qWait(80)
                QTest.keyClick(win.view.focusProxy(), Qt.Key.Key_O,
                               Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                QTest.qWait(120)
            assert explorer.root_path == str(root)
            win.close()
            # A fresh process reads the newly persisted session, not the store's
            # original startup snapshot retained by this test's QApplication.
            win.store.initial_session = win.store.state['session']
            restored = MainWindow(restore_session=True)
            windows.append(restored)
            restored.show()
            wait(lambda: restored.project_explorer.count.text() == '文件 4 · 文件夹 2')
            assert restored.project_explorer.root_path == str(root)
            assert restored.current_tab().filepath == str(nested_file)
            restored.close_project_folder()
            assert not settings.value('files/projectFolder', '')
            print('PASS - Ctrl+Shift+O, project restoration and close-folder preference', flush=True)
        finally:
            for window in windows:
                window.project_explorer.set_folder(None)
                for tab in window._tab_list:
                    tab.dirty = False
                if not window._closed:
                    window.close()
            QTest.qWait(100)
            settings.clear()


if __name__ == '__main__':
    run()
