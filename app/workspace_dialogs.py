"""Compact native tools for local documents; heavy work runs only on request."""
import difflib
import json
import os
import queue
import time
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .document_services import ProjectScan, image_references, bundle_document, templates
from .i18n import t
from .translation_dialog import label, style_dialog
from .dialog_theme import AppDialog


READING_DEFAULTS = {"font": "Segoe UI", "size": 15, "line": 1.9, "paragraph": 1.2, "width": 760}
EXPORT_DEFAULTS = {"paper": "A4", "landscape": False, "margin": 12, "numbers": False, "toc": False, "reference": ""}


def preferences(key, defaults):
    try:
        data = json.loads(QSettings().value(key, "{}"))
        return {**defaults, **{k: v for k, v in data.items() if k in defaults}}
    except (ValueError, TypeError, AttributeError):
        return dict(defaults)


class ToolDialog(AppDialog):
    def __init__(self, window, title, width=820, height=580):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(t(title))
        self.resize(width, height)
        self.setMinimumSize(min(width, 550), min(height, 420))
        style_dialog(self, window._theme)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(22, 20, 22, 20)
        self.layout.setSpacing(12)
        self.layout.addWidget(label(title, "title"))


class NavigateDialog(ToolDialog):
    def __init__(self, window, mode="files"):
        super().__init__(window, {"files": "快速打开文件", "search": "项目全文搜索", "commands": "命令面板"}[mode])
        self.mode, self.scan = mode, None
        self.options = []
        self.seen = set()
        self.query = QLineEdit()
        self.query.setPlaceholderText(t("输入关键词，按 Enter 打开"))
        self.layout.addWidget(self.query)
        self.case = QCheckBox(t("区分大小写"))
        self.case.setVisible(mode == "search")
        self.layout.addWidget(self.case)
        self.results = QListWidget()
        self.results.setSpacing(3)
        self.results.setUniformItemSizes(True)
        self.results.setStyleSheet("QListWidget{border:0;background:transparent;} QListWidget::item{padding:9px;border-radius:5px;}")
        self.layout.addWidget(self.results, 1)
        self.status = label("", "muted")
        self.layout.addWidget(self.status)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.search)
        self.poll = QTimer(self)
        self.poll.setInterval(40)
        self.poll.timeout.connect(self._poll)
        self.query.textChanged.connect(lambda: self.debounce.start())
        self.case.toggled.connect(lambda: self.debounce.start())
        self.query.returnPressed.connect(self._open)
        self.results.itemActivated.connect(self._open)
        self.finished.connect(self._close)
        self.search()
        self.query.setFocus()

    def _add(self, title, subtitle, value):
        item = QListWidgetItem(title + ("\n" + subtitle if subtitle else ""))
        item.setToolTip(subtitle)
        item.setData(Qt.ItemDataRole.UserRole, len(self.options))
        self.options.append(value)
        self.results.addItem(item)
        if self.results.count() == 1:
            self.results.setCurrentRow(0)

    def search(self):
        if self.scan:
            self.scan.cancelled.set()
        self.poll.stop()
        self.results.clear(); self.options.clear(); self.seen.clear()
        query = self.query.text().strip()
        if self.mode == "commands":
            actions = set()
            for menu_action in self.window.menuBar().actions():
                menu = menu_action.menu()
                if not menu:
                    continue
                for action in menu.findChildren(QAction) + menu.actions():
                    if action in actions or action.isSeparator() or action.menu() or not action.text().strip():
                        continue
                    actions.add(action)
                    title = action.text().replace("&", "")
                    if action.isEnabled() and all(q in title.casefold() for q in query.casefold().split()):
                        self._add(title, action.shortcut().toString(), ("action", action))
            self.status.setText(t("输入命令名称；仅显示当前可用的操作。"))
            tab = self.window.current_tab()
            if tab and not tab.file_error and not getattr(tab, "read_only", False) and not getattr(tab, "lightweight", False):
                for mode, caption in (("ir", "即时渲染模式"), ("wysiwyg", "所见即所得模式"), ("sv", "源代码模式")):
                    title = t(caption)
                    if all(q in title.casefold() for q in query.casefold().split()):
                        self._add(title, t("切换编辑模式"), ("mode", mode))
            return
        if self.mode == "files":
            for owner in self.window.store.windows:
                for tab in owner._tab_list:
                    title = tab.display_name()
                    if all(q in (title + " " + (tab.filepath or "")).casefold() for q in query.casefold().split()):
                        self._add(title, t("已打开") + " · " + (tab.filepath or ""), ("tab", owner, tab))
                        if tab.filepath:
                            self.seen.add(os.path.normcase(tab.filepath))
        root = self.window.project_explorer.root_path
        if not root:
            if self.mode == "files":
                for path in self.window.store.recent_files():
                    if os.path.isfile(path) and os.path.normcase(path) not in self.seen and all(q in path.casefold() for q in query.casefold().split()):
                        self._add(Path(path).name, path, ("file", path, 0))
            self.status.setText(t("打开项目文件夹后，可搜索项目内的文件。"))
            return
        if self.mode == "search" and not query:
            self.status.setText(t("输入正文关键词；搜索已保存文件，跳过构建目录及大于 2 MB 的文件。"))
            return
        self.scan = ProjectScan(root, query, self.mode == "search", self.case.isChecked())
        self.status.setText(t("正在搜索…"))
        self.poll.start()

    def _poll(self):
        if not self.scan:
            return
        for _ in range(80):
            try:
                data = self.scan.results.get_nowait()
            except queue.Empty:
                break
            if data[0] == "done":
                self.poll.stop()
                self.status.setText(t("扫描 {0} 个文件 · {1} 个结果 · 跳过 {2} 个文件").format(data[1], self.results.count(), data[3]) + (t(" · 已达上限，请缩小搜索范围") if data[4] else ""))
                break
            _, path, line, excerpt = data
            if not line and os.path.normcase(path) in self.seen:
                continue
            self._add(Path(path).name + (f" : {line}" if line else ""), excerpt, ("file", path, line))

    def _open(self, *_):
        if self.debounce.isActive():
            self.debounce.stop(); self.search()
        item = self.results.currentItem()
        if not item:
            return
        option = self.options[item.data(Qt.ItemDataRole.UserRole)]
        self.accept()
        if option[0] == "action":
            QTimer.singleShot(0, self.window, option[1].trigger)
        elif option[0] == "mode":
            self.window._cur_js("document.querySelector('[data-mode=" + option[1] + "]').click()")
        elif option[0] == "tab":
            owner, tab = option[1:]
            if tab in owner._tab_list:
                owner.tabs.setCurrentWidget(tab.view); owner.bring_to_front()
        else:
            tab = self.window.open_file(option[1])
            if tab and option[2]:
                tab.js(f"window.locateSourceLine({option[2]})")

    def _close(self, *_):
        self.debounce.stop(); self.poll.stop()
        if self.scan:
            self.scan.cancelled.set()


