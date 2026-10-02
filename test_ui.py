# -*- coding: utf-8 -*-
"""真实窗口验证：文档导航、主题、全屏恢复、窄窗口布局及界面截图。"""
import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
app.setOrganizationName("MarkdownViewUITest")
app.setApplicationName("MarkdownViewUITest")
settings = QSettings()
settings.setValue("appearance/theme", "light")
settings.setValue("appearance/sidebarVisible", True)
scratch = tempfile.TemporaryDirectory()
source = Path(scratch.name) / "设计笔记.md"
source.write_text("""# 为专注而留白

好的写作空间，让文字成为视线的中心。记录灵感、整理思路，然后把想法变成清晰的表达。

## 今天的写作计划

- [x] 整理散落的灵感与笔记
- [x] 给文档一个清晰的结构
- [ ] 留一些时间，认真打磨每一段文字

> 把注意力放在内容上。简单的界面，也可以容纳丰富的想法。

## 一个更舒适的工作区

通过 **Markdown** 组织内容，用 `Ctrl + S` 保存当前进展。公式、表格与代码，也都能自然地融入文档。

| 设计细节 | 目的 |
| --- | --- |
| 克制的配色与细线图标 | 让内容拥有更清晰的层次 |
| 合适的行宽与段落间距 | 让长时间阅读更加舒适 |

### 让思路保持流动

从一个简单的想法开始，写下接下来要做的事。
""", encoding="utf-8")
win = MainWindow(startup_file=str(source))
win.resize(1320, 860)
win.show()
failed = []
first = win.current_tab()
second = None


def check(name, condition):
    print(("PASS" if condition else "FAIL") + " - " + name, flush=True)
    if not condition:
        failed.append(name)


def capture(name):
    check(name + " screenshot", win.grab().save(os.path.abspath(name + ".png")))


def wait_ready(callback):
    if win.current_tab().ready:
        QTimer.singleShot(600, callback)
    else:
        QTimer.singleShot(200, lambda: wait_ready(callback))


def initial():
    global second
    check("sidebar reflects loaded document", win.document_list.count() == 1 and
          win.document_list.item(0).text() == source.name)
    check("duplicate top tab bar removed", not win.tab_bar.isVisible())
    check("sidebar contains only document actions", "export" not in win._sidebar_buttons)
    view_top = win.view.mapTo(win, QPoint(0, 0)).y()
    check("editor starts directly below menu", abs(view_top - win.menuBar().height()) <= 1)
    capture("screenshot_ui_light")
    second = win.new_tab()
    wait_ready(empty_document)


def empty_document():
    capture("screenshot_ui_empty")
    second.view.page().runJavaScript(
        "document.getElementById('empty-hint').hidden", lambda hidden: check("empty writing guide", not hidden))
    second.js("window.__setEditorValue('# A second document\\n\\nKeep this content.');")
    QTimer.singleShot(400, reorder)


def reorder():
    check("sidebar shows unsaved changes", second.dirty and "●" in win.document_list.item(1).text())
    win.tab_bar.moveTab(1, 0)
    win.tabs.setCurrentIndex(0)
    check("reordered tab owns correct editor", win.current_tab() is second and win.tabs.currentWidget() is second.view)
    win.document_list.setCurrentRow(1)
    check("sidebar switches to correct document", win.current_tab() is first)
    win.toggle_theme()
    QTimer.singleShot(600, dark_theme)


def dark_theme():
    capture("screenshot_ui_dark")
    check("native theme and preference updated", win._theme == "dark" and settings.value("appearance/theme") == "dark")
    first.view.page().runJavaScript("JSON.stringify({theme: document.documentElement.dataset.theme, redundantHeader: !!document.getElementById('document-header'), saveButton: !!document.getElementById('save-button'), value: window.__getEditorValue(), error: window.__err})", theme_state)


def theme_state(result):
    state = json.loads(result)
    check("web theme updated", state["theme"] == "dark")
    check("theme preserves content and saved state", "为专注而留白" in state["value"] and not first.dirty)
    check("duplicate document header and save UI removed", not state["redundantHeader"] and not state["saveButton"])
    check("no JavaScript error", not state["error"])
    win.detach_tab(0)
    child = next(iter(win._detached_windows))
    check("detached document keeps theme and navigation", child._theme == "dark" and child.current_tab() is second and child.document_list.count() == 1)
    win.toggle_theme()
    check("themes synchronize across windows", child._theme == win._theme == "light")
    check("sidebar has a visible collapse button", win._sidebar_collapse_button.isVisible() and
          win._sidebar_collapse_button.text() == "收起")
    win._sidebar_collapse_button.click()
    check("sidebar collapse button hides sidebar", not win.sidebar.isVisible() and
          not win._sidebar_action.isChecked())
    win.view.page().runJavaScript("document.querySelector('[data-type=mdv-sidebar]').click();", lambda _: QTimer.singleShot(300, expanded))


def expanded():
    check("toolbar button restores sidebar", win.sidebar.isVisible() and win._sidebar_action.isChecked())
    win._sidebar_collapse_button.click()
    QTimer.singleShot(300, collapsed)


def collapsed():
    check("sidebar collapses again", not win.sidebar.isVisible() and not win._sidebar_action.isChecked())
    win.set_editor_fullscreen(first, True)
    check("fullscreen hides sidebar and chrome", not win.sidebar.isVisible() and not win.menuBar().isVisible())
    win.set_editor_fullscreen(first, False)
    check("fullscreen restores sidebar preference", not win.sidebar.isVisible() and not win.tab_bar.isVisible())
    win._sidebar_action.trigger()
    win.resize(860, 680)
    QTimer.singleShot(600, compact)


def compact():
    capture("screenshot_ui_compact")
    extra = win.new_tab()
    count = win.tabs.count()
    row = win.document_list.itemWidget(win.document_list.item(win.tabs.indexOf(extra.view)))
    row.close_button.click()
    check("sidebar close button closes its document", win.tabs.count() == count - 1 and extra not in win._tab_list)
    check("closing a document keeps tab bar hidden", not win.tab_bar.isVisible())
    win.view.page().runJavaScript("JSON.stringify({width: innerWidth, toolbar: document.querySelector('.vditor-toolbar').getBoundingClientRect().width, buttons: Array.from(document.querySelectorAll('.vditor-toolbar__item > button')).every(b => b.getBoundingClientRect().right <= innerWidth), page: document.documentElement.scrollWidth, error: window.__err})", finish)


def finish(result=None):
    if result:
        state = json.loads(result)
        check("compact toolbar stays within viewport", state["buttons"] and state["toolbar"] <= state["width"])
        check("compact page has no horizontal overflow", state["page"] == state["width"])
        check("compact page has no script error", not state["error"])
    else:
        check("UI test completed before timeout", False)
    for window in [*win._detached_windows, win]:
        for tab in window._tab_list:
            tab.dirty = False
        window.close()
    settings.clear()
    scratch.cleanup()
    print("UI_TEST:", "PASSED" if not failed else "FAILED " + repr(failed), flush=True)
    app.exit(1 if failed else 0)


QTimer.singleShot(800, lambda: wait_ready(initial))
QTimer.singleShot(45000, finish)
sys.exit(app.exec())
