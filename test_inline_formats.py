# -*- coding: utf-8 -*-
"""真实工具栏点击：下划线、多色高亮、自定义颜色、撤销、保存重开及导出。"""
import json
import os
import sys
import tempfile
import zipfile
import shutil
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow  # noqa: E402
from app.exporter import export_docx  # noqa: E402


def run():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["MDVIEW_DATA_DIR"] = str(Path(directory) / "profile")
        app = QApplication(sys.argv)
        app.setOrganizationName("MarkdownViewInlineTest")
        app.setApplicationName("MarkdownViewInlineTest")
        settings = QSettings()
        settings.setValue("appearance/theme", "light")
        settings.setValue("appearance/sidebarVisible", True)
        source = Path(directory) / "格式验证.md"
        source.write_text("# Format testing\n\nUnderline Blue Custom.\n", encoding="utf-8")
        window = MainWindow(startup_file=str(source))
        window.resize(1180, 820)
        window.show()
        mode = "ir"

        def ready():
            for _ in range(100):
                QTest.qWait(100)
                if window.current_tab().ready:
                    return
            raise AssertionError("Editor did not become ready")

        def evaluate(code):
            result = []
            loop = QEventLoop()
            def receive(value):
                result.append(value)
                loop.quit()
            window.view.page().runJavaScript(
                "JSON.stringify((function(){try{" + code +
                "}catch(e){return {testError:String(e)};}})())", receive)
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
            assert result and result[0], "JavaScript callback timed out"
            data = json.loads(result[0])
            assert not isinstance(data, dict) or not data.get("testError"), data
            return data

        def switch_mode(next_mode):
            nonlocal mode
            # 模式切换只是测试前置条件；直接调用现有模式按钮，再用原生鼠标测试格式工具。
            evaluate("document.querySelector('button[data-mode=\"' + " + json.dumps(next_mode) + " + '\"]').click();return true;")
            for _ in range(20):
                if evaluate("return getComputedStyle(document.querySelector('.vditor-" + next_mode + "')).display !== 'none';"):
                    mode = next_mode
                    QTest.qWait(200)
                    return
                QTest.qWait(50)
            raise AssertionError('Mode switch did not finish: ' + next_mode)

        def select(text):
            evaluate("""
                var container=document.querySelector('#vditor .vditor-""" + mode + """');
                var root=container.matches('[contenteditable]')?container:container.querySelector('[contenteditable]');
                var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),nodes=[],visible='';
                while(walker.nextNode()){
                  var n=walker.currentNode;
                  if(n.parentElement.closest('[data-type="html-inline"],.vditor-ir__marker,.vditor-ir__preview,.vditor-wysiwyg__preview,[data-type$="-marker"]'))continue;
                  nodes.push({node:n,start:visible.length});visible+=n.nodeValue;
                }
                var text=""" + json.dumps(text) + """,start=visible.indexOf(text),end=start+text.length;
                if(start<0)throw new Error('Selection text not found: '+text+' in '+root.className+': '+root.textContent);
                var a=nodes.find(n=>start>=n.start&&start<n.start+n.node.nodeValue.length);
                var b=nodes.find(n=>end>n.start&&end<=n.start+n.node.nodeValue.length);
                var r=document.createRange();r.setStart(a.node,start-a.start);r.setEnd(b.node,end-b.start);
                root.focus();var s=getSelection();s.removeAllRanges();s.addRange(r);return true;
            """)

        def click(selector):
            position = evaluate("var r=document.querySelector(" + json.dumps(selector) +
                                ").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};")
            QTest.qWait(60)
            QTest.mouseClick(window.view.focusProxy(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, QPoint(round(position["x"]), round(position["y"])))
            QTest.qWait(150)

        def value():
            return evaluate("return window.currentMarkdown();")

        def highlight_state():
            return evaluate("""
              window.refreshInlineFormats();var ranges={};
              CSS.highlights.forEach((h,n)=>{if(n.startsWith('mdv-'))ranges[n]=Array.from(h).map(r=>r.toString().replace(/\u200b/g,'')).join('');});
              return {ranges:ranges,error:window.__err,panel:!document.getElementById('mdv-highlight-panel').hidden};
            """)

        try:
            ready()
            select("Underline")
            click('button[data-type="u-underline"]')
            assert "<u>Underline</u>" in value(), value()
            assert highlight_state()["ranges"]["mdv-underline"] == "Underline"
            print("PASS - Real toolbar click applies visible underline", flush=True)

            select("Blue")
            click('button[data-type="u-mark"]')
            assert highlight_state()["panel"]
            assert evaluate("return document.querySelectorAll('#mdv-highlight-presets button').length;") == 6
            click('#mdv-highlight-presets button[data-color="#bfdbfe"]')
            assert highlight_state()["ranges"]["mdv-color-bfdbfe-0"] == "Blue"
            assert "background-color: #bfdbfe" in value()
            print("PASS - Six preset colors and native mouse selection preserve the selected text", flush=True)

            select("Custom")
            before = value()
            click('button[data-type="u-mark"]')
            evaluate("document.getElementById('mdv-highlight-hex').value='#badzzz';return true;")
            click('#mdv-highlight-apply')
            assert highlight_state()["panel"] and value() == before
            evaluate("var h=document.getElementById('mdv-highlight-hex');h.value='#7950F2';h.dispatchEvent(new Event('input'));return true;")
            click('#mdv-highlight-apply')
            assert "background-color: #7950f2; color: #ffffff" in value(), value()
            assert highlight_state()["ranges"]["mdv-color-7950f2-0"] == "Custom"
            formatted = value()
            click('button[data-type="undo"]')
            assert value() == before, (before, value())
            click('button[data-type="redo"]')
            assert value() == formatted
            print("PASS - Custom colors validate input, keep readable text and support undo/redo", flush=True)

            for next_mode in ("wysiwyg", "sv", "ir"):
                switch_mode(next_mode)
                assert "<u>Underline</u>" in value() and "#7950f2" in value(), value()
                state = highlight_state()
                assert not state["error"], state
                if mode != "sv":
                    assert state["ranges"]["mdv-underline"] == "Underline", state
                    assert state["ranges"]["mdv-color-bfdbfe-0"] == "Blue", state
                else:
                    assert not state["ranges"].get("mdv-underline")
            print("PASS - Formatting survives switches between all three editing modes", flush=True)

            select("Custom")
            unchanged = value()
            click('button[data-type="u-mark"]')
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Escape)
            QTest.qWait(100)
            assert not highlight_state()["panel"] and value() == unchanged
            print("PASS - Escape cancels the palette without changing the document", flush=True)

            original = value()
            for next_mode in ("wysiwyg", "sv", "ir"):
                switch_mode(next_mode)
                evaluate("window.__setEditorValue('Before Mode underline and Mode color.');return true;")
                QTest.qWait(150)
                select("Mode underline")
                click('button[data-type="u-underline"]')
                assert "<u>Mode underline</u>" in value(), (mode, value())
                select("Mode color")
                click('button[data-type="u-mark"]')
                click('#mdv-highlight-presets button[data-color="#bbf7d0"]')
                assert "background-color: #bbf7d0" in value(), (mode, value(), highlight_state())
                if mode != "sv":
                    assert highlight_state()["ranges"]["mdv-color-bbf7d0-0"] == "Mode color"
            print("PASS - Both formatting tools also apply directly in all three modes", flush=True)

            evaluate("window.__setEditorValue('Keep **bold** content.');return true;")
            select("bold content")
            click('button[data-type="u-underline"]')
            assert "**bold**" in value() and "<u>" in value(), value()
            select("bold content")
            click('button[data-type="u-mark"]')
            click('#mdv-highlight-presets button[data-color="#bfdbfe"]')
            assert "**bold**" in value() and "<u>" in value() and "#bfdbfe" in value(), value()
            select("bold content")
            click('button[data-type="u-mark"]')
            click('#mdv-highlight-presets button[data-color="#fecdd3"]')
            state = highlight_state()
            pink = next(key for key in state["ranges"] if key.startswith("mdv-color-fecdd3-"))
            blue = next(key for key in state["ranges"] if key.startswith("mdv-color-bfdbfe-"))
            assert state["ranges"][pink] == "bold content", state
            assert evaluate("return CSS.highlights.get(" + json.dumps(pink) + ").priority > CSS.highlights.get(" + json.dumps(blue) + ").priority;")
            print("PASS - Formatting preserves existing bold and underline; a new color takes precedence", flush=True)
            evaluate("window.__setEditorValue(" + json.dumps(original) + ");return true;")

            evaluate("window.requestSave();return true;")
            QTest.qWait(500)
            saved = source.read_text(encoding="utf-8")
            assert "<u>Underline</u>" in saved and "#7950f2" in saved and "#bfdbfe" in saved
            window.new_tab(filepath=str(source))
            ready()
            QTest.qWait(150)
            state = highlight_state()
            assert state["ranges"]["mdv-underline"] == "Underline", state
            assert state["ranges"]["mdv-color-7950f2-0"] == "Custom", state
            print("PASS - Saving and reopening retain underline and exact colors", flush=True)

            docx = Path(directory) / "formats.docx"
            export_docx(saved + '\n\n`<u>code</u>`\n\nMath $x^2$.', str(docx))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                  "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
            with zipfile.ZipFile(docx) as archive:
                doc = ET.fromstring(archive.read("word/document.xml"))
                styles = ET.fromstring(archive.read("word/styles.xml"))
            assert doc.find(".//w:u", ns) is not None
            fills = {shade.get("{" + ns["w"] + "}fill") for shade in styles.findall(".//w:shd", ns)}
            assert {"BFDBFE", "7950F2"}.issubset(fills), fills
            assert doc.find(".//m:oMath", ns) is not None
            assert "<u>code</u>" in "".join(doc.itertext())
            print("PASS - DOCX exports editable underline, exact highlight colors, code and native math", flush=True)

            pdf = Path("tmp/inline_formats.pdf").resolve()
            pdf.parent.mkdir(exist_ok=True)
            print_result, loop = [], QEventLoop()
            def printed(success, error=None):
                print_result.append((success, error)); loop.quit()
            window._export_pdf_to_path(window.current_tab(), str(pdf), printed)
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            assert print_result and print_result[0][0], print_result
            renderer = shutil.which("pdftoppm")
            assert renderer, "pdftoppm is required to verify PDF colors"
            prefix = str(pdf.with_suffix(""))
            subprocess.run([renderer, "-png", "-scale-to-x", "1100", "-scale-to-y", "-1", "-singlefile", str(pdf), prefix],
                           check=True, capture_output=True, timeout=20)
            image = QImage(prefix + ".png").convertToFormat(QImage.Format.Format_RGBA8888)
            pixels = bytes(image.constBits())
            blue, purple = pixels.count(bytes.fromhex("bfdbfeff")), pixels.count(bytes.fromhex("7950f2ff"))
            assert blue > 50 and purple > 50, ("PDF lost highlight colors", blue, purple)
            print("PASS - Rendered PDF retains the actual blue and custom purple highlights", flush=True)

            line_samples = [('double', 'Double line'), ('wavy', 'Wave line'),
                            ('dashed', 'Dash line'), ('dotted', 'Dot line'), ('solid', 'Single line')]
            evaluate("window.__setEditorValue(" + json.dumps('# Underline styles\n\n' +
                '\n\n'.join(text for _, text in line_samples) + '\n\nRemembered line.') + ");return true;")
            QTest.qWait(150)
            for line_style, text in line_samples:
                select(text)
                before = value()
                click('button[data-type="u-underline-style"]')
                assert evaluate("return document.querySelectorAll('#mdv-underline-options button').length;") == 5
                click('#mdv-underline-options button[data-underline-style="' + line_style + '"]')
                name = 'mdv-underline' if line_style == 'solid' else 'mdv-underline-' + line_style
                assert text in highlight_state()['ranges'][name], (line_style, value(), highlight_state())
                if line_style != 'solid':
                    assert 'text-decoration-style: ' + line_style in value(), value()
                applied = value()
                click('button[data-type="undo"]')
                assert value() == before, (before, value())
                click('button[data-type="redo"]')
                assert value() == applied
                if line_style == 'dotted':
                    select('Remembered line')
                    click('button[data-type="u-underline"]')
                    assert 'Remembered line' in highlight_state()['ranges']['mdv-underline-dotted']
            print("PASS - Five underline styles use real menu clicks, undo/redo and the last selected style", flush=True)

            select('Wave line')
            click('button[data-type="u-mark"]')
            click('#mdv-highlight-presets button[data-color="#bfdbfe"]')
            styled_value = value()
            for next_mode in ('wysiwyg', 'sv', 'ir'):
                switch_mode(next_mode)
                assert 'text-decoration-style: wavy' in value(), value()
                assert not highlight_state()['error'], highlight_state()
                if mode != 'sv':
                    assert highlight_state()['ranges']['mdv-underline-wavy'] == 'Wave line', highlight_state()
            select('Wave line')
            click('button[data-type="u-underline-style"]')
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Escape)
            QTest.qWait(100)
            assert value() == styled_value
            assert evaluate("return document.getElementById('mdv-underline-panel').hidden;")

            # 同一段文字更换线型，只绘制新线型；不损失内嵌的颜色或文字。
            click('button[data-type="u-underline-style"]')
            click('#mdv-underline-options button[data-underline-style="double"]')
            assert 'Wave line' in highlight_state()['ranges']['mdv-underline-double']
            assert 'Wave line' not in highlight_state()['ranges'].get('mdv-underline-wavy', '')
            select('Wave line')
            click('button[data-type="u-underline-style"]')
            click('#mdv-underline-options button[data-underline-style="wavy"]')
            evaluate("window.requestSave();return true;")
            QTest.qWait(400)
            saved_lines = source.read_text(encoding='utf-8')
            window.new_tab(filepath=str(source))
            ready()
            assert highlight_state()['ranges']['mdv-underline-wavy'] == 'Wave line', highlight_state()
            print("PASS - Line styles retain colors, support replacement and survive mode changes and reopening", flush=True)

            line_docx = Path(directory) / 'line_styles.docx'
            export_docx(saved_lines + '\n\n<u style="text-decoration-style: wavy">Outer <u>inner single</u></u>.'
                        '\n\n<mark style="background-color: #bbf7d0"><u style="text-decoration-style: dotted">Combined</u></mark>',
                        str(line_docx))
            with zipfile.ZipFile(line_docx) as archive:
                doc = ET.fromstring(archive.read('word/document.xml'))
            runs = {''.join(run.itertext()): run for run in doc.findall('.//w:r', ns)}
            for text, expected in [('Single line', 'single'), ('Double line', 'double'), ('Wave line', 'wave'),
                                   ('Dash line', 'dash'), ('Dot line', 'dotted'), ('inner single', 'single'), ('Combined', 'dotted')]:
                underline = runs[text].find('w:rPr/w:u', ns)
                assert underline is not None and underline.get('{' + ns['w'] + '}val') == expected, (text, ET.tostring(runs[text]))
            for text, fill in [('Wave line', 'BFDBFE'), ('Combined', 'BBF7D0')]:
                assert runs[text].find('w:rPr/w:shd', ns).get('{' + ns['w'] + '}fill') == fill
            print("PASS - DOCX contains native single/double/wave/dash/dotted lines and combined highlight colors", flush=True)

            line_pdf = Path('tmp/underline_styles.pdf').resolve()
            print_result, loop = [], QEventLoop()
            window._export_pdf_to_path(window.current_tab(), str(line_pdf), printed)
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            assert print_result and print_result[0][0], print_result
            subprocess.run([renderer, '-png', '-scale-to-x', '1100', '-scale-to-y', '-1', '-singlefile',
                            str(line_pdf), str(line_pdf.with_suffix(''))], check=True, capture_output=True, timeout=20)
            select('Double line')
            click('button[data-type="u-underline-style"]')
            assert window.grab().save(os.path.abspath('screenshot_underline_styles_light.png'))
            window.toggle_theme()
            QTest.qWait(200)
            assert evaluate("return !document.getElementById('mdv-underline-panel').hidden;")
            assert window.grab().save(os.path.abspath('screenshot_underline_styles_dark.png'))
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Escape)
            window.toggle_theme()
            print("PASS - PDF and light/dark style menu previews captured", flush=True)

            for next_mode in ('wysiwyg', 'sv', 'ir'):
                switch_mode(next_mode)
                evaluate("window.__setEditorValue('A Mode sample to format.');return true;")
                QTest.qWait(200)
                select('Mode sample')
                click('button[data-type="u-underline-style"]')
                if mode == 'sv':
                    # 模拟源码高亮的延迟重绘，弹出菜单必须保留原选中的文字。
                    evaluate("var r=document.querySelector('.vditor-sv');r.innerHTML=r.innerHTML;return true;")
                click('#mdv-underline-options button[data-underline-style="wavy"]')
                assert '<u style="text-decoration-style: wavy">Mode sample</u>' in value(), (mode, value())
            select('Mode sample')
            click('button[data-type="u-underline-style"]')
            window.statusBar().showMessage('Resize while choosing a line style', 100)
            QTest.qWait(200)
            assert evaluate("return !document.getElementById('mdv-underline-panel').hidden;")
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Home)
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Down)
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Return)
            QTest.qWait(200)
            assert highlight_state()['ranges']['mdv-underline-double'] == 'Mode sample', highlight_state()
            print("PASS - Styles apply in every mode, retain selection after a source redraw and support keyboard navigation", flush=True)

            # 用含中文的示例截图检查格式颜色与弹出面板，避免只验证 DOM。
            evaluate("window.__setEditorValue(" + json.dumps(
                '# 让重点更清晰\n\n<u>下划线标出需要关注的内容</u>，让阅读更有层次。\n\n'
                '<mark style="background-color: #bfdbfe; color: #272724">蓝色记录关键信息</mark>，'
                '<mark style="background-color: #bbf7d0; color: #272724">绿色标记已完成的想法</mark>。\n\n'
                '<mark style="background-color: #7950f2; color: #ffffff">自定义颜色适合自己的写作习惯</mark>。'
            ) + ");return true;")
            QTest.qWait(150)
            select("自己的写作习惯")
            click('button[data-type="u-mark"]')
            assert window.grab().save(os.path.abspath("screenshot_inline_formats_light.png"))
            window.toggle_theme()
            QTest.qWait(300)
            assert window.grab().save(os.path.abspath("screenshot_inline_formats_dark.png"))
            click('#mdv-highlight-cancel')
            window.resize(640, 650)
            QTest.qWait(200)
            select("自己的写作习惯")
            click('button[data-type="u-underline-style"]')
            assert evaluate("var r=document.getElementById('mdv-underline-panel').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;")
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Escape)
            click('button[data-type="u-mark"]')
            assert evaluate("var r=document.getElementById('mdv-highlight-panel').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;")
            QTest.keyClick(window.view.focusProxy(), Qt.Key.Key_Escape)
            print("PASS - Color palette remains within the viewport in a narrow window", flush=True)
            print("PASS - Light and dark theme previews captured", flush=True)
        finally:
            for tab in window._tab_list:
                tab.dirty = False
            window.close()
            settings.clear()
            app.processEvents()
        print("INLINE_FORMATS: PASSED", flush=True)


if __name__ == "__main__":
    run()
