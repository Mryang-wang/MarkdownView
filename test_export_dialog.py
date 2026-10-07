"""实际导出后验证完成弹窗，并检查主题、语言及转换提示。"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.export_dialog import ExportSuccessDialog


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(folder) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewExportDialogTest')
        app.setApplicationName('MarkdownViewExportDialogTest')
        QSettings().setValue('appearance/language', 'zh_CN')
        QSettings().setValue('appearance/theme', 'light')
        source = Path(folder) / '设计笔记.md'
        content = '# 导出验证\n\n这是带有 **重点内容** 的文档。\n\n公式：\\(x^2 + y^2\\)。\n'
        source.write_text(content, encoding='utf-8')
        window = MainWindow(startup_file=str(source))
        window.resize(1080, 750); window.show()
        errors, captured = [], []
        timer = QTimer(); timer.setInterval(60)
        try:
            for _ in range(100):
                QTest.qWait(100)
                if window.current_tab().ready:break
            assert window.current_tab().ready
            QTest.qWait(250)

            def on_dialog():
                dialog = QApplication.activeModalWidget()
                if not isinstance(dialog,ExportSuccessDialog): return
                timer.stop()
                try:
                    captured.append(dialog._name)
                    assert dialog.done_button.isDefault()
                    assert dialog.windowTitle()=='导出成功'
                    assert Path(dialog._path,dialog._name).is_file()
                    assert dialog.name_label.textFormat()==Qt.TextFormat.PlainText
                    assert not dialog.details.isVisible() and not dialog.details_button.isVisible()
                    dialog.grab().save(str(Path('tmp/export-success-light.png').resolve()))
                    QTest.keyClick(dialog,Qt.Key.Key_Return)
                except Exception as error:
                    errors.append(repr(error));dialog.reject()
            timer.timeout.connect(on_dialog)
            docx = Path(folder)/'设计笔记.docx'
            timer.start()
            with patch.object(QFileDialog,'getSaveFileName',return_value=(str(docx),'')):
                window.export_docx(window.current_tab(),content)
            for _ in range(250):
                if captured or errors:break
                QTest.qWait(80)
            timer.stop()
            assert not errors,errors
            assert captured==[docx.name] and zipfile.is_zipfile(docx),captured
            assert not window.current_tab().dirty
            print('PASS - Actual DOCX export opens the styled success dialog; Enter closes it',flush=True)

            pdf=Path(folder)/'设计笔记.pdf'; timer.start()
            with patch.object(QFileDialog,'getSaveFileName',return_value=(str(pdf),'')):
                window.export_pdf(window.current_tab())
            for _ in range(250):
                if len(captured)==2 or errors:break
                QTest.qWait(80)
            timer.stop()
            assert not errors,errors
            assert captured==[docx.name,pdf.name],captured
            assert pdf.read_bytes().startswith(b'%PDF-') and pdf.stat().st_size>1000
            assert not window._pdf_export_in_progress
            print('PASS - Actual PDF export uses the same success dialog',flush=True)

            window.toggle_theme();window.set_language('en')
            dialog=ExportSuccessDialog(window,str(Path(folder)/('非常长的文档名称 '*15+'.docx')),'A conversion note with <tags> and & symbols.\n'*30)
            dialog.show();QTest.qWait(180)
            assert dialog.windowTitle()=='Export complete' and dialog.done_button.text()=='Done'
            assert dialog.details_button.text()=='View export notes'
            assert dialog.name_label.text()!=dialog._name
            assert dialog.name_label.toolTip()==dialog._name
            initial_height=dialog.height()
            QTest.mouseClick(dialog.details_button,Qt.MouseButton.LeftButton);QTest.qWait(100)
            assert dialog.details.isVisible() and '<tags>' in dialog.details.toPlainText()
            assert dialog.details_button.text()=='Hide export notes' and dialog.height()>initial_height
            dialog.grab().save(str(Path('tmp/export-success-dark-notes.png').resolve()))
            QTest.mouseClick(dialog.details_button,Qt.MouseButton.LeftButton);QTest.qWait(100)
            assert not dialog.details.isVisible() and dialog.height()==initial_height,(dialog.height(),initial_height)
            QTest.keyClick(dialog,Qt.Key.Key_Escape);assert not dialog.isVisible();dialog.deleteLater()
            print('PASS - Dark theme, English labels, long paths, expandable notes and Escape',flush=True)

            with patch.object(ExportSuccessDialog,'show_result') as success, patch.object(QMessageBox,'warning') as failure:
                window._finish_pdf_export(str(pdf),False,'test failure')
                assert not success.called and failure.called
            assert docx.exists() and pdf.exists()
            print('EXPORT_DIALOG: PASSED',flush=True)
        finally:
            timer.stop()
            for tab in window._tab_list:tab.dirty=False;tab.backup_timer.stop()
            window.close();QTest.qWait(100)
    return 0

if __name__=='__main__':sys.exit(run())
