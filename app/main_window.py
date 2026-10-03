# -*- coding: utf-8 -*-
"""主窗口：侧栏管理多个文档，每个文档使用独立的 Vditor 编辑器。"""
from .i18n import t, language, install_qt_language, translate_widgets, translate_context_menu, _TRANSLATIONS
import json
import os
import shutil
import ctypes
import uuid
import base64
import re
import weakref
import time
from urllib.parse import quote, unquote

from PySide6.QtCore import (
    QByteArray, QEvent, QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    QRect, QSettings, QSize, QTimer, QUrl, Qt, Signal, QBuffer, QIODevice)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QImageReader, QKeySequence, QPainter, QPixmap, QRegion
from PySide6.QtSvg import QSvgRenderer
from shiboken6 import isValid
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QTabBar, QTabWidget,
    QAbstractItemView, QSizePolicy, QToolButton, QToolTip, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QSplitter, QVBoxLayout, QWidget)

from .bridge import Bridge
from .exporter import ExportError, export_docx, find_pandoc, pandoc_version
from .workspace_store import WorkspaceStore, atomic_write
from .recovery_dialog import RecoveryDialog
from .unsaved_dialog import UnsavedChangesDialog
from .export_dialog import ExportSuccessDialog
from .project_explorer import ProjectExplorer, TEXT_EXTENSIONS
from .file_notice import FileNotice

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
INDEX_PATH = os.path.join(ASSETS_DIR, "index.html")
# Reading tabs can be rebuilt from their in-memory source. Edited tabs retain
# their live editor and undo history, so this is a soft limit across all windows.
READING_EDITOR_CACHE = 3
RESIZE_BORDER = 6
RESIZE_CORNER = 16
WORKSPACE_FOOTER_HEIGHT = 36

_DEBUG = os.environ.get("MDVIEW_DEBUG") == "1"


class _Page(QWebEnginePage):
    """调试模式下把 JS 控制台消息转发到 stdout。"""

    def javaScriptConsoleMessage(self, level, message, line, source):
        if _DEBUG:
            print(f"[CONSOLE:{level}] {os.path.basename(source)}:{line} {message}",
                  flush=True)


class _EditorView(QWebEngineView):
    def childEvent(self, event):
        super().childEvent(event)
        # WebEngine can attach its rendering widget after the view is shown.
        # Keep the native notice above that late-arriving child as well.
        if (event.added() or event.polished()) and getattr(self, "file_notice", None) is not None:
            QTimer.singleShot(0, self, self._place_file_notice)

    def _place_file_notice(self):
        notice = getattr(self, "file_notice", None)
        if notice is not None and not notice.isHidden():
            notice.setGeometry(self.rect())
            notice.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_file_notice()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_file_notice()

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        translate_context_menu(menu)
        menu.addSeparator()
        comment = menu.addAction(t("添加批注…"))
        comment.setObjectName("addReviewComment")
        comment.setToolTip(t("为选中的正文添加批注"))
        comment.setEnabled(False)
        request = self.lastContextMenuRequest()
        position = event.globalPos()

        def show_menu(enabled):
            if not isValid(self) or not isValid(menu):
                return
            comment.setEnabled(bool(enabled))
            chosen = menu.exec(position)
            if chosen == comment:
                self.page().runJavaScript("window.addReviewComment()")
            menu.deleteLater()

        # WebEngine pauses JavaScript while its native context menu is open.
        # Validate the body selection first, then show the complete menu.
        if request and request.isContentEditable() and request.selectedText().strip():
            self.page().runJavaScript(
                "!!window.canAddReviewComment && window.canAddReviewComment()", show_menu)
        else:
            show_menu(False)


class _Workspace(QWidget):
    """Extend each surface into the reserved window resize edges."""

    def __init__(self, parent):
        super().__init__(parent)
        self.sidebar = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.set_colors("#ffffff", "#f5f5f2", "#e7e7e2")

    def set_colors(self, canvas, panel, border):
        self.canvas_color = QColor(canvas)
        self.panel_color = QColor(panel)
        self.border_color = QColor(border)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.canvas_color)
        if self.sidebar is not None and not self.sidebar.isHidden():
            boundary = self.sidebar.geometry().right()
            painter.fillRect(0, 0, boundary, self.height(), self.panel_color)
            painter.fillRect(boundary, 0, 1, self.height(), self.border_color)


