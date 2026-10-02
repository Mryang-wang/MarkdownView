# MarkdownView

一款面向 Windows 的桌面 Markdown 编辑器，让笔记、公式与长文写作保持专注。

基于 **Python + PySide6 / Qt WebEngine + Vditor + KaTeX**，支持即时渲染、多文档、批注、草稿恢复，以及可编辑的 Word 文档导出。

![MarkdownView 浅色界面](docs/screenshots/light.png)

## 功能亮点

| 功能 | 说明 |
| --- | --- |
| 三种编辑模式 | 即时渲染（IR）、所见即所得和源代码模式，支持大纲与预览 |
| 多文档工作区 | 侧栏切换、关闭、拖拽排序，拖出文档可分离为独立窗口 |
| 数学与表格 | KaTeX 渲染 LaTeX 公式；支持可视化表格编辑 |
| 图片插入 | 选择图片、粘贴截图、拖入多张图片；保存时管理相对路径资源 |
| 丰富格式 | 多种下划线、上下标、删除线，以及预设或自定义颜色高亮 |
| 查找替换 | 大小写、整词匹配、匹配数量、单次与全部替换 |
| 批注与统计 | 选区批注、定位原文，查看全文及选中文字、字符和行数 |
| 草稿保护 | 后台草稿备份、异常退出恢复、可选自动保存与外部修改检测 |
| 会话恢复 | 最近文档、上次工作区和阅读位置恢复 |
| Word / PDF 导出 | DOCX 保留 Word 原生公式和表格；PDF 用于阅读、打印与分享 |
| 主题与语言 | 浅色 / 深色主题，简体中文 / English 界面，偏好跨窗口同步 |
| 本地编辑 | 编辑器与公式资源随源码提供，基本编辑与公式渲染无需联网 |

再次打开 Markdown 文件时，会交给已运行的窗口；重复打开同一文件会切换到已有文档，并保留未保存内容。

<details>
<summary>查看深色界面</summary>

![MarkdownView 深色界面](docs/screenshots/dark.png)

</details>

## 从源码运行

当前主要开发与验证环境为 **Windows、Python 3.12**。项目包含 Windows 专用的窗口与安装逻辑，其他平台尚未验证。

在 PowerShell 中执行：

```powershell
git clone https://github.com/Mryang-wang/MarkdownView.git
cd MarkdownView

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe main.py
```

无需激活虚拟环境，直接使用其中的 Python 即可。也可以指定要打开的文件：

```powershell
.\.venv\Scripts\python.exe main.py "D:\Notes\我的笔记.md"
```

首次运行显示空白文档；后续不带参数启动时，默认恢复上次会话。Vditor 与 KaTeX 资源已经包含在 `app/assets/vditor/`，无需另外执行 npm 安装。

### 启用 Word 导出

DOCX 导出需要安装 Pandoc；建议使用 3.x 或更新版本：

```powershell
winget install --id JohnMacFarlane.Pandoc --exact
```

程序会检测 PATH 和 WinGet 的 Pandoc 安装位置。PDF 导出使用 Qt WebEngine，无需额外安装 LaTeX。

## 常用快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+T` | 新建文档 |
| `Ctrl+O` | 打开文档，可多选 |
| `Ctrl+S` / `Ctrl+Shift+S` | 保存 / 另存为 |
| `Ctrl+W` | 关闭当前文档 |
| `Ctrl+F` / `Ctrl+H` | 查找 / 替换 |
| `F3` / `Shift+F3` | 下一个 / 上一个匹配 |
| `Ctrl+V` | 粘贴文字或截图 |
| `Ctrl+Alt+M` | 为选中文字添加批注 |
| `Ctrl+E` | 导出 DOCX |
| `Ctrl+Shift+E` | 导出 PDF |
| `Ctrl+\` | 显示或隐藏侧栏 |
| `Ctrl+Shift+L` | 切换深浅主题 |
| `Ctrl+'` | 切换全屏，`Esc` 退出 |
| `Ctrl+左键` | 打开正文中的链接 |

## 文档与导出说明

### 公式

支持 `\(...\)` 行内公式，以及 `$$...$$`、`\[...\]` 行间公式。加载时会转换为编辑内核使用的分隔符；保存时行内 `$...$` 会转换为 `\(...\)`，代码块和行内代码不参与转换。

注意：如果货币文本中的 `$` 被识别为公式，保存时也可能发生上述转换。建议对字面量美元符号使用 Markdown 转义。

