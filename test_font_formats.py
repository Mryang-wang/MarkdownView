"""Real selection font controls, editing, Markdown round trips and native DOCX/PDF fonts."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.exporter import export_docx


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(folder) / 'profile')
        app = QApplication([]); app.setOrganizationName('MDViewFontTest'); app.setApplicationName('MDViewFontTest')
        QSettings().clear()
        path = Path(folder) / 'fonts.md'; path.write_text('Before Selected words after.\n', encoding='utf-8')
        win = MainWindow(startup_file=str(path)); win.resize(1240, 840); win.show()
        output = Path('tmp/font-formats'); output.mkdir(parents=True, exist_ok=True)

        def ev(code):
            result = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((()=>{try{' + code + '}catch(e){return {error:String(e),stack:e.stack}}})())', lambda value: (result.append(value), loop.quit()))
            QTimer.singleShot(8000, loop.quit); loop.exec()
            assert result and result[0], ('JS timed out', code)
            value = json.loads(result[0]); assert not isinstance(value, dict) or not value.get('error'), value
            return value

        def value(): return ev('return window.currentMarkdown();')

        def load(text, mode='ir'):
            ev('document.querySelector(\'[data-mode="' + mode + '"]\').click();window.setContent(' + json.dumps(text) + ');return true;'); QTest.qWait(250)

        root = "Array.from(document.querySelectorAll('#vditor [contenteditable]')).find(e=>e.getBoundingClientRect().height>0)"
        def select(text):
            ev('''var root=''' + root + ''',w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),nodes=[],content='';
            while(w.nextNode()){var n=w.currentNode;if(n.parentElement.closest('[data-type="html-inline"],.vditor-ir__marker,.vditor-ir__preview,.vditor-wysiwyg__preview,[data-type$="-marker"]'))continue;nodes.push({n,start:content.length});content+=n.nodeValue;}
            var text=''' + json.dumps(text) + ''',start=content.indexOf(text),end=start+text.length;
            if(start<0)throw Error('Missing text: '+text+' in '+content);
            var a=nodes.find(x=>start>=x.start&&start<x.start+x.n.length),b=nodes.find(x=>end>x.start&&end<=x.start+x.n.length),r=document.createRange();
            r.setStart(a.n,start-a.start);r.setEnd(b.n,end-b.start);root.focus();getSelection().removeAllRanges();getSelection().addRange(r);return true;'''); QTest.qWait(90)

        def click(selector):
            position = ev('var e=document.querySelector(' + json.dumps(selector) + ');if(!e)throw Error("Missing control");e.scrollIntoView({block:"nearest"});var r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};')
            QTest.mouseClick(win.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(position['x']), round(position['y']))); QTest.qWait(160)

        def choose(family):
            click('[data-type="mdv-font"]')
            for _ in range(30):
                if ev('return document.querySelectorAll("#mdv-font-options button").length;'): break
                QTest.qWait(60)
            ev('var e=document.getElementById("mdv-font-search");e.value=' + json.dumps(family) + ';e.dispatchEvent(new Event("input"));return true;')
            click('#mdv-font-options button[data-font=' + json.dumps(family) + ']')

        def fonts():
            return ev('return Array.from(' + root + '.querySelectorAll("[data-mdv-font-run]")).map(e=>({text:e.textContent,font:getComputedStyle(e).fontFamily}));')

        def undo(): click('[data-type="undo"]')

        def print_pdf(pdf):
            result=[]; loop=QEventLoop()
            win._export_pdf_to_path(win.current_tab(), str(pdf.resolve()), lambda success,error=None:(result.append((success,error)),loop.quit()))
            QTimer.singleShot(20000,loop.quit);loop.exec();assert result and result[0][0],result

        try:
            for _ in range(100):
                QTest.qWait(100)
                if win.current_tab().ready: break
            assert win.current_tab().ready; QTest.qWait(250)
            for mode in ('ir','wysiwyg','sv'):
                load('Before Selected words after.\n', mode); before=value()
                select('Selected words'); choose('Times New Roman'); current=value()
                assert 'font-family:' in current and 'Times New Roman' in current and 'Before' in current and 'after.' in current,current
                if mode != 'sv':
                    assert any(f['text']=='Selected words' and 'Times New Roman' in f['font'] for f in fonts()),(fonts(),current,ev('return '+root+'.innerHTML;'))
                    assert not any('Before' in f['text'] or 'after.' in f['text'] for f in fonts()),fonts()
                undo(); assert value()==before,(mode,value(),before)
                click('[data-type="redo"]');assert value()==current,(mode,value(),current)
                for next_mode in ('ir','wysiwyg','sv'):
                    ev('document.querySelector(' + json.dumps('[data-mode="' + next_mode + '"]') + ').click();return true;');QTest.qWait(180)
                    assert value().strip()==current.strip(),(mode,next_mode,value(),current)
            print('PASS font selection, exact scope, three modes and undo/redo',flush=True)
            load('First **bold** paragraph\n\nSecond paragraph\n', 'sv')
            ev('var e='+root+',r=document.createRange();r.selectNodeContents(e);e.focus();getSelection().removeAllRanges();getSelection().addRange(r);return true;')
            choose('Arial'); source_formatted=value()
            load(source_formatted)
            assert any('Second paragraph' in f['text'] and 'Arial' in f['font'] for f in fonts()),fonts()
            assert ev('return '+root+'.querySelectorAll("p").length;')>=2
            source_docx=output/'source-paragraphs.docx';export_docx(value(),str(source_docx.resolve()))
            with zipfile.ZipFile(source_docx) as archive: source_document=ET.fromstring(archive.read('word/document.xml'))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            for run in source_document.findall('.//w:r',ns):
                if ''.join(run.itertext()).strip(): assert run.find('w:rPr/w:rFonts',ns).get('{'+ns['w']+'}ascii')=='Arial',ET.tostring(run)
            print('PASS source-mode multi-paragraph fonts and export',flush=True)
            load('Before Redraw selection after.\n');select('Redraw selection');click('[data-type="mdv-font"]')
            before_ime=value()
            ev('var s=document.getElementById("mdv-font-search");s.dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}));s.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true,isComposing:true}));return true;')
            assert value()==before_ime and not ev('return document.getElementById("mdv-font-panel").hidden;')
            ev('document.getElementById("mdv-font-search").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true}));return true;')
            ev('window.__setEditorValue(window.__getEditorValue());return true;');QTest.qWait(160)
            ev('var s=document.getElementById("mdv-font-search");s.value="Arial";s.dispatchEvent(new Event("input"));return true;')
            click('#mdv-font-options button[data-font="Arial"]')
            assert any('Redraw selection' in f['text'] and 'Arial' in f['font'] for f in fonts()),fonts()
            print('PASS selection survives an editor redraw while the font picker is open',flush=True)
            load('Alpha **bold** normal\n\nSecond paragraph\n\n| Title | Other |\n| --- | --- |\n| Cell | Keep |\n')
            select('Alpha bold normalSecond paragraph');choose('Arial')
            assert all('Arial' in f['font'] for f in fonts()),fonts()
            assert '**' in value() and 'Second paragraph' in value() and '| Cell' in value(),value()
            select('bold');choose('Times New Roman')
            assert any(f['text']=='bold' and 'Times New Roman' in f['font'] for f in fonts()),fonts()
            # A new font also replaces older font choices contained inside the selection.
            select('Alpha bold normal');choose('Courier New')
            assert all('Courier New' in f['font'] for f in fonts() if f['text'] in ('Alpha ','bold',' normal')),fonts()
            select('Cell');choose('SimSun');assert any(f['text']=='Cell' and 'SimSun' in f['font'] for f in fonts()),fonts()
            # Keep text editable and preserve selection after asynchronous wrappers/rendering.
            select('bold');QTest.keyClicks(win.view.focusProxy(),'edited');QTest.qWait(300)
            assert 'edited' in value() and 'Second paragraph' in value(),value()
            assert any('edited' in f['text'] and 'Courier New' in f['font'] for f in fonts()),fonts()
            saved=value();win.save_file(win.current_tab(),saved);QTest.qWait(100)
            assert path.read_text(encoding='utf-8')==saved
            load(saved);assert value()==saved and fonts(),(value(),saved)
            edited_docx=output/'edited-fonts.docx';export_docx(saved,str(edited_docx.resolve()))
            with zipfile.ZipFile(edited_docx) as archive: edited_document=ET.fromstring(archive.read('word/document.xml'))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            for text,family in [('edited','Courier New'),('Cell','SimSun')]:
                run=next(r for r in edited_document.findall('.//w:r',ns) if text in ''.join(r.itertext()))
                assert run.find('w:rPr/w:rFonts',ns).get('{'+ns['w']+'}ascii')==family,ET.tostring(run)
            print('PASS mixed formatting, multiple paragraphs, replacement, table cells, typing and Markdown save/reopen',flush=True)
            # DOCX needs native run fonts for both Latin and East Asian glyphs.
            export_source = ('Default text.\n\n<span style="font-family: Times New Roman">Serif **bold** '
                '<u style="text-decoration-style: wavy"><mark style="background-color: #bfdbfe">Combined</mark></u> '
                '<span style="font-family: Courier New">Monospace</span> SerifAgain</span>\n\n'
                '<span style="font-family: SimSun">中文宋体</span>\n\nMath $x^2$.\n')
            load(export_source); docx=output/'fonts.docx';export_docx(value(),str(docx.resolve()))
            with zipfile.ZipFile(docx) as archive: document=ET.fromstring(archive.read('word/document.xml'))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            runs={''.join(r.itertext()):r for r in document.findall('.//w:r',ns)}
            for text,family in [('Combined','Times New Roman'),('Monospace','Courier New'),('中文宋体','SimSun')]:
                run=next(r for s,r in runs.items() if text in s);font=run.find('w:rPr/w:rFonts',ns)
                assert font is not None and all(font.get('{'+ns['w']+'}'+key)==family for key in ('ascii','hAnsi','eastAsia','cs')),(text,ET.tostring(run))
            combined=next(r for s,r in runs.items() if 'Combined' in s)
            assert combined.find('w:rPr/w:u',ns).get('{'+ns['w']+'}val')=='wave'
            assert combined.find('w:rPr/w:shd',ns).get('{'+ns['w']+'}fill')=='BFDBFE'
            pdf=output/'fonts.pdf';print_pdf(pdf)
            listing='\n'.join(name.decode('ascii') for name in re.findall(rb'/BaseFont\s*/([^\s/<>]+)',pdf.read_bytes()))
            assert 'TimesNewRoman' in listing and 'CourierNew' in listing and ('SimSun' in listing or 'STSong' in listing),listing
            (output/'pdf-fonts.txt').write_text(listing,encoding='utf-8')
            subprocess.run([shutil.which('pdftoppm'),'-png','-scale-to','1200','-singlefile',str(pdf),str(output/'fonts')],capture_output=True,check=True)
            print('PASS DOCX editable Latin/East Asian fonts with underline/highlight, and fonts present in rendered PDF',flush=True)
            select('Serif');choose('Arial')
            assert any('Arial' in f['font'] and 'Serif' in f['text'] for f in fonts()),(fonts(),value())
            select('Serif');click('[data-type="mdv-font"]');click('#mdv-font-reset')
            assert any('Segoe UI' in f['font'] and 'Serif' in f['text'] for f in fonts()),fonts()
            before=value();select('Serif');click('[data-type="mdv-font"]');QTest.keyClick(win.view.focusProxy(),Qt.Key.Key_Escape);QTest.qWait(80);assert value()==before
            ev('window.setReadOnly(true);return true;');click('[data-type="mdv-font"]');assert ev('return document.getElementById("mdv-font-panel").hidden;')
            ev('window.setReadOnly(false);return true;');select('Serif');click('[data-type="mdv-font"]')
            win.grab().save(str(output/'font-picker-light.png'))
            win.toggle_theme();win.set_language('en');QTest.qWait(160);win.grab().save(str(output/'font-picker-dark.png'))
            assert ev('return document.querySelector("#mdv-font-panel strong").textContent;')=='Font for selected text'
            win.resize(680,600);QTest.qWait(180)
            assert ev('var r=document.getElementById("mdv-font-panel").getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;')
            assert value()==before
            print('PASS font reset, cancellation, read-only, light/dark, localization and narrow layout',flush=True)
        finally:
            for tab in win._tab_list:tab.dirty=False
            win.close();QTest.qWait(100);QSettings().clear()


if __name__=='__main__':run()
