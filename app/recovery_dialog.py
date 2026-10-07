"""按需显示的草稿恢复列表，恢复内容作为独立的未保存文档打开。"""
from .i18n import t
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QVBoxLayout)


from .dialog_theme import AppDialog, style_dialog


class RecoveryDialog(AppDialog):
    def __init__(self, window, records):
        super().__init__(window)
        style_dialog(self, window._theme)
        self.setWindowTitle(t("恢复未保存的草稿"))
        self.resize(720, 480)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("选择草稿查看内容。恢复后会作为未保存文档打开。")))
        body = QHBoxLayout()
        self.list = QListWidget()
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        body.addWidget(self.list, 2)
        body.addWidget(self.preview, 3)
        layout.addLayout(body, 1)
        for record in records:
            date = datetime.fromtimestamp(record["updated"]).strftime("%m-%d %H:%M")
            item = QListWidgetItem(f"{record['name']}\n{date}")
            item.setData(Qt.ItemDataRole.UserRole, record)
            item.setToolTip(record.get("path") or record.get("origin") or t("未命名草稿"))
            self.list.addItem(item)
        buttons = QHBoxLayout()
        self.delete_button = QPushButton(t("删除备份"))
        self.restore_button = QPushButton(t("恢复选中草稿"))
        close_button = QPushButton(t("关闭"))
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(self.restore_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.restore_button.clicked.connect(lambda: self._restore(window))
        self.delete_button.clicked.connect(lambda: self._delete(window))
        close_button.clicked.connect(self.close)
        self.list.setCurrentRow(0)
        self._selection_changed()

    def _selection_changed(self, *_):
        item = self.list.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.preview.setPlainText(record["content"] if record else t("没有可恢复的草稿。"))
        self.restore_button.setEnabled(bool(item))
        self.delete_button.setEnabled(bool(item))

    def _restore(self, window):
        item = self.list.currentItem()
        if item:
            window.restore_draft(item.data(Qt.ItemDataRole.UserRole))
            self.list.takeItem(self.list.row(item))
            self._selection_changed()
            if not self.list.count():
                self.close()

    def _delete(self, window):
        from PySide6.QtWidgets import QMessageBox
        item = self.list.currentItem()
        if not item:
            return
        if QMessageBox.question(self, t("删除备份"), t("删除这份草稿备份？此操作无法撤销。"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        window.store.remove_draft(record["id"])
        window.store.remove_assets(record["id"])
        self.list.takeItem(self.list.row(item))
        self._selection_changed()
