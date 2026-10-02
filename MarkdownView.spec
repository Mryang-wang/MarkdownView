# -*- mode: python ; coding: utf-8 -*-
import glob
import os
import shutil
import sys


pandoc_path = os.path.join(SPECPATH, "build", "slim", "pandoc.exe")
if not os.path.isfile(pandoc_path):
    pandoc_matches = glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft", "WinGet", "Packages",
        "JohnMacFarlane.Pandoc_*", "pandoc-*", "pandoc.exe"))
    pandoc_path = pandoc_matches[0] if pandoc_matches else shutil.which("pandoc")
if not pandoc_path:
    raise RuntimeError("构建安装包前需要安装 pandoc")

# Qt 使用 Windows 自带的 ICU。开发工具加入 PATH 的其他 ICU DLL
# 可能有相同文件名、不同导出符号，不能混入安装包的依赖扫描。
if sys.platform == "win32":
    windows_dir = os.environ.get("SystemRoot", r"C:\Windows")
    os.environ["PATH"] = os.pathsep.join([
        os.path.dirname(sys.executable),
        sys.base_prefix,
        os.path.join(windows_dir, "System32"),
        windows_dir,
    ])

a = Analysis(
    [os.path.join(SPECPATH, "main.py")],
    pathex=[SPECPATH],
    binaries=[(pandoc_path, ".")],
    datas=[
        (os.path.join(SPECPATH, "app", "assets"), "app/assets"),
        (os.path.join(SPECPATH, "图片1.png"), "."),
        (os.path.join(SPECPATH, "图片1.ico"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtOpenGL",
        "PySide6.QtPositioning",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
    ],
    noarchive=False,
    optimize=0,
)


def keep_runtime_file(item):
    destination = item[0].replace("\\", "/").lower()

    # 本应用的 Qt/Python 运行环境要求 Windows 10 及以上，使用系统 UCRT。
    if destination.startswith("api-ms-win-") or destination == "ucrtbase.dll":
        return False

    if destination.startswith("pyside6/plugins/"):
        return destination in {
            "pyside6/plugins/iconengines/qsvgicon.dll",
            "pyside6/plugins/imageformats/qgif.dll",
            "pyside6/plugins/imageformats/qico.dll",
            "pyside6/plugins/imageformats/qjpeg.dll",
            "pyside6/plugins/imageformats/qsvg.dll",
            "pyside6/plugins/imageformats/qwebp.dll",
            "pyside6/plugins/networkinformation/qnetworklistmanager.dll",
            "pyside6/plugins/platforms/qwindows.dll",
            "pyside6/plugins/styles/qmodernwindowsstyle.dll",
            "pyside6/plugins/tls/qcertonlybackend.dll",
            "pyside6/plugins/tls/qschannelbackend.dll",
        }

    if destination in {
            "libcrypto-3-x64.dll",
            "libssl-3-x64.dll",
            "pyside6/qt6pdf.dll",
            "pyside6/qt6virtualkeyboard.dll"}:
        return False

    if destination.startswith("pyside6/resources/"):
        name = os.path.basename(destination)
        if "debug" in name or "devtools" in name:
            return False

    if destination.startswith("pyside6/translations/"):
        return destination.endswith((
            "/qtbase_zh_cn.qm",
            "/qtwebengine_zh_cn.qm",
            "/qtwebengine_locales/en-us.pak",
            "/qtwebengine_locales/zh-cn.pak",
        ))

    if destination.startswith("app/assets/vditor/dist/"):
        if "/ts/" in destination or "/types/" in destination:
            return False
        if destination.endswith(".d.ts"):
            return False
        if "/js/mathjax/" in destination:
            return False
        if "/js/highlight.js/styles/" in destination:
            return destination.endswith("/github.min.css")
        if destination.endswith((
                "/index.js", "/method.js", "/method.min.js")):
            return False

    return True


a.binaries = [item for item in a.binaries if keep_runtime_file(item)]
a.datas = [item for item in a.datas if keep_runtime_file(item)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MarkdownView",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(SPECPATH, "图片1.ico")],
    version=os.path.join(SPECPATH, "installer", "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MarkdownView",
)
