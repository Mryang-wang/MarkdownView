# -*- coding: utf-8 -*-
"""JS <-> Python 桥对象：由 QWebChannel 注册，供页面 JS 调用。

每个标签页一个桥实例，调用转发给所属标签页，再由标签页委托主窗口处理。
"""
from PySide6.QtCore import QObject, Slot


class Bridge(QObject):
    def __init__(self, tab):
        super().__init__()
        self._tab = tab

    @Slot()
    def editorReady(self):
        self._tab.window.on_editor_ready(self._tab)

    @Slot()
    def notifyDirty(self):
        self._tab.window.set_dirty(self._tab, True)

    @Slot()
    def notifyClean(self):
        self._tab.window.set_dirty(self._tab, False)

    @Slot()
    def requestOpen(self):
        self._tab.window.open_file_dialog()

    @Slot()
    def requestToggleSidebar(self):
        self._tab.window._sidebar_action.trigger()

    @Slot(str)
    def requestSave(self, content):
        self._tab.window.save_file(self._tab, content, save_as=False)

    @Slot(str)
    def requestSaveAs(self, content):
        self._tab.window.save_file(self._tab, content, save_as=True)

    @Slot(str)
    def requestExport(self, content):
        self._tab.window.export_docx(self._tab, content)

    @Slot()
    def requestInsertImage(self):
        self._tab.window.insert_image_dialog(self._tab)

    @Slot(str, str, result=str)
    def importImage(self, data_url, name):
        return self._tab.window.import_image(self._tab, data_url, name)

    @Slot(float)
    def reportPosition(self, position):
        self._tab.window.report_position(self._tab, position)

    @Slot(int, int, str)
    def reportEditorStatus(self, total, selected, mode):
        self._tab.window.update_editor_status(self._tab, total, selected, mode)

    @Slot(bool)
    def requestFullscreen(self, enabled):
        self._tab.window.set_editor_fullscreen(self._tab, enabled)

    @Slot(str)
    def openUrl(self, url):
        self._tab.window.open_url(self._tab, url)

    @Slot(str)
    def log(self, msg):
        print("[JS]", msg)
