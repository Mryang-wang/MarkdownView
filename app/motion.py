"""Short, interruptible UI motion using Qt's existing animation clock."""
import ctypes
import os

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QWidget


def motion_enabled():
    if os.name == "nt":
        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)  # SPI_GETCLIENTAREAANIMATION (read only)
    return True


class AnimatedSidebar(QWidget):
    """Clip a fixed-width interior, so labels never squeeze during a reveal."""
    expanded_width = 216

    def __init__(self, parent):
        super().__init__(parent)
        self.content = QWidget(self)
        self.content.setFixedWidth(self.expanded_width)
        self._expanded = True
        self.setFixedWidth(self.expanded_width)
        self.animation = QPropertyAnimation(self, b"revealWidth", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._finish)

    def _set_width(self, width):
        self.setFixedWidth(width)
        self.parentWidget().update()

    revealWidth = Property(int, lambda self: self.width(), _set_width)

    def set_expanded(self, expanded, animate=False):
        self.animation.stop()
        self._expanded = bool(expanded)
        target = self.expanded_width if expanded else 0
        if not animate or not motion_enabled():
            self._set_width(target)
            self.setVisible(expanded)
            return
        if self.isHidden():
            self._set_width(0)
        self.show()
        start = self.width()
        if start == target:
            self._finish()
            return
        self.animation.setDuration(max(80, round(250 * abs(target - start) / self.expanded_width)))
        self.animation.setStartValue(start)
        self.animation.setEndValue(target)
        self.animation.start()

    def _finish(self):
        self._set_width(self.expanded_width if self._expanded else 0)
        self.setVisible(self._expanded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.content.setGeometry(self.width() - self.expanded_width, 0, self.expanded_width, self.height())

    def hideEvent(self, event):
        self.animation.stop()
        self._set_width(self.expanded_width if self._expanded else 0)
        if not self._expanded:
            self.hide()
        super().hideEvent(event)
