"""Shared dialog palette, controls and compact window chrome."""
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QScrollArea, QSizeGrip, QToolButton, QVBoxLayout, QWidget,
)

from .i18n import t


def style_dialog(dialog, theme):
    dark = theme == "dark"
    bg, panel, fg, muted, line, hover, accent, on_accent = (
        ("#252522", "#20201e", "#e8e8e1", "#a1a197", "#41413a", "#33332e", "#e8e8e1", "#20201e") if dark else
        ("#ffffff", "#f8f8f5", "#2d2d29", "#85857b", "#e5e5de", "#eeeee9", "#292925", "#ffffff"))
    palette = dialog.palette()
    for role, color in ((QPalette.ColorRole.Window, bg), (QPalette.ColorRole.Base, panel),
                        (QPalette.ColorRole.Button, bg), (QPalette.ColorRole.Text, fg),
                        (QPalette.ColorRole.WindowText, fg), (QPalette.ColorRole.ButtonText, fg),
                        (QPalette.ColorRole.Highlight, accent), (QPalette.ColorRole.HighlightedText, on_accent),
                        (QPalette.ColorRole.PlaceholderText, muted)):
        palette.setColor(role, QColor(color))
    dialog.setPalette(palette)
    check = (Path(__file__).parent / "assets/check.svg").as_posix()
    chevron = (Path(__file__).parent / "assets/chevron-down.svg").as_posix()
    dialog.setStyleSheet(f"""
        QDialog {{ background: {bg}; color: {fg}; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; }}
        QDialog[appChrome='true'] {{ background: transparent; }}
        QFrame#dialogCard {{ background: {bg}; border: 1px solid {line}; border-radius: 12px; }}
        QWidget#dialogBody, QWidget#dialogHeader, QWidget#dialogFooter, QScrollArea {{ background: transparent; border: 0; }}
        QLabel, QCheckBox, QRadioButton {{ color: {fg}; background: transparent; }}
        QLabel[role='title'], QLabel#dialogTitle {{ font-size: 18px; font-weight: 600; }}
        QLabel[role='muted'] {{ color: {muted}; }}
        QCheckBox, QRadioButton {{ spacing: 8px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {line}; border-radius: 4px; background: {panel}; }}
        QCheckBox::indicator:checked {{ background: #687c61; border-color: #687c61; image: url("{check}"); }}
        QListView, QTreeView, QTableView, QTabWidget::pane {{ color: {fg}; background: {panel}; border: 1px solid {line}; border-radius: 7px; outline: 0; }}
        QAbstractItemView::item {{ min-height: 25px; padding: 3px; }}
        QAbstractItemView::item:selected {{ background: {hover}; color: {fg}; }}
        QHeaderView::section {{ background: {bg}; color: {muted}; border: 0; border-bottom: 1px solid {line}; padding: 7px; }}
        QTabBar::tab {{ color: {muted}; background: transparent; padding: 10px 15px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: {fg}; border-bottom-color: {accent}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ color: {fg}; background: {panel}; border: 1px solid {line}; border-radius: 6px; padding: 8px; selection-background-color: {accent}; selection-color: {on_accent}; }}
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {muted}; }}
        QComboBox QAbstractItemView {{ color: {fg}; background: {bg}; selection-background-color: {hover}; selection-color: {fg}; }}
        QComboBox {{ padding-right: 30px; }}
        QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 24px; border: 0; background: transparent; }}
        QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
        QPushButton {{ color: {fg}; background: {bg}; border: 1px solid {line}; border-radius: 7px; padding: 8px 14px; min-height: 18px; }}
        QPushButton:hover, QToolButton:hover {{ background: {hover}; }}
        QPushButton:focus {{ border-color: {muted}; }}
        QPushButton[role='primary'], QPushButton:default {{ background: {accent}; border-color: {accent}; color: {on_accent}; font-weight: 600; }}
        QPushButton:disabled {{ color: {muted}; background: {panel}; border-color: {line}; }}
        QToolButton {{ color: {fg}; background: transparent; border: 0; border-radius: 6px; padding: 5px; }}
        QToolButton#dialogClose {{ font-size: 21px; }}
        QToolButton[role='stepper'] {{ background: {panel}; border: 1px solid {line}; font-size: 19px; }}
        QToolButton[role='stepper']:hover {{ background: {hover}; border-color: {muted}; }}
        QToolButton[role='stepper']:disabled {{ color: {muted}; background: {bg}; }}
        QProgressBar {{ border: none; background: {line}; border-radius: 3px; max-height: 5px; }}
        QProgressBar::chunk {{ background: #8a9b81; border-radius: 3px; }}
        QSplitter::handle {{ background: {bg}; width: 8px; height: 8px; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {line}; min-height: 24px; border-radius: 4px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QToolTip {{ color: {fg}; background: {bg}; border: 1px solid {line}; padding: 4px; }}
    """)


