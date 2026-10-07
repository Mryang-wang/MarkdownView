# -*- coding: utf-8 -*-
"""MarkdownView — 类 Typora 的 Markdown 编辑器入口。

用法：
    python main.py [文件.md]
"""
import os
import sys

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

# Qt WebEngine 在 Windows 上需要在 QApplication 创建前设置
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.single_instance import SingleInstance  # noqa: E402


def open_in_running_window(startup_window, files):
    app = QApplication.instance()
    active_ref = getattr(app, "_last_document_window", None)
    target = active_ref() if active_ref else None
    if target is None or target._closed:
        target = next((window for window in startup_window.store.windows if not window._closed), None)
    if target is None:
        return
    focused = target
    for path in files:
        tab = target.open_file(path)
        if tab is not None:
            focused = tab.window
    focused.bring_to_front()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MarkdownView")
    app.setOrganizationName("MarkdownView")
    # An explicitly isolated profile must not borrow real model credentials or UI settings.
    if os.environ.get("MDVIEW_DATA_DIR"):
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                          os.path.join(os.path.abspath(os.environ["MDVIEW_DATA_DIR"]), "settings"))

    paths = [os.path.abspath(path) for path in sys.argv[1:] if os.path.isfile(path)]
    instance = SingleInstance(app)
    try:
        if not instance.start_or_forward(paths):
            return 0
    except RuntimeError as error:
        QMessageBox.warning(None, "打开失败", str(error))
        return 1
    app.aboutToQuit.connect(instance.close)

    # 后续启动只转交路径，不再创建 WebEngine 或第二个窗口。
    from app.main_window import MainWindow

    win = MainWindow(startup_file=paths[0] if paths else None, restore_session=True)

    for path in paths[1:]:
        win.open_file(path)
    instance.set_handler(lambda files: open_in_running_window(win, files))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