class PreferencesDialog(ToolDialog):
    def __init__(self, window, page=0):
        super().__init__(window, "阅读与输出设置", 650, 640)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs, 1)
        reading = preferences("reading/preferences", READING_DEFAULTS)
        output = preferences("export/preferences", EXPORT_DEFAULTS)
        self.fields = {}
        for title in ("阅读排版", "导出设置", "资源与历史"):
            panel = QWidget(); form = QFormLayout(panel); form.setContentsMargins(15, 20, 15, 10); form.setSpacing(14)
            self.tabs.addTab(panel, t(title))
        form = self.tabs.widget(0).layout()
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont(reading["font"]))
        form.addRow(t("正文字体"), self.font)
        for key, caption, low, high, step in (("size", "字号", 11, 30, 1), ("line", "行距", 1.2, 3.0, .1),
                                             ("paragraph", "段落间距", .2, 3.0, .1), ("width", "正文宽度", 420, 1400, 20)):
            spin = QDoubleSpinBox() if isinstance(step, float) else QSpinBox()
            spin.setRange(low, high); spin.setSingleStep(step); spin.setValue(reading[key])
            if isinstance(spin, QDoubleSpinBox): spin.setDecimals(1)
            self.fields[key] = spin; form.addRow(t(caption), spin)
        self.highlight = QCheckBox(t("专注模式突出当前段落"))
        self.highlight.setChecked(QSettings().value("writing/focusHighlight", True, type=bool))
        form.addRow(self.highlight)
        reset = QPushButton(t("恢复默认排版"))
        reset.clicked.connect(self._reset_reading); form.addRow(reset)
        form.addRow(label("字号以像素计；正文宽度随窗口自动收缩。设置适用于所有文档。", "muted"))
        form = self.tabs.widget(1).layout()
        self.paper = QComboBox(); self.paper.addItems(["A4", "A5", "Letter", "Legal"]); self.paper.setCurrentText(output["paper"])
        form.addRow(t("PDF 纸张"), self.paper)
        self.landscape = QCheckBox(t("横向")); self.landscape.setChecked(output["landscape"]); form.addRow(t("方向"), self.landscape)
        self.margin = QSpinBox(); self.margin.setRange(5, 40); self.margin.setValue(output["margin"]); self.margin.setSuffix(" mm"); form.addRow(t("页边距"), self.margin)
        self.numbers = QCheckBox(t("显示页码")); self.numbers.setChecked(output["numbers"]); form.addRow(self.numbers)
        self.toc = QCheckBox(t("在正文前生成目录")); self.toc.setChecked(output["toc"]); form.addRow(self.toc)
        self.reference = QLineEdit(output["reference"])
        row = QHBoxLayout(); row.addWidget(self.reference, 1)
        choose = QPushButton(t("选择…")); choose.clicked.connect(self._choose_reference); row.addWidget(choose)
        form.addRow(t("Word 样式模板"), row)
        form.addRow(label("选择 .docx 作为样式参考；留空使用默认样式。PDF 页码与目录仅影响导出文件。", "muted"))
        form = self.tabs.widget(2).layout()
        self.history = QSpinBox(); self.history.setRange(0, 500); self.history.setSuffix(" MB"); self.history.setValue(QSettings().value("history/maxMB", 50, type=int))
        form.addRow(t("历史快照空间上限"), self.history)
        form.addRow(label("每个文档最多 20 份；空间超限时清理最旧快照。0 表示关闭并清理历史。", "muted"))
        self.compress = QCheckBox(t("插入图片时压缩静态位图")); self.compress.setChecked(QSettings().value("images/compress", False, type=bool)); form.addRow(self.compress)
        self.image_size = QSpinBox(); self.image_size.setRange(640, 8000); self.image_size.setSingleStep(320); self.image_size.setValue(QSettings().value("images/maxEdge", 2560, type=int)); form.addRow(t("图片最长边（像素）"), self.image_size)
        self.quality = QSpinBox(); self.quality.setRange(40, 100); self.quality.setValue(QSettings().value("images/quality", 85, type=int)); form.addRow(t("JPEG 质量"), self.quality)
        self.lightweight = QCheckBox(t("超过 1 MB 的文档自动使用轻量模式")); self.lightweight.setChecked(QSettings().value("performance/autoLightweight", True, type=bool)); form.addRow(self.lightweight)
        form.addRow(label("轻量模式使用源码编辑、减少实时统计并避免公式实时渲染；可随时从“视图”切回。", "muted"))
        self.tabs.setCurrentIndex(page)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject)
        self.layout.addWidget(buttons)

    def _choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, t("选择 Word 样式模板"), self.reference.text(), "Word (*.docx)")
        if path: self.reference.setText(path)

    def _reset_reading(self):
        self.font.setCurrentFont(QFont(READING_DEFAULTS["font"]))
        for key, spin in self.fields.items(): spin.setValue(READING_DEFAULTS[key])

    def _save(self):
        reference = self.reference.text().strip()
        if reference and (not Path(reference).is_file() or Path(reference).suffix.lower() != ".docx"):
            QMessageBox.warning(self, t("模板无效"), t("请选择存在的 .docx 文件，或清空模板路径。")); return
        settings = QSettings()
        settings.setValue("reading/preferences", json.dumps({"font": self.font.currentFont().family(), **{k: s.value() for k, s in self.fields.items()}}))
        settings.setValue("export/preferences", json.dumps({"paper": self.paper.currentText(), "landscape": self.landscape.isChecked(), "margin": self.margin.value(), "numbers": self.numbers.isChecked(), "toc": self.toc.isChecked(), "reference": reference}))
        for key, value in (("writing/focusHighlight", self.highlight.isChecked()), ("history/maxMB", self.history.value()),
                           ("images/compress", self.compress.isChecked()), ("images/maxEdge", self.image_size.value()),
                           ("images/quality", self.quality.value()), ("performance/autoLightweight", self.lightweight.isChecked())):
            settings.setValue(key, value)
        self.accept()


