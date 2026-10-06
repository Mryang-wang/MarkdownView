"""真实 WebEngine 验证：查找替换、图片持久化、草稿恢复和会话恢复。"""
import base64
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

scratch = tempfile.TemporaryDirectory()
os.environ["MDVIEW_DATA_DIR"] = str(Path(scratch.name) / "profile")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMimeData, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow

app = QApplication([])
app.setOrganizationName("MarkdownViewPriorityTest")
app.setApplicationName("MarkdownViewPriorityTest")
QSettings().clear()
class ClipboardFixture:
    """执行环境禁止访问 Windows 剪贴板；保留真实按键与 Qt MIME 格式测试。"""
    def __init__(self):
        self._mime = QMimeData()

    def setImage(self, image):
        self._mime.setImageData(image)

    def mimeData(self):
        return self._mime

    def image(self):
        return self._mime.imageData()


original_clipboard_method = QApplication.clipboard
clipboard = ClipboardFixture()
QApplication.clipboard = staticmethod(lambda: clipboard)
original_get_save_name = QFileDialog.getSaveFileName
failed = []
source = Path(scratch.name) / "note.md"
source.write_text("# Notes\n\nAlpha **alpha** alphabet ALPHA.\n\nMath $x^2$.\n", encoding="utf-8")
win = MainWindow(startup_file=str(source))
win.resize(1100, 760)
win.show()
first = win.current_tab()
image_tab = None
restored_window = None


def check(label, condition):
    print(("PASS" if condition else "FAIL") + " - " + label, flush=True)
    if not condition:
        failed.append(label)


def later(callback, delay=300):
    def guarded():
        try:
            callback()
        except Exception:
            traceback.print_exc()
            failed.append("Python exception")
            finish()
    QTimer.singleShot(delay, guarded)


def evaluate(code, callback, tab=None):
    tab = tab or win.current_tab()
    def received(result):
        try:
            callback(json.loads(result))
        except Exception:
            traceback.print_exc()
            failed.append("JavaScript evaluation or assertion callback failed")
            finish()
    tab.view.page().runJavaScript("JSON.stringify((function(){" + code + "})())", received)


def wait_ready(window, callback):
    if window.current_tab().ready:
        later(callback)
    else:
        later(lambda: wait_ready(window, callback), 100)