DOCX 导出通过 Pandoc 将公式转换为 Word 原生 OMML 对象，将表格转换为原生表格。包含针对部分跨行定界符的兼容预处理；`\tag{n}` 在 Word 中显示为公式末尾的编号文本。复杂公式仍建议在 Word / WPS 中检查导出结果。

### 图片与格式

- 本地插入、粘贴和拖入的图片由程序管理；未命名文档的图片先暂存，保存或另存为时复制到目标文档旁的 `images/` 目录。分享文档时请同时带上图片目录。
- 下划线使用 `<u>` 标签，非单线样式通过 `text-decoration-style` 保存；彩色高亮使用带颜色的 `<mark>` 标签。DOCX 导出保留下划线线型和自定义 RGB 底色。
- 上下标使用 `^文本^` / `~文本~`，不同 Markdown 阅读器对这些扩展语法的支持可能不同。

### 批注与草稿

- 批注以带版本标记的 HTML 注释保存在 Markdown 文件尾部，随文件一起移动；其他阅读器的源码视图可能看到批注数据。
- DOCX / PDF 导出包含正文，不导出本软件的批注面板和批注数据。
- 草稿与会话存放在 Qt 应用本地数据目录中；主动放弃修改会清理相应恢复备份。
- 自动保存为可选功能；检测到磁盘上的文件被外部修改时会暂停自动保存并保留草稿。

详细操作见 [选区统计、批注与界面语言](docs/review-and-language.md)。多文档按需加载、内存缓存策略及实测限制见 [资源实测与优化说明](docs/resource-optimization.md)。

## 构建 Windows 安装包

安装脚本当前版本为 **1.1.3**，目标为 **Windows 10 1809 或更新版本的 x64 兼容环境**。

先完成上述依赖与 Pandoc 安装，再安装 **Inno Setup 6**。在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist/release-1.1.3 --workpath build/release-1.1.3 MarkdownView.spec

# 如安装位置不同，请替换为实际的 ISCC.exe 路径
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer/MarkdownView.iss
```

产物为 `dist/setup.exe`。安装包包含 Python、Qt、编辑器资源及 Pandoc，最终用户无需另外配置这些依赖。安装器注册 `.md`、`.markdown` 的打开方式，默认应用需在 Windows 设置中选择。

仓库提供源码与构建脚本，`dist/` 中的本地安装包不纳入 Git。修改版本号时，请同步检查安装脚本、`installer/version_info.txt` 与构建目录。

## 项目结构

```text
MarkdownView/
├── main.py                   # 应用入口与单实例文件转交
├── app/
│   ├── main_window.py         # 主窗口、文档与编辑器管理
│   ├── bridge.py              # Python / JavaScript 通信
│   ├── exporter.py            # Pandoc 调用与 DOCX 预处理
│   ├── workspace_store.py     # 工作区、会话与草稿管理
│   ├── single_instance.py     # 单实例通信
│   ├── i18n.py                # 界面翻译
│   └── assets/                # HTML、CSS、脚本与本地 Vditor 资源
├── docs/                      # 功能说明、性能记录与界面截图
├── design/app-icon/           # 图标源素材和各尺寸资源
├── installer/                 # Inno Setup 脚本与安装验证
├── tools/                     # 图标生成工具
├── test_*.py                  # 独立的功能与界面回归脚本
├── bench_*.py                 # 性能测量脚本
├── verify_docx.py             # DOCX 公式与表格检查
├── MarkdownView.spec         # PyInstaller 构建配置
└── requirements.txt          # Python 运行依赖
```

## 开发验证

现有测试以独立脚本运行，部分会启动真实 Qt / WebEngine 窗口，需要可用的桌面会话。请逐个运行，例如：

```powershell
.\.venv\Scripts\python.exe test_export_path.py
.\.venv\Scripts\python.exe test_pdf_export.py
.\.venv\Scripts\python.exe test_review_language.py
.\.venv\Scripts\python.exe test_priority_features.py
```

DOCX 相关测试需要 Pandoc；安装验证和部分图标测试还需要先构建对应产物。

早期的 `test_render.py`、`test_edit_save.py`、`test_features.py`、`test_tabs.py` 和两个 `bench_*.py` 使用本地论文样本 `02_建模方法_SCI精简重构版.md`。该私人样本未公开，因此这些脚本不能在干净克隆后直接复现；替换样本时还需同步调整与内容数量有关的断言。性能文档中的历史数据也基于该样本。

## 反馈

欢迎通过 [Issues](https://github.com/Mryang-wang/MarkdownView/issues) 反馈问题。请提供 Windows / Python / PySide6 版本、复现步骤和不含私人内容的最小 Markdown 示例；导出问题请附 Pandoc 版本。