class CompareDialog(ToolDialog):
    def __init__(self, window, current, other, caption="磁盘文件", entries=None):
        super().__init__(window, "版本与差异对比", 1020, 720)
        self.current, self.other = current, other
        self.entries = entries or []
        self.choice = None
        if entries:
            self.versions = QComboBox()
            for path in entries:
                self.versions.addItem(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)) + f" · {path.stat().st_size // 1024 + 1} KB", str(path))
            self.versions.currentIndexChanged.connect(self._version)
            self.layout.addWidget(self.versions)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs, 1)
        split = QSplitter()
        self.left, self.right = QPlainTextEdit(current), QPlainTextEdit(other)
        for title, editor in (("当前编辑内容", self.left), (caption, self.right)):
            panel = QWidget(); column = QVBoxLayout(panel); column.addWidget(label(title)); column.addWidget(editor, 1)
            editor.setReadOnly(True); editor.setUndoRedoEnabled(False); split.addWidget(panel)
        self.tabs.addTab(split, t("并排对照"))
        self.diff = QPlainTextEdit(); self.diff.setReadOnly(True); self.diff.setUndoRedoEnabled(False)
        self.tabs.addTab(self.diff, t("差异"))
        self._diff()
        self.layout.addWidget(label("恢复版本会打开新文档；重新加载磁盘文件前会保留当前内容的历史快照。", "muted"))
        row = QHBoxLayout()
        keep = QPushButton(t("保留当前内容")); keep.clicked.connect(lambda: self._choose("keep")); row.addWidget(keep)
        row.addStretch()
        restore = QPushButton(t("恢复为新文档") if entries else t("重新加载磁盘文件"))
        restore.setProperty("role", "primary"); restore.clicked.connect(lambda: self._choose("restore")); row.addWidget(restore)
        close = QPushButton(t("关闭")); close.clicked.connect(self.reject); row.addWidget(close)
        self.layout.addLayout(row)

    def _version(self):
        try:
            self.other = Path(self.versions.currentData()).read_text(encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, t("读取失败"), str(error)); return
        self.right.setPlainText(self.other); self._diff()

    def _diff(self):
        self._diff_generation = getattr(self, "_diff_generation", 0) + 1
        generation = self._diff_generation
        if len(self.current) + len(self.other) > 400000:
            self.diff.setPlainText(t("大文档请使用并排对照，避免计算差异占用过多资源。")); return
        if self.current == self.other:
            self.diff.setPlainText(t("两个版本内容相同。")); return
        current, other = self.current, self.other
        before, after = t("当前内容"), t("所选版本")
        self.diff.setPlainText(t("正在计算差异…"))
        def completed(value, error):
            from shiboken6 import isValid
            if isValid(self) and generation == self._diff_generation:
                self.diff.setPlainText(str(error) if error else value)
        self.window.features.background(lambda: "\n".join(difflib.unified_diff(
            current.splitlines(), other.splitlines(), fromfile=before, tofile=after, lineterm="")), completed)

    def _choose(self, value):
        self.choice = value; self.accept()


