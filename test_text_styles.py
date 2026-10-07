"""Native toolbar selection size/color, round trips, export and themed controls."""
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.exporter import export_docx


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(folder) / 'profile')
        app = QApplication([]); app.setOrganizationName('MDViewTextStyleTest'); app.setApplicationName('MDViewTextStyleTest')
        QSettings().clear()
        path = Path(folder) / 'styles.md'; path.write_text('Before Selected words after.\n', encoding='utf-8')
        win = MainWindow(startup_file=str(path)); win.resize(1240, 840); win.show()
        output = Path('tmp/text-styles'); output.mkdir(parents=True, exist_ok=True)

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
            r.setStart(a.n,start-a.start);r.setEnd(b.n,end-b.start);root.focus();getSelection().removeAllRanges();getSelection().addRange(r);return true;'''); QTest.qWait(80)

        def click(selector):
            position = ev('var e=document.querySelector(' + json.dumps(selector) + ');if(!e)throw Error("Missing control");e.scrollIntoView({block:"nearest"});var r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};')
            QTest.mouseClick(win.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(position['x']), round(position['y']))); QTest.qWait(150)

        def set_size(points):
            click('[data-type="mdv-font-size"]')
            ev('document.getElementById("mdv-size-value").value=' + json.dumps(str(points)) + ';return true;')
            click('#mdv-size-panel [data-apply]')

        def set_color(color):
            click('[data-type="mdv-text-color"]')
            ev('document.getElementById("mdv-text-color-hex").value=' + json.dumps(color) + ';return true;')
            click('#mdv-color-panel [data-apply]')

        def runs():
            return ev('return Array.from(' + root + '.querySelectorAll("[data-mdv-font-run]")).map(e=>({text:e.textContent,size:getComputedStyle(e).fontSize,color:getComputedStyle(e).color,font:getComputedStyle(e).fontFamily}));')

        def assert_style(text, size=None, color=None):
            found = [r for r in runs() if text in r['text']]; assert found, (text, runs(), value())
            if size: assert all(abs(float(r['size'][:-2]) - size * 4 / 3) < .02 for r in found), found
            if color: assert all(r['color'] == color for r in found), found

        def print_pdf(pdf):
            result=[]; loop=QEventLoop()
            win._export_pdf_to_path(win.current_tab(), str(pdf.resolve()), lambda success,error=None:(result.append((success,error)),loop.quit()))
            QTimer.singleShot(20000,loop.quit);loop.exec();assert result and result[0][0],result

        try:
            for _ in range(100):
                QTest.qWait(100)
                if win.current_tab().ready: break
            assert win.current_tab().ready; QTest.qWait(250)
            for mode in ('ir', 'wysiwyg', 'sv'):
                load('Before Selected words after.\n', mode); before=value()
                select('Selected words'); set_size(18.5); sized=value()
                assert 'font-size: 18.5pt' in sized, (mode, sized)
                click('[data-type="undo"]'); assert value()==before,(mode,value())
                click('[data-type="redo"]'); assert value()==sized,(mode,value())
                select('Selected words'); set_color('#C62828'); colored=value()
                assert 'color: #c62828' in colored,(mode,colored)
                click('[data-type="undo"]'); assert value()==sized,(mode,value())
                click('[data-type="redo"]'); assert value()==colored,(mode,value())
                load(colored)
                assert_style('Selected words',18.5,'rgb(198, 40, 40)')
                assert not any('Before' in r['text'] or 'after.' in r['text'] for r in runs()),runs()
                for next_mode in ('wysiwyg','sv','ir'):
                    ev('document.querySelector(' + json.dumps('[data-mode="' + next_mode + '"]') + ').click();return true;');QTest.qWait(180)
                    assert value().strip()==colored.strip(),(mode,next_mode,value(),colored)
            print('PASS exact selection size/color, half points, three modes, undo/redo and mode round trips',flush=True)

            load('Before Redraw selection after.\n'); select('Redraw selection'); click('[data-type="mdv-font-size"]')
            ev('window.__setEditorValue(window.__getEditorValue());return true;');QTest.qWait(150)
            click('#mdv-size-presets [data-size="22"]');assert_style('Redraw selection',22)
            select('Redraw selection');click('[data-type="mdv-text-color"]')
            ev('window.__setEditorValue(window.__getEditorValue());return true;');QTest.qWait(150)
            click('#mdv-text-colors [data-color="#2563eb"]');assert_style('Redraw selection',22,'rgb(37, 99, 235)')
            print('PASS font size/color panels preserve selection across an editor redraw',flush=True)

            load('Alpha **bold** normal\n\nSecond paragraph\n\n| Title | Other |\n| --- | --- |\n| Cell | Keep |\n')
            select('Alpha bold normalSecond paragraph');set_size(16)
            select('bold');set_color('#2563EB');select('Cell');set_size(24);select('Cell');set_color('#C62828')
            assert_style('bold',16,'rgb(37, 99, 235)');assert_style('Cell',24,'rgb(198, 40, 40)')
            select('bold');QTest.keyClicks(win.view.focusProxy(),'edited');QTest.qWait(250)
            assert_style('edited',16,'rgb(37, 99, 235)')
            saved=value();win.save_file(win.current_tab(),saved);assert path.read_text(encoding='utf-8')==saved
            load(saved);assert_style('edited',16,'rgb(37, 99, 235)');assert_style('Cell',24,'rgb(198, 40, 40)')
            docx=output/'styles.docx';export_docx(value(),str(docx.resolve()))
            with zipfile.ZipFile(docx) as archive: document=ET.fromstring(archive.read('word/document.xml'))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            for text,points,color in [('edited',32,'2563EB'),('Cell',48,'C62828')]:
                run=next(r for r in document.findall('.//w:r',ns) if text in ''.join(r.itertext()))
                assert run.find('w:rPr/w:sz',ns).get('{'+ns['w']+'}val')==str(points),ET.tostring(run)
                assert run.find('w:rPr/w:color',ns).get('{'+ns['w']+'}val')==color,ET.tostring(run)
            pdf=output/'styles.pdf';print_pdf(pdf)
            subprocess.run([shutil.which('pdftoppm'),'-png','-scale-to','1200','-singlefile',str(pdf),str(output/'styles')],capture_output=True,check=True)
            image=QImage(str(output/'styles.png'));red=blue=0
            for y in range(image.height()):
                for x in range(image.width()):
                    c=image.pixelColor(x,y)
                    red += c.red()>100 and c.red()>c.green()*1.8 and c.red()>c.blue()*1.8
                    blue += c.blue()>100 and c.blue()>c.red()*1.8 and c.blue()>c.green()*1.4
            assert red>50 and blue>50,(red,blue)
            print('PASS multi-paragraph, bold, table cells, typing, save/reopen, native DOCX and rendered PDF colors',flush=True)

            load('Highlighted word and next.\n');select('Highlighted word');set_color('#2563EB')
            select('Highlighted word');click('[data-type="u-mark"]');click('#mdv-highlight-presets [data-color="#bfdbfe"]')
            select('Highlighted word');set_size(18)
            assert_style('Highlighted word',18,'rgb(37, 99, 235)')
            ev('window.prepareDocumentPrint({});return true;');QTest.qWait(250)
            assert ev('return getComputedStyle(document.querySelector("#mdv-print-root mark")).color;')=='rgb(37, 99, 235)'
            ev('window.clearDocumentPrint();return true;')
            # Defaults override inherited explicit choices and adapt to the active theme.
            select('Highlighted word');click('[data-type="mdv-text-color"]');click('#mdv-color-panel [data-reset]')
            assert_style('Highlighted word',color='rgb(45, 45, 41)')
            win.toggle_theme();QTest.qWait(200);assert_style('Highlighted word',color='rgb(232, 232, 225)')
            select('Highlighted word');click('[data-type="mdv-font-size"]');click('#mdv-size-panel [data-reset]')
            assert all(r['size']=='15px' for r in runs() if 'Highlighted word' in r['text']),runs()
            print('PASS foreground/highlight precedence and size/automatic color reset in both themes',flush=True)

            before=value();select('Highlighted word');set_size(97);assert value()==before
            click('#mdv-size-panel [data-cancel]');select('Highlighted word');set_color('invalid');assert value()==before
            click('#mdv-color-panel [data-cancel]');ev('window.setReadOnly(true);return true;')
            click('[data-type="mdv-font-size"]');click('[data-type="mdv-text-color"]')
            assert ev('return document.getElementById("mdv-size-panel").hidden&&document.getElementById("mdv-color-panel").hidden;')
            ev('window.setReadOnly(false);return true;');win.set_language('en');win.resize(680,600);QTest.qWait(200)
            for button,panel in [('mdv-font-size','mdv-size-panel'),('mdv-text-color','mdv-color-panel')]:
                select('Highlighted word');click('[data-type="'+button+'"]')
                ev('document.getElementById("mdv-size-value").value="12";document.getElementById("mdv-text-color-hex").value="#2563EB";return true;')
                assert ev('var p=document.getElementById('+json.dumps(panel)+'),r=p.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&!/[\u4e00-\u9fff]/.test(p.innerText);')
                win.grab().save(str(output/(panel+'-dark.png')));click('#'+panel+' [data-cancel]')
            win.resize(480,360);QTest.qWait(200)
            for button,panel in [('mdv-font-size','mdv-size-panel'),('mdv-text-color','mdv-color-panel')]:
                select('Highlighted word');click('[data-type="'+button+'"]')
                assert ev('var p=document.getElementById('+json.dumps(panel)+'),r=p.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&p.scrollWidth<=p.clientWidth;'),panel
                click('#'+panel+' [data-cancel]')
            assert value()==before
            print('PASS invalid input, cancellation, read-only, localization and narrow dark UI',flush=True)
        finally:
            for tab in win._tab_list:tab.dirty=False
            win.close();QTest.qWait(100);QSettings().clear()


if __name__=='__main__':run()
