"""Regression checks for code preservation, search scheduling and compact controls."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from bench_resources import pump, wait


def run():
    with tempfile.TemporaryDirectory(prefix="mdview-audit-") as directory:
        os.environ["MDVIEW_DATA_DIR"] = str(Path(directory) / "profile")
        app = QApplication(sys.argv)
        app.setOrganizationName("MarkdownViewAuditTest")
        app.setApplicationName("MarkdownViewAuditTest")
        QSettings().clear()
        window = MainWindow()
        window.resize(1100, 760)
        window.show()

        def evaluate(code):
            result = []
            window.view.page().runJavaScript("JSON.stringify((function(){" + code + "})())", result.append)
            wait(lambda: bool(result))
            assert result[0] is not None, code
            return json.loads(result[0])

        try:
            wait(lambda: window.current_tab().ready)
            tab = window.current_tab()
            revision = tab.revision
            with patch.object(window, "_update_titles", wraps=window._update_titles) as refresh:
                for _ in range(30):
                    window.set_dirty(tab, True)
                assert refresh.call_count == 1 and tab.revision == revision + 30
                assert tab.backup_timer.isActive()
            window._persist_session()
            with patch.object(window.store, "_commit", wraps=window.store._commit) as commit:
                for _ in range(5):
                    window._persist_session()
                assert commit.call_count == 0
            # Failed metadata writes can be retried even if the state is unchanged.
            with patch.object(window.store, "_commit", side_effect=OSError("test disk failure")):
                try:
                    window.store.write_session([], "failed-write")
                except OSError:
                    pass
                else:
                    raise AssertionError("Expected write failure")
            with patch.object(window.store, "_commit", wraps=window.store._commit) as commit:
                window.store.write_session([], "failed-write")
                assert commit.call_count == 1
            print("PASS - Repeated edits retain revisions and draft protection without rebuilding navigation or rewriting identical sessions", flush=True)
            for code in [
                "~~~text\n\\(literal\\) and $code$\n~~~\n",
                "````md\n```\n\\(literal\\) and $code$\n```\n````\n",
                "```text\n\\(literal\\) and $code$\n",
                "`` with ` inside: \\(literal\\) and $code$ ``",
                "\n    \\(literal\\) and $code$\n\n    more $code$\n",
            ]:
                for direction in ("toEditor", "fromEditor"):
                    assert evaluate("return window.markdownMath." + direction + "(" + json.dumps(code) + ");") == code
            source = r"Math \(x+y\) and \[z^2\]."
            assert evaluate("return window.markdownMath.toEditor(" + json.dumps(source) + ");") == "Math $x+y$ and $$z^2$$."
            literal = r"Prices \$10 and \$20. Math $x+y$ and $$z^2$$."
            expected = r"Prices \$10 and \$20. Math \(x+y\) and $$z^2$$."
            assert evaluate("return window.markdownMath.fromEditor(" + json.dumps(literal) + ");") == expected
            document = "# Code example\n\n~~~text\n\\(literal\\) and $code$\n~~~\n\nMath \\(x+y\\).\n"
            evaluate("window.setContent(" + json.dumps(document) + "); return true;")
            saved = evaluate("return window.currentMarkdown();")
            assert r"\(literal\) and $code$" in saved and r"Math \(x+y\)." in saved, saved
            print("PASS - Variable code fences, inline backticks, indented code and escaped currency survive conversion", flush=True)

            for mode in ("ir", "sv", "wysiwyg"):
                evaluate("document.querySelector('[data-mode=" + mode + "]').click(); window.__setEditorValue('Alpha **alpha** alphabet ALPHA.\\n\\n中文测试。'); return true;")
                pump(.3)
                evaluate("window.openFind(true); document.getElementById('mdv-find-input').value='alpha'; document.getElementById('mdv-find-input').dispatchEvent(new Event('input')); return true;")
                pump(.2)
                assert evaluate("return document.getElementById('mdv-find-count').textContent;") == "1 / 4"
                assert evaluate("var h=CSS.highlights.get('mdv-found'); window.findNext(1); return h === CSS.highlights.get('mdv-found');")
                evaluate("document.getElementById('mdv-find-input').dispatchEvent(new Event('input')); window.findNext(-1); return true;")
                assert evaluate("return document.getElementById('mdv-find-count').textContent;") == "4 / 4"
                assert evaluate("var event = new KeyboardEvent('keydown', {key:'Enter', isComposing:true, bubbles:true, cancelable:true}); document.getElementById('mdv-find-input').dispatchEvent(event); return !event.defaultPrevented;")
                evaluate("document.getElementById('mdv-find-input').value='中文'; document.getElementById('mdv-find-input').dispatchEvent(new Event('input')); window.findNext(1); return true;")
                assert evaluate("return document.getElementById('mdv-find-count').textContent;") == "1 / 1"
                evaluate("document.getElementById('mdv-find-input').dispatchEvent(new Event('input')); window.closeFind(); return true;")
                pump(.3)
                assert evaluate("return !CSS.highlights.has('mdv-found') && !CSS.highlights.has('mdv-active');")
            print("PASS - Search works in all modes; navigation reuses highlights; rapid close cancels pending work", flush=True)

            # Replace multiple matches spanning formatting and sharing a text node.
            evaluate("document.querySelector('[data-mode=ir]').click(); window.__setEditorValue('alpha **alpha** alpha alpha.'); window.openFind(true); document.getElementById('mdv-find-input').value='alpha'; document.getElementById('mdv-find-input').dispatchEvent(new Event('input')); document.getElementById('mdv-replace-input').value='beta'; return true;")
            pump(.2)
            evaluate("document.getElementById('mdv-replace-all').click(); return true;")
            value = evaluate("return window.__getEditorValue();")
            assert 'beta **beta** beta beta.' in value, value
            evaluate("window.closeFind(); return true;")
            print("PASS - Replace all preserves formatting and replaces every match", flush=True)

            for width in (1320, 860, 480):
                window.resize(width, 360 if width == 480 else 760)
                pump(.25)
                assert evaluate("return !document.querySelector('.mdv-toolbar-group') && document.querySelectorAll('.vditor-toolbar > .vditor-toolbar__item').length > 20;")
                # Each row is packed up to the next individual button, not a whole group.
                assert evaluate("""var toolbar=document.querySelector('.vditor-toolbar'), style=getComputedStyle(toolbar);
                    var items=Array.from(toolbar.children).map(n=>n.getBoundingClientRect()).filter(r=>r.width>0);
                    var edge=toolbar.getBoundingClientRect().right-parseFloat(style.paddingRight);
                    return items.every((r,i)=>!i || r.top===items[i-1].top || edge-items[i-1].right < r.width+parseFloat(style.columnGap)+1);"""), width
                overflow = evaluate("return Array.from(document.querySelectorAll('.vditor-toolbar__item > button')).filter(b => b.getBoundingClientRect().width && (b.getBoundingClientRect().right > innerWidth || b.getBoundingClientRect().left < 0)).map(b=>b.dataset.type);")
                assert not overflow, (width, overflow)
                capture = Path(__file__).resolve().parent / 'tmp' / 'audit-after' / f'toolbar-{width}.png'
                capture.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(capture))
                if width == 480:
                    assert evaluate("return document.querySelector('.vditor-content').getBoundingClientRect().height >= 100;")
                    evaluate("window.openFind(true); return true;")
                    assert evaluate("return document.getElementById('mdv-find-input').getBoundingClientRect().width > 120;")
                    capture = Path(__file__).resolve().parent / 'tmp' / 'audit-after' / 'minimum-window.png'
                    capture.parent.mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(capture))
                    evaluate("window.closeFind(); return true;")
            assert not evaluate("return window.__err;")
            print("PASS - Individual toolbar buttons fill rows and remain reachable at 1320, 860 and 480 pixels", flush=True)
        finally:
            for tab in window._tab_list:
                tab.dirty = False
            window.close()
            pump(.3)
            QSettings().clear()


if __name__ == "__main__":
    run()
