# MarkdownView 图标更新（1.1.2）

名称和现有标识保持 MarkdownView。保留深灰色 M、蓝色向下箭头/对勾、三条灰色文档线和白色圆角底板，放大主体并减少留白，使桌面、任务栏和菜单中的图标更醒目。

使用内置 imagegen 编辑原 PNG。采用的提示：保留原有标识与配色，只调整主体比例和布局；放大 M 与箭头，将灰色线靠近 M，减少上下留白，保持居中和安全边距；输出单个正方形应用图标，外部透明，适用于 Windows 的小尺寸显示，无新增文字或符号。生成的原始素材保存为 `artwork-v1.1.2.png`。

采用素材的完整生成提示（内置 imagegen，`transparent_background=true`）：

```text
Use case: precise-object-edit. Asset: production Windows desktop application icon for the existing app MarkdownView. Edit target: the supplied existing logo. Keep the existing recognizable thick dark charcoal capital M, the overlapping muted blue downward chevron/checkmark at its lower right, the three subtle gray horizontal document lines at the upper right, and the warm white rounded-square backplate. Preserve this identity, restrained colors, clean softly shaded finish and front-facing geometry. Change only the proportions/composition needed to make the icon read larger: substantially enlarge the dark M and blue chevron, bring the decorative lines closer to the M, reduce the excessive top and bottom empty white space, and optically center the mark. The combined visible colored/dark symbol should occupy about 90% of the square's width and 75–80% of its height, with a small consistent safe inset so no stroke is clipped. The white rounded-square backplate should fill essentially the whole canvas, with genuinely transparent pixels only outside its rounded corners; no surrounding whitespace, no extra drop shadow outside the tile. The output must be exactly square and useful as a Windows icon at 16, 32, 48 and 256 pixels. Crisp substantial strokes, subtly rounded edges, small-size legibility; do not add text or change the M into another letter, do not add a border, do not introduce additional symbols or a new color palette. Produce one single isolated final icon, no presentation board, mockup, labels, duplicates or comparison layout.
```

`original.png` 和 `original.ico` 保留旧素材。原 ICO 只有一个非正方形的 250×256 帧。

使用 Windows System.Drawing 导出流程统一透明圆角边界，保留图标内部生成的图案，并生成规范的 PNG 与 ICO。新 ICO 包含 16、20、24、32、40、48、64、96、128、256 共 10 个尺寸，均为 32 位透明图像。原始生成图的透明边缘未直接用作 Windows 图标边界，避免残留的抠图杂边。

重建图标（PowerShell 7）：

```powershell
& tools/build_icon.ps1
```

程序窗口、菜单栏图标、EXE 资源及安装器统一使用项目根目录的 `图片1.ico`，`图片1.png` 保留为 1024×1024 的标准 PNG。各个尺寸的独立预览位于 `sizes/`。

可见主体高度从原图约 51.8% 提升为约 67.1%。`test_icon_assets.py` 已检查透明边缘、主体比例、Qt 与 Windows 原生加载、打包 EXE 和 setup 的 10 个图标资源；隔离安装还验证了桌面与开始菜单快捷方式均引用新 EXE 图标，卸载时正确清理测试快捷方式。旧文件关联与现有 MarkdownView 安装保持原样。
