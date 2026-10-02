# -*- coding: utf-8 -*-
"""编辑→保存一致性测试：临时文件上验证数学分隔符还原与文件写入。"""
import os
import shutil
import sys

if os.environ.get("MDVIEW_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402

TMP_MD = os.path.abspath("test_tmp_edit.md")
shutil.copyfile("02_建模方法_SCI精简重构版.md", TMP_MD)

app = QApplication(sys.argv)
win = MainWindow(startup_file=TMP_MD)
win.show()

results = {"ok": False}


def step2_edit_and_save():
    # 追加一行含行内数学的内容，然后触发保存
    js = r"""
    (function(){
      var v = window.vditor || null;
      // 通过全局接口：直接构造新内容 = 当前值 + 追加
      var md = window.__getEditorValue();
      window.__setEditorValue(md + '\n\n追加测试行：公式 $x^2+y^2$ 与 $$a=b$$ 结束。\n');
      window.requestSave();
      return 'saved';
    })()
    """
    win.view.page().runJavaScript(js, lambda r: QTimer.singleShot(1500, step3_verify))


def step3_verify():
    content = open(TMP_MD, encoding="utf-8").read()
    tail = content[-200:]
    print("SAVED TAIL:", repr(tail))
    ok_math = "\\(x^2+y^2\\)" in content
    ok_disp = "$$\na=b\n$$" in content  # Vditor 会把行内 $$ 规范化为独立数学块
    ok_orig = "\\(H_{i,b}:\\eta\\mapsto\\xi\\)" in content  # 原有公式未被破坏
    print("inline math restored as \\(...\\):", ok_math)
    print("display math kept as $$:", ok_disp)
    print("original formulas intact:", ok_orig)
    print("dirty flag cleared:", not win._dirty)
    results["ok"] = ok_math and ok_disp and ok_orig and not win._dirty
    print("EDIT_SAVE_TEST:", "PASSED" if results["ok"] else "FAILED")
    app.quit()
    os.remove(TMP_MD)
    sys.exit(0 if results["ok"] else 1)


QTimer.singleShot(12000, step2_edit_and_save)
QTimer.singleShot(40000, lambda: (print("TIMEOUT"), sys.exit(2)))
app.exec()
