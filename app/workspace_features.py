"""Local document workflow, kept separate from window chrome and editor rendering."""
import json
import os
import queue
import threading
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QSettings, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox

from .document_services import HistoryStore, TEXT_SUFFIXES
from .i18n import t
from .workspace_dialogs import (CompareDialog, ImagesDialog, NavigateDialog, PreferencesDialog,
                                READING_DEFAULTS, TemplateDialog, preferences)


class WorkspaceFeatures(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.closed_documents = []
        self.focus = False
        self.jobs = []
        self.job_timer = QTimer(self)
        self.job_timer.setInterval(60)
        self.job_timer.timeout.connect(self._poll_jobs)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(lambda _: self.check_external())
        self.watcher.directoryChanged.connect(lambda _: self.check_external())
        self._menus()
        tree = window.project_explorer.tree
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._project_menu)

    def _menus(self):
        window = self.window
        file_menu, edit_menu, view_menu, settings_menu = window._main_menus[:4]
        quit_action = file_menu.actions()[-1]

        def action(menu, text, callback, shortcut=None, check=False, document=False):
            value = menu.addAction(t(text))
            value.triggered.connect(callback)
            value.setToolTip(t(text))
            if shortcut: value.setShortcut(shortcut)
            value.setCheckable(check)
            if document: window._document_actions.append(value)
            return value

        file_menu.addSeparator()
        action(file_menu, "快速打开文件…", lambda: self.navigate("files"), "Ctrl+P")
        self.reopen_action = action(file_menu, "恢复最近关闭的文档", self.reopen, "Ctrl+Shift+T")
        self.reopen_action.setEnabled(False)
        action(file_menu, "从模板新建…", lambda: self.template(False))
        self.external_action = action(file_menu, "外部修改对比…", self.external, document=True)
        action(file_menu, "历史版本…", self.history, document=True)
        action(file_menu, "图片管理与打包…", self.images, document=True)
        # Keep Exit at the bottom, after the document tools.
        file_menu.removeAction(quit_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)
        edit_menu.addSeparator()
        action(edit_menu, "项目全文搜索…", lambda: self.navigate("search"), "Ctrl+Shift+F")
        action(edit_menu, "命令面板…", lambda: self.navigate("commands"), "Ctrl+Shift+P")
        self.snippet_action = action(edit_menu, "插入常用片段…", lambda: self.template(True), document=True)
        view_menu.addSeparator()
        self.readonly_action = action(view_menu, "只读阅读模式", self.set_readonly, "Ctrl+Shift+R", True, True)
        self.focus_action = action(view_menu, "专注写作模式", self.set_focus, "Ctrl+Shift+Return", True, True)
        self.light_action = action(view_menu, "大文档轻量模式", self.set_lightweight, None, True, True)
        action(view_menu, "阅读排版设置…", lambda: self.settings(0))
        settings_menu.addSeparator()
        action(settings_menu, "阅读与输出设置…", lambda: self.settings(0))
        action(settings_menu, "PDF / Word 导出设置…", lambda: self.settings(1))
        action(settings_menu, "资源与历史设置…", lambda: self.settings(2))

    def sync(self):
        tab = self.window.current_tab()
        for action, state in ((self.readonly_action, bool(tab and getattr(tab, "read_only", False))),
                              (self.light_action, bool(tab and getattr(tab, "lightweight", False))),
                              (self.focus_action, self.focus)):
            action.blockSignals(True); action.setChecked(state); action.blockSignals(False)
        self.snippet_action.setEnabled(bool(tab and not tab.file_error and not getattr(tab, "read_only", False)))
        if tab and getattr(tab, "read_only", False):
            self.window.editor_status.format.setText(t("只读") + " · UTF-8")
        else:
            self.window.editor_status.format.setText("UTF-8   ·   Markdown")
        self.external_action.setText(t("外部修改对比…") + (" ●" if tab and getattr(tab, "external_changed", False) else ""))

    def apply(self, tab):
        if not tab.ready or tab.file_error: return
        tab.js("window.applyReadingPreferences(%s); window.setReadOnly(%s); window.setFocusWriting(%s, %s);" % (
            json.dumps(preferences("reading/preferences", READING_DEFAULTS)),
            json.dumps(getattr(tab, "read_only", False)), json.dumps(self.focus),
            json.dumps(QSettings().value("writing/focusHighlight", True, type=bool))))

    def settings(self, page=0):
        dialog = PreferencesDialog(self.window, page)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for owner in self.window.store.windows:
                for tab in owner._tab_list: owner.features.apply(tab)
            try: self.history_store().prune()
            except OSError as error: self.window.statusBar().showMessage(str(error), 6000)
        dialog.deleteLater()

    def navigate(self, mode):
        dialog = NavigateDialog(self.window, mode); dialog.exec(); dialog.deleteLater()

    def set_readonly(self, enabled):
        tab = self.window.current_tab()
        if tab:
            tab.read_only = enabled
            tab.js("window.setReadOnly(%s)" % json.dumps(enabled))
        self.sync()

    def set_lightweight(self, enabled):
        tab = self.window.current_tab()
        if tab:
            tab.lightweight = enabled
            tab.js("window.setLightweight(%s)" % json.dumps(enabled))
        self.sync()

    def set_focus(self, enabled):
        self.focus = enabled
        self.window.sidebar.setVisible(False if enabled else self.window._sidebar_action.isChecked())
        for tab in self.window._tab_list: self.apply(tab)
        self.sync()

    def capture(self, callback):
        tab = self.window.current_tab()
        if not tab or tab.file_error: return
        if not tab.ready:
            tab.ensure_loaded()
            self.window.statusBar().showMessage(t("文档正在加载，请稍后重试。"), 3000)
            return
        def received(content):
            if not self.window._closed and tab in self.window._tab_list and isinstance(content, str): callback(tab, content)
        tab.view.page().runJavaScript("window.currentMarkdown()", received)

    def new_document(self, content, name, resource_dir=None):
        tab = self.window.open_translated_document(content, resource_dir, name)
        tab.suggested_name = name if name.endswith(".md") else name + ".md"
        self.window._update_titles()
        return tab

    def template(self, snippets):
        tab = self.window.current_tab()
        if snippets and (not tab or getattr(tab, "read_only", False)): return
        dialog = TemplateDialog(self.window, snippets)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if snippets:
                if tab in self.window._tab_list: tab.js("window.insertSnippet(%s)" % json.dumps(dialog.content()))
            else: self.new_document(dialog.content(), dialog.name.text().strip() or t("未命名"))
        dialog.deleteLater()

    def remember_closed(self, tab):
        if tab.filepath and not tab.file_error:
            self.closed_documents.append((tab.filepath, tab.scroll_position))
            self.closed_documents = self.closed_documents[-10:]
            self.reopen_action.setEnabled(True)

    def reopen(self):
        if not self.closed_documents: return
        path, position = self.closed_documents.pop()
        self.reopen_action.setEnabled(bool(self.closed_documents))
        tab = self.window.open_file(path)
        if tab:
            tab.scroll_position = position
            if tab.ready: tab.js("window.restorePosition(%s)" % json.dumps(position))

    def history_store(self):
        return HistoryStore(self.window.store.root, QSettings().value("history/maxMB", 50, type=int) * 1024 * 1024)

    def snapshot(self, path, content, automatic=False):
        try: self.history_store().capture(path, content, automatic)
        except OSError as error: self.window.statusBar().showMessage(t("历史快照保存失败：{0}").format(error), 6000)

    def history(self):
        def show(tab, content):
            entries = self.history_store().entries(tab.filepath) if tab.filepath else []
            if not entries:
                QMessageBox.information(self.window, t("历史版本"), t("保存文档后会保留有限数量的历史快照。当前没有可用版本。")); return
            try: other = entries[0].read_text(encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(self.window, t("读取失败"), str(error)); return
            dialog = CompareDialog(self.window, content, other, "历史版本", entries)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.choice == "restore":
                self.new_document(dialog.other, Path(tab.display_name()).stem + t(" - 恢复"), tab.file_dir())
            dialog.deleteLater()
        self.capture(show)

    def watch(self):
        paths = {tab.filepath for tab in self.window._tab_list if tab.filepath}
        paths |= {str(Path(path).parent) for path in paths}
        existing = set(self.watcher.files() + self.watcher.directories())
        remove = list(existing - paths)
        if remove: self.watcher.removePaths(remove)
        add = [path for path in paths - existing if os.path.exists(path)]
        if add: self.watcher.addPaths(add)

    def check_external(self):
        if self.window._closed: return
        for tab in self.window._tab_list:
            if tab.filepath and tab.file_stamp is not None and self.window._file_stamp(tab.filepath) != tab.file_stamp:
                if not getattr(tab, "external_changed", False):
                    tab.external_changed = True
                    tab.autosave_paused = True
                    self.window.statusBar().showMessage(t("文件已在外部修改，可从“文件 → 外部修改对比”查看差异。"), 9000)
        self.watch(); self.sync()

    def external(self):
        self.capture(self.compare_external)

    def compare_external(self, tab, content):
        if not tab.filepath:
            QMessageBox.information(self.window, t("外部修改"), t("请先保存文档。")); return
        try:
            stamp = self.window._file_stamp(tab.filepath)
            disk = Path(tab.filepath).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self.window, t("读取失败"), str(error)); return
        dialog = CompareDialog(self.window, content, disk)
        if dialog.exec() == QDialog.DialogCode.Accepted and tab in self.window._tab_list:
            if self.window._file_stamp(tab.filepath) != stamp:
                QMessageBox.information(self.window, t("文件已再次变化"), t("请重新比较最新磁盘版本。"))
            elif dialog.choice == "restore":
                # Draft protection remains available even when history is disabled.
                backup = self.new_document(content, Path(tab.display_name()).stem + t(" - 重载前"), tab.file_dir()) if tab.dirty else None
                self.snapshot(tab.filepath, content)
                self.window.load_file(tab, tab.filepath)
                self.window.tabs.setCurrentWidget(tab.view)
                tab.external_changed = False
            elif dialog.choice == "keep":
                self.snapshot(tab.filepath, disk)
                tab.file_stamp = stamp
                tab.external_changed = False
                tab.autosave_paused = True
                self.window.set_dirty(tab, content != disk)
                self.window.statusBar().showMessage(t("已保留当前内容；下次手动保存将写入文件，自动保存仍暂停。"), 8000)
        dialog.deleteLater(); self.sync()

    def images(self):
        def show(tab, content):
            dialog = ImagesDialog(self.window, content, tab.file_dir(), tab.display_name())
            dialog.exec(); dialog.deleteLater()
        self.capture(show)

    def background(self, function, callback):
        result = queue.Queue(maxsize=1)
        def run():
            try: result.put((function(), None))
            except Exception as error: result.put((None, error))
        threading.Thread(target=run, daemon=True).start()
        self.jobs.append((result, callback)); self.job_timer.start()

    def _poll_jobs(self):
        for result, callback in list(self.jobs):
            try: value, error = result.get_nowait()
            except queue.Empty: continue
            self.jobs.remove((result, callback))
            if not self.window._closed: callback(value, error)
        if not self.jobs: self.job_timer.stop()

    def _project_menu(self, point):
        explorer = self.window.project_explorer
        if not explorer.model: return
        index = explorer.tree.indexAt(point)
        path = explorer.model.filePath(index) if index.isValid() else explorer.root_path
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        menu = QMenu(explorer.tree)
        create = menu.addAction(t("新建 Markdown 文件…"))
        mkdir = menu.addAction(t("新建文件夹…"))
        menu.addSeparator()
        rename = menu.addAction(t("重命名…")); rename.setEnabled(path != explorer.root_path and os.path.isfile(path))
        move = menu.addAction(t("移动文件…")); move.setEnabled(os.path.isfile(path))
        reveal = menu.addAction(t("在资源管理器中定位"))
        chosen = menu.exec(explorer.tree.viewport().mapToGlobal(point))
        if chosen == reveal:
            if os.path.isfile(path) and os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
            else: QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif chosen in (create, mkdir):
            name, ok = QInputDialog.getText(self.window, t("新建"), t("名称"))
            if not ok: return
            try:
                target = self.safe_child(folder, name)
                if chosen == create:
                    if not target.suffix: target = target.with_suffix(".md")
                    with target.open("x", encoding="utf-8") as stream: stream.write("")
                    self.window.open_file(str(target))
                else: target.mkdir()
            except (OSError, ValueError) as error: QMessageBox.warning(self.window, t("创建失败"), str(error))
        elif chosen in (rename, move):
            if chosen == rename:
                name, ok = QInputDialog.getText(self.window, t("重命名"), t("名称"), text=Path(path).name)
                if not ok: return
                try: target = self.safe_child(folder, name)
                except ValueError as error:
                    QMessageBox.warning(self.window, t("重命名失败"), str(error)); return
            else:
                destination = QFileDialog.getExistingDirectory(self.window, t("移动到文件夹"), explorer.root_path)
                if not destination: return
                target = Path(destination) / Path(path).name
            try: self.move_file(path, str(target))
            except (OSError, ValueError) as error: QMessageBox.warning(self.window, t("移动失败"), str(error))
        menu.deleteLater()

    @staticmethod
    def safe_child(folder, name):
        name = name.strip()
        if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|') or name.endswith((".", " ")):
            raise ValueError(t("名称无效，请勿使用路径分隔符或特殊字符。"))
        target = (Path(folder) / name).resolve()
        if target.parent != Path(folder).resolve(): raise ValueError(t("目标必须位于当前文件夹内。"))
        return target

    def move_file(self, source, destination):
        if os.path.abspath(source) == os.path.abspath(destination): return
        if os.path.exists(destination): raise ValueError(t("目标文件已存在，请使用其他名称。"))
        if not os.path.isfile(source): raise ValueError(t("仅支持移动文件。"))
        import shutil
        # Relocate references on disk too, including documents that are not open.
        # Exclusively create the destination so a late file creation cannot be overwritten.
        content = None
        if os.path.dirname(source) != os.path.dirname(destination) and Path(source).suffix.lower() in TEXT_SUFFIXES:
            try: content = Path(source).read_text(encoding="utf-8-sig")
            except UnicodeError: pass
        if content is None:
            shutil.move(source, destination)
        else:
            content = self.window._relocate_images(content, os.path.dirname(source), os.path.dirname(destination))
            with open(destination, "x", encoding="utf-8", newline="\n") as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            shutil.copystat(source, destination)
            os.unlink(source)
        history = self.history_store()
        old_history, new_history = history.directory(source), history.directory(destination)
        if old_history.exists() and not new_history.exists():
            try: old_history.rename(new_history)
            except OSError as error: self.window.statusBar().showMessage(str(error), 6000)
        for owner in self.window.store.windows:
            for tab in owner._tab_list:
                if tab.filepath and os.path.normcase(tab.filepath) == os.path.normcase(source):
                    # Keep image resolution based on the source directory until saved.
                    old_dir = tab.file_dir()
                    tab.filepath = os.path.abspath(destination)
                    if tab.pending_file: tab.pending_file = tab.filepath
                    tab.file_stamp = owner._file_stamp(tab.filepath)
                    tab.external_changed = False
                    if old_dir != os.path.dirname(destination):
                        if tab.ready:
                            def relocated(content, tab=tab, owner=owner, old_dir=old_dir):
                                if tab not in owner._tab_list or owner._closed: return
                                try:
                                    converted = owner._relocate_images(content, old_dir, os.path.dirname(tab.filepath))
                                    if converted != content: tab.js("window.setContent(%s); window.notifyEdited();" % json.dumps(converted))
                                    owner._sync_md_dir(tab)
                                except OSError as error: QMessageBox.warning(owner, t("图片复制失败"), str(error))
                            tab.view.page().runJavaScript("window.currentMarkdown()", relocated)
                        else: owner._sync_md_dir(tab)
                    owner._remember_file(tab.filepath)
            owner._update_titles(); owner.features.watch()

    def close(self):
        self.job_timer.stop()
        paths = self.watcher.files() + self.watcher.directories()
        if paths: self.watcher.removePaths(paths)
