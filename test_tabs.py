# -*- coding: utf-8 -*-
"""多标签页与自定义全屏测试。"""
import json
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
win = MainWindow(startup_file=os.path.abspath("02_建模方法_SCI精简重构版.md"))
win.show()

failed = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        failed.append(name)


def step2():
    # 开第二个标签页（不带文件）
    win.new_tab()
    QTimer.singleShot(6000, step3)


def step3():
    check("two tabs", win.tabs.count() == 2)
    check("second tab is untitled", win.current_tab().filepath is None)
    tab2 = win.current_tab()
    # 在第二个标签页写入内容 → 脏标记
    tab2.js("window.__setEditorValue('# 第二个文档\\n\\n内容 $a^2$ 测试。');")
    QTimer.singleShot(2000, step4)


def step4():
    tab2 = win.current_tab()
    check("tab2 dirty after edit", tab2.dirty)
    check("tab2 label has mark", "●" in win.tabs.tabText(1))
    # 切回第一个标签页
    win.tabs.setCurrentIndex(0)
    tab1 = win.current_tab()
    check("tab1 still has file", bool(tab1.filepath))
    check("tab1 not dirty", not tab1.dirty)
    # 全屏滚动测试在 tab1 上做
    js = r"""
    (function(){
      window.toggleFullscreen();
      var fs = document.getElementById('vditor').classList.contains('mdv-fullscreen');
      // 自动探测真正的滚动容器
      var scroller = null;
      var all = document.querySelectorAll('#vditor *');
      for (var i = 0; i < all.length; i++) {
        if (all[i].scrollHeight > all[i].clientHeight + 100 && all[i].clientHeight > 100) {
          scroller = all[i]; break;
        }
      }
      var scrolled = false;
      if (scroller) {
        scroller.scrollTop = 500;
        scrolled = scroller.scrollTop >= 400;
      }
      window.toggleFullscreen();
      var restored = !document.getElementById('vditor').classList.contains('mdv-fullscreen');
      return JSON.stringify({fs: fs, scrolled: scrolled, restored: restored,
        scrollerCls: scroller ? scroller.className.toString().slice(0,40) : null});
    })()
    """
    win.view.page().runJavaScript(js, step5)


def step5(result):
    d = json.loads(result)
    check("fullscreen class applied", d["fs"])
    check("content scrollable in fullscreen", d["scrolled"])
    check("fullscreen toggled off", d["restored"])
    # 工具栏按钮存在性检查
    js = r"""
    (function(){
      var names = ['u-underline','u-sup','u-sub','u-mark','insert-image','mdv-fullscreen'];
      var found = {};
      names.forEach(function(n){
        found[n] = !!document.querySelector('[data-type="' + n + '"]') ||
                   !!document.querySelector('.vditor-toolbar__item button[data-type="' + n + '"]') ||
                   !!document.querySelector('button[name="' + n + '"]');
      });
      return JSON.stringify(found);
    })()
    """
    win.view.page().runJavaScript(js, step6)


def step6(result):
    d = json.loads(result)
    for name, found in d.items():
        check(f"toolbar button {name}", found)
    pixmap = win.view.grab()
    print("screenshot saved:", pixmap.save("screenshot_tabs.png"))
    print("TABS_TEST:", "PASSED" if not failed else f"FAILED {failed}")
    app.quit()
    sys.exit(0 if not failed else 1)


QTimer.singleShot(12000, step2)
QTimer.singleShot(60000, lambda: (print("TIMEOUT"), sys.exit(2)))
app.exec()
