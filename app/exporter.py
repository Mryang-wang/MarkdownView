# -*- coding: utf-8 -*-
"""docx 导出：优先使用系统 PATH 中的 pandoc，其次 winget 安装位置。

包含针对 pandoc texmath 已知限制的预处理：
`\\leftX ... \\\\ ... \\rightY`（定界符跨换行）无法转换，
自动改写为 `\\leftX ... \\right. \\\\ \\left. ... \\rightY` 的等价形式。
"""
from .i18n import t
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def _parse_version(text):
    m = re.search(r"pandoc(?:\.exe)?\s+(\d+(?:\.\d+)*)", text or "")
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


def find_pandoc():
    """返回版本最高的 pandoc 可执行文件路径，找不到返回 None。"""
    candidates = []
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "pandoc.exe")
    if os.path.isfile(bundled):
        candidates.append(bundled)
    p = shutil.which("pandoc")
    if p:
        candidates.append(p)
    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(
        local, "Microsoft", "WinGet", "Packages",
        "JohnMacFarlane.Pandoc_*", "pandoc-*", "pandoc.exe")
    candidates.extend(glob.glob(pattern))
    if not candidates:
        return None

    best, best_ver = None, (0,)
    for cand in candidates:
        ver = _parse_version(pandoc_version(cand))
        if ver > best_ver:
            best, best_ver = cand, ver
    return best


