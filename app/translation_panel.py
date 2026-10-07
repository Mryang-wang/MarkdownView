"""Per-document translation controller; the reading UI shares the editor's WebEngine."""
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from .i18n import t
from .translation import load_config
from .translation_dialog import PromptDialog, TranslationSettingsDialog, load_prompts
from .translation_markdown import TranslationJob
from .translation_memory import IncrementalMarkdown
from .workspace_store import atomic_write


class TranslationPanel(QObject):
    def __init__(self, tab):
        super().__init__(tab.view)
        self.tab = tab
        self.job = None
        self.snapshot = {}
        self.mode = "selection"
        self.assets = None
        self.closed = False
        self.generation = 0
        self.sent_parts = -1
        self.memory = None
        self.memory_options = None
        self.source_stale = False
        self.source_revision = 0
        self.options = {"source": "auto detect", "target": QSettings().value("translation/target", "简体中文"),
                        "prompt": QSettings().value("translation/prompt", "通用翻译"), "glossary": ""}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)

    @property
    def window(self):
        return self.tab.window

    def send(self, method, data):
        if not self.closed and self.tab.ready:
            self.tab.js("window.translationUI.%s(%s)" % (method, json.dumps(data, ensure_ascii=False)))

    def settings(self):
        config = load_config()
        return {"options": self.options, "prompts": [{"name": name, "label": t(name)} for name in load_prompts()],
                "model": config.model, "configured": bool(config.endpoint and config.model)}

    def open(self, snapshot, mode="selection"):
        # Reopening the same source retains progress; selecting new text starts a new task.
        selected_mode = "selection" if mode != "full" and snapshot.get("selection", "").strip() else "full"
        source = snapshot.get(selected_mode, "")
        if not source.strip():
            return
        if len(source) > 500_000:
            QMessageBox.information(self.window, t("翻译"), t("文档过长，请分次选择需要翻译的章节。"))
            return
        if self.snapshot.get(selected_mode) == source and self.mode == selected_mode:
            self.send("show", {"mode": self.mode})
            self.send("settings", self.settings())
            self.refresh()
            return
        self.reset_job()
        if self.assets:
            self.assets.cleanup()
        self.assets = None
        self.snapshot = snapshot
        self.source_stale = False
        self.mode = selected_mode
        self.source_path, self.source_dir = self.tab.filepath, self.tab.file_dir()
        self.name = self.tab.display_name()
        # Keep unsaved local images valid if the document is saved/moved during translation.
        self.render_source = source
        if not self.source_path and self.source_dir:
            from .document_services import relocate_images
            self.assets = tempfile.TemporaryDirectory(prefix="mdview-translation-")
            try:
                self.render_source = relocate_images(source, self.source_dir, self.assets.name)
                self.source_dir = self.assets.name
            except OSError:
                self.assets.cleanup()
                self.assets = None
        self.generation += 1
        self.sent_parts = -1
        self.restore()
        config = load_config()
        if config.endpoint and config.model:
            self.start(reuse=True)

    def restore(self, hidden=False):
        self.send("open", {**self.settings(), "mode": self.mode, "source": self.render_source,
                           "base": QUrl.fromLocalFile(self.source_dir + os.sep).toString() if self.source_dir else "",
                           "name": self.name, "generation": self.generation})
        self.sent_parts = -1
        self.refresh()
        if hidden: self.send("exit", {})

    def action(self, action, options):
        if self.closed:
            return
        if action in ("start", "update", "settings", "prompt", "full") and not (self.job and self.job.state == "running"):
            for key in self.options:
                if isinstance(options.get(key), str):
                    self.options[key] = options[key][:12000]
        if action == "start":
            if self.source_stale: self.update_source()
            else: self.start()
        elif action == "update":
            self.update_source()
        elif action == "cancel":
            if self.job: self.job.cancel()
        elif action == "settings":
            dialog = TranslationSettingsDialog(self.window, self.window._theme)
            dialog.exec()
            dialog.deleteLater()
            self.send("settings", self.settings())
        elif action == "prompt":
            name = self.options["prompt"]
            prompts = load_prompts()
            dialog = PromptDialog(self.window, name, prompts.get(name, prompts["通用翻译"]), self.window._theme)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.options["prompt"] = dialog.name.text().strip()
                if self.options["prompt"] not in load_prompts(): self.options["prompt"] = "通用翻译"
            dialog.deleteLater()
            self.send("settings", self.settings())
        elif action == "full":
            self.window.open_translation(self.tab, "full")
        elif action == "copy" and self.job and not self.source_stale:
            QApplication.clipboard().setText(self.job.result)
        elif action == "open" and self.job and self.job.parts and not self.source_stale:
            self.window.open_translated_document(self.job.result, self.source_dir, self.name)
        elif action == "save":
            self.save()
        elif action == "reset":
            self.reset_job()
            for key in ("source", "target"):
                if isinstance(options.get(key), str):
                    self.options[key] = options[key][:100]
            self.send("reset", {})
        elif action == "exit":
            # Closing the reader stops further paid requests; completed results can be resumed.
            if self.job: self.job.cancel()
            self.send("exit", {})

    def source_changed(self):
        if self.mode != "full" or not self.snapshot: return
        self.source_revision += 1
        self.source_stale = True
        if self.job: self.job.cancel()
        self.schedule()

    def update_source(self):
        if self.mode != "full" or not self.tab.ready: return
        revision = self.source_revision
        def received(value):
            if self.closed or revision != self.source_revision: return
            try: snapshot = json.loads(value)
            except (ValueError, TypeError): return
            if not isinstance(snapshot, dict): return
            if snapshot.get("full", "").strip():
                if snapshot.get("full") == self.snapshot.get("full"):
                    self.source_stale = False
                    self.start(reuse=True)
                else:
                    self.open(snapshot, "full")
                    self.send("hide", {})
            else:
                self.reset_job(); self.snapshot = snapshot; self.render_source = ""; self.source_stale = False
                self.generation += 1; self.restore(); self.send("hide", {})
        self.tab.view.page().runJavaScript("JSON.stringify(window.translationSource())", received)

    def start(self, reuse=False):
        if self.job and self.job.state == "running":
            return
        config = load_config()
        if not config.endpoint or not config.model:
            self.action("settings", {})
            config = load_config()
        prompt = load_prompts().get(self.options["prompt"], "")
        try:
            signature = (config.url(), config.protocol, config.model, self.options["source"], self.options["target"],
                         self.options["glossary"], prompt)
        except ValueError as error:
            self.send("error", str(error)); return
        if self.job and self.job.state in ("failed", "cancelled") and self.job.memory_signature == signature:
            self.job.config = replace(config, chunk_size=self.job.config.chunk_size)
            self.job.start()
            return
        self.reset_job()
        try:
            document = None
            if self.mode == "full":
                previous = self.memory if reuse and signature == self.memory_options else None
                document = IncrementalMarkdown(self.render_source, config.chunk_size, previous)
            self.job = TranslationJob(config, self.render_source, self.options["source"], self.options["target"],
                                      self.options["glossary"], self, prompt, document=document)
            self.job.memory_signature = signature
        except ValueError as error:
            self.send("error", str(error))
            return
        QSettings().setValue("translation/target", self.options["target"])
        QSettings().setValue("translation/prompt", self.options["prompt"])
        self.job.changed.connect(self.schedule)
        self.send("reset", {})
        self.job.start()
        self.refresh()

    def schedule(self):
        if not self.timer.isActive(): self.timer.start()

    def refresh(self):
        if not self.job or self.closed: return
        if self.tab is not self.window.current_tab():
            self.sent_parts = -1
            return
        job = self.job
        done, total = len(job.parts), len(job.document.chunks)
        running, retry = job.state == "running", job.state in ("failed", "cancelled")
        if self.source_stale:
            status = t("原文已修改。点击“更新改动”，仅翻译变化的内容。")
        elif running:
            status = t("正在翻译：{0} / {1} 段，已接收 {2} 个字符").format(min(done + 1, total), total, len(job.partial))
        elif job.state == "complete":
            status = t("翻译完成，共 {0} 段。请检查译文后保存。").format(total)
        else:
            status = (job.error or t("翻译已取消。")) + " " + t("已保留 {0} / {1} 段，可继续或保存已完成部分。").format(done, total)
        reused = getattr(job.document, "reused_units", 0)
        if reused and not self.source_stale:
            status += " " + t("已复用 {0} 个未改句段。").format(reused)
        data = {"generation": self.generation, "state": job.state, "status": status, "done": done, "total": total,
                "retry": retry, "preview": job.partial_preview, "stale": self.source_stale, "reused": reused}
        # Only the current chunk travels on each refresh. Committed Markdown/math is
        # rendered separately, so streaming never reparses the entire document.
        if self.sent_parts != done:
            data["result"] = job.result
            if isinstance(job.document, IncrementalMarkdown):
                data["layout"] = job.document.display_markdown()
                data["live_source"] = job.document.source_before(job.document.chunks[done]) if done < total else ""
            self.sent_parts = done
        self.send("update", data)

    def save(self):
        if not self.job or not self.job.parts or self.source_stale: return
        proposed = str(Path(self.source_path).with_name(Path(self.source_path).stem + "-translated.md")) if self.source_path else "translated.md"
        path, _ = QFileDialog.getSaveFileName(self.window, t("另存译文"), proposed, "Markdown (*.md);;Text (*.txt)")
        if not path: return
        if self.source_path and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self.source_path)):
            QMessageBox.information(self.window, t("另存译文"), t("请选择其他文件名，以保留原文。"))
            return
        try:
            atomic_write(path, self.window._relocate_images(self.job.result, self.source_dir, os.path.dirname(path)))
        except OSError as error:
            QMessageBox.warning(self.window, t("保存失败"), str(error))

    def reset_job(self):
        if self.job:
            if isinstance(self.job.document, IncrementalMarkdown):
                self.memory = self.job.document
                self.memory_options = self.job.memory_signature
            self.job.changed.disconnect(self.schedule)
            self.job.cancel()
            self.job.deleteLater()
            self.job = None
        self.timer.stop()
        self.sent_parts = -1

    def close(self):
        self.reset_job()
        self.closed = True
        if self.assets:
            self.assets.cleanup()
            self.assets = None
