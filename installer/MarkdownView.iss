#ifndef MyAppName
  #define MyAppName "MarkdownView"
#endif
#ifndef MyAppId
  #define MyAppId "{{44E48D8B-D406-4A75-AF86-D6677ECF5697}"
#endif
#ifndef MyRegistryExeName
  #define MyRegistryExeName "MarkdownView.exe"
#endif
#define MyAppVersion "1.1.3"
#define MyAppPublisher "MarkdownView"
#define MyAppExeName "MarkdownView.exe"
#define MyProgId MyAppName + ".Markdown"
#define MyBuildDir "..\dist\release-" + MyAppVersion + "\MarkdownView"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=setup
SetupIconFile=..\图片1.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
ChangesAssociations=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; 注册当前用户的候选阅读器，由 Windows 默认应用设置确认最终选择。
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}"; ValueType: string; ValueData: "Markdown 文档"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Markdown 文档"
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}\DefaultIcon"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}\shell"; ValueType: string; ValueData: "open"
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"
Root: HKCU; Subkey: "Software\Classes\{#MyProgId}\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#MyAppExeName}"",0"

Root: HKCU; Subkey: "Software\Classes\.md"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.markdown"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.md\OpenWithProgids"; ValueType: string; ValueName: "{#MyProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.markdown\OpenWithProgids"; ValueType: string; ValueName: "{#MyProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty

Root: HKCU; Subkey: "Software\Classes\Applications\{#MyRegistryExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyRegistryExeName}\DefaultIcon"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyRegistryExeName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyRegistryExeName}\SupportedTypes"; ValueType: string; ValueName: ".md"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyRegistryExeName}\SupportedTypes"; ValueType: string; ValueName: ".markdown"; ValueData: ""

Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Markdown 文档阅读与编辑，支持公式、表格和多种文字样式。"
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".md"; ValueData: "{#MyProgId}"
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".markdown"; ValueData: "{#MyProgId}"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\{#MyAppName}\Capabilities"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#MyRegistryExeName}"; ValueType: string; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{sys}\compact.exe"; Parameters: "/C /S:""{app}"" /EXE:LZX /I /Q"; StatusMsg: "正在优化安装空间…"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "ms-settings:defaultapps?registeredAppUser={#MyAppName}"; Description: "打开默认应用设置，选择 {#MyAppName} 作为 .md 阅读器"; Flags: shellexec nowait postinstall skipifsilent unchecked
