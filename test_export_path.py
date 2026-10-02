# -*- coding: utf-8 -*-
"""验证 DOCX/PDF 导出对话框共用并持久化最近一次保存目录。"""
import os
import sys
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFileDialog

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402


settings_dir = tempfile.TemporaryDirectory()
export_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(
    QSettings.Format.IniFormat,
    QSettings.Scope.UserScope,
    settings_dir.name)

app = QApplication(sys.argv)
app.setOrganizationName("MarkdownViewTests")
app.setApplicationName("ExportPath")
QSettings().clear()

window = MainWindow()
tab = window.current_tab()
tab.filepath = os.path.join(settings_dir.name, "测试文档.md")
window._remember_export_directory(os.path.join(export_dir.name, "上次导出.pdf"))

expected_docx = os.path.join(export_dir.name, "测试文档.docx")
expected_pdf = os.path.join(export_dir.name, "测试文档.pdf")

with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")) as chooser:
    window.export_docx(tab, "# 测试")
    docx_default = chooser.call_args.args[2]

with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")) as chooser:
    window.export_pdf(tab)
    pdf_default = chooser.call_args.args[2]

passed = docx_default == expected_docx and pdf_default == expected_pdf
print("EXPORT_PATH:", "PASSED" if passed else "FAILED", flush=True)
if not passed:
    print("DOCX_DEFAULT:", docx_default, flush=True)
    print("PDF_DEFAULT:", pdf_default, flush=True)

window.close()
settings_dir.cleanup()
export_dir.cleanup()
sys.exit(0 if passed else 1)
