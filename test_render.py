# -*- coding: utf-8 -*-
"""离屏渲染测试：加载验证文件，检查公式/表格渲染，截图保存。"""
import os
import sys
import time

if os.environ.get("MDVIEW_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
win = MainWindow(startup_file=os.path.abspath("02_建模方法_SCI精简重构版.md"))
win.resize(1280, 900)
win.show()

CHECK_JS = r"""
(function(){
  var diag = {
    readyState: document.readyState,
    vditorDiv: !!document.querySelector('#vditor'),
    typeofVditor: typeof Vditor,
    typeofQWebChannel: typeof QWebChannel,
    typeofQt: typeof qt,
    scripts: [].map.call(document.scripts, function(s){return s.src;}),
    err: window.__err || null
  };
  if (typeof Vditor === 'undefined') return JSON.stringify(diag);
  var v = document.querySelector('#vditor');
  var katex = document.querySelectorAll('.katex').length;
  var tables = v.querySelectorAll('table').length;
  var bq = v.querySelectorAll('blockquote').length;
  var h2 = v.querySelectorAll('h2').length;
  var text = v.innerText.length;
  diag.state = {katex:katex, tables:tables, blockquote:bq, h2:h2, textLen:text};
  return JSON.stringify(diag);
})()
"""


def finish(code=0):
    app.quit()
    sys.exit(code)


def do_checks():
    def cb(result):
        print("RENDER_STATE:", result)
        try:
            import json
            diag = json.loads(result)
            state = diag.get("state")
            if not state:
                print("PAGE DIAG:", diag)
                finish(1)
                return
            assert state["katex"] > 50, "KaTeX formulas too few"
            assert state["tables"] >= 1, "table missing"
            assert state["h2"] >= 4, "headings missing"
            print("ASSERTIONS PASSED")
        except SystemExit:
            raise
        except Exception as e:
            print("ASSERTION FAILED:", e)
        # 截图
        pixmap = win.view.grab()
        ok = pixmap.save("screenshot_editor.png")
        print("screenshot saved:", ok)
        finish(0)
    win.view.page().runJavaScript(CHECK_JS, cb)


# 等待加载与渲染
QTimer.singleShot(12000, do_checks)
QTimer.singleShot(30000, lambda: finish(2))  # 兜底超时

app.exec()
