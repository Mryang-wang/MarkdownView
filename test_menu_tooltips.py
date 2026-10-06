# -*- coding: utf-8 -*-
"""原生菜单悬停事件：气泡位置、编辑区稳定性及操作消息保留。"""
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt, QEvent
from PySide6.QtGui import QHelpEvent, QMouseEvent, QStatusTipEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow  # noqa: E402


def tooltip_widgets():
    return [widget for widget in QApplication.topLevelWidgets()
            if widget.isVisible() and widget.windowType() == Qt.WindowType.ToolTip]


def hover(menu, action):
    position = menu.actionGeometry(action).center()
    QTest.mouseMove(menu, position)
    QTest.qWait(100)
    # Windows 上全局光标移动可能被其他窗口接收，直接补发相同的 Qt 鼠标事件。
    QApplication.sendEvent(menu, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(position), QPointF(menu.mapToGlobal(position)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(menu, QHelpEvent(QEvent.Type.ToolTip, position, menu.mapToGlobal(position)))
    assert menu.activeAction() is action, action.text()
    assert QToolTip.isVisible() and QToolTip.text() == action.toolTip(), (
        action.text(), QToolTip.text())
    bubbles = tooltip_widgets()
    assert bubbles, "No floating tooltip window"
    row = QRect(menu.mapToGlobal(menu.actionGeometry(action).topLeft()),
                menu.actionGeometry(action).size())
    assert row.adjusted(-30, -30, bubbles[0].width() + 30,
                        bubbles[0].height() + 30).contains(bubbles[0].pos()), (
        "Tooltip is not near the hovered item", row, bubbles[0].geometry())


def open_menu(window, menu):
    menu.popup(window.menuBar().mapToGlobal(QPoint(55, window.menuBar().height())))
    QTest.qWait(150)


def run():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["MDVIEW_DATA_DIR"] = str(Path(directory) / "profile")
        app = QApplication(sys.argv)
        app.setEffectEnabled(Qt.UIEffect.UI_FadeTooltip, False)
        app.setEffectEnabled(Qt.UIEffect.UI_AnimateTooltip, False)
        app.setOrganizationName("MarkdownViewMenuTest")
        app.setApplicationName("MarkdownViewMenuTest")
        settings = QSettings()
        settings.setValue("appearance/theme", "light")
        settings.setValue("appearance/sidebarVisible", True)
        window = MainWindow()
        window.resize(1120, 820)
        window.show()
        try:
            for _ in range(100):
                QTest.qWait(100)
                if window.current_tab().ready:
                    break
            assert window.current_tab().ready, "Editor did not become ready"
            assert not window._close_project_action.isEnabled()
            window.open_project_folder(directory)
            assert window._close_project_action.isEnabled()
            menu = window._file_menu
            layout = (QRect(window.centralWidget().geometry()),
                      QRect(window.current_tab().view.geometry()))
            messages = []
            window.statusBar().messageChanged.connect(messages.append)
            open_menu(window, menu)
            actions = [action for action in menu.actions()
                       if not action.isSeparator()
                       and action is not window._recent_menu.menuAction()]
            for action in actions:
                hover(menu, action)
                assert not window.statusBar().isVisible(), action.text()
                assert not window.statusBar().currentMessage(), action.text()
                assert layout == (window.centralWidget().geometry(),
                                  window.current_tab().view.geometry()), action.text()
            assert messages == [], messages
            print("PASS - All File menu bubbles appear near the hovered item without layout changes", flush=True)
            menu.hide()
            QTest.qWait(400)
            assert not QToolTip.isVisible(), "Tooltip remains after closing menu"
            assert layout == (window.centralWidget().geometry(),
                              window.current_tab().view.geometry())
            QApplication.sendEvent(window, QStatusTipEvent("悬停说明"))
            assert not window.statusBar().isVisible()
            print("PASS - Closing menus and status-tip events leave the editor layout stable", flush=True)

            window.statusBar().showMessage("已保存：示例.md", 6000)
            QTest.qWait(100)
            operation_layout = QRect(window.centralWidget().geometry())
            open_menu(window, menu)
            hover(menu, actions[0])
            QApplication.sendEvent(window, QStatusTipEvent(""))
            menu.hide()
            QTest.qWait(300)
            assert window.statusBar().currentMessage() == "已保存：示例.md"
            assert window.statusBar().isVisible()
            assert window.centralWidget().geometry() == operation_layout
            window.statusBar().clearMessage()
            QTest.qWait(100)
            print("PASS - Hovering and closing menus preserve operation messages", flush=True)

            window.toggle_theme()
            QTest.qWait(200)
            dark_layout = (QRect(window.centralWidget().geometry()),
                           QRect(window.current_tab().view.geometry()))
            open_menu(window, menu)
            close_action = next(action for action in actions if action.shortcut().toString() == "Ctrl+W")
            hover(menu, close_action)
            assert not window.statusBar().isVisible()
            assert dark_layout == (window.centralWidget().geometry(),
                                   window.current_tab().view.geometry()), (
                dark_layout, window.centralWidget().geometry(),
                window.current_tab().view.geometry())
            menu.hide()
            QTest.qWait(400)
            print("PASS - Menu bubbles and stable layout also work in the dark theme", flush=True)

            source = Path(directory) / "最近的文档.md"
            source.write_text("# Recent", encoding="utf-8")
            window.store.remember_file(str(source))
            recent = window._recent_menu
            open_menu(window, menu)
            recent.popup(menu.mapToGlobal(menu.actionGeometry(recent.menuAction()).topRight()))
            QTest.qWait(150)
            recent_action = recent.actions()[0]
            hover(recent, recent_action)
            assert QToolTip.text() == str(source)
            assert not window.statusBar().isVisible()
            recent.hide()
            menu.hide()
            QTest.qWait(400)
            print("PASS - Recent documents still show the full path in a bubble", flush=True)
        finally:
            for popup in (window._recent_menu, window._file_menu):
                popup.hide()
            for tab in window._tab_list:
                tab.dirty = False
            window.close()
            settings.clear()
            app.processEvents()
        print("MENU_TOOLTIPS: PASSED", flush=True)


if __name__ == "__main__":
    run()
