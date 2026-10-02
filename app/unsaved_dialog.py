"""与工作区主题一致的未保存修改提示，返回原有的保存/放弃/取消结果。"""
from .i18n import t
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSizePolicy, QToolButton, QVBoxLayout)


class UnsavedChangesDialog(QDialog):
    def __init__(self, window, tab, closing_window=False):
        super().__init__(window)
        self.setObjectName("unsavedDialog")
        self.setWindowTitle(t("未保存的修改"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(536)
        dark = window._theme == "dark"
        background, surface = ("#252522", "#2d2d29") if dark else ("#ffffff", "#f8f8f5")
        text, muted = ("#e8e8e1", "#a1a197") if dark else ("#2d2d29", "#85857b")
        border, hover = ("#41413a", "#383832") if dark else ("#e5e5de", "#eeeee9")
        primary, on_primary = ("#e8e8e1", "#20201e") if dark else ("#292925", "#ffffff")
        primary_hover = "#ffffff" if dark else "#43433d"
        self.setStyleSheet(f"""
            QDialog#unsavedDialog {{ background: transparent; }}
            QFrame#unsavedCard {{ background: {background}; border: 1px solid {border}; border-radius: 14px; }}
            QLabel {{ background: transparent; color: {text}; border: 0;
                font-family: "Segoe UI", "Microsoft YaHei"; font-size: 13px; }}
            QLabel#unsavedTitle {{ font-size: 18px; font-weight: 600; }}
            QLabel#unsavedDescription, QLabel#unsavedPath {{ color: {muted}; }}
            QLabel#unsavedPath {{ font-size: 11px; }}
            QLabel#unsavedName {{ font-weight: 600; }}
            QFrame#unsavedDocument {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; }}
            QPushButton, QToolButton {{ background: transparent; color: {text}; border: 1px solid transparent;
                border-radius: 7px; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 12px; }}
            QPushButton {{ padding: 8px 14px; min-height: 18px; }}
            QPushButton:hover, QToolButton:hover {{ background: {hover}; }}
            QPushButton:focus, QToolButton:focus {{ border-color: {muted}; }}
            QPushButton#unsavedCancel {{ border-color: {border}; }}
            QPushButton#unsavedCancel:focus {{ border-color: {muted}; }}
            QPushButton#unsavedDiscard {{ color: {muted}; padding-left: 8px; padding-right: 8px; }}
            QPushButton#unsavedSave {{ background: {primary}; color: {on_primary}; font-weight: 600; }}
            QPushButton#unsavedSave:hover {{ background: {primary_hover}; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 22)
        card = QFrame(self)
        card.setObjectName("unsavedCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 100 if dark else 38))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(0)

        header = QHBoxLayout()
        title = QLabel(t("保存文档修改？"))
        title.setObjectName("unsavedTitle")
        header.addWidget(title)
        header.addStretch()
        self.close_button = QToolButton()
        self.close_button.setObjectName("unsavedClose")
        self.close_button.setIcon(window._ui_icon("close", muted))
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setFixedSize(28, 28)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setToolTip(t("取消关闭"))
        self.close_button.setAccessibleName(t("取消关闭"))
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        layout.addSpacing(10)
        description = QLabel(t("关闭前请保存，以免丢失这次编辑的内容。"))
        description.setObjectName("unsavedDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addSpacing(20)

        document = QFrame()
        document.setObjectName("unsavedDocument")
        document_layout = QHBoxLayout(document)
        document_layout.setContentsMargins(14, 13, 14, 13)
        document_layout.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(window._ui_icon("file", muted).pixmap(QSize(24, 24)))
        icon.setFixedSize(28, 28)
        document_layout.addWidget(icon)
        info = QVBoxLayout()
        info.setSpacing(4)
        self._name = tab.display_name()
        self._path = tab.filepath or t("尚未保存到本地")
        self.name_label = QLabel(self._name)
        self.name_label.setObjectName("unsavedName")
        self.path_label = QLabel(self._path)
        self.path_label.setObjectName("unsavedPath")
        for label, value in ((self.name_label, self._name), (self.path_label, self._path)):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setToolTip(value)
            info.addWidget(label)
        document_layout.addLayout(info, 1)
        layout.addWidget(document)
        layout.addSpacing(24)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.discard_button = QPushButton(t("放弃修改"))
        self.discard_button.setObjectName("unsavedDiscard")
        self.cancel_button = QPushButton(t("取消"))
        self.cancel_button.setObjectName("unsavedCancel")
        self.save_button = QPushButton(t("保存并退出") if closing_window else t("保存并关闭"))
        self.save_button.setObjectName("unsavedSave")
        for button, choice in ((self.discard_button, QMessageBox.StandardButton.Discard),
                               (self.cancel_button, QMessageBox.StandardButton.Cancel),
                               (self.save_button, QMessageBox.StandardButton.Save)):
            button.setAutoDefault(True)
            button.clicked.connect(lambda checked=False, result=choice: self.done(int(result)))
        self.save_button.setDefault(True)
        actions.addWidget(self.discard_button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        self.save_button.setFocus()

    def reject(self):
        self.done(int(QMessageBox.StandardButton.Cancel))

    def showEvent(self, event):
        super().showEvent(event)
        for label, value in ((self.name_label, self._name), (self.path_label, self._path)):
            label.setText(label.fontMetrics().elidedText(value, Qt.TextElideMode.ElideMiddle, label.width()))
        parent = self.parentWidget()
        center = parent.frameGeometry().center()
        bounds = parent.screen().availableGeometry()
        left = max(bounds.left(), min(center.x() - self.width() // 2, bounds.right() - self.width() + 1))
        top = max(bounds.top(), min(center.y() - self.height() // 2, bounds.bottom() - self.height() + 1))
        self.move(left, top)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 74 and self.windowHandle():
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    @staticmethod
    def ask(window, tab, closing_window=False):
        dialog = UnsavedChangesDialog(window, tab, closing_window)
        try:
            return QMessageBox.StandardButton(dialog.exec())
        finally:
            dialog.deleteLater()
