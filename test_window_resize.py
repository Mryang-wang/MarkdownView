"""Hit actual edge widgets and send targeted Qt drags; never move the OS mouse."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    # Native Windows sizing is covered by test_native_window_resize.py. Here
    # simulate a platform without support to exercise the compatibility fallback.
    with tempfile.TemporaryDirectory() as directory, patch.object(QWindow, 'startSystemResize', return_value=False):
        os.environ['MDVIEW_DATA_DIR'] = str(Path(directory) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewResizeTest')
        app.setApplicationName('MarkdownViewResizeTest')
        win = MainWindow(create_initial_tab=False)
        original = QRect(130, 110, 950, 650)
        win.setGeometry(original)
        win.show()
        QTest.qWait(200)
        cases = [
            ('left', QPoint(2,325), QPoint(-40,0), Qt.CursorShape.SizeHorCursor, QRect(90,110,990,650)),
            ('right', QPoint(947,325), QPoint(40,0), Qt.CursorShape.SizeHorCursor, QRect(130,110,990,650)),
            ('top', QPoint(475,2), QPoint(0,-35), Qt.CursorShape.SizeVerCursor, QRect(130,75,950,685)),
            ('bottom', QPoint(475,647), QPoint(0,35), Qt.CursorShape.SizeVerCursor, QRect(130,110,950,685)),
            ('top left', QPoint(2,2), QPoint(-40,-35), Qt.CursorShape.SizeFDiagCursor, QRect(90,75,990,685)),
            ('top right', QPoint(947,2), QPoint(40,-35), Qt.CursorShape.SizeBDiagCursor, QRect(130,75,990,685)),
            ('bottom left', QPoint(2,647), QPoint(-40,35), Qt.CursorShape.SizeBDiagCursor, QRect(90,110,990,685)),
            ('bottom right', QPoint(947,647), QPoint(40,35), Qt.CursorShape.SizeFDiagCursor, QRect(130,110,990,685)),
        ]
        try:
            for name, point, delta, cursor, expected in cases:
                win.setGeometry(original)
                QTest.qWait(80)
                handle=win.childAt(point)
                assert handle is not None and handle.objectName()=='windowResizeHandle',(name,handle)
                assert handle.cursor().shape()==cursor,(name,handle.cursor())
                start=win.mapToGlobal(point)
                QTest.mousePress(handle,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,handle.mapFromGlobal(start))
                assert QWidget.mouseGrabber() is win,(name,'no mouse capture')
                # Use fixed global points, including points beyond the old window bounds.
                for step in range(1,5):
                    global_pos=start+delta*step/4
                    QApplication.sendEvent(win,QMouseEvent(QEvent.Type.MouseMove,QPointF(win.mapFromGlobal(global_pos)),QPointF(global_pos),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
                    QTest.qWait(30)
                end=start+delta
                QTest.mouseRelease(win,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,win.mapFromGlobal(end))
                QTest.qWait(80)
                assert win.geometry()==expected,(name,win.geometry(),expected)
                assert QWidget.mouseGrabber() is None and not win._resize_drag_edges
                print('PASS - '+name+' cursor, dragging and release',flush=True)
            win.setGeometry(original)
            QTest.qWait(80)
            for point in (QPoint(8,8),QPoint(941,8),QPoint(8,641),QPoint(941,641)):
                assert win.childAt(point) not in win._resize_handles,'Corner overlaps content'
            for point in (QPoint(2,12),QPoint(12,2)):
                assert win._resize_handles[win.childAt(point)]==Qt.Edge.TopEdge|Qt.Edge.LeftEdge
            win.statusBar().showMessage('Saved')
            QTest.qWait(50)
            assert win.childAt(QPoint(475,647)) in win._resize_handles,'Status message covers the bottom handle'
            win.statusBar().clearMessage()
            # A burst of mouse events must coalesce, but release must use its own
            # final position immediately and leave no delayed resize behind.
            point=QPoint(947,325);handle=win.childAt(point);start=win.mapToGlobal(point)
            QTest.mousePress(handle,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,handle.mapFromGlobal(start))
            for i in range(100):
                position=start+QPoint(i,0)
                QApplication.sendEvent(win,QMouseEvent(QEvent.Type.MouseMove,QPointF(win.mapFromGlobal(position)),QPointF(position),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
            assert win.geometry()==original,'Mouse bursts trigger synchronous layouts'
            QTest.qWait(40)
            assert win.width()==original.width()+99,'Latest queued pointer position was lost'
            end=start+QPoint(120,0)
            QTest.mouseRelease(win,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,win.mapFromGlobal(end))
            final=win.geometry()
            assert final.width()==original.width()+120 and not win._resize_timer.isActive()
            QTest.qWait(50)
            assert win.geometry()==final and QWidget.mouseGrabber() is None
            print('PASS - High-rate moves coalesce; release applies the final size without drift',flush=True)
            for change in (win.showMaximized,win.showFullScreen):
                change();QTest.qWait(200)
                assert not any(h.isVisible() for h in win._resize_handles)
            win.showNormal();win.setGeometry(original);QTest.qWait(200)
            assert all(h.isVisible() for h in win._resize_handles)
            print('PASS - Corners preserve controls; handles follow window state',flush=True)
            print('WINDOW_RESIZE: PASSED',flush=True)
        finally:
            win.close()
            QTest.qWait(100)


if __name__=='__main__':
    run()
