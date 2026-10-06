"""本地草稿、最近文档和上次会话；所有元数据使用原子写入。"""
import json
import os
import re
import shutil
import time
import uuid
import weakref
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication


def atomic_write(path, content):
    target = Path(path)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class WorkspaceStore:
    def __init__(self, directory=None):
        self.root = Path(directory or os.environ.get("MDVIEW_DATA_DIR") or
                         QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        self.drafts_dir = self.root / "drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.windows = weakref.WeakSet()
        self.recovery_offered = False
        self.state = self._read(self.root / "workspace.json", {})
        if not isinstance(self.state, dict):
            self.state = {}
        self.initial_session = self.state.get("session", {})
        if not isinstance(self.initial_session, dict):
            self.initial_session = {}

    @classmethod
    def shared(cls):
        app = QApplication.instance()
        if not hasattr(app, "_workspace_store"):
            app._workspace_store = cls()
        return app._workspace_store

    @staticmethod
    def _read(path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _commit(self):
        atomic_write(self.root / "workspace.json", json.dumps(self.state, ensure_ascii=False))

    def recent_files(self):
        paths = self.state.get("recent", [])
        return [path for path in paths if isinstance(path, str)] if isinstance(paths, list) else []

    def remember_file(self, path):
        path = os.path.abspath(path)
        self.state["recent"] = ([path] + [p for p in self.recent_files()
                                        if os.path.normcase(p) != os.path.normcase(path)])[:15]
        self._commit()

    def clear_recent(self):
        self.state["recent"] = []
        self._commit()

    def write_session(self, documents, active):
        session = {"documents": documents, "active": active}
        if self.state.get("session") == session:
            return
        previous = self.state.get("session")
        self.state["session"] = session
        try:
            self._commit()
        except OSError:
            # A failed write must remain retryable with the same session.
            self.state["session"] = previous
            raise

    def write_draft(self, tab, content):
        record = {"id": tab.draft_id, "path": tab.filepath,
                  "origin": tab.recovery_origin, "resource_dir": tab.file_dir(),
                  "name": tab.display_name(), "content": content,
                  "scroll": tab.scroll_position, "updated": time.time()}
        atomic_write(self.drafts_dir / f"{tab.draft_id}.json",
                     json.dumps(record, ensure_ascii=False))

    def drafts(self):
        records = []
        for path in self.drafts_dir.glob("*.json"):
            record = self._read(path, None)
            if (isinstance(record, dict) and record.get("id") == path.stem
                    and re.fullmatch(r"[0-9a-f]{32}", path.stem)
                    and isinstance(record.get("content"), str)
                    and isinstance(record.get("name"), str)
                    and isinstance(record.get("updated"), (int, float))):
                records.append(record)
        return sorted(records, key=lambda item: item.get("updated", 0), reverse=True)

    def remove_draft(self, draft_id):
        if re.fullmatch(r"[0-9a-f]{32}", draft_id):
            (self.drafts_dir / f"{draft_id}.json").unlink(missing_ok=True)

    def asset_directory(self, draft_id):
        if not re.fullmatch(r"[0-9a-f]{32}", draft_id):
            raise ValueError("无效的草稿标识")
        directory = self.root / "assets" / draft_id
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    def remove_assets(self, draft_id):
        if re.fullmatch(r"[0-9a-f]{32}", draft_id):
            directory = self.root / "assets" / draft_id
            if directory.is_dir():
                shutil.rmtree(directory)