class AppDialog(QDialog):
    """Rounded, draggable, screen-fitting frame for application-owned tool dialogs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setProperty("appChrome", True)
        self._chrome_ready = False
        self._footer = None

    def set_footer_layout(self, layout):
        """Keep primary actions visible while a long form scrolls."""
        self._footer = QWidget(self)
        self._footer.setObjectName("dialogFooter")
        self._footer.setLayout(layout)

    def showEvent(self, event):
        if not self._chrome_ready:
            self._chrome_ready = True
            previous = QWidget.layout(self)
            content = QWidget(); content.setObjectName("dialogBody")
            content.setLayout(previous)
            # The tool's own heading may be more descriptive than its window title.
            for heading in content.findChildren(QLabel):
                if heading.property("role") == "title" and heading.text() == self.windowTitle(): heading.hide()
            outer = QVBoxLayout(self); outer.setContentsMargins(6, 6, 6, 6)
            card = QFrame(); card.setObjectName("dialogCard"); outer.addWidget(card)
            layout = QVBoxLayout(card); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
            self._header = QWidget(); self._header.setObjectName("dialogHeader")
            row = QHBoxLayout(self._header); row.setContentsMargins(22, 14, 16, 4)
            self._title = QLabel(self.windowTitle()); self._title.setObjectName("dialogTitle")
            self._title.setTextFormat(Qt.TextFormat.PlainText)
            self.windowTitleChanged.connect(self._title.setText)
            row.addWidget(self._title, 1)
            close = QToolButton(); close.setObjectName("dialogClose"); close.setText("×")
            close.setFixedSize(30, 30); close.setToolTip(t("关闭")); close.setAccessibleName(t("关闭"))
            close.clicked.connect(self.reject); row.addWidget(close)
            self._header.installEventFilter(self); self._title.installEventFilter(self)
            layout.addWidget(self._header)
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            layout.addWidget(scroll, 1)
            if self._footer is not None:
                layout.addWidget(self._footer)
            grip = QSizeGrip(card); layout.addWidget(grip, 0, Qt.AlignmentFlag.AlignRight)
            bounds = self.screen().availableGeometry()
            self.setMinimumSize(360, 260)
            self.resize(min(self.width(), bounds.width() - 24), min(self.height() + 42, bounds.height() - 32))
            parent = self.parentWidget()
            center = parent.frameGeometry().center() if parent else bounds.center()
            self.move(max(bounds.left(), min(center.x() - self.width() // 2, bounds.right() - self.width())),
                      max(bounds.top(), min(center.y() - self.height() // 2, bounds.bottom() - self.height())))
        super().showEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self.windowHandle(): self.windowHandle().startSystemMove()
        return super().eventFilter(watched, event)


def refresh_dialog_themes(theme):
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, (AppDialog, QMessageBox, QInputDialog, QFileDialog)):
            style_dialog(widget, theme)


class _DialogTheme(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, (QMessageBox, QInputDialog, QFileDialog)):
            dark = QSettings().value("appearance/theme", "light") == "dark"
            style_dialog(watched, "dark" if dark else "light")
            # System title bars on common Qt dialogs use the same light/dark palette.
            if sys.platform == "win32":
                import ctypes
                value = ctypes.c_int(int(dark))
                try: ctypes.windll.dwmapi.DwmSetWindowAttribute(int(watched.winId()), 20, ctypes.byref(value), 4)
                except (OSError, AttributeError): pass
        return False


def install_dialog_theme():
    app = QApplication.instance()
    if getattr(app, "_dialog_theme", None): return
    # Qt file choosers remain local and inherit the app palette in both themes.
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app._dialog_theme = _DialogTheme(app)
    app.installEventFilter(app._dialog_theme)
