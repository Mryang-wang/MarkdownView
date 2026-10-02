"""Real editor checks for selected word counts, comments and live UI language."""
import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.i18n import language, translate_context_menu, t


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(folder) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewReviewLanguageTest')
        app.setApplicationName('MarkdownViewReviewLanguageTest')
        settings = QSettings()
        settings.setValue('appearance/language', 'zh_CN')
        settings.setValue('appearance/theme', 'light')
        source = Path(folder) / '批注验证.md'
        source.write_text('# 标题\n\n你好 **world** 后续。\n\n重复文字。\n\n重复文字。\n', encoding='utf-8')
        win = MainWindow(startup_file=str(source)); win.resize(1240, 840); win.show()
        def ready():
            for _ in range(100):
                QTest.qWait(100)
                if win.current_tab().ready:
                    QTest.qWait(200); return
            raise AssertionError('Editor did not become ready')
        def ev(code):
            result=[]; loop=QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((function(){try{' + code + '}catch(e){return {testError:String(e),stack:e.stack};}})())', lambda value:(result.append(value),loop.quit()))
            QTimer.singleShot(8000, loop.quit); loop.exec()
            assert result and result[0], 'No JS result'
            data=json.loads(result[0]); assert not isinstance(data,dict) or not data.get('testError'), data
            return data
        def select(text, occurrence=0):
            ev('''
            var mode=document.getElementById('editor-mode').textContent;
            var root=document.querySelector('#vditor .vditor-ir pre[contenteditable],#vditor .vditor-wysiwyg pre[contenteditable],#vditor .vditor-sv[contenteditable]');
            root=Array.from(document.querySelectorAll('#vditor [contenteditable=true]')).find(e=>e.getBoundingClientRect().height>0);
            var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),nodes=[],visible='';
            while(walker.nextNode()){
              var n=walker.currentNode;
              if(n.parentElement.closest('.vditor-ir__marker,.vditor-ir__preview,.vditor-wysiwyg__preview,[data-type$="-marker"],[data-type="html-inline"],[data-type="newline"],[class*="vditor-sv__marker"]'))continue;
              nodes.push({node:n,start:visible.length});visible+=n.nodeValue;
            }
            var text='''+json.dumps(text)+''',start=-1;
            for(var i=0;i<='''+str(occurrence)+''';i++)start=visible.indexOf(text,start+1);
            if(start<0)throw new Error('Missing selection: '+visible);
            var end=start+text.length,a=nodes.find(n=>start>=n.start&&start<n.start+n.node.length),b=nodes.find(n=>end>n.start&&end<=n.start+n.node.length);
            var r=document.createRange();r.setStart(a.node,start-a.start);r.setEnd(b.node,end-b.start);
            root.focus();getSelection().removeAllRanges();getSelection().addRange(r);return true;
            '''); QTest.qWait(100)
        def click(selector):
            pos=ev('var r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};')
            QTest.mouseClick(win.view.focusProxy(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(pos['x']),round(pos['y']))); QTest.qWait(180)
        def value(): return ev('return window.currentMarkdown();')
        def state(): return ev("return {error:window.__err,count:document.getElementById('mdview-counter').textContent,cards:document.querySelectorAll('.review-card').length,highlight:CSS.highlights.has('mdv-comments'),hidden:document.getElementById('mdv-review-panel').hidden,body:window.__getEditorValue()};")
        def menu_action(menu_label, action_label):
            menu=next(m for m in win.findChildren(QMenu) if m.title()==menu_label)
            return next(a for a in menu.actions() if a.text()==action_label)
        try:
            ready(); assert not state()['error'],state()
            assert [a.text() for a in win.menuBar().actions() if a.text().strip()]==['文件(&F)','编辑(&E)','视图(&V)','设置(&S)','帮助(&H)']
            select('你好 world'); assert state()['count']=='选中 3 / 全文 15',state()
            assert win.editor_status.counter.text() == '选中 3 / 全文 15'
            QTest.mouseClick(win.editor_status.counter, Qt.MouseButton.LeftButton); QTest.qWait(180)
            assert ev("return document.getElementById('mdview-stats-title').textContent;")=='选中文字统计'
            assert ev("return document.querySelector('[data-stat=words]').textContent;")=='3'
            ev("document.getElementById('mdview-stats-close').click();return true;")
            select('你好 world')
            # Use native shortcut, not just direct JS invocation.
            QTest.keyClick(win.view.focusProxy(),Qt.Key.Key_M,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier); QTest.qWait(150)
            assert ev("return !document.getElementById('mdv-review-composer').hidden;")
            ev("document.getElementById('mdv-review-input').value='第一条批注 <script>alert(1)</script> -->';return true;")
            ev("window.showReview(false);window.showReview(true);return document.getElementById('mdv-review-input').value;")
            assert ev("return document.getElementById('mdv-review-input').value;")=='第一条批注 <script>alert(1)</script> -->'
            click('#mdv-review-submit'); assert state()['cards']==1 and state()['highlight'],state()
            assert win.current_tab().dirty
            content=value(); assert '<!-- markdownview-review:v1' in content and '<script>' not in content
            assert '<!-- markdownview-review' not in state()['body']
            for mode in ['sv','wysiwyg','ir']:
                ev("document.querySelector('[data-mode="+mode+"]').click();return true;"); QTest.qWait(300)
                assert state()['highlight'],(mode,state())
                select('你好 world'); assert state()['count'].startswith('选中 3 / 全文 '),(mode,state())
            select('重复文字',1); menu_action('编辑(&E)','添加批注…').trigger(); QTest.qWait(180)
            ev("document.getElementById('mdv-review-input').value='第二处重复文字的批注';document.getElementById('mdv-review-composer').requestSubmit();return true;"); QTest.qWait(200)
            assert state()['cards']==2,state()
            menu_action('视图(&V)','隐藏批注').trigger(); QTest.qWait(150); assert state()['hidden'] and not state()['highlight']
            assert value()==value() and '<!-- markdownview-review' in value()
            menu_action('视图(&V)','显示批注').trigger(); QTest.qWait(150)
            # Editing before an anchor moves it without losing it.
            ev("window.__setEditorValue('前置内容。\\n\\n'+window.__getEditorValue());return true;"); QTest.qWait(350)
            assert ev("return !document.querySelector('.review-card small');"),value()
            win.save_file(win.current_tab(),value()); QTest.qWait(200)
            assert not win.current_tab().dirty
            assert source.read_text(encoding='utf-8')==value()
            ev('window.setContent('+json.dumps(source.read_text(encoding='utf-8'))+');return true;'); QTest.qWait(300)
            assert state()['cards']==2 and state()['highlight'],state()
            # Keep comment text and selected text unchanged during language switches.
            original=value(); win.set_language('en'); QTest.qWait(250)
            assert [a.text() for a in win.menuBar().actions() if a.text().strip()]==['&File','&Edit','&View','&Settings','&Help']
            assert ev("return document.querySelector('.review-header h2').firstChild.textContent.trim();")=='Comments'
            select('你好 world'); assert state()['count'].startswith('Selected 3 / Total '),state()
            assert value()==original,(value(),original)
            win.view.grab().save(str(Path('tmp/review-english-test.png').resolve()))
            assert ev("return document.querySelector('.review-card p').textContent;")=='第一条批注 <script>alert(1)</script> -->'
            assert t('已保存：C:/test.md')=='Saved: C:/test.md'
            menu=QMenu(); [menu.addAction(label) for label in ['Undo','Copy','Paste','Select All','Copy image address']]
            win.set_language('zh_CN'); QTest.qWait(200); translate_context_menu(menu)
            assert [a.text() for a in menu.actions()]==['撤销','复制','粘贴','全选','复制图片地址']
            assert any(a.text()=='设置(&S)' for a in win.menuBar().actions())
            assert value()==original
            win.view.grab().save(str(Path('tmp/review-chinese-test.png').resolve()))
            # Open the actual WebEngine context menu with a Qt event; no OS cursor injection.
            context=[]
            comment_enabled=[]
            def inspect_popup():
                popup=QApplication.activePopupWidget()
                if popup and isinstance(popup,QMenu):
                    context.extend(a.text() for a in popup.actions() if not a.isSeparator())
                    action=next((a for a in popup.actions() if a.objectName()=='addReviewComment'),None)
                    comment_enabled.append(bool(action and action.isEnabled()))
                    if action and action.isEnabled():
                        QTest.mouseClick(popup,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,popup.actionGeometry(action).center())
                    else: popup.close()
            select('world');pos=ev("var r=getSelection().getRangeAt(0).getBoundingClientRect();return {x:r.x+5,y:r.y+5};")
            QTimer.singleShot(250,inspect_popup)
            QTest.mouseClick(win.view.focusProxy(),Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier,QPoint(round(pos['x']),round(pos['y'])))
            QTest.qWait(450)
            assert context and all(not any(c.isascii() and c.isalpha() for c in label.replace('Ctrl','')) for label in context),context
            assert comment_enabled==[True],comment_enabled
            assert ev("return !document.getElementById('mdv-review-composer').hidden && document.getElementById('mdv-review-quote').textContent==='world';")
            ev("document.getElementById('mdv-review-input').value='批注文字';document.getElementById('mdv-review-input').focus();document.getElementById('mdv-review-input').select();return true;")
            assert not ev('return window.canAddReviewComment();')
            ev("document.getElementById('mdv-review-cancel').click();return true;")
            print('CONTEXT_MENU',context,flush=True)
            # Selecting the second occurrence must locate the second paragraph.
            click('.review-card:last-child .review-quote')
            selected=ev("var r=getSelection().getRangeAt(0);return r.startContainer.parentElement.closest('p').textContent;")
            assert '重复文字' in selected
            assert ev("var p=getSelection().getRangeAt(0).startContainer.parentElement.closest('p');return Array.from(p.parentElement.querySelectorAll('p')).filter(n=>n.textContent==='重复文字。').indexOf(p);")==1
            menu_action('编辑(&E)','删除当前批注').trigger(); QTest.qWait(150); assert state()['cards']==1
            # Remove original text: keep the note instead of moving it to another copy.
            ev("window.__setEditorValue(window.__getEditorValue().replace('你好 **world** 后续。','删除后的文字。'));return true;"); QTest.qWait(300)
            assert ev("return !!document.querySelector('.review-card small');"),state()
            # Draft backups include review metadata.
            win._checkpoint_tab(win.current_tab()); QTest.qWait(400)
            draft=win.store.drafts()[0]
            assert '<!-- markdownview-review:v1' in draft['content'],draft
            ev("window.deleteReviewComment(document.querySelector('.review-card').dataset.commentId);return true;"); QTest.qWait(120)
            assert state()['cards']==0 and '<!-- markdownview-review' not in value()
            assert not state()['error'],state()
            # Language switching keeps live undo history and applies to new windows.
            ev("window.__setEditorValue('Undo check text.');return true;");QTest.qWait(300)
            select('check');click('[data-type=u-underline]');before=value();assert '<u>' in before,before
            win.set_language('en');QTest.qWait(200)
            for _ in range(3):
                click('[data-type=undo]')
                if '<u>' not in value():break
            assert '<u>' not in value() and 'check' in value(),value()
            other=MainWindow();other.show();QTest.qWait(500)
            assert any(a.text()=='&Settings' for a in other.menuBar().actions())
            assert other._language_actions['en'].isChecked() and language()=='en'
            other.current_tab().dirty=False;other.close();QTest.qWait(100)
            win.set_language('zh_CN');QTest.qWait(100)
            # HTML inline formatting is excluded from counts in every editor mode.
            formatted='A <u>hello</u> <mark style="background-color: #bfdbfe;">世界</mark> end.'
            for mode in ['ir','wysiwyg','sv']:
                ev("document.querySelector('[data-mode="+mode+"]').click();window.setContent("+json.dumps(formatted)+");return true;");QTest.qWait(250)
                select('hello');assert state()['count']=='选中 1 / 全文 5',(mode,state())
            ev("document.querySelector('[data-mode=ir]').click();return true;");QTest.qWait(150)
            # Save malformed metadata without stripping user-authored content.
            malformed='note\n\n<!-- markdownview-review:v1\n{broken}\n-->\n'
            ev('window.setContent('+json.dumps(malformed)+');return true;');QTest.qWait(200)
            assert '{broken}' in value(),value()
            win.view.grab().save(str(Path('tmp/review-ui-test.png').resolve()))
            print('PASS: selected counts, stats, native shortcut, comments, modes, safe persistence, anchoring, language, context labels',flush=True)
        finally:
            for tab in win._tab_list:tab.dirty=False;tab.backup_timer.stop()
            settings.setValue('appearance/language','zh_CN');win.close();QTest.qWait(150)
    return 0
if __name__=='__main__':sys.exit(run())
