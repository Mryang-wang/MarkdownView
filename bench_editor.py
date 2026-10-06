"""Reproducible editor hot-path measurements using a generated document."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from bench_resources import pump, wait


def run(label):
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="mdview-bench-") as directory:
        os.environ["MDVIEW_DATA_DIR"] = str(Path(directory) / "profile")
        app = QApplication(sys.argv)
        app.setOrganizationName("MarkdownViewEditorBench")
        app.setApplicationName("MarkdownViewEditorBench")
        QSettings().clear()
        source = Path(directory) / "benchmark.md"
        source.write_text("# Editor benchmark\n\n" + "\n\n".join(
            f"Paragraph {i}: benchmark **writing** and 中文排版 with $x_{i}^2+y^2$."
            for i in range(600)), encoding="utf-8")
        window = MainWindow(startup_file=str(source))
        window.resize(1100, 760)
        window.show()

        def evaluate(code):
            values = []
            window.view.page().runJavaScript("JSON.stringify((function(){" + code + "})())", values.append)
            wait(lambda: bool(values))
            return json.loads(values[0])

        try:
            wait(lambda: window.current_tab().ready)
            wait(lambda: evaluate("return document.querySelectorAll('.katex').length;") == 600, 40)
            pump(1)
            results = evaluate("""
                function measure(fn, count) {
                    var times = [];
                    for (var i = 0; i < count; i++) { var start = performance.now(); fn(); times.push(performance.now() - start); }
                    times.sort((a,b) => a-b);
                    return {median_ms: times[Math.floor(count/2)], p95_ms: times[Math.floor(count*.95)]};
                }
                window.editorDocumentText();
                var stats = measure(window.editorDocumentText, 25);
                document.getElementById('mdv-find-input').value = 'benchmark';
                var search = measure(() => window.openFind(false), 12);
                var navigation = measure(() => window.findNext(1), 50);
                return {text_index: stats, search: search, next_match: navigation,
                    matches: document.getElementById('mdv-find-count').textContent,
                    nodes: document.querySelectorAll('*').length, error: window.__err};
            """)
            assert not results["error"], results
            results["label"] = label
            results["document_bytes"] = source.stat().st_size
            output = root / "tmp" / "editor-benchmark"
            output.mkdir(parents=True, exist_ok=True)
            (output / (label + ".json")).write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
        finally:
            for tab in window._tab_list:
                tab.dirty = False
            window.close()
            pump(.3)
            QSettings().clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    run(parser.parse_args().label)
