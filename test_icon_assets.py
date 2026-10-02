"""Validate Windows icon sizes, transparent edges and native EXE resources."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import struct
import sys

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def symbol_fraction(image):
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > 220 and min(color.red(), color.green(), color.blue()) < 170:
                xs.append(x)
                ys.append(y)
    assert xs
    return ((max(xs) - min(xs) + 1) / image.width(),
            (max(ys) - min(ys) + 1) / image.height())


class IconInfo(ctypes.Structure):
    _fields_ = [('icon', wintypes.BOOL), ('x', wintypes.DWORD), ('y', wintypes.DWORD),
                ('mask', ctypes.c_void_p), ('color', ctypes.c_void_p)]


class Bitmap(ctypes.Structure):
    _fields_ = [('kind', wintypes.LONG), ('width', wintypes.LONG), ('height', wintypes.LONG),
                ('stride', wintypes.LONG), ('planes', wintypes.WORD), ('bits', wintypes.WORD),
                ('pixels', ctypes.c_void_p)]


def native_icon_sizes(path):
    user = ctypes.windll.user32
    user.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user.LoadImageW.restype = ctypes.c_void_p
    for size in SIZES:
        handle = user.LoadImageW(None, str(path), 1, size, size, 0x10)
        assert handle, (size, ctypes.get_last_error())
        info = IconInfo()
        try:
            assert user.GetIconInfo(ctypes.c_void_p(handle), ctypes.byref(info))
            bitmap = Bitmap()
            assert ctypes.windll.gdi32.GetObjectW(ctypes.c_void_p(info.color), ctypes.sizeof(bitmap), ctypes.byref(bitmap))
            assert (bitmap.width, bitmap.height) == (size, size)
        finally:
            for bitmap_handle in (info.color, info.mask):
                if bitmap_handle:
                    ctypes.windll.gdi32.DeleteObject(ctypes.c_void_p(bitmap_handle))
            user.DestroyIcon(ctypes.c_void_p(handle))


def exe_icon_sizes(executable):
    kernel = ctypes.windll.kernel32
    kernel.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = ctypes.c_void_p
    kernel.FindResourceW.restype = ctypes.c_void_p
    kernel.LoadResource.restype = ctypes.c_void_p
    kernel.LockResource.restype = ctypes.c_void_p
    module = kernel.LoadLibraryExW(str(executable), None, 0x22)
    assert module
    names = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)

    def receive(_module, _type, name, _data):
        names.append(name if name < 65536 else ctypes.wstring_at(name))
        return True

    try:
        assert kernel.EnumResourceNamesW(ctypes.c_void_p(module), ctypes.c_void_p(14), callback_type(receive), 0)
        groups = []
        for name in names:
            native_name = ctypes.c_void_p(name) if isinstance(name, int) else ctypes.c_wchar_p(name)
            resource = kernel.FindResourceW(ctypes.c_void_p(module), native_name, ctypes.c_void_p(14))
            assert resource
            count = kernel.SizeofResource(ctypes.c_void_p(module), ctypes.c_void_p(resource))
            loaded = kernel.LoadResource(ctypes.c_void_p(module), ctypes.c_void_p(resource))
            pointer = kernel.LockResource(ctypes.c_void_p(loaded))
            data = ctypes.string_at(pointer, count)
            _, _, entries = struct.unpack_from('<HHH', data)
            groups.append({data[6 + i * 14] or 256 for i in range(entries)})
        return groups
    finally:
        kernel.FreeLibrary(ctypes.c_void_p(module))


def run(executable=None, installer=None):
    application = QApplication(sys.argv)
    source = QImage(str(ROOT / '图片1.png'))
    assert source.size() == QSize(1024, 1024) and source.hasAlphaChannel()
    assert source.pixelColor(0, 0).alpha() == 0
    assert source.pixelColor(512, 512).alpha() == 255
    old = symbol_fraction(QImage(str(ROOT / 'design/app-icon/original.png')))
    current = symbol_fraction(source)
    assert all(new > previous * 1.15 for new, previous in zip(current, old)), (old, current)
    print('PASS - Icon remains transparent and its visible mark is larger: %.1f%% -> %.1f%% of canvas height' %
          (old[1] * 100, current[1] * 100), flush=True)

    path = ROOT / '图片1.ico'
    data = path.read_bytes()
    _, kind, count = struct.unpack_from('<HHH', data)
    assert kind == 1 and count == len(SIZES)
    for index, size in enumerate(SIZES):
        w, h, _, _, planes, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
        assert (w or 256, h or 256, planes, bits) == (size, size, 1, 32)
        image = QImage.fromData(data[offset:offset + length], 'PNG')
        assert image.size() == QSize(size, size) and image.hasAlphaChannel()
        assert image.pixelColor(0, 0).alpha() == 0
    icon = QIcon(str(path))
    assert not icon.isNull() and {size.width() for size in icon.availableSizes()} == set(SIZES)
    assert all(not icon.pixmap(size, size).isNull() for size in SIZES)
    native_icon_sizes(path)
    print('PASS - Qt and Windows load all ten square ICO sizes with transparent corners', flush=True)

    if executable:
        assert set(SIZES) in exe_icon_sizes(executable)
        assert (executable.parent / '_internal/图片1.ico').read_bytes() == data
        print('PASS - Native EXE icon resources and the packaged window icon use the new multi-size icon', flush=True)
    if installer:
        assert set(SIZES) in exe_icon_sizes(installer)
        print('PASS - The setup executable embeds the same ten icon sizes', flush=True)
    print('ICON_ASSETS: PASSED', flush=True)


if __name__ == '__main__':
    run(*[Path(value).resolve() for value in sys.argv[1:]])
