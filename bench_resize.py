"""Benchmark the manual compatibility fallback, not native Windows resizing."""
import argparse
import json
import math
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


class MeasuredWindow(MainWindow):
    def __init__(self, *args, **kwargs):
        self.resize_count = 0
        super().__init__(*args, **kwargs)

    def resizeEvent(self, event):
        self.resize_count += 1
        super().resizeEvent(event)


def run(label, event_count=360):
    root = Path(__file__).resolve().parent
    output = root / 'tmp' / 'resize-benchmark'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory, patch.object(QWindow, 'startSystemResize', return_value=False):
        os.environ['MDVIEW_DATA_DIR'] = str(Path(directory) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewResizeBench')
        app.setApplicationName('MarkdownViewResizeBench')
        QSettings().setValue('appearance/theme', 'light')
        QSettings().setValue('appearance/sidebarVisible', True)
        source = Path(directory) / 'resize.md'
        body = (root / '02_建模方法_SCI精简重构版.md').read_text(encoding='utf-8')
        source.write_text(body * 3, encoding='utf-8')
        win = MeasuredWindow(startup_file=str(source))
        win.setGeometry(80, 80, 1100, 760)
        win.show()

        def js(code):
            loop = QEventLoop(); result = []
            win.view.page().runJavaScript(code, lambda value: (result.append(value), loop.quit()))
            QTimer.singleShot(8000, loop.quit); loop.exec()
            assert result, 'Editor did not reply'
            return result[0]

        try:
            for _ in range(150):
                QTest.qWait(100)
                if win.current_tab().ready:
                    break
            assert win.current_tab().ready
            QTest.qWait(500)
            assert js('document.hidden') is False
            point = QPoint(win.width()-2, win.height()-2)
            grip = win.childAt(point)
            start = win.mapToGlobal(point)
            QTest.mousePress(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip.mapFromGlobal(start))
            win.resize_count = 0
            costs = []; positions = []; done = QEventLoop()
            timer = QTimer(); timer.setTimerType(Qt.TimerType.PreciseTimer)
            def tick():
                i = len(costs)
                delta = QPoint(round(155*math.sin(i*math.pi/90)), round(55*math.sin(i*math.pi/90)))
                position = start + delta
                begin = time.perf_counter()
                QApplication.sendEvent(win, QMouseEvent(QEvent.Type.MouseMove, QPointF(win.mapFromGlobal(position)), QPointF(position), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
                costs.append((time.perf_counter()-begin)*1000)
                positions.append(position)
                if len(costs) == event_count:
                    timer.stop(); done.quit()
            timer.timeout.connect(tick)
            started = time.perf_counter(); cpu = time.process_time()
            timer.start(4); done.exec()
            QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, win.mapFromGlobal(positions[-1]))
            elapsed = time.perf_counter()-started
            cpu = time.process_time()-cpu
            result = {
                'backend': 'manual compatibility fallback (not native Windows resizing)',
                'label': label, 'document_bytes': source.stat().st_size,
                'pointer_events': len(costs), 'window_resize_events': win.resize_count,
                'elapsed_ms': round(elapsed*1000), 'main_cpu_ms': round(cpu*1000),
                'mouse_handler_p95_ms': round(sorted(costs)[int(len(costs)*.95)],2),
                'mouse_handler_total_ms': round(sum(costs)),
            }
            (output / (label+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result),flush=True)
        finally:
            win.current_tab().dirty=False
            win.close(); QTest.qWait(100)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',default='current')
    parser.add_argument('--events',default=360,type=int)
    args=parser.parse_args()
    run(args.label,args.events)
