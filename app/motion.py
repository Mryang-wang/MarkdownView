"""Short, interruptible UI motion using Qt's existing animation clock."""
import ctypes
import os

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Signal
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
    motionStarted = Signal(int)
    motionFinished = Signal()

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

    revealWidth = Property(int, lambda self: self.width(), _set_width)

    def set_expanded(self, expanded, animate=False):
        self.animation.stop()
        self._expanded = bool(expanded)
        target = self.expanded_width if expanded else 0
        if not animate or not motion_enabled():
            self._finish()
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
        self.motionStarted.emit(start - target)
        self.animation.start()

    def _finish(self):
        self._set_width(self.expanded_width if self._expanded else 0)
        self.setVisible(self._expanded)
        self.parentWidget().layout().activate()
        self.motionFinished.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.content.setGeometry(self.width() - self.expanded_width, 0, self.expanded_width, self.height())

    def hideEvent(self, event):
        was_moving = self.animation.state() != QPropertyAnimation.State.Stopped
        self.animation.stop()
        self._set_width(self.expanded_width if self._expanded else 0)
        if not self._expanded:
            self.hide()
        if was_moving:
            self.motionFinished.emit()
        super().hideEvent(event)


class EditorViewport(QWidget):
    """Clip the editor while the sidebar moves; resize WebEngine only once."""

    def __init__(self, editor, parent):
        super().__init__(parent)
        self.editor = editor
        self._moving = False
        editor.setParent(self)
        editor.show()

    def begin_motion(self, extra_width):
        self._moving = True
        # Retain the wider surface during either direction and on reversal.
        # Expanding the sidebar clips it until the final width is committed.
        self.editor.resize(max(self.editor.width(), self.width(), self.width() + extra_width), self.height())

    def end_motion(self):
        self._moving = False
        self.editor.resize(self.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(self.editor.width(), self.width()) if self._moving else self.width()
        self.editor.resize(width, self.height())
