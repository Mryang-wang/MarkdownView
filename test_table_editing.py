"""Table editing in the actual Qt editor, including the native right-click menu."""
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow


def run():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['MDVIEW_DATA_DIR'] = str(Path(folder) / 'profile')
        app = QApplication([])
        app.setOrganizationName('MarkdownViewTableTest')
        app.setApplicationName('MarkdownViewTableTest')
        settings = QSettings()
        settings.setValue('appearance/language', 'zh_CN')
        settings.setValue('appearance/theme', 'light')
        source = Path(folder) / 'tables.md'
        source.write_text('Before\n\nAfter\n', encoding='utf-8')
        win = MainWindow(startup_file=str(source)); win.resize(1240, 840); win.show()
        shots = Path('tmp/table-editing'); shots.mkdir(parents=True, exist_ok=True)

        def ev(code):
            result = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((function(){try{' + code + '}catch(e){return {testError:String(e),stack:e.stack};}})())', lambda value: (result.append(value), loop.quit()))
            QTimer.singleShot(8000, loop.quit); loop.exec()
            assert result and result[0], 'No JavaScript result'
            data = json.loads(result[0])
            assert not isinstance(data, dict) or not data.get('testError'), data
            return data

        def click(selector):
            p = ev('var r=document.querySelector(' + json.dumps(selector) + ').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};')
            QTest.mouseClick(win.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(p['x']), round(p['y']))); QTest.qWait(160)

        root = "Array.from(document.querySelectorAll('#vditor [contenteditable]')).find(e=>e.getBoundingClientRect().height>0)"

        def value(): return ev('return window.currentMarkdown();')

        def load(text, mode='ir'):
            ev('document.querySelector(\'[data-mode="' + mode + '"]\').click();window.setContent(' + json.dumps(text) + ');return true;')
            QTest.qWait(320)

        def table():
            return ev('var t=' + root + '.querySelector("table");return t?Array.from(t.rows).map(r=>Array.from(r.cells).map(c=>c.textContent.trim())):null;')

        def context(row=0, col=0):
            return ev('var t=' + root + '.querySelector("table"),c=t.rows[' + str(row) + '].cells[' + str(col) + '],r=c.getBoundingClientRect();return window.tableContext(r.x+r.width/2,r.y+r.height/2);')

        def act(action, row=0, col=0):
            assert context(row, col)['editable']
            assert ev('return window.tableAction(' + json.dumps(action) + ');')
            QTest.qWait(240)

        def undo(): click('#vditor .vditor-toolbar [data-type="undo"]')

        def native_menu(command, row=0, col=0):
            point = ev('var c=' + root + '.querySelector("table").rows[' + str(row) + '].cells[' + str(col) + '],r=c.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};')
            found = []

            def choose():
                popup = QApplication.activePopupWidget()
                if not isinstance(popup, QMenu):
                    found.append('missing popup'); return
                actions = popup.actions() + [a for m in popup.findChildren(QMenu) for a in m.actions()]
                target = next((a for a in actions if a.objectName() == 'table_' + command), None)
                found.append(bool(target))
                popup.grab().save(str(shots / 'context-menu.png'))
                QTimer.singleShot(2500, popup.close)
                if target:
                    parent = target.parent()
                    if parent is not popup:
                        popup.setActiveAction(parent.menuAction())
                        QTest.keyClick(popup, Qt.Key.Key_Right); QTest.qWait(200)
                        parent.grab().save(str(shots / 'insert-menu.png'))
                    parent.setActiveAction(target)
                    QTest.mouseClick(parent, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, parent.actionGeometry(target).center())
                else: popup.close()

            QTimer.singleShot(350, choose)
            QTest.mouseClick(win.view.focusProxy(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(round(point['x']), round(point['y'])))
            QTest.qWait(700)
            assert found == [True], found

        fixture = 'Before **bold**\n\n| Name | Value |\n| :--- | ---: |\n| A | **one** |\n| B | `two` |\n\nAfter $x^2$\n'
        try:
            for _ in range(100):
                QTest.qWait(100)
                if win.current_tab().ready: break
            assert win.current_tab().ready
            QTest.qWait(300)
            # Different dimensions, single header row, insertion position, and undo in all modes.
            for mode in ('ir', 'wysiwyg', 'sv'):
                for rows, cols in ((5, 4), (1, 1)):
                    load('Before\n\nAfter\n', mode)
                    ev('var e=' + root + ',w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),n;while(w.nextNode()){if(w.currentNode.textContent.includes("Before")){n=w.currentNode;break;}}var r=document.createRange();r.setStart(n,n.textContent.indexOf("Before")+6);r.collapse(true);e.focus();getSelection().removeAllRanges();getSelection().addRange(r);return true;')
                    before = value(); click('#vditor .vditor-toolbar [data-type="table"]')
                    assert ev('return !document.getElementById("mdv-table-panel").hidden;')
                    if mode == 'ir' and rows == 5:
                        ev('document.getElementById("mdv-table-rows").value="0";document.getElementById("mdv-table-panel").requestSubmit();return true;')
                        assert value() == before
                        win.grab().save(str(shots / 'insert-light.png'))
                    ev('document.getElementById("mdv-table-rows").value=' + str(rows) + ';document.getElementById("mdv-table-cols").value=' + str(cols) + ';return true;')
                    click('#mdv-table-panel button[type="submit"]')
                    current = value(); lines = [line for line in current.splitlines() if line.startswith('|')]
                    assert len(lines) == rows + 1, (mode, rows, current)
                    assert current.index('Before') < current.index('|') < current.index('After'), (mode, current)
                    if mode != 'sv': assert len(table()) == rows and all(len(r) == cols for r in table()), table()
                    undo(); assert value() == before, (mode, value(), before)
            # All four insertion directions; header promotion; deletion and format preservation.
            for mode in ('ir', 'wysiwyg'):
                load(fixture, mode); original = value()
                for action, row, col in [('rowAbove', 0, 0), ('rowBelow', 1, 1), ('columnLeft', 0, 0), ('columnRight', 2, 1)]:
                    act(action, row, col)
                    expected_rows = 4 if action.startswith('row') else 3
                    expected_cols = 3 if action.startswith('column') else 2
                    assert len(table()) == expected_rows and all(len(r) == expected_cols for r in table()), (action, table())
                    assert '**one**' in value() and '`two`' in value() and 'After \\(x^2\\)' in value(), value()
                    undo(); assert value() == original, (action, value(), original)
                act('deleteRow', 0, 0); assert table()[0][0] == 'A', table()
                assert '**one**' in value() and 'Name' not in value(), value()
                undo(); assert value() == original
                act('deleteColumn', 1, 1); assert all(len(r) == 1 for r in table()), table()
                undo(); assert value() == original
                act('selectTable'); assert ev('return !!document.querySelector(".mdv-table-selected");')
                # Delete in an auxiliary input must never remove a previously selected table.
                ev('document.getElementById("mdv-find-panel").hidden=false;var input=document.getElementById("mdv-find-input");input.value="abc";input.focus();input.setSelectionRange(0,1);return true;')
                QTest.keyClick(win.view.focusProxy(), Qt.Key.Key_Delete); QTest.qWait(100)
                assert value() == original and ev('return document.getElementById("mdv-find-input").value;') == 'bc'
                ev('document.getElementById("mdv-find-panel").hidden=true;return true;'); act('selectTable')
                QTest.keyClick(win.view.focusProxy(), Qt.Key.Key_Delete); QTest.qWait(250)
                assert table() is None and 'Before **bold**' in value() and 'After \\(x^2\\)' in value(), value()
                undo(); assert value() == original, (value(), original)
                click('#vditor .vditor-toolbar [data-type="redo"]'); assert table() is None
                undo(); assert value() == original
                act('deleteTable'); assert table() is None
                undo(); assert value() == original
                # Last row / column becomes an ordinary editable paragraph.
                for action in ('deleteRow', 'deleteColumn'):
                    load('| Header |\n| --- |\n', mode); act(action)
                    assert table() is None, value()
                    QTest.keyClicks(win.view.focusProxy(), 'Text'); QTest.qWait(200)
                    assert 'Text' in value(), value()
            load(fixture)
            print('PASS: insertion and structural edits in each mode, undo/redo and last-cell deletion', flush=True)
            native_menu('rowBelow', 1, 0); assert len(table()) == 4, table()
            undo(); native_menu('deleteTable'); assert table() is None
            undo(); assert len(table()) == 3
            assert win.current_tab().dirty
            # Read-only and translation reading surfaces cannot mutate the document.
            before = value(); context()
            ev('window.setReadOnly(true);return true;'); QTest.qWait(100)
            assert not ev('return window.tableAction("deleteTable");')
            click('#vditor .vditor-toolbar [data-type="table"]')
            assert ev('return document.getElementById("mdv-table-panel").hidden;') and value() == before
            ev('window.setReadOnly(false);window.setDocumentZoom(1.75);return true;'); QTest.qWait(200)
            native_menu('columnRight'); assert len(table()[0]) == 3
            undo(); ev('window.setDocumentZoom(1);return true;')
            load('Before\n\nAfter\n')
            win.set_language('en'); QTest.qWait(150)
            click('#vditor .vditor-toolbar [data-type="table"]')
            assert ev('return document.getElementById("mdv-table-title").textContent;') == 'Insert table'
            win.toggle_theme(); QTest.qWait(200)
            positions = ev('return ["rows","cols"].map(id=>document.getElementById("mdv-table-"+id).getBoundingClientRect().top);')
            assert abs(positions[0] - positions[1]) < 1, positions
            win.grab().save(str(shots / 'insert-dark-english.png'))
            QTest.keyClick(win.view.focusProxy(), Qt.Key.Key_Escape); QTest.qWait(100)
            assert ev('return document.getElementById("mdv-table-panel").hidden;')
            print('PASS: table dimensions, insertion/deletion, selection, undo/redo, native menus, modes, read-only, zoom and localization')
        finally:
            for tab in win._tab_list: tab.dirty = False
            settings.setValue('appearance/language', 'zh_CN'); win.close(); QTest.qWait(150)


if __name__ == '__main__':
    run()