class TemplateDialog(ToolDialog):
    def __init__(self, window, snippets=False):
        super().__init__(window, "常用片段" if snippets else "文档模板", 800, 660)
        self.snippets = snippets
        self.selector = QComboBox()
        self.layout.addWidget(self.selector)
        self.name = QLineEdit(); self.name.setPlaceholderText(t("模板名称；修改名称即可新增")); self.layout.addWidget(self.name)
        self.body = QPlainTextEdit(); self.layout.addWidget(self.body, 1)
        self.layout.addWidget(label("{date} 会替换为当天日期。可以编辑、保存或新增自己的模板。", "muted"))
        row = QHBoxLayout()
        save = QPushButton(t("保存模板")); save.clicked.connect(self._save); row.addWidget(save)
        remove = QPushButton(t("删除自定义 / 恢复预设")); remove.clicked.connect(self._remove); row.addWidget(remove)
        row.addStretch()
        use = QPushButton(t("插入片段") if snippets else t("创建文档")); use.setProperty("role", "primary"); use.clicked.connect(self.accept); row.addWidget(use)
        self.layout.addLayout(row)
        self.selector.currentIndexChanged.connect(self._select)
        self._fill()

    def _fill(self, name=None):
        self.selector.clear()
        for key in templates(QSettings(), self.snippets): self.selector.addItem(t(key), key)
        if name: self.selector.setCurrentIndex(max(0, self.selector.findData(name)))

    def _select(self):
        key = self.selector.currentData()
        if key:
            self.name.setText(key); self.body.setPlainText(templates(QSettings(), self.snippets)[key])

    def _save(self):
        name, body = self.name.text().strip(), self.body.toPlainText()
        if not name or not body or len(body) > 100000:
            QMessageBox.warning(self, t("模板无效"), t("请填写名称和正文，正文不超过 100000 字符。")); return
        values = templates(QSettings(), self.snippets); values[name] = body
        QSettings().setValue("writing/snippets" if self.snippets else "writing/templates", json.dumps(values, ensure_ascii=False))
        self._fill(name)

    def _remove(self):
        from .document_services import DOCUMENT_TEMPLATES, SNIPPETS
        values = templates(QSettings(), self.snippets); name = self.name.text().strip(); values.pop(name, None)
        defaults = SNIPPETS if self.snippets else DOCUMENT_TEMPLATES
        if name in defaults: values[name] = defaults[name]
        QSettings().setValue("writing/snippets" if self.snippets else "writing/templates", json.dumps(values, ensure_ascii=False))
        self._fill()

    def content(self):
        return self.body.toPlainText().replace("{date}", time.strftime("%Y-%m-%d"))


