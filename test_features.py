# -*- coding: utf-8 -*-
"""功能测试：图片显示与保存还原、左下角计数条。"""
import base64
import json
import os
import shutil
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402

TMP_MD = os.path.abspath("test_feat_tmp.md")
IMG_DIR = os.path.abspath("images")
os.makedirs(IMG_DIR, exist_ok=True)

# 用 Qt 画一张 240x120 的测试图
_pm_app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
pm = QPixmap(240, 120)
pm.fill(QColor("#e74c3c"))
pm.save(os.path.join(IMG_DIR, "test_img.png"), "PNG")

shutil.copyfile("02_建模方法_SCI精简重构版.md", TMP_MD)

app = QApplication.instance()
win = MainWindow(startup_file=TMP_MD)
win.show()


def step2():
    js = r"""
    (function(){
      var md = window.__getEditorValue();
      window.__setEditorValue(md + '\n\n![测试图](images/test_img.png)\n\n末尾。\n');
      return 'ok';
    })()
    """
    win.view.page().runJavaScript(js, lambda r: QTimer.singleShot(2500, step3))


def step3():
    js = r"""
    (function(){
      var img = document.querySelector('#vditor img');
      var counter = document.getElementById('mdview-counter');
      var before = counter ? counter.textContent : null;
      if (counter) counter.click();
      var statsOpen = document.getElementById('mdview-stats-backdrop')
        .classList.contains('is-open');
      var statWords = document.querySelector('[data-stat="words"]').textContent;
      var statChars = document.querySelector('[data-stat="chars"]').textContent;
      return JSON.stringify({
        imgSrc: img ? img.getAttribute('src') : null,
        imgOsrc: img ? img.getAttribute('data-osrc') : null,
        counterBefore: before, statsOpen: statsOpen, statWords: statWords,
        statChars: statChars,
        mdDirUrl: window.__mdDirUrl
      });
    })()
    """
    def cb(result):
        print("FEATURE_STATE:", result)
        d = json.loads(result)
        ok = True
        if not d["imgSrc"] or not d["imgSrc"].startswith("file:///"):
            print("FAIL: img src not rewritten:", d["imgSrc"]); ok = False
        if d["imgOsrc"] != "images/test_img.png":
            print("FAIL: orig src not preserved:", d["imgOsrc"]); ok = False
        if not d["counterBefore"] or "字数" not in d["counterBefore"]:
            print("FAIL: counter default:", d["counterBefore"]); ok = False
        if not d["statsOpen"] or not d["statWords"] or not d["statChars"]:
            print("FAIL: statistics dialog:", d["statsOpen"], d["statWords"], d["statChars"]); ok = False
        print("statistics dialog:", d["statsOpen"], "words", d["statWords"], "chars", d["statChars"])
        # 滚动到图片处截图，确认图片真实渲染
        win.view.page().runJavaScript(
            "var i=document.querySelector('#vditor img'); if(i) i.scrollIntoView({block:'center'}); 'ok'",
            lambda r: QTimer.singleShot(1200, take_shot))
        if ok:
            pass
        else:
            cleanup(1)

    win.view.page().runJavaScript(js, cb)


def take_shot():
    pixmap = win.view.grab()
    print("screenshot saved:", pixmap.save("screenshot_features.png"))
    QTimer.singleShot(100, step4_save)


def step4_save():
    win.view.page().runJavaScript("window.requestSave(); 'ok'",
                                  lambda r: QTimer.singleShot(1500, step5))


def step5():
    content = open(TMP_MD, encoding="utf-8").read()
    ok_rel = "![测试图](images/test_img.png)" in content
    ok_noabs = "file:///" not in content
    print("relative img path saved:", ok_rel)
    print("no file:// leaked into md:", ok_noabs)
    cleanup(0 if (ok_rel and ok_noabs) else 1)


def cleanup(code):
    print("FEATURE_TEST:", "PASSED" if code == 0 else "FAILED")
    app.quit()
    for p in [TMP_MD, os.path.join(IMG_DIR, "test_img.png")]:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(IMG_DIR)
    except OSError:
        pass
    sys.exit(code)


QTimer.singleShot(12000, step2)
QTimer.singleShot(45000, lambda: (print("TIMEOUT"), cleanup(2)))
app.exec()
