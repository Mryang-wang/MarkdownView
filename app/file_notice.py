"""A native, non-editable reading-area message for unavailable files."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from .i18n import t


class FileNotice(QWidget):
    retryRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("fileNotice")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("fileNoticeScroll")
        scroll.viewport().setObjectName("fileNoticeViewport")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        content.setObjectName("fileNoticeContent")
        scroll.setWidget(content)
        layout.addWidget(scroll)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        card = QWidget(content)
        card.setMaximumWidth(540)
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)
        self.icon = QLabel(card)
        self.icon.setFixedHeight(56)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.icon)
        self.title = QLabel(card)
        self.title.setObjectName("fileNoticeTitle")
        self.filename = QLabel(card)
        self.filename.setObjectName("fileNoticeName")
        self.filename.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.description = QLabel(card)
        self.description.setObjectName("fileNoticeDescription")
        for label in (self.title, self.filename, self.description):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.retry_button = QPushButton(card)
        self.retry_button.clicked.connect(self.retryRequested)
        buttons.addWidget(self.retry_button)
        self.close_button = QPushButton(card)
        self.close_button.clicked.connect(self.closeRequested)
        buttons.addWidget(self.close_button)
        buttons.addStretch()
        column.addLayout(buttons)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def refresh(self, path, reason, detail, icon):
        self.icon.setPixmap(icon.pixmap(48, 48))
        self.title.setText(t("无法读取该类型文件") if reason == "type" else t("无法读取文件"))
        self.filename.setText(os.path.basename(path))
        self.filename.setToolTip(path)
        if reason == "type":
            description = t("当前支持 Markdown 和 TXT 文本文件。此文件无法在阅读区中预览。")
        elif reason == "encoding":
            description = t("文件不是有效的 UTF-8 文本，或包含二进制内容。请检查文件编码后重试。")
        else:
            description = t("文件可能已被移动、删除或无法访问。请检查后重试。")
        self.description.setText(description)
        self.description.setToolTip(detail)
        self.retry_button.setText(t("重试"))
        self.retry_button.setVisible(reason != "type")
        self.close_button.setText(t("关闭文件"))
