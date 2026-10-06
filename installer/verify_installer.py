"""用独立安装标识验证真实安装器，保护已有 MarkdownView 和默认文件关联。"""
import os
import json
import re
from pathlib import Path
import subprocess
import sys
import uuid
import winreg

ROOT = Path(__file__).resolve().parents[1]


def snapshot(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            values, children = {}, {}
            count, value_count, _ = winreg.QueryInfoKey(key)
            for index in range(value_count):
                name, data, kind = winreg.EnumValue(key, index)
                values[name] = (data, kind)
            for index in range(count):
                name = winreg.EnumKey(key, index)
                child = snapshot(path + '\\' + name)
                if child is not None:
                    children[name] = child
            return {'values': values, 'children': children} if values or children else None
    except FileNotFoundError:
        return None


def value(path, name=''):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        return winreg.QueryValueEx(key, name)[0]


def execute(arguments, timeout=180):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    subprocess.run(arguments, check=True, timeout=timeout, startupinfo=startup)


def read_shortcuts(name):
    """Read the real shell links without saving or changing them."""
    command = r'''
      $ErrorActionPreference = 'Stop'
      [Console]::InputEncoding = [System.Text.Encoding]::UTF8
      [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
      $probe = [Console]::In.ReadToEnd() | ConvertFrom-Json
      $shell = New-Object -ComObject WScript.Shell
      $links = @()
      foreach ($folder in @('DesktopDirectory', 'Programs')) {
        $path = Join-Path ([Environment]::GetFolderPath($folder)) ($probe.name + '.lnk')
        if (!(Test-Path -LiteralPath $path)) { throw ('Shortcut missing: ' + $path) }
        $link = $shell.CreateShortcut($path)
        $links += [PSCustomObject]@{path=$path; target=$link.TargetPath; icon=$link.IconLocation}
      }
      ConvertTo-Json -InputObject $links -Compress
    '''
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    completed = subprocess.run(
        [str(windows / 'System32/WindowsPowerShell/v1.0/powershell.exe'), '-NoProfile', '-NonInteractive', '-Command', command],
        input=json.dumps({'name': name}), encoding='utf-8-sig', capture_output=True,
        check=True, timeout=30, startupinfo=startup)
    return json.loads(completed.stdout)


def run():
    version = re.search(r'#define MyAppVersion "([^"]+)"',
                        (ROOT / 'installer' / 'MarkdownView.iss').read_text(encoding='utf-8')).group(1)
    suffix = uuid.uuid4().hex[:12]
    name = 'MarkdownViewSetupTest_' + suffix
    application_id = '{' + str(uuid.uuid4()).upper() + '}'
    directory = (ROOT / 'tmp' / ('installer-test-' + suffix)).resolve()
    assert directory.is_relative_to(ROOT / 'tmp')
    directory.mkdir(parents=True)
    install_dir = directory / '安装测试 带空格'
    compiler = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe'
    prog_id = name + '.Markdown'
    class_path = 'Software\\Classes\\' + prog_id
    capabilities = 'Software\\' + name + '\\Capabilities'
    application_path = 'Software\\Classes\\Applications\\' + name + '.exe'
    app_paths = 'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\' + name + '.exe'
    uninstall_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + application_id + '_is1'
    protected = [
        'Software\\Classes\\.md', 'Software\\Classes\\.markdown',
        'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\.md\\UserChoice',
        'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\.markdown\\UserChoice',
        'Software\\Classes\\MarkdownView.Markdown',
        'Software\\Classes\\Applications\\MarkdownView.exe',
        'Software\\MarkdownView',
        'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\MarkdownView.exe',
        'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{44E48D8B-D406-4A75-AF86-D6677ECF5697}_is1']
    before = {path: snapshot(path) for path in protected}
    registered_before = snapshot('Software\\RegisteredApplications')
    assert all(snapshot(path) is None for path in (class_path, capabilities, application_path, app_paths, uninstall_path))
    print('Compiling an isolated test installer...', flush=True)
    execute([str(compiler), '/Q', '/O' + str(directory), '/Finstaller-probe',
             '/DMyAppName=' + name, '/DMyAppId={' + application_id,
             '/DMyRegistryExeName=' + name + '.exe', str(ROOT / 'installer' / 'MarkdownView.iss')], timeout=600)
    installer = directory / 'installer-probe.exe'
    uninstaller = install_dir / 'unins000.exe'
    try:
        arguments = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                     '/MERGETASKS=desktopicon', '/DIR=' + str(install_dir), '/LOG=' + str(directory / 'install.log')]
        execute(arguments)
        executable = install_dir / 'MarkdownView.exe'
        assert executable.is_file() and uninstaller.is_file()
        command = '"' + str(executable) + '" "%1"'
        assert value(class_path + '\\shell\\open\\command') == command
        assert value(application_path + '\\shell\\open\\command') == command
        assert value(app_paths) == str(executable)
        assert value('Software\\RegisteredApplications', name) == capabilities
        for extension in ('.md', '.markdown'):
            assert value(capabilities + '\\FileAssociations', extension) == prog_id
            assert value('Software\\Classes\\' + extension + '\\OpenWithProgids', prog_id) == ''
        assert value(uninstall_path, 'DisplayVersion') == version
        for path in protected[2:]:
            assert snapshot(path) == before[path], 'An existing user registration changed: ' + path
        print('PASS - Native installer registers app capabilities, Open With, icons and quoted Unicode-safe open commands', flush=True)

        shortcuts = read_shortcuts(name)
        for shortcut in shortcuts:
            assert os.path.normcase(shortcut['target']) == os.path.normcase(str(executable)), shortcut
            icon_path, _, icon_index = shortcut['icon'].rpartition(',')
            assert not icon_path or os.path.normcase(icon_path) == os.path.normcase(str(executable)), shortcut
            assert not icon_index or int(icon_index) == 0, shortcut
        print('PASS - Desktop and Start menu shortcuts reference the updated native EXE icon', flush=True)

        # 按注册的命令启动真实安装目录中的程序，验证安装文件和离线资源。
        execute([sys.executable, str(ROOT / 'installer' / 'verify_release.py'), str(executable)])
        sentinel = install_dir / 'user-note.md'
        sentinel.write_text('Keep user-added documents.', encoding='utf-8')
        # Recreate resources shipped by 1.1.4 to exercise upgrade cleanup.
        assets = install_dir / '_internal' / 'app' / 'assets' / 'vditor' / 'dist' / 'js'
        obsolete = [assets / 'katex/fonts/KaTeX_Main-Regular.ttf',
                    assets / 'katex/fonts/KaTeX_Main-Regular.woff',
                    assets / 'icons/material.js', assets / 'i18n/fr_FR.js']
        for path in obsolete:
            path.write_text('obsolete bundled resource', encoding='utf-8')
        execute(arguments)
        assert not any(path.exists() for path in obsolete), 'Upgrade left obsolete runtime assets behind'
        assert (assets / 'katex/fonts/KaTeX_Main-Regular.woff2').is_file()
        assert (assets / 'i18n/zh_CN.js').is_file() and (assets / 'i18n/en_US.js').is_file()
        assert sentinel.read_text(encoding='utf-8') == 'Keep user-added documents.'
        assert value(class_path + '\\shell\\open\\command') == command
        print('PASS - Reinstall/upgrade preserves user-added documents and repairs registrations', flush=True)
    finally:
        if uninstaller.is_file():
            execute([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                     '/LOG=' + str(directory / 'uninstall.log')])
    assert all(snapshot(path) is None for path in (class_path, capabilities, application_path, app_paths, uninstall_path))
    assert all(not Path(shortcut['path']).exists() for shortcut in shortcuts)
    assert snapshot('Software\\RegisteredApplications') == registered_before
    for path in protected:
        assert snapshot(path) == before[path], 'Uninstall changed an existing registration: ' + path
    assert sentinel.read_text(encoding='utf-8') == 'Keep user-added documents.'
    print('PASS - Uninstall removes its own registrations and keeps existing associations, the old installation and user documents', flush=True)
    print('INSTALLER: PASSED', flush=True)


if __name__ == '__main__':
    run()
