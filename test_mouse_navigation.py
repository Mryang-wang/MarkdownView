"""实际鼠标输入验证正文滚动条，不使用系统鼠标注入。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QSettings, QTimer, Qt
from PySide6.QtGui import QMouseEvent, QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR']=str(Path(folder)/'profile')
        app=QApplication([]);app.setOrganizationName('MarkdownViewMouseTest');app.setApplicationName('MarkdownViewMouseTest')
        settings=QSettings();settings.setValue('appearance/sidebarVisible',True);settings.setValue('appearance/theme','light');settings.setValue('appearance/language','zh_CN')
        source=Path(folder)/'滚动条验证.md'
        source.write_text('# 长文档\n\n'+'\n\n'.join('第'+str(i)+'段：滚动条必须可以用鼠标左键拖动和点击轨道翻页。' for i in range(75)),encoding='utf-8')
        win=MainWindow(startup_file=str(source));win.setGeometry(80,80,1180,800);win.show()
        def ev(code):
            result=[];loop=QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((function(){'+code+'})())',lambda value:(result.append(value),loop.quit()))
            QTimer.singleShot(8000,loop.quit);loop.exec();assert result and result[0],'No JavaScript result';return json.loads(result[0])
        def send_move(widget, point):
            event=QMouseEvent(QEvent.Type.MouseMove,QPointF(point),QPointF(widget.mapToGlobal(point)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(widget,event);QTest.qWait(40)
        def drag(widget,start,end):
            global_start=widget.mapToGlobal(start);global_end=widget.mapToGlobal(end)
            QTest.mousePress(widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
            resizing=bool(win._resize_drag_edges)
            for i in range(1,7):send_move(widget,widget.mapFromGlobal(global_start+(global_end-global_start)*i/6))
            QTest.mouseRelease(widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,widget.mapFromGlobal(global_end));QTest.qWait(140)
            return resizing
        def hover_cursor(point):
            widget=win.view.focusProxy()
            QApplication.sendEvent(widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(point),QPointF(widget.mapToGlobal(point)),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
            QTest.qWait(160)
            return widget.cursor().shape()
        def scroll_state(selector='.vditor-ir'):
            return ev("var e=document.querySelector("+json.dumps(selector)+");e=e.querySelector('pre.vditor-reset')||e;var r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,top:e.scrollTop,max:e.scrollHeight-e.clientHeight,client:e.clientHeight,scroll:e.scrollHeight,bar:parseFloat(getComputedStyle(e,'::-webkit-scrollbar').width)};")
        try:
            for _ in range(100):
                QTest.qWait(100)
                if win.current_tab().ready:break
            assert win.current_tab().ready;QTest.qWait(200)
            assert [a.text() for a in win.menuBar().actions() if a.text().strip()]==['文件(&F)','编辑(&E)','视图(&V)','设置(&S)','帮助(&H)']
            def reset_scroll(selector):
                ev("var e=document.querySelector("+json.dumps(selector)+");e=e.querySelector('pre.vditor-reset')||e;e.scrollTop=0;return true;");QTest.qWait(80)
            def check_scrollbar(selector,label):
                reset_scroll(selector)
                s=scroll_state(selector);assert s['max']>200,(label,s)
                thumb=max(28,s['client']*s['client']/s['scroll'])
                start=QPoint(round(s['x']+s['w']-s['bar']/2),round(s['y']+thumb/2))
                end=QPoint(start.x(),round(s['y']+s['h']*.65))
                assert hover_cursor(start)==Qt.CursorShape.ArrowCursor,(label,'thumb cursor',win.view.focusProxy().cursor().shape())
                assert hover_cursor(end)==Qt.CursorShape.ArrowCursor,(label,'track cursor',win.view.focusProxy().cursor().shape())
                geo=win.geometry();resizing=drag(win.view.focusProxy(),start,end);after=scroll_state(selector)
                assert not resizing and after['top']>s['max']*.25 and win.geometry()==geo,(label,after,resizing)
                # Click the track above and below the thumb, then drag back to the top.
                top_before=after['top']
                QTest.mouseClick(win.view.focusProxy(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(start.x(),round(s['y']+8)));QTest.qWait(280)
                after=scroll_state(selector);assert after['top']<top_before-30,(label,'page up',after)
                top_before=after['top']
                QTest.mouseClick(win.view.focusProxy(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(start.x(),round(s['y']+s['h']-8)));QTest.qWait(280)
                after=scroll_state(selector);assert after['top']>top_before+30,(label,'page down',after)
                thumb_y=s['y']+after['top']/s['max']*(s['client']-thumb)+thumb/2
                assert not drag(win.view.focusProxy(),QPoint(start.x(),round(thumb_y)),QPoint(start.x(),round(s['y']+thumb/2)))
                assert scroll_state(selector)['top']<s['max']*.05 and win.geometry()==geo,(label,scroll_state(selector))
                print('PASS - '+label+' supports thumb dragging and track paging in both directions',flush=True)
            s=scroll_state();assert s['max']>1000,s
            start=QPoint(round(s['x']+s['w']-s['bar']/2),round(s['y']+s['client']*s['client']/s['scroll']/2))
            end=QPoint(start.x(),round(s['y']+s['h']*.65))
            geo=win.geometry();resizing=drag(win.view.focusProxy(),start,end);after=scroll_state()
            print('SCROLL_DRAG',{'before':s['top'],'after':after['top'],'resizing':resizing,'geometryChanged':win.geometry()!=geo},flush=True)
            assert not resizing and after['top']>s['max']*.3 and win.geometry()==geo,'Scrollbar drag is intercepted'
            reset_scroll('.vditor-ir')
            text_pos=ev("var p=document.querySelector('.vditor-ir pre p');var range=document.createRange();range.selectNodeContents(p);var r=range.getBoundingClientRect();return {x:r.x+3,y:r.y+r.height/2};")
            text_start=QPoint(round(text_pos['x']),round(text_pos['y']))
            assert hover_cursor(text_start)==Qt.CursorShape.IBeamCursor,'Body text must keep its text cursor'
            assert not drag(win.view.focusProxy(),text_start,text_start+QPoint(85,0))
            assert ev('return getSelection().toString().length;')>0,'Mouse selection in body text failed'
            print('PASS - Body text keeps its text cursor and mouse selection',flush=True)
            for mode in ['ir','wysiwyg','sv']:
                ev("document.querySelector('[data-mode="+mode+"]').click();return true;");QTest.qWait(160)
                check_scrollbar('.vditor-'+mode,mode)
            ev("document.querySelector('[data-mode=ir]').click();return true;");QTest.qWait(150)
            assert not win.current_tab().dirty,'Scrolling must not dirty the document'
            win._sidebar_action.setChecked(False);QTest.qWait(150);check_scrollbar('.vditor-ir','sidebar hidden')
            normal_geometry=win.geometry()
            win.showMaximized();QTest.qWait(250);check_scrollbar('.vditor-ir','maximized window')
            win.set_editor_fullscreen(win.current_tab(),True);QTest.qWait(250);check_scrollbar('.vditor-ir','fullscreen window')
            win.set_editor_fullscreen(win.current_tab(),False);QTest.qWait(250)
            assert win.isMaximized() and not win.isFullScreen()
            win.showNormal();QTest.qWait(250)
            assert not win.isMaximized() and not win.isFullScreen() and win.geometry()==normal_geometry
            print('PASS - Fullscreen restores maximized state and original window size',flush=True)
            win.toggle_theme();QTest.qWait(180);check_scrollbar('.vditor-ir','dark theme')
            # Long review lists share the right edge; their scrollbars must work too.
            notes=[{'id':str(i),'text':'第'+str(i)+'条批注：检查侧栏滚动。'*4,'anchor':{'start':0,'end':3,'quote':'长文档','before':'','after':'','detached':False}} for i in range(25)]
            marked=source.read_text(encoding='utf-8')+'\n\n<!-- markdownview-review:v1\n'+json.dumps({'version':1,'comments':notes},ensure_ascii=False)+'\n-->\n'
            ev('window.setContent('+json.dumps(marked)+');window.showReview(true);return true;');QTest.qWait(200)
            check_scrollbar('#mdv-review-panel','review panel')
            win.grab().save(str(Path('tmp/mouse-navigation-fixed.png').resolve()))
            ev('window.showReview(false);return true;');win._sidebar_action.setChecked(True);QTest.qWait(120)
            # Wide code blocks must expose a usable horizontal scrollbar too.
            wide='# 横向滚动\n\n```text\n'+('column_value ' * 160)+'\n```\n'
            ev('window.setContent('+json.dumps(wide)+');return true;');QTest.qWait(250)
            for _ in range(25):
                horizontal=ev("var e=Array.from(document.querySelectorAll('#vditor *')).find(e=>e.scrollWidth>e.clientWidth+200 && ['auto','scroll'].includes(getComputedStyle(e).overflowX) && e.getBoundingClientRect().height>20);if(!e)return null;window.__horizontalTest=e;var r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,client:e.clientWidth,scroll:e.scrollWidth,bar:parseFloat(getComputedStyle(e,'::-webkit-scrollbar').height)};")
                if horizontal:break
                QTest.qWait(100)
            assert horizontal,'Wide code block has no horizontal scrollbar'
            thumb=max(28,horizontal['client']**2/horizontal['scroll'])
            start=QPoint(round(horizontal['x']+thumb/2),round(horizontal['y']+horizontal['h']-horizontal['bar']/2))
            assert not drag(win.view.focusProxy(),start,QPoint(round(horizontal['x']+horizontal['w']*.65),start.y()))
            assert ev('return window.__horizontalTest.scrollLeft;')>100
            print('PASS - Wide code blocks support left-button horizontal scrolling',flush=True)
            # Window resizing remains possible in the dedicated outside border.
            geo=win.geometry();edge=QPoint(win.width()-2,win.height()//2)
            workspace=win.childAt(edge)
            global_start=win.mapToGlobal(edge)
            start=workspace.mapFromGlobal(global_start)
            # This helper sends Qt events; the separate native test covers the OS loop.
            with patch.object(QWindow,'startSystemResize',return_value=False):
                result=drag(workspace,start,start+QPoint(25,0))
            print('WINDOW_RESIZE',{'active':result,'before':str(geo),'after':str(win.geometry()),'frame':str(win.frameGeometry()),'global':str(global_start),'local':str(start),'maximized':win.isMaximized(),'fullscreen':win.isFullScreen()},flush=True)
            assert result and win.width()>geo.width()+15
            win.setGeometry(geo);QTest.qWait(150)
            print('PASS - Dedicated window border still resizes the window',flush=True)
            # The native open-document list also supports left-button scroll gestures.
            for i in range(25):
                other=Path(folder)/('侧栏'+str(i)+'.md');other.write_text('Document '+str(i),encoding='utf-8');win.new_tab(str(other))
            QTest.qWait(350)
            bar=win.document_list.verticalScrollBar();assert bar.isVisible() and bar.maximum()>0
            bar.setValue(bar.maximum());option=QStyleOptionSlider();option.initFrom(bar)
            option.orientation=Qt.Orientation.Vertical;option.minimum=bar.minimum();option.maximum=bar.maximum();option.sliderPosition=bar.value();option.sliderValue=bar.value();option.pageStep=bar.pageStep();option.singleStep=bar.singleStep()
            thumb=bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar,option,QStyle.SubControl.SC_ScrollBarSlider,bar)
            current=win.current_tab();count=win.tabs.count()
            assert not drag(bar,thumb.center(),QPoint(bar.width()//2,12))
            assert bar.value()<bar.maximum()*.2 and win.current_tab() is current and win.tabs.count()==count
            print('PASS - Sidebar scrollbar scrolls without selecting or detaching documents',flush=True)
            print('MOUSE_NAVIGATION: PASSED',flush=True)
        finally:
            for tab in win._tab_list:tab.dirty=False;tab.backup_timer.stop()
            win.close();QTest.qWait(100)
    return 0
if __name__=='__main__':sys.exit(run())
