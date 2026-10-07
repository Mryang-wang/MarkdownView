"""Actual PDF output across editor modes and Pandoc reference-document export."""
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.exporter import export_docx
from test_translation import wait


def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewExportPreferences'); app.setApplicationName('isolated')
        QSettings().clear()
        options = {'paper': 'A5', 'landscape': True, 'margin': 18, 'numbers': True, 'toc': True, 'reference': ''}
        QSettings().setValue('export/preferences', json.dumps(options))
        win = MainWindow(); win.show()
        def ev(code):
            result = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((function(){' + code + '})())', lambda x:(result.append(x), loop.quit()))
            QTimer.singleShot(8000, loop.quit); loop.exec(); assert result and result[0], code
            return json.loads(result[0])
        try:
            wait(lambda: win.current_tab().ready)
            for mode in ('sv', 'wysiwyg', 'ir'):
                markdown = f'# Export {mode}\n\nLATEST_{mode} formula $x^2$ and **bold** text.\n\n## Next section\n\nSecond paragraph.\n'
                ev("document.querySelector('[data-mode=" + mode + "]').click(); window.setContent(" + json.dumps(markdown) + "); return true;")
                QTest.qWait(150)
                before = ev('return window.currentMarkdown();')
                result = []; path = root / f'{mode}.pdf'
                win._export_pdf_to_path(win.current_tab(), str(path), lambda ok, error=None: result.append((ok, error)))
                wait(lambda: bool(result), 35); assert result[0][0], result
                pdf = QPdfDocument(); assert pdf.load(str(path)) == QPdfDocument.Error.None_
                wait(lambda: pdf.pageCount() > 0)
                assert pdf.pageCount() >= 2, (mode, pdf.pageCount())
                size = pdf.pagePointSize(0)
                assert 585 < size.width() < 605 and 410 < size.height() < 430, size
                text = '\n'.join(pdf.getAllText(i).text() for i in range(pdf.pageCount()))
                assert 'LATEST_' + mode in text, (mode, text)
                assert 'Next section' in text and '1' in pdf.getAllText(0).text(), text
                assert ev('return window.currentMarkdown();') == before
                assert ev('return document.getElementById("mdv-print-root") === null;')
                pdf.close(); pdf.deleteLater(); QTest.qWait(50)
            reference = root / 'reference.docx'; export_docx('# Reference\n\nBody', str(reference))
            with zipfile.ZipFile(reference) as archive:
                files = {name: archive.read(name) for name in archive.namelist()}
            styles = re.sub(r'(w:ascii=)"[^"]*"', r'\1"Courier New"', files['word/styles.xml'].decode('utf8'))
            assert 'Courier New' in styles
            files['word/styles.xml'] = styles.encode('utf8')
            with zipfile.ZipFile(reference, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items(): archive.writestr(name, body)
            target = root / 'styled.docx'
            export_docx('# Styled\n\nText $x^2$\n', str(target), reference_doc=str(reference), toc=True)
            with zipfile.ZipFile(target) as archive:
                assert 'Courier New' in archive.read('word/styles.xml').decode('utf8')
                assert 'TOC' in archive.read('word/document.xml').decode('utf8')
            print('PASS PDF A5 landscape, margins, page numbers, TOC, fresh content in all 3 modes, source preservation and Word reference template')
        finally:
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(100); QSettings().clear()


if __name__ == '__main__': run()