def initial():
    check("recent list records real file", win.store.recent_files() == [str(source)])
    check("opening same file reuses existing document", win.open_file(str(source)) is first and win.tabs.count() == 1)
    first.view.setFocus()
    QTest.keyClick(first.view.focusProxy(), Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    later(search)


def search():
    evaluate("""
      var panel=document.getElementById('mdv-find-panel');
      var q=document.getElementById('mdv-find-input');
      q.value='alpha'; q.dispatchEvent(new Event('input'));
      window.findNext(1); // Enter flushes the debounced query immediately.
      var initial=document.getElementById('mdv-find-count').textContent;
      document.getElementById('mdv-find-case').click();
      var sensitive=document.getElementById('mdv-find-count').textContent;
      document.getElementById('mdv-find-word').click();
      var whole=document.getElementById('mdv-find-count').textContent;
      document.getElementById('mdv-replace-input').value='beta';
      document.getElementById('mdv-replace-all').click();
      return {open:!panel.hidden,replace:!document.getElementById('mdv-replace-row').hidden,
        initial:initial,sensitive:sensitive,whole:whole,value:window.currentMarkdown(),error:window.__err};
    """, searched)


def searched(state):
    print("SEARCH_STATE", state, flush=True)
    check("native Ctrl+H opens replace panel", state["open"] and state["replace"])
    check("case insensitive count", state["initial"] == "1 / 4")
    check("case sensitive count", state["sensitive"] == "1 / 2")
    check("whole word count", state["whole"] == "1 / 1")
    check("replacement preserves bold and surrounding words", "**beta**" in state["value"] and "alphabet ALPHA" in state["value"])
    check("replacement preserves math delimiters", "\\(x^2\\)" in state["value"])
    check("no JavaScript error", not state["error"])
    first.js("window.closeFind(); document.querySelector('button[data-type=undo]').click();")
    later(undo, 600)


def undo():
    evaluate("return {value:window.currentMarkdown(),hidden:document.getElementById('mdv-find-panel').hidden};", undone)


def undone(state):
    check("replace can be undone", "**alpha**" in state["value"] and "**beta**" not in state["value"])
    check("find panel closes", state["hidden"])
    first.js("window.__setEditorValue('# Notes\\n\\nAlpha **alpha** alphabet ALPHA.\\n\\n```python\\nalpha = 1\\n```'); window.openFind(true); var q=document.getElementById('mdv-find-input'); q.value='alpha'; document.getElementById('mdv-find-case').checked=false; document.getElementById('mdv-find-word').checked=false; q.dispatchEvent(new Event('input'));")
    later(code_search)


def code_search():
    evaluate("return {count:document.getElementById('mdv-find-count').textContent};", lambda s: (check("code searched once without preview duplicate", s["count"] == "1 / 5"), test_modes()))


def test_modes():
    evaluate("""
      var results=[];
      ['sv','wysiwyg','ir'].forEach(function(mode){
        window.closeFind(); document.querySelector('[data-mode='+mode+']').click();
        window.__setEditorValue('# Mode\\n\\nword **word** word.\\n\\n![existing](images/test.png)');
        window.openFind(true);
        var q=document.getElementById('mdv-find-input');q.value='word';
        document.getElementById('mdv-find-case').checked=false;
        document.getElementById('mdv-find-word').checked=false;
        q.dispatchEvent(new Event('input'));
        window.findNext(1);
        var count=document.getElementById('mdv-find-count').textContent;
        document.getElementById('mdv-replace-input').value='term';
        document.getElementById('mdv-replace-all').click();
        results.push({mode:mode,count:count,value:window.currentMarkdown()});
      });
      return results;
    """, modes_tested)


def modes_tested(states):
    print("MODE_STATES", states, flush=True)
    check("find and replace work in all editing modes", all(s["count"] == "1 / 3" and "**term**" in s["value"] and "word" not in s["value"] for s in states))
    check("replacement preserves relative image references", all("images/test.png" in s["value"] and "file:///" not in s["value"] for s in states))
    image_document()


def image_document():
    global image_tab
    first.js("window.closeFind();")
    win.set_dirty(first, False)
    image_tab = win.new_tab()
    wait_ready(win, paste_image)


def paste_image():
    image = QImage(120, 60, QImage.Format.Format_RGB32)
    image.fill(QColor("#8aab87"))
    clipboard.setImage(image)
    image_tab.js("window.__setEditorValue('# Screenshot\\n\\n');")
    image_tab.view.setFocus()
    def paste():
        QTest.keyClick(image_tab.view.focusProxy(), Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        later(pasted, 1600)
    later(paste)


def pasted():
    evaluate("""
      var imgs=Array.from(document.querySelectorAll('#vditor .vditor-ir img'));
      return {value:window.currentMarkdown(),images:imgs.map(i=>({src:i.src,original:i.dataset.osrc,loaded:i.complete&&i.naturalWidth>0}))};
    """, pasted_state)


def pasted_state(state):
    print("PASTE_STATE", state, flush=True)
    check("native clipboard screenshot inserts image", len(state["images"]) == 1)
    check("clipboard image displays from local file", bool(state["images"]) and state["images"][0]["loaded"] and state["images"][0]["src"].startswith("file:///"))
    check("unsaved image Markdown uses relative path", "images/" in state["value"] and "file:///" not in state["value"] and "data:image" not in state["value"])
    check("untitled draft and its image are backed up", any(r["id"] == image_tab.draft_id and "images/" in r["content"] for r in win.store.drafts()))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image = QImage(120, 60, QImage.Format.Format_RGB32)
    image.fill(QColor("#8aab87"))
    image.save(buffer, "PNG")
    data = base64.b64encode(bytes(buffer.data())).decode("ascii")
    image_tab.js("""window.__batchImportDone=false;
      var originalImport=window.importDroppedImages;
      window.importDroppedImages=async function(files){
        var result=await originalImport(files);window.__batchImportError=result;window.__batchImportDone=true;
        window.importDroppedImages=originalImport;return result;};
      var bytes=Uint8Array.from(atob(%s), c=>c.charCodeAt(0));
      var transfer=new DataTransfer();
      transfer.items.add(new File([bytes],'图 (1).png',{type:'image/png'}));
      transfer.items.add(new File([bytes],'图 (1).png',{type:'image/png'}));
      document.querySelector('.vditor-ir > pre').dispatchEvent(new DragEvent('drop',
        {bubbles:true,cancelable:true,dataTransfer:transfer,clientX:300,clientY:220}));
    """ % json.dumps(data))
    later(batch_import, 1300)


def batch_import():
    evaluate("return {done:window.__batchImportDone,error:window.__batchImportError,value:window.currentMarkdown(),images:Array.from(document.querySelectorAll('#vditor .vditor-ir img')).map(i=>i.complete&&i.naturalWidth>0)};", batch_state)


def batch_state(state):
    print("BATCH_STATE", state, flush=True)
    check("batch image import handles Chinese spaces and parentheses", state["done"] and not state["error"] and len(state["images"]) == 3 and all(state["images"]))
    saved = Path(scratch.name) / "saved"
    saved.mkdir()
    target = saved / "images.md"
    QFileDialog.getSaveFileName = staticmethod(lambda *_args, **_kwargs: (str(target), ""))
    win.save_file(image_tab, state["value"])
    check("saving untitled document copies all images", len(list((saved / "images").glob("*"))) == 3)
    check("saved Markdown keeps relative image paths", "file:///" not in target.read_text(encoding="utf-8"))
    check("saved draft is cleared", not any(r["id"] == image_tab.draft_id for r in win.store.drafts()))
    later(saved_images, 700)


def saved_images():
    evaluate("return {images:Array.from(document.querySelectorAll('#vditor .vditor-ir img')).map(i=>({src:i.src,original:i.dataset.osrc,loaded:i.complete&&i.naturalWidth>0})),value:window.currentMarkdown()};", save_as)


def save_as(state):
    check("images still display after first save", len(state["images"]) == 3 and all(i["loaded"] and "/saved/images/" in i["src"] for i in state["images"]))
    another = Path(scratch.name) / "another"
    another.mkdir()
    target = another / "copy.md"
    QFileDialog.getSaveFileName = staticmethod(lambda *_args, **_kwargs: (str(target), ""))
    content = state["value"] + '\n\n<img src="' + state["images"][0]["original"] + '" width="80">\n'
    win.save_file(image_tab, content, save_as=True)
    check("Save As copies relative images to new folder", len(list((another / "images").glob("*"))) == 3)
    later(drafts, 800)


def drafts():
    evaluate("return Array.from(document.querySelectorAll('#vditor .vditor-ir img')).map(i=>i.complete&&i.naturalWidth>0);", lambda images: check("Save As preserves resized HTML images", len(images) == 4 and all(images)))
    first.js("window.__setEditorValue('# Crash draft\\n\\nNever lose this formula: $a+b$.');")
    later(recover, 1600)


def recover():
    records = [r for r in win.store.drafts() if r["id"] == first.draft_id]
    check("dirty named file has a durable draft", bool(records) and "\\(a+b\\)" in records[0]["content"])
    # 模拟上一个进程留下的备份，不改写原文件。
    record = dict(records[0])
    record["id"] = "a" * 32
    recovery = win.restore_draft(record)
    wait_ready(win, lambda: recovered(recovery))


def recovered(tab):
    evaluate("return {value:window.currentMarkdown()};", lambda state: recovered_state(tab, state), tab)


def recovered_state(tab, state):
    check("recovered draft opens as dirty independent document", tab.dirty and tab.filepath is None and "Crash draft" in state["value"])
    check("recovery does not overwrite source", "Crash draft" not in source.read_text(encoding="utf-8"))
    win._destroy_tab(win._tab_list.index(tab))
    win.tabs.setCurrentWidget(first.view)
    win._autosave_action.setChecked(True)
    later(autosaved, 1700)


def autosaved():
    check("optional auto-save writes named file", "Crash draft" in source.read_text(encoding="utf-8") and not first.dirty)
    source.write_text("# Edited elsewhere\n", encoding="utf-8")
    first.js("window.__setEditorValue('# Local unsaved change');")
    later(conflict, 1600)


def conflict():
    check("auto-save detects external modification", source.read_text(encoding="utf-8") == "# Edited elsewhere\n" and first.autosave_paused and first.dirty)
    check("external conflict still leaves recovery draft", any(r["id"] == first.draft_id and "Local unsaved" in r["content"] for r in win.store.drafts()))
    win._autosave_action.setChecked(False)
    win._remove_draft(first)
    win.set_dirty(first, False)
    win.tabs.setCurrentWidget(image_tab.view)
    evaluate("var value=window.__getEditorValue();window.__setEditorValue(value+'\\n\\n'+('Reading position paragraph.\\n\\n').repeat(75));return window.currentMarkdown();", save_long_document)


def save_long_document(content):
    win.save_file(image_tab, content)
    image_tab.js("window.restorePosition(800);")
    later(close_and_restore, 700)


def close_and_restore():
    check("reading position is reported from real scroll", image_tab.scroll_position >= 790)
    expected = [t.filepath for t in win._tab_list if t.filepath]
    win.close()
    check("normal exit stores open documents", [r["path"] for r in win.store.state["session"]["documents"]] == expected)
    # 同一测试进程模拟全新启动时读取文件。
    from app.workspace_store import WorkspaceStore
    fresh = WorkspaceStore(os.environ["MDVIEW_DATA_DIR"])
    app._workspace_store = fresh
    global restored_window
    restored_window = MainWindow(restore_session=True)
    restored_window.show()
    check("startup loads prior document list", [t.pending_file for t in restored_window._tab_list] == expected)
    check("startup selects previously active document", restored_window.current_tab().pending_file == image_tab.filepath)
    check("startup restores stored reading position", restored_window.current_tab().scroll_position >= 790)
    wait_ready(restored_window, reopened)


def reopened():
    check("reopened documents are clean", all(not t.dirty for t in restored_window._tab_list))
    restored_window._refresh_recent_menu()
    check("recent documents exposed in File menu", len(restored_window._recent_menu.actions()) >= 3)
    evaluate("var restored=window.getEditorPosition();window.openFind(true);var q=document.getElementById('mdv-find-input');q.value='Reading';q.dispatchEvent(new Event('input'));return restored;", reopened_position, restored_window.current_tab())


def reopened_position(position):
    check("startup restores actual editor scroll", position >= 790)
    later(lambda: (restored_window.grab().save(os.path.abspath("screenshot_priority_features.png")), finish()), 450)


def finish():
    QFileDialog.getSaveFileName = original_get_save_name
    QApplication.clipboard = original_clipboard_method
    for window in list(WorkspaceStore.shared().windows):
        for tab in window._tab_list:
            tab.dirty = False
        window.close()
    print("PRIORITY_FEATURES:", "FAILED " + repr(failed) if failed else "PASSED", flush=True)
    app.exit(1 if failed else 0)


from app.workspace_store import WorkspaceStore
app.setQuitOnLastWindowClosed(False)
later(lambda: wait_ready(win, initial), 100)
later(lambda: (failed.append("TIMEOUT"), finish()), 65000)
status = app.exec()
scratch.cleanup()
sys.exit(status)