def pandoc_version(pandoc_path):
    try:
        out = subprocess.run(
            [pandoc_path, "--version"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        return out.stdout.splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "unknown"


class ExportError(Exception):
    pass


# ---------- texmath 兼容性预处理 ----------

_MATH_SEGMENT = re.compile(
    r"(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))")

_LEFT_RIGHT_TOKENS = re.compile(r"(\\left\s*\S|\\right\s*\S|\\\\)")


def _fix_left_right_linebreaks(math_text):
    r"""把 \leftX A \\ B \rightY 改写为 \leftX A \right. \\ \left. B \rightY。

    texmath（pandoc 的 LaTeX→OMML 引擎）不支持定界符跨 \\ 换行。
    """
    if "\\\\" not in math_text or "\\left" not in math_text:
        return math_text
    parts = _LEFT_RIGHT_TOKENS.split(math_text)
    out = []
    depth = 0
    for part in parts:
        if part.startswith("\\left"):
            depth += 1
            out.append(part)
        elif part.startswith("\\right"):
            if depth > 0:
                depth -= 1
            out.append(part)
        elif part == "\\\\" and depth > 0:
            out.append("\\right. " * depth)
            out.append("\\\\\n")
            out.append("\\left. " * depth)
        else:
            out.append(part)
    return "".join(out)


def _transform_math_segments(md_text, fn):
    """对 $$..$$ / \\[..\\] / \\(..\\) 数学段应用 fn，其余文本不动。

     fenced 代码块整体跳过（fenced code 内不会出现上述定界符误匹配，
    因为 fenced code 先于数学解析，这里简单按 fenced 分段）。
    """
    code_split = re.split(r"(```[\s\S]*?(?:```|$))", md_text)
    for i in range(0, len(code_split), 2):
        seg = code_split[i]
        code_split[i] = _MATH_SEGMENT.sub(
            lambda m: fn(m.group(0)), seg)
    return "".join(code_split)


def preprocess_for_texmath(md_text):
    return _transform_math_segments(md_text, _fix_left_right_linebreaks)


# ---------- 导出 ----------

def _apply_inline_styles(output_path):
    """补上 Word 原生下划线和 RGB 高亮，兼容同一选区上的格式叠加。"""
    underline_values = {"solid": "single", "double": "double", "wavy": "wave",
                        "dashed": "dash", "dotted": "dotted"}

    def properties(style_id):
        highlight = re.fullmatch(r"MDViewHighlight_([A-F0-9]{6})_([A-F0-9]{6})(?:_U_(\w+))?", style_id)
        underline = re.fullmatch(r"MDViewUnderline_(\w+)", style_id)
        result = ""
        if highlight:
            result = (f'<w:shd w:val="clear" w:color="auto" w:fill="{highlight[1]}"/>'
                      f'<w:color w:val="{highlight[2]}"/>')
        line = highlight[3] if highlight else underline[1] if underline else None
        if line in underline_values:
            result += f'<w:u w:val="{underline_values[line]}"/>'
        return result

    def decorate(block, style_id, closing_tag):
        added = properties(style_id)
        if not added:
            return block
        def update_run(match):
            content = match[1]
            for tag in ("shd", "color", "u"):
                if f"<w:{tag} " in added:
                    content = re.sub(rf'<w:{tag}\b[^>]*(?:/>|>.*?</w:{tag}>)', "", content, flags=re.DOTALL)
            return "<w:rPr>" + content + added + "</w:rPr>"
        if "<w:rPr>" in block:
            return re.sub(r"<w:rPr>(.*?)</w:rPr>", update_run, block, count=1, flags=re.DOTALL)
        return block.replace(closing_tag, "<w:rPr>" + added + "</w:rPr>" + closing_tag, 1)

    with zipfile.ZipFile(output_path) as source:
        styles = source.read("word/styles.xml").decode("utf-8")
        document = source.read("word/document.xml").decode("utf-8")
        updated_styles = re.sub(r'<w:style\b[^>]*\bw:styleId="(MDView(?:Highlight|Underline)_\w+)"[^>]*>.*?</w:style>',
                                lambda match: decorate(match[0], match[1], "</w:style>"), styles, flags=re.DOTALL)
        def decorate_text(match):
            block = match[0]
            inline_style = re.search(r'<w:rStyle\b[^>]*\bw:val="(MDView(?:Highlight|Underline)_\w+)"', block)
            return decorate(block, inline_style[1], "</w:r>") if inline_style else block
        updated_document = re.sub(r"<w:r\b[^>]*>.*?</w:r>", decorate_text, document, flags=re.DOTALL)
        if updated_styles == styles and updated_document == document:
            return
        updated = {"word/styles.xml": updated_styles.encode("utf-8"),
                   "word/document.xml": updated_document.encode("utf-8")}
        handle, temporary = tempfile.mkstemp(prefix=".mdview-format-", suffix=".docx",
                                             dir=os.path.dirname(output_path))
        os.close(handle)
        try:
            with zipfile.ZipFile(temporary, "w") as target:
                for entry in source.infolist():
                    target.writestr(entry, updated[entry.filename] if entry.filename in updated else source.read(entry.filename))
        except Exception:
            os.remove(temporary)
            raise
    try:
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def export_docx(markdown_text, output_path, resource_dir=None):
    """把 markdown 文本导出为 docx，返回 pandoc 的 stderr 警告（可为空字符串）。

    公式转为 Word 原生 OMML，表格转为 Word 原生表格。
    源文件使用 \\(...\\) / $$...$$ 分隔符，通过启用
    tex_math_single_backslash / tex_math_double_backslash 扩展支持。
    """
    pandoc = find_pandoc()
    if not pandoc:
        raise ExportError(
            t("未找到 pandoc。请安装：https://pandoc.org/installing.html\n"
            "或运行：winget install --id JohnMacFarlane.Pandoc"))

    markdown_text = preprocess_for_texmath(markdown_text)
    output_path = os.path.abspath(output_path)

    # 写入临时 md 文件（pandoc 以文件为输入最稳妥）
    tmp_dir = tempfile.mkdtemp(prefix="mdview_")
    tmp_md = os.path.join(tmp_dir, "input.md")
    with open(tmp_md, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    cmd = [
        pandoc, tmp_md,
        "--from",
        "markdown+tex_math_single_backslash+tex_math_double_backslash+mark",
        "--to", "docx",
        "--lua-filter", os.path.join(os.path.dirname(__file__), "assets", "export_formats.lua"),
        "--standalone",
        "--output", output_path,
    ]
    if resource_dir:
        cmd.extend(["--resource-path", resource_dir])

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
            cwd=resource_dir or tmp_dir)
    except subprocess.TimeoutExpired:
        raise ExportError(t("pandoc 导出超时（120 秒）。"))

    if proc.returncode != 0:
        raise ExportError(t("pandoc 导出失败：\n") + (proc.stderr or t("未知错误")))
    if not os.path.exists(output_path):
        raise ExportError(t("pandoc 未生成输出文件。"))
    try:
        _apply_inline_styles(output_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise ExportError(t(f"无法保留导出的下划线与高亮格式：{error}")) from error
    return proc.stderr or ""
