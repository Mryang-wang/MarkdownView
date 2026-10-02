# -*- coding: utf-8 -*-
"""回归测试：格式按钮、统计弹窗、工具提示、全屏和标签拆窗。"""
import json
import sys

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402


app = QApplication(sys.argv)
win = MainWindow()
win.show()
failed = []


def check(name, condition):
    print(("PASS" if condition else "FAIL"), "-", name, flush=True)
    if not condition:
        failed.append(name)


def check_page():
    js = r"""
    (function(){
      try {
      function selectText(text) {
        var root = document.querySelector('#vditor .vditor-ir');
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        var node = null;
        while (walker.nextNode()) {
          if (walker.currentNode.nodeValue.indexOf(text) >= 0) { node = walker.currentNode; break; }
        }
        if (!node) { throw new Error('selection text not found'); }
        var start = node.nodeValue.indexOf(text);
        var range = document.createRange();
        range.setStart(node, start); range.setEnd(node, start + text.length);
        var selection = window.getSelection();
        selection.removeAllRanges(); selection.addRange(range);
      }
      function apply(type, text) {
        window.__setEditorValue(text);
        selectText(text);
        document.querySelector('button[data-type="' + type + '"]').click();
        return { markdown: window.__getEditorValue(), html: document.querySelector('#vditor .vditor-ir').innerHTML };
      }
      var underline = apply('u-underline', 'underline');
      underline.rendered = Array.from(CSS.highlights.get('mdv-underline') || []).map(r => r.toString()).join('') === 'underline';
      var strike = apply('u-strike', 'strike');
      var sup = apply('u-sup', 'superscript');
      var sub = apply('u-sub', 'subscript');
      window.__setEditorValue('one two\n\nthree');
      document.getElementById('mdview-counter').click();
      document.querySelector('button[data-type="emoji"]').click();
      var dialog = document.getElementById('mdview-stats-backdrop');
      var tips = {};
      ['emoji', 'u-underline', 'u-strike', 'u-sup', 'u-sub', 'insert-image', 'mdv-fullscreen'].forEach(function(type) {
        var button = document.querySelector('#vditor .vditor-toolbar [data-type="' + type + '"]');
        tips[type] = button ? button.getAttribute('aria-label') : null;
      });
      return JSON.stringify({
        underline: underline, strike: strike, sup: sup, sub: sub,
        dialogOpen: dialog.classList.contains('is-open'),
        wordCount: document.querySelector('[data-stat="words"]').textContent,
        lineCount: document.querySelector('[data-stat="lines"]').textContent,
        emojiCount: document.querySelectorAll('.vditor-emojis button').length,
        underlineButton: !!document.querySelector('button[data-type="u-underline"]'),
        tips: tips,
        nativeTitles: [].map.call(document.querySelectorAll('#vditor .vditor-toolbar [data-type]'), function(button) {
          return button.hasAttribute('title');
        }),
        missingTooltips: [].map.call(document.querySelectorAll('#vditor .vditor-toolbar__item > [data-type]'), function(button) {
          return !button.getAttribute('data-mdv-tip') || !button.getAttribute('aria-label') || !button.classList.contains('vditor-tooltipped');
        }),
        tooltipVisible: (function() {
          var button = document.querySelector('#vditor .vditor-toolbar__item > [data-mdv-tip]');
          if (!button) { return false; }
          button.dispatchEvent(new PointerEvent('pointerover', {bubbles: true, clientX: 120, clientY: 80}));
          var tooltip = document.getElementById('mdv-toolbar-tooltip');
          var position = tooltip.style.left + ',' + tooltip.style.top;
          button.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, clientX: 500, clientY: 500}));
          return tooltip.style.display === 'block' && tooltip.textContent === button.getAttribute('data-mdv-tip') &&
            position === tooltip.style.left + ',' + tooltip.style.top;
        })(),
        outlineOnLeft: (function() {
          var button = document.querySelector('#vditor .vditor-toolbar [data-type="outline"]');
          var outline = document.querySelector('#vditor .vditor-outline');
          if (!button || !outline) { return false; }
          button.click();
          return outline.parentElement.firstElementChild === outline &&
            !outline.classList.contains('vditor-outline--right');
        })(),
        error: window.__err
      });
      } catch (error) {
        return JSON.stringify({ testError: String(error), error: window.__err });
      }
    })()
    """

    def done(result):
        print("PAGE_STATE:", result)
        data = json.loads(result)
        if data.get("testError"):
            check("page test completed", False)
            print("PAGE_TEST_ERROR:", data["testError"], flush=True)
            finish()
            return
        check("no page error", not data["error"])
        check("underline markup preserved", "<u>underline</u>" in data["underline"]["markdown"])
        check("underline rendered", data["underline"]["rendered"])
        check("strike markdown", "~~strike~~" in data["strike"]["markdown"])
        check("superscript rendered", "<sup" in data["sup"]["html"])
        check("subscript rendered", "<sub" in data["sub"]["html"])
        check("statistics dialog opens", data["dialogOpen"])
        check("statistics word count", data["wordCount"] == "3")
        check("statistics line count", data["lineCount"] == "3")
        check("expanded emoji list", data["emojiCount"] >= 40)
        check("underline toolbar button available", data["underlineButton"])
        check("toolbar tooltips", all(data["tips"].values()))
        check("no duplicate browser tooltips", not any(data["nativeTitles"]))
        check("all toolbar buttons have black tooltips", not any(data["missingTooltips"]))
        check("black tooltip opens on hover", data["tooltipVisible"])
        check("outline appears on the left", data["outlineOnLeft"])
        check_window_features()

    win.view.page().runJavaScript(js, done)


