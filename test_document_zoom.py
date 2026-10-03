"""Document-only zoom: fixed toolbar, anchored palettes, selection and scrolling."""
import json
import os
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(directory) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewDocumentZoomTest')
        app.setApplicationName('MarkdownViewDocumentZoomTest')
        settings = QSettings()
        settings.setValue('appearance/theme', 'light')
        settings.setValue('appearance/sidebarVisible', True)
        settings.setValue('appearance/language', 'zh_CN')
        source = Path(directory) / 'zoom.md'
        picture = QImage(32, 20, QImage.Format.Format_RGB32)
        picture.fill(Qt.GlobalColor.blue)
        picture.save(str(Path(directory) / 'image.png'))
        source.write_text('# Zoom\n\nSelectable words here.\n\n$x^2$\n\n![image](image.png)\n\n' +
                          '\n\n'.join('Paragraph %d: writing with zoom.' % i for i in range(70)), encoding='utf-8')
        win = MainWindow(startup_file=str(source))
        win.resize(1240, 840)
        win.show()

        def wait(predicate):
            end = time.monotonic() + 10
            while time.monotonic() < end:
                if predicate():
                    return
                QTest.qWait(25)
            raise AssertionError('Timed out')

        def js(code):
            result = []
            win.view.page().runJavaScript('JSON.stringify((function(){' + code + '})())', result.append)
            wait(lambda: bool(result))
            assert result[0], code
            return json.loads(result[0])

        def click(selector):
            pos = js('var r=document.querySelector(' + json.dumps(selector) + ').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};')
            QTest.mouseClick(win.view.focusProxy(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, QPoint(round(pos['x']), round(pos['y'])))
            QTest.qWait(150)

        def dimensions(mode):
            return js('''
              var pane=document.querySelector('.vditor-''' + mode + '''');
              var root=pane.matches('[contenteditable]')?pane:pane.querySelector('pre[contenteditable]');
              var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),range=document.createRange();
              while(walker.nextNode()){var n=walker.currentNode,i=n.textContent.indexOf('Zoom');
                if(i>=0){range.setStart(n,i);range.setEnd(n,i+4);break;}}
              function rect(e){var r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom};}
              return {toolbar:rect(document.querySelector('.vditor-toolbar')),
                button:rect(document.querySelector('[data-type=bold]')), text:rect(range),pane:rect(pane),
                content:rect(document.querySelector('.vditor-content')),root:rect(root),
                image:root.querySelector('img')?rect(root.querySelector('img')):null,
                formula:root.querySelector('.katex')?rect(root.querySelector('.katex')):null,
                overflow:document.documentElement.scrollWidth>innerWidth,
                nestedScroll:pane!==root&&pane.scrollHeight>pane.clientHeight+2};
            ''')

        try:
            wait(lambda: win.current_tab().ready and win.current_tab().document_status[0] > 0)
            QTest.qWait(300)
            original = js('return window.currentMarkdown();')
            for mode in ('ir', 'wysiwyg', 'sv'):
                js("document.querySelector('[data-mode=" + mode + "]').click();return true;")
                win.set_page_zoom(1)
                QTest.qWait(200)
                baseline = dimensions(mode)
                for factor in (.5, 1.5, 2, 3, 1):
                    win.set_page_zoom(factor)
                    QTest.qWait(200)
                    state = dimensions(mode)
                    assert state['toolbar'] == baseline['toolbar'], (mode, factor, state, baseline)
                    assert state['button'] == baseline['button'], (mode, factor, state)
                    assert abs(state['text']['h'] - baseline['text']['h'] * factor) < 2, (mode, factor, state)
                    assert abs(state['pane']['bottom'] - state['content']['bottom']) < 2, (mode, factor, state)
                    assert not state['overflow'] and not state['nestedScroll'], (mode, factor, state)
                    for name in ('image', 'formula'):
                        if baseline[name]:
                            assert abs(state[name]['w'] - baseline[name]['w'] * factor) < 2, (mode, factor, name, state)
                    assert win.view.zoomFactor() == 1
                    assert win.editor_status.zoom.text() == str(round(factor * 100)) + '%'
                print('PASS - Fixed toolbar, scaled text/images/math and fitting viewport:', mode, flush=True)
                for factor in (.5, 2):
                    win.set_page_zoom(factor); QTest.qWait(120)
                    metrics = js('''var pane=document.querySelector('.vditor-''' + mode + '''');
                      var e=pane.matches('[contenteditable]')?pane:pane.querySelector('pre[contenteditable]');
                      e.scrollTop=0;window.__zoomScroller=e;var r=e.getBoundingClientRect(),scale=r.height/e.offsetHeight;
                      return {x:r.right-6*scale,y:r.top,w:r.width,h:r.height,
                        thumb:Math.max(28*scale,r.height*e.clientHeight/e.scrollHeight)};''')
                    QTest.qWait(60)
                    start = QPoint(round(metrics['x']), round(metrics['y'] + metrics['thumb'] / 2))
                    end = QPoint(start.x(), round(metrics['y'] + metrics['h'] * .7))
                    proxy = win.view.focusProxy()
                    QTest.mousePress(proxy, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
                    QTest.mouseMove(proxy, end, 70)
                    QTest.mouseRelease(proxy, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
                    QTest.qWait(130)
                    assert js('return window.__zoomScroller.scrollTop;') > 100, (mode, factor)
                    js('window.__zoomScroller.scrollTop=0;return true;')
                assert not win.current_tab().dirty
                print('PASS - Native scrollbar dragging at 50% and 200%:', mode, flush=True)

            js("document.querySelector('[data-mode=ir]').click();return true;")
            win.set_page_zoom(2)
            QTest.qWait(250)
            # Native mouse drag in scaled text; the unchanged toolbar must act on it.
            pos = js("var p=document.querySelector('.vditor-ir p'),r=document.createRange();r.setStart(p.firstChild,0);r.setEnd(p.firstChild,10);var b=r.getBoundingClientRect();return {x:b.x+1,y:b.y+b.height/2,w:b.width};")
            start = QPoint(round(pos['x']), round(pos['y']))
            end = QPoint(round(pos['x'] + pos['w'] - 1), start.y())
            proxy = win.view.focusProxy()
            QTest.mousePress(proxy, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
            QTest.mouseMove(proxy, end, 60)
            QTest.mouseRelease(proxy, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
            QTest.qWait(150)
            assert js('return getSelection().toString();').startswith('Selectable')
            for button, popup in (('[data-type=u-underline-style]', '#mdv-underline-panel'),
                                  ('[data-type=u-mark]', '#mdv-highlight-panel')):
                click(button)
                state = js('var a=document.querySelector(' + json.dumps(button) + ').getBoundingClientRect(),p=document.querySelector(' + json.dumps(popup) + '),r=p.getBoundingClientRect();return {hidden:p.hidden,top:r.top,bottom:r.bottom,right:r.right,width:r.width,anchor:a.bottom,viewport:innerWidth,height:innerHeight};')
                assert not state['hidden'] and abs(state['top'] - state['anchor'] - 8) < 2, state
                assert state['right'] <= state['viewport'] and state['bottom'] <= state['height'], state
                QTest.keyClick(proxy, Qt.Key.Key_Escape); QTest.qWait(100)
            click('[data-type=bold]')
            assert '**Selectable**' in js('return window.currentMarkdown();')
            click('[data-type=undo]')
            assert '**Selectable**' not in js('return window.currentMarkdown();')
            print('PASS - Mouse text selection, palette anchoring and formatting at 200%', flush=True)

            # Search a distant paragraph: viewport coordinates must be converted
            # back into the zoomed scroller's CSS coordinates before centering.
            for factor in (.5, 2, 3):
                win.set_page_zoom(factor)
                js("window.openFind(false);var q=document.getElementById('mdv-find-input');q.value='Paragraph 60';q.dispatchEvent(new Event('input',{bubbles:true}));return true;")
                QTest.qWait(220)
                js('window.findNext(1);return true;')
                QTest.qWait(180)
                state = js("var r=Array.from(CSS.highlights.get('mdv-active'))[0].getBoundingClientRect(),p=document.querySelector('.vditor-ir pre').getBoundingClientRect();return {top:r.top,bottom:r.bottom,viewportTop:p.top,viewportBottom:p.bottom};")
                assert state['top'] >= state['viewportTop'] and state['bottom'] <= state['viewportBottom'], (factor, state)
                js('window.closeFind();return true;')
            js("window.addReviewComment();document.getElementById('mdv-review-input').value='Zoom navigation';document.getElementById('mdv-review-composer').requestSubmit();return true;")
            QTest.qWait(180)
            for factor in (.5, 2, 3):
                win.set_page_zoom(factor)
                js('window.restorePosition(0);return true;'); QTest.qWait(150)
                click('.review-quote')
                state = js("var r=getSelection().getRangeAt(0).getBoundingClientRect(),p=document.querySelector('.vditor-ir pre').getBoundingClientRect(),panel=document.getElementById('mdv-review-panel').getBoundingClientRect();return {top:r.top,bottom:r.bottom,viewportTop:p.top,viewportBottom:p.bottom,panelWidth:panel.width};")
                assert state['top'] >= state['viewportTop'] and state['bottom'] <= state['viewportBottom'], (factor, state)
                assert state['panelWidth'] == 286
            js("window.deleteReviewComment(document.querySelector('.review-card').dataset.commentId);window.showReview(false);return true;")
            print('PASS - Comment navigation and fixed comment panel at multiple zoom levels', flush=True)
            win.set_page_zoom(2)
            js('window.restorePosition(0);return true;'); QTest.qWait(200)
            win.grab().save(str(Path('tmp/document-zoom-200.png').resolve()))
            # Viewing scale must not change the exported document's print scale.
            printed_pages = []
            for factor in (2, 1):
                win.set_page_zoom(factor)
                QTest.qWait(100)
                exported = []
                pdf_path = Path(directory) / ('zoom-%d.pdf' % factor)
                win._export_pdf_to_path(win.current_tab(), str(pdf_path),
                                        lambda success, error=None: exported.append((success, error)))
                wait(lambda: bool(exported))
                assert exported[0][0] and pdf_path.read_bytes().startswith(b'%PDF-'), exported
                assert js('return getComputedStyle(document.querySelector(".vditor-ir")).zoom;') == str(factor)
                pdf = QPdfDocument(app)
                assert pdf.load(str(pdf_path)) == QPdfDocument.Error.None_
                assert pdf.pageCount() > 0
                printed_pages.append([(pdf.pagePointSize(i), pdf.getAllText(i).text(),
                                       pdf.getAllText(i).bounds()) for i in range(pdf.pageCount())])
                pdf.close()
                pdf.deleteLater()
                QTest.qWait(30)
            assert printed_pages[0] == printed_pages[1], 'Viewing zoom changed PDF text or pagination'
            print('PASS - PDF keeps its original scale and restores the viewing scale', flush=True)
            win.set_page_zoom(2)
            QTest.keyClick(win.view.focusProxy(), Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
            QTest.qWait(180)
            assert win.current_tab().zoom_factor == 1 and dimensions('ir')['toolbar'] == baseline['toolbar']
            assert js('return window.currentMarkdown();') == original
            assert not js('return window.__err;')
            print('PASS - Search navigation at multiple zoom levels, Ctrl+0 and content preservation', flush=True)
        finally:
            win.current_tab().dirty = False
            win.close(); QTest.qWait(100)


if __name__ == '__main__':
    run()
