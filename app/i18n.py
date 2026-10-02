"""Application language and shared Chinese / English UI translations."""
import json
import re
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QSettings, QTranslator
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QAbstractButton, QLabel, QLineEdit, QMenu

_TRANSLATIONS = json.loads((Path(__file__).parent / "assets/locales/en.json").read_text(encoding="utf-8"))
_PATTERNS = []
for _source, _target in _TRANSLATIONS.items():
    if "{0}" in _source:
        def expression(template):
            return re.compile("^" + re.sub(r"\\\{\d+\\\}", "(.*?)", re.escape(template)) + "$", re.S)
        _PATTERNS.append((_source, _target, expression(_source), expression(_target)))
_qt_translators = []


def language():
    return "en" if QSettings().value("appearance/language", "zh_CN") == "en" else "zh_CN"


def translate(text, target):
    if target == "en":
        if text in _TRANSLATIONS:
            return _TRANSLATIONS[text]
    else:
        for source, value in _TRANSLATIONS.items():
            if text == value:
                return source
    for source, translated, source_pattern, translated_pattern in _PATTERNS:
        match = (source_pattern if target == "en" else translated_pattern).fullmatch(text)
        if match:
            return (translated if target == "en" else source).format(*match.groups())
    return text


def t(text):
    return translate(text, "en") if language() == "en" else text


def install_qt_language():
    app = QApplication.instance()
    for translator in _qt_translators:
        app.removeTranslator(translator)
    _qt_translators.clear()
    if language() == "zh_CN":
        directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for name in ("qtbase_zh_CN", "qtwebengine_zh_CN"):
            translator = QTranslator(app)
            if translator.load(name, directory):
                app.installTranslator(translator)
                _qt_translators.append(translator)


def translate_widgets(window):
    """Update live native controls; document names are refreshed separately."""
    target = language()
    objects = [window, *window.findChildren(QAction), *window.findChildren(QAbstractButton),
               *window.findChildren(QLabel), *window.findChildren(QLineEdit), *window.findChildren(QMenu)]
    for obj in objects:
        if isinstance(obj, (QAction, QAbstractButton, QLabel)):
            obj.setText(translate(obj.text(), target))
        if isinstance(obj, QLineEdit):
            obj.setPlaceholderText(translate(obj.placeholderText(), target))
        if isinstance(obj, QMenu):
            obj.setTitle(translate(obj.title(), target))
        if hasattr(obj, "toolTip"):
            obj.setToolTip(translate(obj.toolTip(), target))
        if hasattr(obj, "accessibleName"):
            obj.setAccessibleName(translate(obj.accessibleName(), target))


_CONTEXT_ZH = {
    "Back": "后退", "Forward": "前进", "Reload": "重新加载", "Stop": "停止加载",
    "Undo": "撤销", "Redo": "重做", "Cut": "剪切", "Copy": "复制", "Paste": "粘贴", "Delete": "删除",
    "Select All": "全选", "Select all": "全选", "Paste and Match Style": "粘贴并匹配样式",
    "Paste as plain text": "粘贴为纯文本", "Open link in this window": "在当前窗口打开链接",
    "Open link in new window": "在新窗口打开链接", "Open link in new tab": "在新标签页打开链接",
    "Save link": "保存链接", "Save link as…": "链接另存为…", "Save link as...": "链接另存为…",
    "Copy link address": "复制链接地址", "Copy link": "复制链接", "Copy image": "复制图片",
    "Copy image address": "复制图片地址", "Save image": "保存图片", "Save image as…": "图片另存为…",
    "Open image in new tab": "在新标签页打开图片", "Save page": "保存页面", "Save page as…": "页面另存为…",
    "View page source": "查看页面源代码", "Inspect": "检查元素", "Inspect Element": "检查元素",
    "Exit Full Screen": "退出全屏", "Exit full screen": "退出全屏", "Toggle Play/Pause": "播放 / 暂停",
    "Toggle Looping": "循环播放", "Toggle Mute": "静音 / 取消静音", "Save media": "保存媒体",
    "Copy media address": "复制媒体地址", "Spelling and grammar": "拼写与语法", "No spelling suggestions": "无拼写建议",
}


def translate_context_menu(menu):
    target = language()
    for action in menu.actions():
        if action.menu():
            translate_context_menu(action.menu())
        if action.isSeparator():
            continue
        label = action.text()
        plain = label.replace("&", "").split("\t")[0]
        if target == "zh_CN" and plain in _CONTEXT_ZH:
            action.setText(_CONTEXT_ZH[plain])
        elif target == "en":
            for english, chinese in _CONTEXT_ZH.items():
                if plain == chinese:
                    action.setText(english)
                    break