def check_window_features():
    original = win.current_tab()
    check("compact top chrome without duplicate tabs", 28 <= win.menuBar().height() <= 32 and not win.tab_bar.isVisible())
    check("menu bar is the topmost window chrome", win.menuBar().pos().y() == 0)
    check("window title hides document name", win.windowTitle() == "MarkdownView")
    check("application icon is shown before menus",
          win.menuBar().actions()[0] is win._app_icon_action and not win.windowIcon().isNull())
    check("application icon is enlarged", win._app_icon_button.iconSize().width() == 20)
    icon_rect = win.menuBar().actionGeometry(win._app_icon_action)
    file_rect = win.menuBar().actionGeometry(win._file_menu.menuAction())
    check("application icon does not overlap File menu", icon_rect.right() < file_rect.left())
    check("application icon control is visible and separated",
          win._app_icon_button.isVisible()
          and win._app_icon_button.geometry().right() < file_rect.left())
    check("File menu is close to application icon",
          0 < file_rect.left() - win._app_icon_button.geometry().right() <= 8)
    check("PDF export action is available", any(
        "PDF" in action.text() and action.shortcut().toString() == "Ctrl+Shift+E"
        for action in win._file_menu.actions()))
    check("window avoids jagged corner mask", win.mask().isEmpty())
    view_top = win.current_tab().view.mapTo(win, QPoint(0, 0)).y()
    check("no blank band above editor", abs(view_top - win.menuBar().height()) <= 1)
    base_geometry = QRect(100, 100, 800, 600)
    resize_cases = (
        (Qt.Edge.LeftEdge, QPoint(20, 0), QRect(120, 100, 780, 600)),
        (Qt.Edge.RightEdge, QPoint(20, 0), QRect(100, 100, 820, 600)),
        (Qt.Edge.TopEdge, QPoint(0, 20), QRect(100, 120, 800, 580)),
        (Qt.Edge.BottomEdge, QPoint(0, 20), QRect(100, 100, 800, 620)),
        (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, QPoint(20, 20), QRect(120, 120, 780, 580)),
        (Qt.Edge.RightEdge | Qt.Edge.TopEdge, QPoint(20, 20), QRect(100, 120, 820, 580)),
        (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, QPoint(20, 20), QRect(120, 100, 780, 620)),
        (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, QPoint(20, 20), QRect(100, 100, 820, 620)),
    )
    check("all window edges and corners resize", all(
        win._resized_geometry(base_geometry, edges, delta) == expected
        for edges, delta, expected in resize_cases))
    second = win.new_tab()
    row = win.document_list.itemWidget(win.document_list.item(1))
    check("sidebar document has close button", row.close_button.text() == "×")
    check("sidebar document row identifies its editor", row.tab is second)
    win.detach_tab(1)
    children = list(win._detached_windows)
    check("tab moved from main window", win.tabs.count() == 1 and win.current_tab() is original)
    check("detached window owns tab", len(children) == 1 and children[0].current_tab() is second)
    check("detached window animation started", hasattr(children[0], "_detach_animation"))
    win.view.page().runJavaScript("window.toggleFullscreen(); 'ok'",
                                  lambda _r: QTimer.singleShot(500, check_fullscreen_on))


def check_fullscreen_on():
    check("application fullscreen enabled", win.isFullScreen())
    check("window chrome hidden", not win.menuBar().isVisible() and not win.tabs.tabBar().isVisible())
    win.view.page().runJavaScript("window.toggleFullscreen(); 'ok'",
                                  lambda _r: QTimer.singleShot(500, finish))


def finish():
    check("application fullscreen disabled", not win.isFullScreen())
    print("REGRESSION_TEST:", "PASSED" if not failed else "FAILED " + repr(failed), flush=True)
    for child in list(win._detached_windows):
        for tab in child._tab_list:
            tab.dirty = False
        child.close()
    for tab in win._tab_list:
        tab.dirty = False
    win.close()
    app.quit()


QTimer.singleShot(12000, check_page)
QTimer.singleShot(45000, lambda: (print("TIMEOUT", flush=True), app.quit()))
exit_code = app.exec()
sys.exit(1 if failed else exit_code)