class _EditorStatusBar(QWidget):
    """Keep the footer in Qt's layout, independent of WebEngine resize frames."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorStatusBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(WORKSPACE_FOOTER_HEIGHT)
        self._unavailable = False
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(12)
        self.counter = QToolButton(self)
        self.counter.setObjectName("wordCounter")
        # A mouse click must keep the editor selection for selected-word stats.
        self.counter.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.counter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.counter.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.counter.setMinimumWidth(1)
        self.counter.setFixedHeight(26)
        self.divider = QLabel("/", self)
        self.mode = QLabel(self)
        self.format = QLabel("UTF-8   ·   Markdown", self)
        self.zoom = QToolButton(self)
        self.zoom.setObjectName("pageZoom")
        self.zoom.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.zoom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom.setFixedHeight(26)
        self.zoom.setMinimumWidth(46)
        row.addWidget(self.counter)
        row.addWidget(self.divider)
        row.addWidget(self.mode)
        row.addStretch(1)
        row.addWidget(self.format)
        row.addWidget(self.zoom)
        self.set_document_status((0, -1, "ir"))
        self.set_zoom(1.0)

    def set_zoom(self, factor):
        percent = round(factor * 100)
        self.zoom.setText(f"{percent}%")
        self.zoom.setAccessibleName(t(f"页面缩放：{percent}%"))
        self.zoom.setToolTip(t(f"页面缩放：{percent}% · 点击恢复 100%（Ctrl+0）"))

    def set_document_status(self, status):
        total, selected, mode = status
        text = t(f"选中 {selected} / 全文 {total}") if selected >= 0 else t(f"字数 {total}")
        self.counter.setText(text)
        self.counter.setToolTip(t("查看文字统计"))
        self.mode.setText(t({"ir": "即时渲染", "sv": "源代码", "wysiwyg": "所见即所得"}.get(mode, "即时渲染")))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_visibility()

    def set_unavailable(self, unavailable):
        self._unavailable = unavailable
        if unavailable:
            self.mode.setText(t("无法预览"))
        self._update_visibility()

    def _update_visibility(self):
        self.counter.setVisible(not self._unavailable)
        self.zoom.setVisible(not self._unavailable)
        self.format.setVisible(not self._unavailable and self.width() >= 640)
        self.divider.setVisible(not self._unavailable and self.width() >= 420)
        self.mode.setVisible(self._unavailable or self.width() >= 420)


class _DetachableTabBar(QTabBar):
    """将标签拖出标签栏时通知主窗口创建独立窗口。"""

    tabDetached = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_index = -1
        self._drag_start = None
        self._drag_start_global = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_index = self.tabAt(event.position().toPoint())
            self._drag_start = event.position().toPoint()
            self._drag_start_global = event.globalPosition().toPoint()
        super().mousePressEvent(event)
        if self._drag_index >= 0:
            QApplication.instance().installEventFilter(self)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._stop_drag_tracking()
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        if self._drag_index < 0:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._stop_drag_tracking()
            return super().eventFilter(watched, event)
        if (event.type() != QEvent.Type.MouseMove
                or not event.buttons() & Qt.MouseButton.LeftButton):
            return super().eventFilter(watched, event)
        global_pos = event.globalPosition().toPoint()
        moved_far_enough = (global_pos - self._drag_start_global).manhattanLength() >= QApplication.startDragDistance()
        outside_tab_bar = not self.rect().contains(self.mapFromGlobal(global_pos))
        if moved_far_enough and outside_tab_bar:
            index = self._drag_index
            self._stop_drag_tracking()
            self.tabDetached.emit(index, global_pos)
            return True
        return super().eventFilter(watched, event)

    def _stop_drag_tracking(self):
        QApplication.instance().removeEventFilter(self)
        self._drag_index = -1
        self._drag_start = None
        self._drag_start_global = None


class _DocumentList(QListWidget):
    """侧栏内拖拽排序，拖出窗口后分离文档。"""

    documentMoved = Signal(int, int)
    documentDetached = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_tab = None
        self._dragging = False
        self._drag_preview = None

    def mousePressEvent(self, event):
        self.cancel_drag()
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            row = self.itemWidget(item) if item else None
            if row is not None:
                self._drag_tab = row.tab
                self._press_position = event.globalPosition().toPoint()
                QApplication.instance().installEventFilter(self)

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        if self._drag_tab is None:
            event.accept()
            return
        position = event.globalPosition().toPoint()
        if not self._dragging and (position - self._press_position).manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            preview = QLabel(self._drag_tab.display_name(), self.window(), Qt.WindowType.ToolTip)
            preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            preview.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            dark = self.window()._theme == "dark"
            preview.setStyleSheet(
                "QLabel { padding: 8px 12px; border-radius: 6px; border: 1px solid %s; background: %s; color: %s; }" %
                ("#484844" if dark else "#dcdcd6", "#30302d" if dark else "#f7f7f4", "#e9e9e5" if dark else "#292926"))
            preview.adjustSize()
            self._drag_preview = preview
        if self._drag_preview is not None:
            self._drag_preview.move(position + QPoint(14, 18))
            self._drag_preview.show()
        event.accept()

    def mouseReleaseEvent(self, event):
        tab, dragging = self._drag_tab, self._dragging
        position = event.globalPosition().toPoint()
        window = self.window()
        self.cancel_drag()
        super().mouseReleaseEvent(event)
        if (event.button() != Qt.MouseButton.LeftButton or not dragging
                or window._closed or tab not in window._tab_list):
            return
        old = window._tab_list.index(tab)
        if not window.frameGeometry().contains(position):
            self.documentDetached.emit(old, position)
        else:
            local = self.viewport().mapFromGlobal(position)
            if self.viewport().rect().contains(local):
                new = self.indexAt(local).row()
                if new < 0:
                    new = self.count() - 1
                if new != old:
                    self.documentMoved.emit(old, new)

    def cancel_drag(self):
        QApplication.instance().removeEventFilter(self)
        if self._drag_preview is not None:
            self._drag_preview.hide()
            self._drag_preview.deleteLater()
            self._drag_preview = None
        self.viewport().unsetCursor()
        self._drag_tab = None
        self._dragging = False

    def eventFilter(self, watched, event):
        if (self._dragging and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            self.cancel_drag()
            return True
        return super().eventFilter(watched, event)

    def dropEvent(self, event):
        old = self.currentRow()
        blocked = self.blockSignals(True)
        super().dropEvent(event)
        new = self.currentRow()
        self.blockSignals(blocked)
        if event.isAccepted() and old >= 0 and new >= 0 and old != new:
            self.documentMoved.emit(old, new)


class _DocumentName(QLabel):
    """为侧栏关闭按钮留出空间，较长的文件名在中间省略。"""

    def __init__(self, parent):
        super().__init__(parent)
        self._name = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_name(self, name):
        self._name = name
        self.setText(self.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_name(self._name)


class EditorTab:
    """一个编辑器标签页：QWebEngineView + 文件路径 + 脏标记。"""

    def __init__(self, window):
        self.window = window
        self.filepath = None          # 当前 md 文件绝对路径
        self.dirty = False
        self.pending_file = None      # 编辑器就绪后要加载的文件
        self.close_after_save = False
        self.quit_after_save = False
        self.ready = False
        self.draft_id = uuid.uuid4().hex
        self.recovery_origin = None
        self.resource_dir = None
        self.pending_draft = None
        self.scroll_position = 0
        self.revision = 0
        self.file_stamp = None
        self.autosave_paused = False
        self.initialized = False
        self.parked = False
        self.ever_edited = False
        self.cached_content = None
        self.reading_state = None
        self.last_used = 0
        self.cache_pending = False
        self.appearance = None
        self.pending_commands = []
        self.printing = False
        self.document_status = (0, -1, "ir")
        self.file_error = None
        self.file_error_detail = ""
        self.file_notice = None

        self.view = _EditorView()
        self.zoom_factor = 1.0
        self.zoom_wheel_delta = 0
        self.backup_timer = QTimer(self.view)
        self.backup_timer.setSingleShot(True)
        self.backup_timer.setInterval(1000)
        self.backup_timer.timeout.connect(lambda: self.window._checkpoint_tab(self))
        self.view.setPage(_Page(self.view))
        self.view.page().setBackgroundColor(QColor("#20201e" if window._theme == "dark" else "#ffffff"))
        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.channel = QWebChannel(self.view.page())
        self.bridge = Bridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

    def ensure_loaded(self):
        if self.file_error:
            return
        if self.parked:
            self.parked = False
            self.initialized = True
            self.view.page().setLifecycleState(QWebEnginePage.LifecycleState.Active)
        elif not self.initialized:
            self.initialized = True
            self.view.load(QUrl.fromLocalFile(INDEX_PATH))

    def js(self, code):
        if self.file_error:
            return
        if not self.ready:
            self.pending_commands.append(code)
            self.ensure_loaded()
        else:
            self.view.page().runJavaScript(code)

    def show_file_error(self, reason, detail=""):
        self.file_error = reason
        self.file_error_detail = detail
        self.ready = False
        self.pending_file = None
        self.pending_commands.clear()
        self.backup_timer.stop()
        if self.initialized:
            # Failed reads do not need to keep an empty editor and its scripts alive.
            self.view.setUrl(QUrl("about:blank"))
            self.initialized = False
        if self.file_notice is None:
            self.file_notice = FileNotice(self.view)
            self.view.file_notice = self.file_notice
            self.file_notice.retryRequested.connect(lambda: self.window.retry_file(self))
            self.file_notice.closeRequested.connect(
                lambda: self.window.close_tab(self.window.tabs.indexOf(self.view)))
        self.file_notice.show()
        self.view._place_file_notice()
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.window._sync_document_ui(self)
        if self.window.current_tab() is self:
            self.window._refresh_editor_status()

    def display_name(self):
        if self.filepath or self.pending_file:
            return os.path.basename(self.filepath or self.pending_file)
        return t("恢复 - ") + os.path.basename(self.recovery_origin) if self.recovery_origin else t("未命名")

    def file_dir(self):
        return os.path.dirname(self.filepath) if self.filepath else self.resource_dir


class MainWindow(QMainWindow):
    def __init__(self, startup_file=None, create_initial_tab=True, restore_session=False):
        super().__init__()
        self._tab_list = []
        self._detached_windows = set()
        self._was_maximized_before_fullscreen = False
        self._resize_drag_edges = Qt.Edge(0)
        self._resize_drag_start = None
        self._resize_drag_geometry = None
        self._resize_pending_geometry = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._resize_timer.setInterval(16)
        self._resize_timer.timeout.connect(self._apply_pending_resize)
        install_qt_language()
        self._theme = QSettings().value("appearance/theme", "light", type=str)
        self.store = WorkspaceStore.shared()
        self.store.windows.add(self)
        self._closed = False
        self._restoring = True
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(500)
        self._session_timer.timeout.connect(self._persist_session)
        self._activation_timer = QTimer(self)
        self._activation_timer.setSingleShot(True)
        self._activation_timer.timeout.connect(self._activate_current_editor)
        self._resource_timer = QTimer(self)
        self._resource_timer.setSingleShot(True)
        self._resource_timer.setInterval(1500)
        self._resource_timer.timeout.connect(self._trim_reading_editors)

        self.setWindowTitle("MarkdownView")
        self.setWindowIcon(QIcon(os.path.join(
            os.path.dirname(os.path.dirname(ASSETS_DIR)), "图片1.ico")))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        # Native interactive resizing observes the same limits as the fallback.
        self.setMinimumSize(480, 360)
        self._init_geometry()

        self.tabs = QTabWidget(self)
        self.tab_bar = _DetachableTabBar(self.tabs)
        self.tabs.setTabBar(self.tab_bar)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._current_changed)
        self.tab_bar.tabDetached.connect(self.detach_tab)
        self.tab_bar.tabMoved.connect(self._tab_moved)
        self._build_workspace()

        self._build_app_icon()
        self._build_menus()
        self._build_window_controls()
        self._apply_chrome_style()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().messageChanged.connect(
            lambda message: self.statusBar().setVisible(bool(message) and not self.isFullScreen()))
        self.statusBar().hide()
        self._build_resize_handles()
        self.menuBar().installEventFilter(self)
        # Do not wrap WebEngine's internal object/layout events in Python.
        # Resize gestures only involve the handles and this mouse-grabbing window.
        self.installEventFilter(self)

        # 首个标签页（可携带启动文件）
        if create_initial_tab:
            if startup_file and os.path.exists(startup_file):
                self.new_tab(filepath=startup_file)
            elif restore_session and QSettings().value("files/restoreSession", True, type=bool):
                session = self.store.initial_session
                active_tab = None
                for document in session.get("documents", []):
                    path = document.get("path")
                    if path and os.path.isfile(path):
                        tab = self.new_tab(filepath=path)
                        tab.scroll_position = document.get("scroll", 0)
                        if document.get("id") == session.get("active"):
                            active_tab = tab
                if active_tab is not None:
                    self.tabs.setCurrentWidget(active_tab.view)
            if not self._tab_list:
                self.new_tab()
        if restore_session and QSettings().value("files/restoreSession", True, type=bool):
            folder = QSettings().value("files/projectFolder", "", type=str)
            if folder and os.path.isdir(folder):
                self.open_project_folder(folder)
        self._restoring = False
        if restore_session and not self.store.recovery_offered:
            self.store.recovery_offered = True
            QTimer.singleShot(1200, self._offer_recovery)

    # ---------- 窗口几何：普通窗口、居中、约占屏幕 75% ----------
    def _current_changed(self, _index):
        self._update_titles()
        self._refresh_editor_status()
        self._schedule_session()
        # Coalesce intermediate selections during multi-file opening/restoration.
        self._activation_timer.start(0)

    def _activate_current_editor(self):
        if self._closed:
            return
        tab = self.current_tab()
        if tab:
            tab.last_used = time.monotonic()
            tab.ensure_loaded()
        self._resource_timer.start()

    def _loaded_tabs(self):
        return [tab for window in self.store.windows if not window._closed
                for tab in window._tab_list if tab.initialized and not tab.parked and not tab.file_error]

    def _trim_reading_editors(self):
        if self._closed:
            return
        loaded = self._loaded_tabs()
        excess = len(loaded) - READING_EDITOR_CACHE
        if excess <= 0:
            return
        candidates = sorted((tab for tab in loaded
                             if tab.ready and tab.cached_content is not None
                             and not tab.ever_edited and not tab.dirty
                             and not tab.pending_commands and not tab.cache_pending and not tab.printing
                             and tab.window.current_tab() is not tab
                             and not tab.view.page().isLoading()
                             and not tab.view.page().isVisible()), key=lambda tab: tab.last_used)
        for tab in candidates[:excess]:
            tab.cache_pending = True

            def received(value, tab=tab):
                tab.cache_pending = False
                window = tab.window
                if (window._closed or tab not in window._tab_list or not tab.ready
                        or tab.ever_edited or tab.dirty or tab.pending_commands or tab.printing
                        or window.current_tab() is tab or tab.view.page().isVisible()
                        or len(self._loaded_tabs()) <= READING_EDITOR_CACHE):
                    return
                try:
                    state = json.loads(value) if isinstance(value, str) else None
                except ValueError:
                    return
                if not isinstance(state, dict):
                    return  # Find/format panels or printing still need the live page.
                page = tab.view.page()
                page.setLifecycleState(QWebEnginePage.LifecycleState.Discarded)
                if page.lifecycleState() == QWebEnginePage.LifecycleState.Discarded:
                    tab.reading_state = state
                    tab.scroll_position = state.get("scroll", tab.scroll_position)
                    tab.parked = True
                    tab.ready = False
                    tab.appearance = None
                    window._schedule_session()

            tab.view.page().runJavaScript("JSON.stringify(window.readingStateForCache())", received)

    def _schedule_session(self):
        if not self._restoring and not self._closed and not self._session_timer.isActive():
            self._session_timer.start()

    def _persist_session(self, exclude_self=False):
        windows = [window for window in self.store.windows if not window._closed
                   and not (exclude_self and window is self)]
        documents = []
        for window in windows:
            for tab in window._tab_list:
                path = tab.filepath or tab.pending_file
                if path or tab.dirty or tab.pending_draft:
                    documents.append({"id": tab.draft_id, "path": path, "scroll": tab.scroll_position})
        active = self.current_tab()
        if exclude_self and windows:
            active = windows[0].current_tab()
        try:
            self.store.write_session(documents, active.draft_id if active else None)
        except OSError as error:
            self.statusBar().showMessage(t(f"无法保存上次会话：{error}"), 6000)

    @staticmethod
    def _file_stamp(path):
        try:
            stat = os.stat(path)
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _checkpoint_tab(self, tab):
        if tab not in self._tab_list or not tab.ready or not tab.dirty or self._closed:
            return
        revision = tab.revision

        def received(content):
            if tab not in self._tab_list or not tab.dirty or self._closed:
                return
            if tab.revision != revision:
                tab.backup_timer.start()
                return
            if not isinstance(content, str):
                return
            try:
                self.store.write_draft(tab, content)
            except OSError as error:
                self.statusBar().showMessage(t(f"草稿备份失败：{error}"), 8000)
                tab.backup_timer.start(5000)
                return
            self._schedule_session()
            if (self._autosave_action.isChecked() and tab.filepath
                    and not tab.autosave_paused):
                if self._file_stamp(tab.filepath) != tab.file_stamp:
                    tab.autosave_paused = True
                    self.statusBar().showMessage(t("文件已在外部修改，自动保存已暂停；当前内容已备份为草稿。"), 8000)
                else:
                    self.save_file(tab, content, automatic=True)

        tab.view.page().runJavaScript("window.currentMarkdown()", received)

    def _remove_draft(self, tab, remove_assets=False):
        try:
            self.store.remove_draft(tab.draft_id)
            if remove_assets:
                self.store.remove_assets(tab.draft_id)
        except OSError as error:
            self.statusBar().showMessage(t(f"无法清理草稿备份：{error}"), 6000)

    def _toggle_autosave(self, enabled):
        QSettings().setValue("files/autoSave", enabled)
        for window in self.store.windows:
            if window._closed:
                continue
            window._autosave_action.blockSignals(True)
            window._autosave_action.setChecked(enabled)
            window._autosave_action.blockSignals(False)
            for tab in window._tab_list:
                tab.autosave_paused = False
                if tab.ready and tab.dirty:
                    tab.backup_timer.start()

    def _remember_file(self, path):
        try:
            self.store.remember_file(path)
        except OSError as error:
            self.statusBar().showMessage(t(f"无法记录最近文档：{error}"), 6000)

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        paths = self.store.recent_files()
        if not paths:
            self._recent_menu.addAction(t("没有最近打开的文档")).setEnabled(False)
            return
        for path in paths:
            action = self._recent_menu.addAction(os.path.basename(path).replace("&", "&&"))
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_file(p))
        self._recent_menu.addSeparator()
        self._recent_menu.addAction(t("清空最近记录"), self._clear_recent)

    def _clear_recent(self):
        try:
            self.store.clear_recent()
        except OSError as error:
            self.statusBar().showMessage(t(f"无法清空最近记录：{error}"), 6000)

    def open_file(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            QMessageBox.warning(self, t("打开失败"), t(f"文件不存在或已被移动：\n{path}"))
            return
        for window in self.store.windows:
            for tab in window._tab_list:
                existing = tab.filepath or tab.pending_file
                if not window._closed and existing and os.path.normcase(existing) == os.path.normcase(path):
                    window.tabs.setCurrentWidget(tab.view)
                    window.bring_to_front()
                    self._remember_file(path)
                    return tab
        return self.new_tab(filepath=path)

    def bring_to_front(self):
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _offer_recovery(self):
        if not self._closed and self._available_drafts():
            self.show_recovery_dialog()

    def _available_drafts(self):
        active_ids = {tab.draft_id for window in self.store.windows
                      if not window._closed for tab in window._tab_list if tab.dirty or tab.pending_draft}
        return [record for record in self.store.drafts() if record["id"] not in active_ids]

    def show_recovery_dialog(self):
        if getattr(self, "_recovery_dialog", None):
            self._recovery_dialog.raise_()
            self._recovery_dialog.activateWindow()
            return
        dialog = RecoveryDialog(self, self._available_drafts())
        self._recovery_dialog = dialog
        dialog.destroyed.connect(lambda *_: setattr(self, "_recovery_dialog", None))
        dialog.show()

    def restore_draft(self, record):
        tab = self.new_tab()
        tab.draft_id = record["id"]
        tab.pending_draft = record
        tab.recovery_origin = record.get("path") or record.get("origin")
        tab.resource_dir = record.get("resource_dir")
        tab.scroll_position = record.get("scroll", 0)
        self._update_titles()
        return tab

    def report_position(self, tab, position):
        tab.scroll_position = max(0, position)
        self._schedule_session()

    def _init_geometry(self):
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = min(1440, int(geo.width() * 0.75))
            h = min(940, int(geo.height() * 0.8))
            self.resize(w, h)
            self.move(geo.x() + (geo.width() - w) // 2,
                      geo.y() + (geo.height() - h) // 2)
        else:
            self.resize(1200, 800)
        self.showNormal()

    # ---------- 菜单 ----------
    def _ui_icon(self, name, color=None):
        """与编辑区一致的细线图标；不依赖系统图标主题。"""
        paths = {
            "new": '<path d="M12 5v14M5 12h14"/>',
            "project": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M8 13h8M12 9v8"/>',
            "collapse": '<path d="M8 3h11a2 2 0 0 1 2 2v11M5 7h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2ZM7 14h6"/>',
            "close": '<path d="m6 6 12 12M18 6 6 18"/>',
            "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
            "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
            "sidebar": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
            "moon": '<path d="M20.5 13A9 9 0 0 1 11 3.5 9 9 0 1 0 20.5 13Z"/>',
            "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
        }
        color = color or ("#c5c5c0" if self._theme == "dark" else "#66665f")
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'fill="none" stroke="{color}" stroke-width="1.6" '
               f'stroke-linecap="round" stroke-linejoin="round">{paths[name]}</svg>')
        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
        painter.end()
        return QIcon(pixmap)

    def _build_workspace(self):
        workspace = _Workspace(self)
        workspace.setMouseTracking(True)
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(RESIZE_BORDER, 0, RESIZE_BORDER, RESIZE_BORDER)
        layout.setSpacing(0)
        self.sidebar = QWidget(workspace)
        workspace.sidebar = self.sidebar
        self.sidebar.setObjectName("workspaceSidebar")
        self.sidebar.setFixedWidth(216)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 16, 14, 0)
        side.setSpacing(6)

        brand = QLabel("MarkdownView")
        brand.setObjectName("workspaceBrand")
        brand_row = QHBoxLayout()
        brand_row.setSpacing(4)
        brand_row.addWidget(brand, 1)
        self._sidebar_collapse_button = QToolButton(self.sidebar)
        self._sidebar_collapse_button.setObjectName("sidebarCollapse")
        self._sidebar_collapse_button.setText(t("收起"))
        self._sidebar_collapse_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._sidebar_collapse_button.setIconSize(QSize(14, 14))
        self._sidebar_collapse_button.setFixedSize(52, 28)
        self._sidebar_collapse_button.setToolTip(t("隐藏侧边栏 · Ctrl+\\"))
        self._sidebar_collapse_button.setAccessibleName(t("隐藏侧边栏"))
        self._sidebar_collapse_button.clicked.connect(
            lambda: self._sidebar_action.setChecked(False))
        brand_row.addWidget(self._sidebar_collapse_button)
        side.addLayout(brand_row)
        side.addSpacing(12)
        self._sidebar_buttons = {}
        for key, text, callback, tip in (
                ("new", t("新建文档"), lambda: self.new_tab(), t("新建文档 · Ctrl+T")),
                ("folder", t("打开文件"), self.open_file_dialog, t("打开文件 · Ctrl+O")),
                ("project", t("打开文件夹"), self.open_project_dialog, t("打开项目文件夹 · Ctrl+Shift+O"))):
            button = QToolButton(self.sidebar)
            button.setObjectName("sidebarAction")
            button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIconSize(QSize(18, 18))
            button.setFixedHeight(36)
            button.setMinimumWidth(188)
            button.clicked.connect(callback)
            button.setToolTip(tip)
            self._sidebar_buttons[key] = button
            side.addWidget(button)
        side.addSpacing(12)
        self._sidebar_sections = QSplitter(Qt.Orientation.Vertical, self.sidebar)
        self._sidebar_sections.setObjectName("sidebarSections")
        self._sidebar_sections.setChildrenCollapsible(False)
        self._sidebar_sections.setHandleWidth(6)
        opened_section = QWidget(self._sidebar_sections)
        opened_layout = QVBoxLayout(opened_section)
        opened_layout.setContentsMargins(0, 0, 0, 0)
        opened_layout.setSpacing(5)
        heading = QHBoxLayout()
        documents_label = QLabel(t("打开的文档"))
        documents_label.setObjectName("sectionCaption")
        self._document_count = QLabel("0")
        self._document_count.setObjectName("documentCount")
        heading.addWidget(documents_label)
        heading.addStretch()
        heading.addWidget(self._document_count)
        opened_layout.addLayout(heading)
        self.document_list = _DocumentList(self.sidebar)
        self.document_list.setObjectName("documentList")
        self.document_list.setIconSize(QSize(16, 16))
        self.document_list.setSpacing(3)
        self.document_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.document_list.setMinimumHeight(0)
        self.document_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.document_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.document_list.documentMoved.connect(self.tab_bar.moveTab)
        self.document_list.documentDetached.connect(self.detach_tab)
        self.document_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.document_list.customContextMenuRequested.connect(self._show_document_context_menu)
        self.document_list.currentRowChanged.connect(
            lambda row: self.tabs.setCurrentIndex(row) if row >= 0 else None)
        opened_layout.addWidget(self.document_list, 1)
        self._sidebar_sections.addWidget(opened_section)
        self.project_explorer = ProjectExplorer(self._sidebar_sections)
        self.project_explorer.fileRequested.connect(self.open_file)
        self.project_explorer.closeRequested.connect(self.close_project_folder)
        self._sidebar_sections.addWidget(self.project_explorer)
        self._sidebar_sections.setStretchFactor(0, 0)
        self._sidebar_sections.setStretchFactor(1, 1)
        self.project_explorer.hide()
        side.addWidget(self._sidebar_sections, 1)

        self._theme_button = QToolButton(self.sidebar)
        self._theme_button.setObjectName("themeAction")
        self._theme_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._theme_button.setIconSize(QSize(18, 18))
        self._theme_button.setFixedSize(188, WORKSPACE_FOOTER_HEIGHT)
        self._theme_button.clicked.connect(self.toggle_theme)
        side.addWidget(self._theme_button)
        layout.addWidget(self.sidebar)
        editor_column = QVBoxLayout()
        editor_column.setContentsMargins(0, 0, 0, 0)
        editor_column.setSpacing(0)
        editor_column.addWidget(self.tabs, 1)
        self.editor_status = _EditorStatusBar(workspace)
        self.editor_status.counter.clicked.connect(
            lambda: self._cur_js("window.showStatsDialog()"))
        self.editor_status.zoom.clicked.connect(lambda: self.set_page_zoom(1.0))
        editor_column.addWidget(self.editor_status)
        layout.addLayout(editor_column, 1)
        self.setCentralWidget(workspace)

        self.tab_bar.hide()

    def _apply_chrome_style(self):
        """原生窗口和网页共用浅暖灰 / 炭灰配色。"""
        dark = self._theme == "dark"
        bg, panel, text, muted, border, hover, selected = (
            ("#20201e", "#181816", "#efefeb", "#9b9b93", "#333330", "#30302c", "#393933")
            if dark else
            ("#ffffff", "#f5f5f2", "#272724", "#83837b", "#e7e7e2", "#ebebe6", "#e6e6df"))
        self.centralWidget().set_colors(bg, panel, border)
        self.setStyleSheet(f"""
            QWidget {{ color: {text}; font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 12px; }}
            QMainWindow {{ background: {bg}; }}
            QMenuBar {{ background: {panel}; border: 0; padding: 0 8px; }}
            QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: 5px; }}
            QMenuBar::item:selected {{ background: {hover}; }}
            QMenu {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; padding: 6px; }}
            QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 5px; }}
            QMenu::item:selected {{ background: {hover}; }}
            QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}
            QTabWidget::pane {{ background: {bg}; border: 0; top: 0; }}
            QTabBar {{ background: {panel}; border: 0; }}
            QTabBar::tab {{ background: transparent; color: {muted}; font-size: 11px;
                border: 0; border-radius: 6px; min-height: 18px;
                padding: 3px 4px 3px 12px; margin: 2px 2px; }}
            QTabBar::tab:selected {{ background: {bg}; color: {text}; }}
            QTabBar::tab:hover:!selected {{ background: {hover}; color: {text}; }}
            QToolButton {{ border: 0; background: transparent; border-radius: 6px; padding: 0; }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: {selected}; }}
            QTabBar QToolButton {{ color: {muted}; font-size: 15px; }}
            QMenuBar QToolButton {{ color: {muted}; font-size: 16px; border-radius: 0; }}
            QToolButton[closeButton="true"]:hover {{ background: #c94b4b; color: #ffffff; }}
            QWidget#workspaceSidebar {{ background: {panel}; border-right: 1px solid {border}; }}
            QLabel#workspaceBrand {{ font-size: 17px; font-weight: 600; padding-left: 8px; }}
            QLabel#sectionCaption {{ color: {muted}; padding-left: 8px; font-size: 11px; }}
            QLabel#documentCount {{ color: {muted}; font-size: 10px; padding-right: 8px; }}
            QToolButton#sidebarAction {{ text-align: left; padding: 0 10px; font-size: 12px; }}
            QToolButton#sidebarAction::menu-indicator {{ image: none; }}
            QToolButton#themeAction {{ text-align: left; padding: 0 10px;
                border-top: 1px solid transparent; font-size: 11px; }}
            QWidget#editorStatusBar {{ background: {bg}; border-top: 1px solid {border}; }}
            QWidget#editorStatusBar QLabel, QWidget#editorStatusBar QToolButton {{ color: {muted}; font-size: 11px; }}
            QWidget#editorStatusBar QToolButton {{ padding: 0 7px; border-radius: 5px; }}
            QWidget#editorStatusBar QToolButton:hover {{ color: {text}; }}
            QWidget#fileNotice {{ background: {bg}; }}
            QScrollArea#fileNoticeScroll, QWidget#fileNoticeViewport, QWidget#fileNoticeContent {{ background: {bg}; }}
            QLabel#fileNoticeTitle {{ color: {text}; font-size: 20px; font-weight: 600; }}
            QLabel#fileNoticeName {{ color: {text}; font-size: 13px; }}
            QLabel#fileNoticeDescription {{ color: {muted}; font-size: 12px; }}
            QToolButton#sidebarCollapse {{ color: {muted}; font-size: 10px; }}
            QTreeView#projectTree {{ background: transparent; border: 0; outline: 0; }}
            QTreeView#projectTree::item {{ height: 28px; padding: 0 3px; border-radius: 0; }}
            QTreeView#projectTree::item:selected {{ background: {selected}; color: {text}; }}
            QTreeView#projectTree::item:hover:!selected {{ background: {hover}; }}
            QTreeView#projectTree QScrollBar::handle:vertical {{ border-color: {panel}; }}
            QLabel#projectTitle {{ font-weight: 600; font-size: 11px; }}
            QLabel#projectCount {{ color: {muted}; font-size: 10px; }}
            QSplitter#sidebarSections::handle {{ background: transparent; }}
            QSplitter#sidebarSections::handle:hover {{ background: {border}; }}
            QListWidget#documentList {{ background: transparent; border: 0; outline: 0; }}
            QListWidget#documentList::item {{ padding: 0; border-radius: 6px; color: transparent; }}
            QListWidget#documentList::item:selected {{ background: {selected}; color: transparent; }}
            QListWidget#documentList::item:hover:!selected {{ background: {hover}; color: transparent; }}
            QToolButton#documentClose {{ color: {muted}; font-size: 15px; }}
            QToolTip {{ background: {text}; color: {panel}; border: 0; padding: 6px 9px; }}
            QStatusBar {{ background: {bg}; color: {muted}; border-top: 1px solid {border}; font-size: 10px; }}
            QStatusBar::item {{ border: 0; }}
            QScrollBar:vertical {{ background: transparent; width: 12px; }}
            QScrollBar::handle:vertical {{ background: {muted}; border: 3px solid {bg}; border-radius: 6px; min-height: 24px; }}
            QScrollBar::handle:vertical:hover {{ background: {text}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QMessageBox, QFileDialog {{ background: {bg}; }}
            QPushButton {{ background: {hover}; border: 1px solid {border}; padding: 6px 16px; border-radius: 5px; }}
            QPushButton:hover {{ background: {selected}; }}
        """)
        self.menuBar().setFixedHeight(30)
        self.tab_bar.setFixedHeight(30)
        for name, button in self._sidebar_buttons.items():
            button.setIcon(self._ui_icon(name))
        self._sidebar_collapse_button.setIcon(self._ui_icon("sidebar"))
        self._theme_button.setIcon(self._ui_icon("sun" if dark else "moon"))
        self._theme_button.setText(t("浅色模式") if dark else t("深色模式"))
        self._theme_button.setToolTip(t("切换浅色主题") if dark else t("切换深色主题"))
        self._document_icon = self._ui_icon("file")
        self.project_explorer.set_icons(self._ui_icon, muted)
        for i in range(self.document_list.count()):
            row = self.document_list.itemWidget(self.document_list.item(i))
            if row:
                row.icon_label.setPixmap(self._document_icon.pixmap(16, 16))
        for tab in self._tab_list:
            self._sync_document_ui(tab)

    def toggle_theme(self):
        theme = "light" if self._theme == "dark" else "dark"
        QSettings().setValue("appearance/theme", theme)
        for window in QApplication.topLevelWidgets():
            if isinstance(window, MainWindow):
                window._theme = theme
                window._apply_chrome_style()

    def _toggle_sidebar(self, visible):
        self.sidebar.setVisible(visible)
        self.centralWidget().update()
        QSettings().setValue("appearance/sidebarVisible", visible)
        for tab in self._tab_list:
            self._sync_document_ui(tab)

    def _tab_moved(self, old, new):
        tab = self._tab_list.pop(old)
        self._tab_list.insert(new, tab)
        self._update_titles()
        self._schedule_session()

    def _sync_document_ui(self, tab):
        appearance = (self._theme, self._sidebar_action.isChecked(), language())
        canvas = QColor("#20201e" if self._theme == "dark" else "#ffffff")
        if tab.view.page().backgroundColor() != canvas:
            tab.view.page().setBackgroundColor(canvas)
        if tab.file_error:
            tab.file_notice.refresh(tab.filepath, tab.file_error, tab.file_error_detail, self._ui_icon("file"))
            return
        if tab.ready and tab.appearance != appearance:
            tab.appearance = appearance
            tab.js("window.setAppearance(%s, %s);" % (
                json.dumps(appearance[0]), json.dumps(appearance[1])))
            tab.js("window.setLanguage(%s, %s);" % (json.dumps(appearance[2]), json.dumps(_TRANSLATIONS)))

    def _build_app_icon(self):
        """显示应用图标，并以不可见菜单项为“文件”预留空间。"""
        self._app_icon_action = QAction("\u200a", self)
        self._app_icon_action.setEnabled(False)
        self.menuBar().addAction(self._app_icon_action)
        self._app_icon_button = QToolButton(self.menuBar())
        self._app_icon_button.setIcon(self.windowIcon())
        self._app_icon_button.setIconSize(QSize(20, 20))
        self._app_icon_button.setAutoRaise(True)
        self._app_icon_button.setFixedSize(34, 30)
        self._app_icon_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._app_icon_button.setToolTip("MarkdownView")
        self.menuBar().setCornerWidget(
            self._app_icon_button, Qt.Corner.TopLeftCorner)

    def _build_window_controls(self):
        """将系统窗口操作放入无边框窗口的右上角。"""
        controls = QWidget(self.menuBar())
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for text, tip, callback, close_button in (
                ("−", t("最小化"), self.showMinimized, False),
                ("□", t("最大化 / 还原"), self._toggle_window_maximized, False),
                ("×", t("关闭窗口"), self.close, True)):
            button = QToolButton(controls)
            button.setText(text)
            button.setAutoRaise(True)
            button.setFixedSize(38, 30)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if close_button:
                button.setProperty("closeButton", True)
            button.clicked.connect(callback)
            layout.addWidget(button)
        self._window_controls = controls
        self.menuBar().setCornerWidget(controls, Qt.Corner.TopRightCorner)

    def _toggle_window_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _build_resize_handles(self):
        self._resize_handles = {}
        left, right, top, bottom = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        for edges, cursor in (
                (left, Qt.CursorShape.SizeHorCursor), (right, Qt.CursorShape.SizeHorCursor),
                (top, Qt.CursorShape.SizeVerCursor), (bottom, Qt.CursorShape.SizeVerCursor),
                (top | left, Qt.CursorShape.SizeFDiagCursor), (bottom | right, Qt.CursorShape.SizeFDiagCursor),
                (top | right, Qt.CursorShape.SizeBDiagCursor), (bottom | left, Qt.CursorShape.SizeBDiagCursor)):
            handle = QWidget(self)
            handle.setObjectName("windowResizeHandle")
            handle.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
            handle.setMouseTracking(True)
            handle.setCursor(cursor)
            handle.installEventFilter(self)
            if (edges & (left | right)) and (edges & (top | bottom)):
                # Corner masks never change with the window size.
                border, corner = RESIZE_BORDER, RESIZE_CORNER
                handle.setMask(QRegion(corner - border if edges & right else 0, 0, border, corner)
                               | QRegion(0, corner - border if edges & bottom else 0, corner, border))
            self._resize_handles[handle] = edges
        self._update_resize_handles(visibility=True)

    def _update_resize_handles(self, visibility=False):
        border, corner = RESIZE_BORDER, RESIZE_CORNER
        width, height = self.width(), self.height()
        for handle, edges in getattr(self, "_resize_handles", {}).items():
            horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
            vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
            right, bottom = bool(edges & Qt.Edge.RightEdge), bool(edges & Qt.Edge.BottomEdge)
            if horizontal and vertical:
                handle.setGeometry(width - corner if right else 0, height - corner if bottom else 0, corner, corner)
            elif horizontal:
                handle.setGeometry(width - border if right else 0, corner, border, height - 2 * corner)
            else:
                handle.setGeometry(corner, height - border if bottom else 0, width - 2 * corner, border)
            if visibility:
                handle.setVisible(not self.isMaximized() and not self.isFullScreen())
                handle.raise_()

    def _apply_pending_resize(self):
        geometry = self._resize_pending_geometry
        self._resize_pending_geometry = None
        if geometry is not None and geometry != self.geometry():
            self.setGeometry(geometry)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_resize_handles()

    def event(self, event):
        if event.type() == QEvent.Type.WindowActivate:
            QApplication.instance()._last_document_window = weakref.ref(self)
        # 菜单说明使用气泡，悬停事件不能显示状态栏或清除保存/导出消息。
        if event.type() == QEvent.Type.StatusTip:
            event.accept()
            return True
        return super().event(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.centralWidget():
            border = 0 if self.isMaximized() or self.isFullScreen() else RESIZE_BORDER
            self.centralWidget().layout().setContentsMargins(border, 0, border, border)
            self._update_resize_handles(visibility=True)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and not self._closed):
            tab = self.current_tab()
            if tab and (watched is tab.view or watched is tab.view.focusProxy()):
                tab.zoom_wheel_delta += event.angleDelta().y()
                steps = int(tab.zoom_wheel_delta / 120)
                tab.zoom_wheel_delta -= steps * 120
                if steps:
                    self.step_page_zoom(steps)
                event.accept()
                return True
        if (event.type() == QEvent.Type.KeyPress and isinstance(watched, QWidget)
                and event.matches(QKeySequence.StandardKey.Paste)
                and not self._closed):
            tab = self.current_tab()
            if tab and tab.ready and (watched is tab.view or tab.view.isAncestorOf(watched)):
                mime = QApplication.clipboard().mimeData()
                if mime.hasImage():
                    self._paste_clipboard_image(tab)
                    return True
        if self._resize_drag_edges:
            if (event.type() == QEvent.Type.MouseMove
                    and event.buttons() & Qt.MouseButton.LeftButton):
                delta = (event.globalPosition().toPoint()
                         - self._resize_drag_start)
                self._resize_pending_geometry = self._resized_geometry(
                    self._resize_drag_geometry, self._resize_drag_edges, delta)
                # Keep the latest pointer position; repaint at most once per frame.
                if not self._resize_timer.isActive():
                    self._resize_timer.start()
                return True
            if (event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton):
                self._resize_timer.stop()
                self._resize_pending_geometry = self._resized_geometry(
                    self._resize_drag_geometry, self._resize_drag_edges,
                    event.globalPosition().toPoint() - self._resize_drag_start)
                self._apply_pending_resize()
                self._resize_drag_edges = Qt.Edge(0)
                self._resize_drag_start = None
                self._resize_drag_geometry = None
                self.releaseMouse()
                return True
        if (event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and watched in self._resize_handles
                and not self.isMaximized() and not self.isFullScreen()):
            edges = self._resize_handles[watched]
            handle = self.windowHandle()
            # Let the window manager synchronize pointer movement, geometry and
            # composition. A timer-driven setGeometry loop can visibly trail it.
            if handle and handle.startSystemResize(edges):
                return True
            # Keep manual resizing only for platforms without native support.
            self._resize_drag_edges = edges
            self._resize_drag_start = event.globalPosition().toPoint()
            self._resize_drag_geometry = QRect(self.geometry())
            self.grabMouse(watched.cursor())
            return True
        if (watched is self.menuBar()
                and event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
                and self.menuBar().actionAt(event.position().toPoint()) is None):
            self._toggle_window_maximized()
            return True
        if (watched is self.menuBar()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self.menuBar().actionAt(event.position().toPoint()) is None
                and not self._window_controls.geometry().contains(event.position().toPoint())):
            handle = self.windowHandle()
            if handle:
                handle.startSystemMove()
            return True
        return super().eventFilter(watched, event)

    def _resized_geometry(self, start_geometry, edges, delta):
        """根据起始窗口矩形和鼠标位移计算任意边或角的缩放结果。"""
        left, top = start_geometry.left(), start_geometry.top()
        right, bottom = start_geometry.right(), start_geometry.bottom()
        min_width = max(self.minimumWidth(), 480)
        min_height = max(self.minimumHeight(), 360)
        if edges & Qt.Edge.LeftEdge:
            left = min(left + delta.x(), right - min_width + 1)
        if edges & Qt.Edge.RightEdge:
            right = max(right + delta.x(), left + min_width - 1)
        if edges & Qt.Edge.TopEdge:
            top = min(top + delta.y(), bottom - min_height + 1)
        if edges & Qt.Edge.BottomEdge:
            bottom = max(bottom + delta.y(), top + min_height - 1)
        return QRect(QPoint(left, top), QPoint(right, bottom))

    def showEvent(self, event):
        super().showEvent(event)
        if os.name == "nt":
            corner_preference = ctypes.c_int(3)  # DWMWCP_ROUNDSMALL
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()), 33, ctypes.byref(corner_preference),
                ctypes.sizeof(corner_preference))

    def _build_menus(self):
        self._document_actions = []
        file_menu = self.menuBar().addMenu(t("文件(&F)"))
        self._file_menu = file_menu

        act_new = QAction(t("新建文档(&N)"), self)
        act_new.setShortcut("Ctrl+T")
        act_new.setToolTip(t("新建一个空白 Markdown 文档"))
        act_new.triggered.connect(lambda: self.new_tab())
        file_menu.addAction(act_new)

        act_open = QAction(t("打开(&O)…"), self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.setToolTip(t("打开一个或多个 Markdown 文件，在侧栏切换文档"))
        act_open.triggered.connect(self.open_file_dialog)
        file_menu.addAction(act_open)

        act_folder = QAction(t("打开文件夹…"), self)
        act_folder.setShortcut("Ctrl+Shift+O")
        act_folder.setToolTip(t("在侧栏浏览整个项目文件夹"))
        act_folder.triggered.connect(self.open_project_dialog)
        file_menu.addAction(act_folder)
        self.addAction(act_folder)
        self._close_project_action = file_menu.addAction(t("关闭项目文件夹"), self.close_project_folder)
        self._close_project_action.setEnabled(False)

        self._recent_menu = file_menu.addMenu(t("最近打开"))
        self._recent_menu.setToolTipsVisible(True)
        self._recent_menu.aboutToShow.connect(self._refresh_recent_menu)
        recover_action = file_menu.addAction(t("恢复未保存的草稿…"))
        recover_action.setToolTip(t("查看并恢复未保存的文档草稿"))
        recover_action.triggered.connect(self.show_recovery_dialog)
        file_menu.addSeparator()

        act_save = QAction(t("保存(&S)"), self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.setToolTip(t("保存当前文档"))
        act_save.triggered.connect(
            lambda: self._cur_js("window.requestSave()"))
        file_menu.addAction(act_save)

        act_save_as = QAction(t("另存为(&A)…"), self)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        act_save_as.setToolTip(t("将当前文档保存为新的文件"))
        act_save_as.triggered.connect(
            lambda: self._cur_js("window.requestSaveAs()"))
        file_menu.addAction(act_save_as)

        self._autosave_action = file_menu.addAction(t("自动保存已命名文档"))
        self._autosave_action.setToolTip(t("自动保存已有文件路径的文档；未命名文档仍保留草稿备份"))
        self._autosave_action.setCheckable(True)
        self._autosave_action.setChecked(QSettings().value("files/autoSave", False, type=bool))
        self._autosave_action.toggled.connect(self._toggle_autosave)
        self._restore_session_action = file_menu.addAction(t("启动时恢复上次打开的文档"))
        self._restore_session_action.setToolTip(t("下次启动时恢复已打开的文档及阅读位置"))
        self._restore_session_action.setCheckable(True)
        self._restore_session_action.setChecked(QSettings().value("files/restoreSession", True, type=bool))
        self._restore_session_action.toggled.connect(
            lambda enabled: QSettings().setValue("files/restoreSession", enabled))
        file_menu.addSeparator()

        act_close = QAction(t("关闭文档(&C)"), self)
        act_close.setShortcut("Ctrl+W")
        act_close.setToolTip(t("关闭当前文档（未保存时会提示）"))
        act_close.triggered.connect(
            lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addAction(act_close)

        file_menu.addSeparator()

        act_export = QAction(t("导出为 DOCX(&E)…"), self)
        act_export.setShortcut("Ctrl+E")
        act_export.setToolTip(t("把当前文档导出为 Word（公式/表格转为 Word 原生格式）"))
        act_export.triggered.connect(
            lambda: self._cur_js("window.requestExport()"))
        file_menu.addAction(act_export)

        act_export_pdf = QAction(t("导出为 PDF(&P)…"), self)
        act_export_pdf.setShortcut("Ctrl+Shift+E")
        act_export_pdf.setToolTip(t("将当前文档导出为适合打印与分享的 PDF"))
        act_export_pdf.triggered.connect(
            lambda: self.export_pdf(self.current_tab()))
        file_menu.addAction(act_export_pdf)
        self._document_actions.extend((act_save, act_save_as, act_export, act_export_pdf))

        file_menu.addSeparator()

        act_quit = QAction(t("退出(&Q)"), self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.setToolTip(t("退出程序（未保存的文档会逐个提示）"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        edit_menu = self.menuBar().addMenu(t("编辑(&E)"))
        for label, shortcut, code in (
                (t("查找…"), "Ctrl+F", "window.openFind(false)"),
                (t("替换…"), "Ctrl+H", "window.openFind(true)"),
                (t("下一个匹配"), "F3", "window.findNext(1)"),
                (t("上一个匹配"), "Shift+F3", "window.findNext(-1)")):
            action = edit_menu.addAction(label)
            self._document_actions.append(action)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, js=code: self._cur_js(js))

        edit_menu.addSeparator()
        for label, shortcut, code, tip in (
                (t("添加批注…"), "Ctrl+Alt+M", "window.addReviewComment()", t("为选中的正文添加批注")),
                (t("删除当前批注"), None, "window.deleteReviewComment()", t("删除选中或定位到的批注"))):
            action = edit_menu.addAction(label)
            self._document_actions.append(action)
            action.setToolTip(tip)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, js=code: self._cur_js(js))

        view_menu = self.menuBar().addMenu(t("视图(&V)"))
        self._sidebar_action = QAction(t("显示侧栏"), self)
        self._sidebar_action.setCheckable(True)
        self._sidebar_action.setChecked(QSettings().value(
            "appearance/sidebarVisible", True, type=bool))
        self._sidebar_action.setShortcut("Ctrl+\\")
        self._sidebar_action.toggled.connect(self._toggle_sidebar)
        self.sidebar.setVisible(self._sidebar_action.isChecked())
        view_menu.addAction(self._sidebar_action)
        theme_action = view_menu.addAction(t("切换深浅主题"))
        theme_action.setShortcut("Ctrl+Shift+L")
        theme_action.triggered.connect(self.toggle_theme)

        view_menu.addSeparator()
        for label, shortcuts, callback in (
                ("放大页面", ["Ctrl++", "Ctrl+="], lambda: self.step_page_zoom(1)),
                ("缩小页面", ["Ctrl+-"], lambda: self.step_page_zoom(-1)),
                ("恢复为 100%", ["Ctrl+0"], lambda: self.set_page_zoom(1.0))):
            action = view_menu.addAction(t(label))
            self._document_actions.append(action)
            action.setShortcuts([QKeySequence(shortcut) for shortcut in shortcuts])
            action.triggered.connect(callback)
            # Window shortcuts remain available when fullscreen hides the menu.
            self.addAction(action)

        view_menu.addSeparator()
        for label, code, tip in (
                (t("显示批注"), "window.showReview(true)", t("显示批注面板与正文标记")),
                (t("隐藏批注"), "window.showReview(false)", t("隐藏批注面板与正文标记"))):
            action = view_menu.addAction(label)
            self._document_actions.append(action)
            action.setToolTip(tip)
            action.triggered.connect(lambda _checked=False, js=code: self._cur_js(js))

        settings_menu = self.menuBar().addMenu(t("设置(&S)"))
        language_menu = settings_menu.addMenu(t("语言"))
        self._language_actions = {}
        for code, label in (("zh_CN", "简体中文"), ("en", "English")):
            action = language_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(language() == code)
            action.triggered.connect(lambda _checked=False, code=code: self.set_language(code))
            self._language_actions[code] = action

        help_menu = self.menuBar().addMenu(t("帮助(&H)"))
        act_about = QAction(t("关于(&A)"), self)
        act_about.setToolTip(t("显示版本与导出引擎信息"))
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

        for menu in (file_menu, self._recent_menu, edit_menu, view_menu, settings_menu, language_menu, help_menu):
            menu.setToolTipsVisible(True)
            menu.aboutToHide.connect(QToolTip.hideText)

    def set_language(self, code):
        if code not in ("zh_CN", "en"):
            return
        QSettings().setValue("appearance/language", code)
        install_qt_language()
        for window in self.store.windows:
            if window._closed:
                continue
            translate_widgets(window)
            window.project_explorer.retranslate()
            for value, action in window._language_actions.items():
                action.setChecked(value == code)
            window._update_titles()
            window._refresh_editor_status()
            for tab in window._tab_list:
                window._sync_document_ui(tab)

    def _show_about(self):
        pandoc = find_pandoc()
        ver = pandoc_version(pandoc) if pandoc else t("未安装")
        QMessageBox.about(
            self, t("关于 MarkdownView"),
            t("<b>MarkdownView</b> — 类 Typora 的 Markdown 编辑器<br>"
            "多标签页 · 所见即所得（Vditor IR 模式）· KaTeX 公式渲染<br>"
            f"DOCX 导出引擎：{ver}"))

    # ---------- 标签页管理 ----------
    def new_tab(self, filepath=None):
        tab = EditorTab(self)
        if filepath:
            tab.pending_file = os.path.abspath(filepath)
            tab.filepath = tab.pending_file
            if os.path.splitext(tab.filepath)[1].lower() not in TEXT_EXTENSIONS:
                tab.show_file_error("type")
                self._remember_file(tab.filepath)
        self._tab_list.append(tab)
        index = self.tabs.addTab(tab.view, tab.display_name())
        self.tabs.setCurrentIndex(index)
        self._activation_timer.start(0)
        self._update_titles()
        self._schedule_session()
        return tab

    def _create_document_row(self, item):
        row = QWidget(self.document_list)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(9, 4, 4, 4)
        layout.setSpacing(7)
        row.icon_label = QLabel(row)
        row.icon_label.setFixedSize(16, 16)
        row.icon_label.setPixmap(self._document_icon.pixmap(16, 16))
        row.name_label = _DocumentName(row)
        row.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(row.icon_label)
        layout.addWidget(row.name_label, 1)
        button = QToolButton(row)
        button.setObjectName("documentClose")
        button.setText("×")
        button.setAutoRaise(True)
        button.setFixedSize(22, 22)
        button.setToolTip(t("关闭文档 · Ctrl+W"))
        button.setAccessibleName(t("关闭文档"))
        button.clicked.connect(
            lambda: self.close_tab(self.tabs.indexOf(row.tab.view)))
        row.close_button = button
        layout.addWidget(button)
        item.setSizeHint(QSize(0, 36))
        self.document_list.setItemWidget(item, row)
        return row

    def _show_document_context_menu(self, pos):
        index = self.document_list.indexAt(pos).row()
        if index < 0:
            return
        menu = QMenu(self)
        tab = self._tab_list[index]
        menu.addAction(t("关闭文档"), lambda: self.close_tab(self.tabs.indexOf(tab.view)))
        menu.exec(self.document_list.viewport().mapToGlobal(pos))

    def detach_tab(self, index, global_pos=None):
        """把一个标签页及其编辑器实例转交给新窗口。"""
        if index < 0 or index >= len(self._tab_list):
            return
        tab = self._tab_list.pop(index)
        proxy = tab.view.focusProxy()
        if proxy:
            proxy.removeEventFilter(self)
        self.tabs.removeTab(index)

        window = MainWindow(create_initial_tab=False)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tab.window = window
        if proxy:
            proxy.installEventFilter(window)
        window._tab_list.append(tab)
        new_index = window.tabs.addTab(tab.view, tab.display_name())
        window.tabs.setCurrentIndex(0)
        window._update_titles()
        self._detached_windows.add(window)
        window.destroyed.connect(lambda *_: self._detached_windows.discard(window))

        target_geometry = window.geometry()
        if global_pos is not None:
            target_geometry.moveTopLeft(QPoint(
                global_pos.x() - 80, global_pos.y() - 20))
        start_geometry = QRect(target_geometry)
        start_geometry.setSize(target_geometry.size() * 0.92)
        start_geometry.moveCenter(target_geometry.center())
        window.setGeometry(start_geometry)
        window.setWindowOpacity(0.0)
        window.show()
        animation = QParallelAnimationGroup(window)
        fade = QPropertyAnimation(window, b"windowOpacity", animation)
        fade.setDuration(160)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        grow = QPropertyAnimation(window, b"geometry", animation)
        grow.setDuration(160)
        grow.setStartValue(start_geometry)
        grow.setEndValue(target_geometry)
        grow.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.addAnimation(fade)
        animation.addAnimation(grow)
        window._detach_animation = animation
        animation.start()
        window.raise_()
        window.activateWindow()

        if not self._tab_list:
            self.new_tab()
        self._update_titles()

    def current_tab(self):
        i = self.tabs.currentIndex()
        return self._tab_list[i] if 0 <= i < len(self._tab_list) else None

    def close_tab(self, index):
        if index < 0 or index >= len(self._tab_list):
            return
        tab = self._tab_list[index]
        if tab.dirty:
            ret = UnsavedChangesDialog.ask(self, tab)
            if ret == QMessageBox.StandardButton.Cancel:
                return
            if ret == QMessageBox.StandardButton.Save:
                tab.close_after_save = True
                tab.js("window.requestSave()")
                return
        self._destroy_tab(index)

    def _destroy_tab(self, index):
        tab = self._tab_list.pop(index)
        tab.backup_timer.stop()
        self._remove_draft(tab, remove_assets=True)
        self.tabs.removeTab(index)
        tab.view.setPage(None)
        tab.view.deleteLater()
        if not self._tab_list:
            self.new_tab()  # 始终保留一个标签页
        self._update_titles()
        self._schedule_session()

    def on_editor_ready(self, tab):
        if self._closed or tab not in self._tab_list or tab.file_error:
            return
        tab.ready = True
        tab.js("window.setDocumentZoom(%s);" % json.dumps(tab.zoom_factor))
        proxy = tab.view.focusProxy()
        if proxy:
            proxy.installEventFilter(self)
        if tab.pending_file:
            path = tab.pending_file
            tab.pending_file = None
            self.load_file(tab, path)
            if tab.file_error:
                return
        elif tab.pending_draft:
            record = tab.pending_draft
            tab.pending_draft = None
            self._sync_md_dir(tab)
            tab.js("window.setContent(%s); window.restorePosition(%s); window.notifyEdited();" %
                   (json.dumps(record["content"]), json.dumps(tab.scroll_position)))
        elif tab.cached_content is not None:
            self._sync_md_dir(tab)
            tab.js("window.setContent(%s); window.markClean(); window.restoreReadingState(%s);" %
                   (json.dumps(tab.cached_content), json.dumps(tab.reading_state)))
        else:
            self._sync_md_dir(tab)
        self._sync_document_ui(tab)
        commands, tab.pending_commands = tab.pending_commands, []
        for command in commands:
            tab.js(command)
        self._resource_timer.start()

    # ---------- JS 交互 ----------
    def update_editor_status(self, tab, total, selected, mode):
        if self._closed or tab not in self._tab_list or tab.file_error:
            return
        tab.document_status = (total, selected, mode)
        if tab is self.current_tab():
            self._refresh_editor_status()

    def _refresh_editor_status(self):
        tab = self.current_tab()
        self.editor_status.set_document_status(tab.document_status if tab else (0, -1, "ir"))
        self.editor_status.set_zoom(tab.zoom_factor if tab else 1.0)
        unavailable = bool(tab and tab.file_error)
        self.editor_status.set_unavailable(unavailable)
        for action in self._document_actions:
            action.setEnabled(not unavailable)

    def _apply_document_zoom(self, tab, factor):
        if tab.file_error:
            return
        tab.zoom_factor = max(0.5, min(3.0, factor))
        if tab.ready:
            tab.js("window.setDocumentZoom(%s);" % json.dumps(tab.zoom_factor))
        self.editor_status.set_zoom(tab.zoom_factor)

    def set_page_zoom(self, factor):
        tab = self.current_tab()
        if tab:
            tab.zoom_wheel_delta = 0
            self._apply_document_zoom(tab, factor)

    def step_page_zoom(self, steps):
        tab = self.current_tab()
        if tab:
            percent = round(tab.zoom_factor * 100) + steps * 10
            self._apply_document_zoom(tab, percent / 100)

    def _cur_js(self, code):
        tab = self.current_tab()
        if tab:
            tab.js(code)

    # ---------- 文件操作 ----------
    def load_file(self, tab, path):
        tab.filepath = os.path.abspath(path)
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
            if "\x00" in text:
                raise UnicodeError("Binary content in a text document")
        except UnicodeError as error:
            tab.show_file_error("encoding", str(error))
            return
        except OSError as e:
            tab.show_file_error("read", str(e))
            return
        tab.filepath = os.path.abspath(path)
        tab.file_stamp = self._file_stamp(tab.filepath)
        tab.autosave_paused = False
        tab.cached_content = text
        self._remember_file(tab.filepath)
        tab.js("window.setContent(%s); window.markClean();" % json.dumps(text))
        self._sync_md_dir(tab)
        self.set_dirty(tab, False)
        tab.js("window.restorePosition(%s)" % json.dumps(tab.scroll_position))
        self._schedule_session()

    def retry_file(self, tab):
        if self._closed or tab not in self._tab_list or tab.file_error not in ("read", "encoding"):
            return
        tab.file_error = None
        tab.file_error_detail = ""
        tab.file_notice.hide()
        tab.view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        tab.pending_file = tab.filepath
        tab.initialized = False
        tab.appearance = None
        tab.ensure_loaded()
        if tab is self.current_tab():
            self._refresh_editor_status()

    def open_file_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, t("打开 Markdown 文件"), self.project_explorer.root_path,
            t("Markdown 文件 (*.md *.markdown);;所有文件 (*)"))
        for path in paths:
            self.open_file(path)

    def open_project_dialog(self):
        folder = QFileDialog.getExistingDirectory(
            self, t("打开项目文件夹"), self.project_explorer.root_path or
            QSettings().value("files/projectFolder", "", type=str))
        if folder:
            self.open_project_folder(folder)

    def open_project_folder(self, path):
        if not os.path.isdir(path):
            QMessageBox.warning(self, t("打开失败"), t("文件夹不存在或无法访问：\n{0}").format(path))
            return
        first_open = not self.project_explorer.root_path
        self.project_explorer.set_folder(path)
        self.project_explorer.set_icons(self._ui_icon, "#9b9b93" if self._theme == "dark" else "#83837b")
        self._close_project_action.setEnabled(True)
        self._sidebar_action.setChecked(True)
        if first_open:
            height = self._sidebar_sections.height()
            self._sidebar_sections.setSizes([min(150, height // 3), max(0, height * 2 // 3)])
        QSettings().setValue("files/projectFolder", self.project_explorer.root_path)
        tab = self.current_tab()
        self.project_explorer.reveal_file(tab.filepath if tab else None)

    def close_project_folder(self):
        self.project_explorer.set_folder(None)
        self._close_project_action.setEnabled(False)
        QSettings().remove("files/projectFolder")

    def save_file(self, tab, content, save_as=False, automatic=False):
        if tab.file_error:
            return
        path = tab.filepath
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, t("保存 Markdown 文件"),
                path or tab.recovery_origin or self.project_explorer.root_path,
                t("Markdown 文件 (*.md);;所有文件 (*)"))
            if not path:
                tab.close_after_save = False
                tab.quit_after_save = False
                return
        old_dir = tab.file_dir()
        path = os.path.abspath(path)
        try:
            content = self._relocate_images(content, old_dir, os.path.dirname(path))
            atomic_write(path, content)
        except OSError as e:
            if automatic:
                tab.autosave_paused = True
                self.statusBar().showMessage(t(f"自动保存失败，草稿已备份：{e}"), 8000)
            else:
                QMessageBox.warning(self, t("保存失败"), t(f"无法写入文件：\n{e}"))
            tab.close_after_save = False
            tab.quit_after_save = False
            return
        tab.filepath = os.path.abspath(path)
        tab.file_stamp = self._file_stamp(path)
        tab.autosave_paused = False
        if old_dir and os.path.normcase(old_dir) != os.path.normcase(os.path.dirname(path)):
            tab.js("window.applySavedContent(%s)" % json.dumps(content))
        else:
            tab.js("window.markCleanIfUnchanged(%s)" % json.dumps(content))
        self._sync_md_dir(tab)
        self.set_dirty(tab, False)
        self._remove_draft(tab)
        self._remember_file(path)
        self._schedule_session()
        if not automatic:
            self.statusBar().showMessage(t(f"已保存：{tab.filepath}"), 4000)
        # 保存后的挂起动作
        if tab.close_after_save:
            tab.close_after_save = False
            if tab in self._tab_list:
                self._destroy_tab(self._tab_list.index(tab))
        if tab.quit_after_save:
            tab.quit_after_save = False
            self.close()

    def export_docx(self, tab, content):
        if tab.file_error:
            return
        default = self._export_default_path(tab, "docx")
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出为 DOCX"), default, t("Word 文档 (*.docx)"))
        if not path:
            return
        try:
            warnings = export_docx(
                content, path,
                resource_dir=tab.file_dir())
        except ExportError as e:
            QMessageBox.critical(self, t("导出失败"), str(e))
            return
        self._remember_export_directory(path)
        self.statusBar().showMessage(t(f"已导出：{path}"), 5000)
        ExportSuccessDialog.show_result(self, path, warnings)

    def export_pdf(self, tab):
        if not tab or tab.file_error:
            return
        if getattr(self, "_pdf_export_in_progress", False):
            self.statusBar().showMessage(t("PDF 正在导出，请稍候…"), 3000)
            return
        default = self._export_default_path(tab, "pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出为 PDF"), default, t("PDF 文档 (*.pdf)"))
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._pdf_export_in_progress = True
        self.statusBar().showMessage(t("正在导出 PDF…"))
        self._export_pdf_to_path(
            tab, path,
            lambda success, error=None: self._finish_pdf_export(path, success, error))

    def _export_pdf_to_path(self, tab, path, finished):
        """先生成临时 PDF，成功后再替换目标，避免已有文件导致打印失败。"""
        if tab.file_error:
            finished(False, t("无法读取文件"))
            return
        target_path = os.path.abspath(path)
        target_dir = os.path.dirname(target_path)
        temporary_path = os.path.join(
            target_dir, f".mdview-{uuid.uuid4().hex}.pdf")

        def discard_temporary_file():
            try:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                pass

        def printed(success):
            generated = (
                success
                and os.path.isfile(temporary_path)
                and os.path.getsize(temporary_path) > 0
            )
            if not generated:
                discard_temporary_file()
                finished(False, t("PDF 引擎未能生成文件，请确认导出目录可写后重试。"))
                return

            try:
                os.replace(temporary_path, target_path)
            except PermissionError:
                discard_temporary_file()
                finished(
                    False,
                    t("无法覆盖目标文件。该 PDF 可能正在阅读器中打开，"
                    "请关闭后重新导出。"))
                return
            except OSError as error:
                discard_temporary_file()
                finished(False, t(f"无法保存到目标位置：\n{error}"))
                return

            finished(True, None)

        self._print_pdf(tab, temporary_path, printed)

    def _print_pdf(self, tab, path, finished):
        """打印当前 Vditor 文档内容，临时隐藏编辑器控件。"""
        tab.printing = True
        page = tab.view.page()
        print_style = """
          @page { size: A4; margin: 12mm; }
          html, body { display: block !important; height: auto !important; overflow: visible !important;
                       background: white !important; }
          html[data-theme="dark"] { --canvas: white; --surface: #f8f8f5; --text: #222;
              --muted: #666; --line: #e0e0dc; --code: #f4f4ef; color-scheme: light; }
          #vditor { display: block !important; width: 100% !important; height: auto !important;
                     overflow: visible !important; position: static !important; }
          #vditor .vditor-content { display: block !important; width: 100% !important;
                                     height: auto !important; overflow: visible !important; margin-right: 0 !important; }
          #vditor .vditor-ir, #vditor .vditor-ir > pre { display: block !important;
              width: 100% !important; height: auto !important; min-height: 0 !important;
              overflow: visible !important; flex: none !important; box-sizing: border-box !important; }
          #vditor .vditor-ir > pre { padding: 10px 15.75% !important; }
          #vditor .vditor-ir__preview { overflow: visible !important; }
          #vditor .vditor-outline, #vditor .vditor-wysiwyg, #vditor .vditor-sv,
          #vditor .vditor-preview { display: none !important; }
          #vditor .vditor-toolbar, #mdview-counter, #mdview-stats-backdrop,
          #editor-statusbar, #empty-hint, #mdv-review-panel, #mdv-find-panel,
          #mdv-highlight-panel, #mdv-underline-panel,
          #mdv-toolbar-tooltip { display: none !important; }
          #vditor, #vditor .vditor-ir { background: white !important; color: #222 !important; }
          #vditor .vditor-reset { color: #222 !important; }
          * { scrollbar-width: none !important; }
          *::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
        """
        add_style = """
          var existing = document.getElementById('mdview-pdf-print-style');
          if (existing) { existing.remove(); }
          var style = document.createElement('style');
          style.id = 'mdview-pdf-print-style';
          style.textContent = %s;
          document.head.appendChild(style);
        """ % json.dumps(print_style)

        def pdf_finished(_file_path, success):
            tab.printing = False
            if not tab.window._closed:
                tab.window._resource_timer.start()
            try:
                page.pdfPrintingFinished.disconnect(pdf_finished)
            except RuntimeError:
                pass
            page.runJavaScript(
                "var style = document.getElementById('mdview-pdf-print-style');"
                "if (style) { style.remove(); }")
            finished(success)

        def start_print(_result):
            page.pdfPrintingFinished.connect(pdf_finished)
            page.printToPdf(path)

        page.runJavaScript(add_style, start_print)

    def _finish_pdf_export(self, path, success, error=None):
        self._pdf_export_in_progress = False
        if success:
            self._remember_export_directory(path)
            self.statusBar().showMessage(t(f"已导出 PDF：{path}"), 5000)
            ExportSuccessDialog.show_result(self, path)
        else:
            self.statusBar().showMessage(t("PDF 导出失败"), 5000)
            QMessageBox.warning(
                self, t("导出失败"), error or t("无法生成 PDF，请重试。"))

    @staticmethod
    def _remember_export_directory(path):
        directory = os.path.dirname(os.path.abspath(path))
        QSettings().setValue("export/lastDirectory", directory)

    @staticmethod
    def _export_default_path(tab, extension):
        base_name = (
            os.path.splitext(os.path.basename(tab.filepath))[0]
            if tab.filepath else t("文档"))
        directory = QSettings().value("export/lastDirectory", "", type=str)
        if not directory or not os.path.isdir(directory):
            directory = tab.file_dir() or ""
        filename = f"{base_name}.{extension}"
        return os.path.join(directory, filename) if directory else filename

    def _sync_md_dir(self, tab):
        """把当前 md 文件所在目录传给页面，用于相对路径图片的显示。"""
        d = tab.file_dir()
        tab.js("window.setMdDir(%s);" % json.dumps(
            d.replace("\\", "/") if d else None))

    # ---------- 全屏 ----------
    def set_editor_fullscreen(self, tab, enabled):
        if tab is not self.current_tab():
            return
        if enabled:
            self._was_maximized_before_fullscreen = self.isMaximized()
            self._normal_geometry_before_fullscreen = self.normalGeometry()
            self.menuBar().hide()
            self.sidebar.hide()
            self.tabs.tabBar().hide()
            self.statusBar().hide()
            self.showFullScreen()
            return
        # Windows fullscreen transitions overwrite Qt's normal geometry. Give
        # each native state/geometry change an event-loop turn before maximizing.
        self.showNormal()
        if self._was_maximized_before_fullscreen:
            geometry = self._normal_geometry_before_fullscreen

            def maximize():
                if not self._closed and not self.isFullScreen():
                    self.showMaximized()

            def restore_geometry():
                if not self._closed and not self.isFullScreen():
                    self.setGeometry(geometry)
                    QTimer.singleShot(0, self, maximize)

            QTimer.singleShot(0, self, restore_geometry)
        else:
            self.setGeometry(self._normal_geometry_before_fullscreen)
        self.menuBar().show()
        self.sidebar.setVisible(self._sidebar_action.isChecked())
        self.tabs.tabBar().hide()
        self.statusBar().setVisible(bool(self.statusBar().currentMessage()))

    # ---------- 插入图片 ----------
    def _paste_clipboard_image(self, tab):
        # 直接读取 Windows 剪贴板位图，避免 WebEngine 的剪贴板权限和格式差异。
        image = QApplication.clipboard().image()
        if image.isNull():
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            self.statusBar().showMessage(t("无法读取剪贴板图片。"), 5000)
            return
        data = bytes(buffer.data())

        def accepted(allowed):
            if not allowed or tab not in self._tab_list or self._closed:
                return
            try:
                result = self._store_image(tab, data, "截图.png")
                tab.js("window.insertImageAtCursor(%s, %s)" %
                       (json.dumps(result["path"]), json.dumps(result["alt"])))
            except (OSError, ValueError) as error:
                self.statusBar().showMessage(t(f"粘贴图片失败：{error}"), 6000)

        tab.view.page().runJavaScript("window.editorAcceptsImage()", accepted)

    def insert_image_dialog(self, tab):
        sources, _ = QFileDialog.getOpenFileNames(
            self, t("选择图片"), "",
            t("图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg);;所有文件 (*)"))
        for source in sources:
            try:
                with open(source, "rb") as stream:
                    data = stream.read(50 * 1024 * 1024 + 1)
                result = self._store_image(tab, data, os.path.basename(source))
                tab.js("window.insertImageAtCursor(%s, %s);" %
                       (json.dumps(result["path"]), json.dumps(result["alt"])))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, t("插入图片"), str(error))

    def import_image(self, tab, data_url, name):
        try:
            if len(data_url) > 70 * 1024 * 1024 or not data_url.startswith("data:"):
                raise ValueError(t("图片文件过大或格式无效。"))
            header, encoded = data_url.split(",", 1)
            if ";base64" not in header:
                raise ValueError(t("图片编码无效。"))
            data = base64.b64decode(encoded, validate=True)
            return json.dumps(self._store_image(tab, data, name), ensure_ascii=False)
        except (OSError, ValueError) as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)

    def _store_image(self, tab, data, name):
        if len(data) > 50 * 1024 * 1024:
            raise ValueError(t("单张图片不能超过 50 MB。"))
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        if not reader.canRead():
            raise ValueError(t("无法读取这张图片，请选择 PNG、JPEG、GIF、WebP 或 SVG 等图片文件。"))
        extension = bytes(reader.format()).decode("ascii").lower()
        if extension == "jpeg":
            extension = "jpg"
        base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", os.path.splitext(os.path.basename(name))[0])
        base = base.strip(" .")[:80] or "截图"
        # UUID 后缀避免批量粘贴、同名文件或不同窗口互相覆盖。
        filename = f"{base}-{uuid.uuid4().hex[:8]}.{extension}"
        if not tab.file_dir():
            tab.resource_dir = self.store.asset_directory(tab.draft_id)
            self._sync_md_dir(tab)
        img_dir = os.path.join(tab.file_dir(), "images")
        os.makedirs(img_dir, exist_ok=True)
        with open(os.path.join(img_dir, filename), "xb") as stream:
            stream.write(data)
        return {"path": "images/" + quote(filename, safe="-_."), "alt": base.replace("[", "").replace("]", "")}

    @staticmethod
    def _relocate_images(content, source_dir, target_dir):
        if not source_dir or os.path.normcase(source_dir) == os.path.normcase(target_dir):
            return content
        relocated = {}

        def relocate(match):
            reference = match.group(2)
            relative = unquote(reference.strip("<>")).removeprefix("./")
            if not relative.startswith("images/"):
                return match.group(0)
            if relative in relocated:
                return match.group(1) + relocated[relative]
            source = os.path.abspath(os.path.join(source_dir, relative))
            image_root = os.path.abspath(os.path.join(source_dir, "images"))
            if os.path.commonpath([source, image_root]) != image_root or not os.path.isfile(source):
                return match.group(0)
            destination_dir = os.path.join(target_dir, "images")
            os.makedirs(destination_dir, exist_ok=True)
            name = os.path.basename(source)
            destination = os.path.join(destination_dir, name)
            if os.path.exists(destination):
                stem, extension = os.path.splitext(name)
                name = f"{stem}-{uuid.uuid4().hex[:8]}{extension}"
                destination = os.path.join(destination_dir, name)
            shutil.copyfile(source, destination)
            relocated[relative] = "images/" + quote(name, safe="-_.")
            return match.group(1) + relocated[relative]

        parts = re.split(r'(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)', content)
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(r'(!\[[^\]]*\]\()(<[^>]*>|[^\s)]+)', relocate, parts[index])
            parts[index] = re.sub(r'''(<img\b[^>]*?\bsrc=["'])([^"']+)''', relocate, parts[index])
        return "".join(parts)

    # ---------- 打开链接 ----------
    def open_url(self, tab, url):
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))
            return
        # 相对路径：相对当前 md 文件目录解析后打开本地文件
        if tab.file_dir():
            local = os.path.normpath(os.path.join(tab.file_dir(), url))
            if os.path.exists(local):
                QDesktopServices.openUrl(QUrl.fromLocalFile(local))

    # ---------- 脏标记 / 标题 ----------
    def set_dirty(self, tab, dirty):
        if tab.file_error:
            return
        if tab.dirty != dirty:
            tab.dirty = dirty
        if dirty:
            tab.ever_edited = True
            tab.cached_content = None
            tab.reading_state = None
            tab.revision += 1
            if not tab.backup_timer.isActive():
                tab.backup_timer.start()
        else:
            tab.backup_timer.stop()
        self._update_titles()
        self._schedule_session()

    def _update_titles(self):
        self.tab_bar.hide()
        self.document_list.blockSignals(True)
        while self.document_list.count() > len(self._tab_list):
            self.document_list.takeItem(self.document_list.count() - 1)
        for i, tab in enumerate(self._tab_list):
            star = " ●" if tab.dirty else ""
            self.tabs.setTabText(i, tab.display_name() + star)
            self.tabs.setTabToolTip(i, tab.filepath or tab.pending_file or t("未保存的新文档"))
            if i >= self.document_list.count():
                item = QListWidgetItem()
                self.document_list.addItem(item)
            item = self.document_list.item(i)
            item.setText(tab.display_name() + star)
            item.setToolTip(tab.filepath or tab.pending_file or t("未保存的新文档"))
            row = self.document_list.itemWidget(item)
            if row is None:
                row = self._create_document_row(item)
            row.tab = tab
            row.name_label.set_name(tab.display_name() + star)
            row.setToolTip(item.toolTip() + t("\n拖动可排序，拖出窗口可独立打开"))
            self._sync_document_ui(tab)
        self.document_list.setCurrentRow(self.tabs.currentIndex())
        self.document_list.blockSignals(False)
        self._document_count.setText(str(len(self._tab_list)))
        tab = self.current_tab()
        self.project_explorer.reveal_file(tab.filepath if tab else None)
        self.setWindowTitle("MarkdownView")

    # ---------- 关闭窗口 ----------
    def closeEvent(self, event):
        for tab in list(self._tab_list):
            if not tab.dirty:
                continue
            self.tabs.setCurrentIndex(self._tab_list.index(tab))
            ret = UnsavedChangesDialog.ask(self, tab, closing_window=True)
            if ret == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if ret == QMessageBox.StandardButton.Save:
                # 保存完成后由 save_file 再次触发 close()
                tab.quit_after_save = True
                tab.js("window.requestSave()")
                event.ignore()
                return
            tab.dirty = False  # 放弃修改
            self._remove_draft(tab, remove_assets=True)
        others = [w for w in self.store.windows if w is not self and not w._closed]
        self._persist_session(exclude_self=bool(others))
        self.document_list.cancel_drag()
        self._closed = True
        self.project_explorer.set_folder(None)
        self._resize_timer.stop()
        self._resize_pending_geometry = None
        self._session_timer.stop()
        self._activation_timer.stop()
        self._resource_timer.stop()
        for tab in self._tab_list:
            tab.backup_timer.stop()
            self._remove_draft(tab, remove_assets=True)
        event.accept()

    # ---------- 测试兼容 ----------
    @property
    def view(self):
        tab = self.current_tab()
        return tab.view if tab else None

    @property
    def _dirty(self):
        tab = self.current_tab()
        return tab.dirty if tab else False