class ImagesDialog(ToolDialog):
    def __init__(self, window, content, directory, name):
        super().__init__(window, "图片管理", 840, 570)
        self.content, self.directory, self.name = content, directory, name
        self.references = image_references(content, directory)
        self.list = QListWidget(); self.list.setSpacing(4); self.layout.addWidget(self.list, 1)
        captions = {"local": "本地图片", "remote": "网络 / 内嵌图片", "missing": "路径失效"}
        for reference in self.references:
            item = QListWidgetItem(t(captions[reference["status"]]) + "  ·  " + reference["reference"])
            item.setToolTip(reference["path"] or reference["reference"]); self.list.addItem(item)
        missing = sum(r["status"] == "missing" for r in self.references)
        self.status = label(t("共 {0} 个引用 · {1} 个失效路径；网络图片不会自动下载。").format(len(self.references), missing), "muted")
        self.layout.addWidget(self.status)
        row = QHBoxLayout()
        reveal = QPushButton(t("定位本地图片")); reveal.clicked.connect(self._reveal); row.addWidget(reveal)
        settings = QPushButton(t("压缩设置…")); settings.clicked.connect(lambda: window.features.settings(2)); row.addWidget(settings)
        row.addStretch()
        self.share = QPushButton(t("打包文档与图片…")); self.share.setProperty("role", "primary"); self.share.clicked.connect(self._share); row.addWidget(self.share)
        self.layout.addLayout(row)

    def _reveal(self):
        index = self.list.currentRow()
        if index >= 0 and self.references[index]["path"]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.references[index]["path"]).parent)))

    def _share(self):
        path, _ = QFileDialog.getSaveFileName(self, t("打包分享"), Path(self.name).stem + ".zip", "ZIP (*.zip)")
        if not path: return
        self.share.setEnabled(False); self.status.setText(t("正在打包…"))
        self.window.features.background(lambda: bundle_document(self.content, self.directory, path, self.name), lambda value, error: self._shared(path, error))

    def _shared(self, path, error):
        from shiboken6 import isValid
        if not isValid(self): return
        self.share.setEnabled(True)
        self.status.setText(str(error) if error else t("已保存：{0}").format(path))
