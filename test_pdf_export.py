# -*- coding: utf-8 -*-
"""端到端检查 PDF 导出是否生成可读取的 PDF 文件。"""
import os
import sys
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402


app = QApplication(sys.argv)
window = MainWindow()
window.show()
output_dir = os.environ.get("MDVIEW_PDF_TEST_DIR")
temp_dir = None if output_dir else tempfile.TemporaryDirectory()
if not output_dir:
    output_dir = temp_dir.name
os.makedirs(output_dir, exist_ok=True)
pdf_path = os.path.join(output_dir, "markdownview-export.pdf")
with open(pdf_path, "wb") as existing_pdf:
    existing_pdf.write(b"old PDF placeholder")
failed = False
completed = False


def finish(success, error=None):
    global failed, completed
    if completed:
        return
    completed = True
    try:
        with open(pdf_path, "rb") as pdf_file:
            signature = pdf_file.read(5)
        valid = success and os.path.getsize(pdf_path) > 1000 and signature == b"%PDF-"
        print("PDF_EXPORT:", "PASSED" if valid else "FAILED", flush=True)
        if error:
            print("PDF_ERROR:", error, flush=True)
        failed = not valid
    finally:
        window.current_tab().dirty = False
        window.close()
        if temp_dir:
            temp_dir.cleanup()
        app.quit()


def export_when_ready(result):
    if result:
        window.view.page().runJavaScript(
            "window.__setEditorValue('# PDF 标题\\n\\n这是 PDF 导出测试。');")
        QTimer.singleShot(300, lambda: window._export_pdf_to_path(
            window.current_tab(), pdf_path, finish))
        return
    QTimer.singleShot(300, wait_for_ready)


def wait_for_ready():
    window.view.page().runJavaScript(
        "typeof window.__setEditorValue === 'function'", export_when_ready)


QTimer.singleShot(1000, wait_for_ready)
QTimer.singleShot(45000, lambda: finish(False))
exit_code = app.exec()
sys.exit(1 if failed else exit_code)
