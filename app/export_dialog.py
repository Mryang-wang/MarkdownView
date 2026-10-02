"""与工作区风格一致的 DOCX / PDF 导出完成提示。"""
import os

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSizePolicy, QToolButton, QVBoxLayout)

from .i18n import t


class ExportSuccessDialog(QDialog):
    def __init__(self, window, path, warnings=""):
        super().__init__(window)
        self.setObjectName("exportSuccessDialog")
        self.setWindowTitle(t("导出成功"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(min(536, window.screen().availableGeometry().width() - 32))
        dark = window._theme == "dark"
        background, surface = ("#252522", "#2d2d29") if dark else ("#ffffff", "#f8f8f5")
        text, muted = ("#e8e8e1", "#a1a197") if dark else ("#2d2d29", "#85857b")
        border, hover = ("#41413a", "#383832") if dark else ("#e5e5de", "#eeeee9")
        primary, on_primary = ("#e8e8e1", "#20201e") if dark else ("#292925", "#ffffff")
        success, success_bg = ("#b6cbb1", "#354031") if dark else ("#5d7957", "#edf3e9")
        self.setStyleSheet(f"""
            QDialog#exportSuccessDialog {{ background: transparent; }}
            QFrame#exportCard {{ background: {background}; border: 1px solid {border}; border-radius: 14px; }}
            QLabel {{ background: transparent; color: {text}; border: 0;
                font-family: "Segoe UI", "Microsoft YaHei"; font-size: 13px; }}
            QLabel#exportTitle {{ font-size: 18px; font-weight: 600; }}
            QLabel#exportDescription, QLabel#exportPath {{ color: {muted}; font-size: 12px; }}
            QLabel#exportSuccessIcon {{ background: {success_bg}; color: {success}; border-radius: 22px;
                font-family: "Segoe UI Symbol"; font-size: 24px; }}
            QLabel#exportName {{ font-weight: 600; }}
            QLabel#exportFormat {{ color: {muted}; font-size: 10px; font-weight: 600; }}
            QFrame#exportDocument {{ background: {surface}; border: 1px solid {border}; border-radius: 9px; }}
            QPushButton, QToolButton {{ background: transparent; color: {text}; border: 1px solid transparent;
                border-radius: 7px; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 12px; }}
            QPushButton {{ padding: 8px 24px; min-height: 18px; }}
            QPushButton:hover, QToolButton:hover {{ background: {hover}; }}
            QPushButton:focus, QToolButton:focus {{ border-color: {muted}; }}
            QPushButton#exportDone {{ background: {primary}; color: {on_primary}; font-weight: 600; }}
            QToolButton#exportWarningsToggle {{ color: {muted}; padding: 6px 0; }}
            QPlainTextEdit {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 7px;
                padding: 8px; font-size: 11px; selection-background-color: {hover}; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 22)
        card = QFrame()
        card.setObjectName("exportCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 100 if dark else 38))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel("✓")
        icon.setObjectName("exportSuccessIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(44, 44)
        header.addWidget(icon)
        heading = QVBoxLayout()
        heading.setSpacing(5)
        title = QLabel(t("导出成功"))
        title.setObjectName("exportTitle")
        heading.addWidget(title)
        description = QLabel(t("文件已导出，可展开查看转换提示。") if warnings.strip()
                             else t("文件已保存到以下位置。"))
        description.setObjectName("exportDescription")
        description.setWordWrap(True)
        heading.addWidget(description)
        header.addLayout(heading, 1)
        self.close_button = QToolButton()
        self.close_button.setIcon(window._ui_icon("close", muted))
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setFixedSize(28, 28)
        self.close_button.setToolTip(t("关闭"))
        self.close_button.setAccessibleName(t("关闭"))
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        document = QFrame()
        document.setObjectName("exportDocument")
        document_layout = QHBoxLayout(document)
        document_layout.setContentsMargins(14, 14, 14, 14)
        document_layout.setSpacing(12)
        file_icon = QLabel()
        file_icon.setPixmap(window._ui_icon("file", muted).pixmap(QSize(26, 26)))
        file_icon.setFixedSize(28, 28)
        document_layout.addWidget(file_icon)
        info = QVBoxLayout()
        info.setSpacing(5)
        absolute = os.path.abspath(path)
        self._name, self._path = os.path.basename(absolute), os.path.dirname(absolute)
        self.name_label = QLabel(self._name)
        self.name_label.setObjectName("exportName")
        self.path_label = QLabel(self._path)
        self.path_label.setObjectName("exportPath")
        for label, value in ((self.name_label, self._name), (self.path_label, self._path)):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setToolTip(value)
            info.addWidget(label)
        document_layout.addLayout(info, 1)
        format_label = QLabel(os.path.splitext(absolute)[1].lstrip(".").upper())
        format_label.setObjectName("exportFormat")
        document_layout.addWidget(format_label)
        layout.addWidget(document)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(warnings.strip())
        self.details.setAccessibleName(t("导出提示"))
        self.details.setFixedHeight(126)
        self.details.hide()
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.details_button = QToolButton()
        self.details_button.setObjectName("exportWarningsToggle")
        self.details_button.setText(t("查看导出提示"))
        self.details_button.setCheckable(True)
        self.details_button.setVisible(bool(warnings.strip()))
        self.details_button.toggled.connect(self._toggle_details)
        actions.addWidget(self.details_button)
        actions.addStretch()
        self.done_button = QPushButton(t("完成"))
        self.done_button.setObjectName("exportDone")
        self.done_button.setDefault(True)
        self.done_button.clicked.connect(self.accept)
        actions.addWidget(self.done_button)
        layout.addLayout(actions)
        self.done_button.setFocus()

    def _toggle_details(self, visible):
        self.details.setVisible(visible)
        self.details_button.setText(t("收起导出提示") if visible else t("查看导出提示"))
        # Let Qt update the layout's minimum height after hiding the details.
        QTimer.singleShot(0, self.adjustSize)

    def showEvent(self, event):
        super().showEvent(event)
        for label, value in ((self.name_label, self._name), (self.path_label, self._path)):
            label.setText(label.fontMetrics().elidedText(value, Qt.TextElideMode.ElideMiddle, label.width()))
        parent = self.parentWidget()
        center, bounds = parent.frameGeometry().center(), parent.screen().availableGeometry()
        self.move(max(bounds.left(), min(center.x() - self.width() // 2, bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(center.y() - self.height() // 2, bounds.bottom() - self.height() + 1)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 110 and self.windowHandle():
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    @staticmethod
    def show_result(window, path, warnings=""):
        dialog = ExportSuccessDialog(window, path, warnings)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
