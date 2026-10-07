"""Bounded local storage and cancellable project scans, without extra dependencies."""
import hashlib
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit, quote

from .workspace_store import atomic_write


TEXT_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".txt"}
IGNORED_FOLDERS = {".git", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


class ProjectScan:
    """A fresh worker per user search; cancellation is checked before every file."""
    def __init__(self, root, query="", contents=False, case_sensitive=False):
        self.cancelled = threading.Event()
        self.results = queue.Queue(maxsize=1200)
        self.thread = threading.Thread(target=self._run, args=(root, query, contents, case_sensitive), daemon=True)
        self.thread.start()

    def _put(self, value):
        while not self.cancelled.is_set():
            try:
                self.results.put(value, timeout=.1)
                return
            except queue.Full:
                continue

    def _run(self, root, query, contents, case_sensitive):
        scanned, found, skipped, total_bytes = 0, 0, 0, 0
        needle = query if case_sensitive else query.casefold()
        try:
            for directory, folders, files in os.walk(root, followlinks=False):
                if self.cancelled.is_set():
                    return
                folders[:] = [name for name in folders if name not in IGNORED_FOLDERS and
                              not os.path.islink(os.path.join(directory, name)) and
                              not (hasattr(os.path, "isjunction") and os.path.isjunction(os.path.join(directory, name)))]
                for name in files:
                    if self.cancelled.is_set():
                        return
                    path = Path(directory) / name
                    if path.suffix.lower() not in TEXT_SUFFIXES or path.is_symlink():
                        continue
                    scanned += 1
                    if scanned > 20000 or found >= 1000 or total_bytes > 100 * 1024 * 1024:
                        self._put(("done", scanned, found, skipped, True))
                        return
                    relative = str(path.relative_to(root))
                    if not contents:
                        haystack = relative if case_sensitive else relative.casefold()
                        if all(part in haystack for part in needle.split()):
                            self._put(("item", str(path), 0, relative))
                            found += 1
                        continue
                    try:
                        if path.stat().st_size > 2 * 1024 * 1024:
                            skipped += 1
                            continue
                        text = path.read_text(encoding="utf-8-sig")
                        total_bytes += len(text.encode("utf-8"))
                    except (OSError, UnicodeError):
                        skipped += 1
                        continue
                    if "\x00" in text:
                        skipped += 1
                        continue
                    for line_number, line in enumerate(text.splitlines(), 1):
                        if self.cancelled.is_set():
                            return
                        offset = (line if case_sensitive else line.casefold()).find(needle)
                        if offset >= 0:
                            excerpt = line[max(0, offset - 45):offset + len(query) + 110].strip()
                            self._put(("item", str(path), line_number, excerpt))
                            found += 1
                            if found >= 1000:
                                self._put(("done", scanned, found, skipped, True))
                                return
            self._put(("done", scanned, found, skipped, False))
        except OSError:
            self._put(("done", scanned, found, skipped + 1, True))


class HistoryStore:
    def __init__(self, root, max_bytes=50 * 1024 * 1024, per_file=20):
        self.root = Path(root) / "history"
        self.max_bytes, self.per_file = max_bytes, per_file

    def directory(self, path):
        key = hashlib.sha256(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()
        return self.root / key

    def entries(self, path):
        return sorted(self.directory(path).glob("*.md"), key=lambda p: p.name, reverse=True)

    def capture(self, path, content, automatic=False):
        if not self.max_bytes or len(content.encode("utf-8")) > min(self.max_bytes, 10 * 1024 * 1024):
            return
        entries = self.entries(path)
        if entries:
            if automatic and time.time() - entries[0].stat().st_mtime < 60:
                return
            if entries[0].read_text(encoding="utf-8") == content:
                return
        folder = self.directory(path)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000000:09d}.md")
        atomic_write(target, content)
        for entry in self.entries(path)[self.per_file:]:
            entry.unlink(missing_ok=True)
        self.prune()

    def prune(self):
        entries = sorted(self.root.glob("*/*.md"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in entries)
        for entry in entries:
            if total <= self.max_bytes:
                break
            total -= entry.stat().st_size
            entry.unlink(missing_ok=True)


def code_spans(content):
    spans, opening, start, offset = [], None, 0, 0
    for line in content.splitlines(keepends=True):
        match = re.match(r"^[ \t>]*(`{3,}|~{3,})", line)
        if opening is None and match:
            opening, start = match[1], offset
        elif opening and re.match(r"^[ \t>]*" + re.escape(opening[0]) + "{" + str(len(opening)) + r",}[ \t]*(?:\r?\n)?$", line):
            spans.append((start, offset + len(line))); opening = None
        offset += len(line)
    if opening: spans.append((start, len(content)))
    spans.extend((m.start(), m.end()) for m in re.finditer(r"(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)", content)
                 if not any(a <= m.start() < b for a, b in spans))
    return spans


_IMAGE = re.compile(r'''!\[(?:\\.|[^\]\\])*\]\(\s*(?P<md><[^>]+>|(?:\\.|[^\s()]|\([^()]*\))+)|<img\b[^>]*?\bsrc=["'](?P<html>[^"']+)|!\[[^\]]*\]\[(?P<ref>[^\]]*)\]|!\[(?P<shortcut>(?:\\.|[^\]\\])*)\](?![\[(])''', re.I)


def image_references(content, source_dir):
    """Locations refer to destination text only, allowing exact in-place rewriting."""
    excluded = code_spans(content)
    definitions = {m[1].casefold(): m for m in re.finditer(r"(?m)^ {0,3}\[([^\]]+)\]:[ \t]*(<[^>]+>|\S+)", content)
                   if not any(a <= m.start() < b for a, b in excluded)}
    items, used = [], set()
    for match in _IMAGE.finditer(content):
        if any(a <= match.start() < b for a, b in excluded):
            continue
        if match.group("ref") is not None or match.group("shortcut") is not None:
            name = match.group("shortcut") if match.group("shortcut") is not None else match.group("ref") or re.match(r"!\[([^\]]*)", match[0])[1]
            definition = definitions.get(name.casefold())
            if not definition:
                # An undefined shortcut is ordinary Markdown text, not an image.
                if match.group("shortcut") is not None:
                    continue
                items.append({"reference": f"[{name}]", "path": None, "status": "missing", "span": None})
                continue
            start, end = definition.span(2)
        else:
            start, end = match.span("md" if match.group("md") is not None else "html")
        if (start, end) in used:
            continue
        used.add((start, end))
        reference = content[start:end].strip("<>")
        raw = unquote(reference.split("#", 1)[0])
        path = None
        if raw.startswith(("http://", "https://", "data:", "//")):
            status = "remote"
        else:
            if raw.startswith("file:"):
                parts = urlsplit(raw)
                raw = ("//" + parts.netloc + parts.path) if parts.netloc else parts.path.lstrip("/") if os.name == "nt" else parts.path
            path = os.path.abspath(os.path.join(source_dir or "", raw))
            status = "local" if os.path.isfile(path) else "missing"
        items.append({"reference": reference, "path": path, "status": status, "span": (start, end)})
    return items


def relocate_images(content, source_dir, target_dir):
    if not source_dir or os.path.normcase(os.path.abspath(source_dir)) == os.path.normcase(os.path.abspath(target_dir)):
        return content
    replacements, copied = [], {}
    for item in image_references(content, source_dir):
        if item["status"] != "local" or not item["span"]:
            continue
        source = item["path"]
        if source not in copied:
            folder = Path(target_dir) / "images"
            folder.mkdir(parents=True, exist_ok=True)
            name = Path(source).name
            destination = folder / name
            if destination.exists() and os.path.normcase(str(destination)) != os.path.normcase(source):
                name = Path(source).stem + "-" + uuid.uuid4().hex[:8] + Path(source).suffix
                destination = folder / name
            if os.path.normcase(str(destination)) != os.path.normcase(source):
                shutil.copyfile(source, destination)
            copied[source] = "images/" + quote(name, safe="-_.")
        replacements.append((*item["span"], copied[source]))
    for start, end, replacement in sorted(replacements, reverse=True):
        content = content[:start] + replacement + content[end:]
    return content


def bundle_document(content, source_dir, destination, name="document.md"):
    import tempfile
    # Assemble next to the target, then replace atomically; never leave a partial ZIP.
    with tempfile.TemporaryDirectory(prefix="mdview-share-") as folder:
        content = relocate_images(content, source_dir, folder)
        atomic_write(Path(folder) / Path(name).name, content)
        temporary = Path(destination).with_name("." + Path(destination).name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in Path(folder).rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(folder).as_posix())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


DOCUMENT_TEMPLATES = {
    "会议记录": "# 会议记录\n\n日期：{date}\n参与者：\n\n## 议题\n\n## 讨论与决定\n\n## 待办\n\n- [ ] 任务 · 负责人 · 截止日期\n",
    "科研笔记": "# 科研笔记\n\n日期：{date}\n文献：\n\n## 研究问题\n\n## 方法\n\n## 主要结果\n\n## 局限与疑问\n\n## 后续工作\n",
    "实验记录": "# 实验记录\n\n日期：{date}\n编号：\n\n## 目的\n\n## 条件与材料\n\n## 步骤\n\n1. \n\n## 数据与结果\n\n| 项目 | 数值 | 单位 |\n| --- | --- | --- |\n| | | |\n\n## 结论\n",
    "项目计划": "# 项目计划\n\n## 目标\n\n## 范围\n\n## 里程碑\n\n- [ ] 需求确认\n- [ ] 实施\n- [ ] 验证\n\n## 风险\n",
}
SNIPPETS = {
    "公式": "\n$$\ny = ax + b\n$$\n",
    "表格": "\n| 列一 | 列二 |\n| --- | --- |\n| 内容 | 内容 |\n",
    "代码块": "\n```python\nprint('Hello')\n```\n",
    "待办清单": "\n- [ ] 待办事项\n- [x] 已完成事项\n",
    "引用": "\n> 引用内容\n",
}


def templates(settings, snippets=False):
    defaults = SNIPPETS if snippets else DOCUMENT_TEMPLATES
    try:
        data = json.loads(settings.value("writing/snippets" if snippets else "writing/templates", "{}"))
        return {**defaults, **{k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}}
    except (ValueError, TypeError, AttributeError):
        return dict(defaults)
