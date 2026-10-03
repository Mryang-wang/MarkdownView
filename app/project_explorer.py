"""Lazy, read-only project navigation backed by Qt's filesystem watcher."""
import os

from PySide6.QtCore import QDir, QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFileSystemModel, QHBoxLayout, QLabel, QSizePolicy,
    QToolButton, QTreeView, QVBoxLayout, QWidget)

from .i18n import t

TEXT_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".txt"}


class _ProjectModel(QFileSystemModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.icons = {}
        self.muted = QColor("#83837b")
        self.setReadOnly(True)
        self.setOption(QFileSystemModel.Option.DontUseCustomDirectoryIcons, True)
        self.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files |
                       QDir.Filter.Hidden | QDir.Filter.NoDotAndDotDot)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (index.isValid() and index.column() == 0 and role in (
                Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.ForegroundRole,
                Qt.ItemDataRole.ToolTipRole)):
            folder = self.isDir(index)
            supported = os.path.splitext(self.fileInfo(index).fileName())[1].lower() in TEXT_EXTENSIONS
            if role == Qt.ItemDataRole.DecorationRole and self.icons:
                return self.icons["folder" if folder else "file"]
            if role == Qt.ItemDataRole.ForegroundRole and not folder and not supported:
                return self.muted
            if role == Qt.ItemDataRole.ToolTipRole:
                tip = self.filePath(index)
                if not folder and not supported:
                    tip += "\n" + t("点击查看此文件的预览说明")
                return tip
        return super().data(index, role)


class _ProjectTree(QTreeView):
    openRequested = Signal(QModelIndex)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.openRequested.emit(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # A single click has already opened the item or toggled its folder.
        event.accept()


class ProjectExplorer(QWidget):
    fileRequested = Signal(str)
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_path = ""
        self.model = None
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(60)
        self._count_timer.timeout.connect(self._update_count)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        heading = QHBoxLayout()
        heading.setContentsMargins(8, 0, 0, 0)
        heading.setSpacing(2)
        self.title = QLabel(self)
        self.title.setObjectName("projectTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.title, 1)
        self.collapse_button = QToolButton(self)
        self.collapse_button.setFixedSize(24, 24)
        self.collapse_button.clicked.connect(lambda: self.tree.collapseAll())
        heading.addWidget(self.collapse_button)
        self.close_button = QToolButton(self)
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.closeRequested)
        heading.addWidget(self.close_button)
        layout.addLayout(heading)
        self.count = QLabel(self)
        self.count.setObjectName("projectCount")
        self.count.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(self.count)
        self.tree = _ProjectTree(self)
        self.tree.setObjectName("projectTree")
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setAnimated(False)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.clicked.connect(self._open_index)
        self.tree.openRequested.connect(self._open_index)
        layout.addWidget(self.tree, 1)
        self.retranslate()

    def set_folder(self, path):
        # Replacing the model releases watchers for the previous project.
        old_model = self.model
        self.root_path = os.path.abspath(path) if path else ""
        self.model = _ProjectModel(self) if path else None
        self.tree.setModel(self.model)
        if old_model:
            old_model.deleteLater()
        if self.model:
            self.model.directoryLoaded.connect(self._directory_loaded)
            self.model.rowsInserted.connect(lambda *_: self._count_timer.start())
            self.model.rowsRemoved.connect(lambda *_: self._count_timer.start())
            self.model.modelReset.connect(lambda *_: self._count_timer.start())
            root = self.model.setRootPath(self.root_path)
            self.tree.setRootIndex(root)
            for column in (1, 2, 3):
                self.tree.hideColumn(column)
            self.tree.header().setStretchLastSection(True)
            self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setVisible(bool(path))
        self.retranslate()

    def _directory_loaded(self, _path):
        self._count_timer.start()

    def _update_count(self, *_args):
        if not self.model:
            self.count.clear()
            return
        root = self.tree.rootIndex()
        if not root.isValid() or not os.path.isdir(self.root_path):
            self.count.setText(t("文件夹已被移动或删除"))
            # An invalid root index otherwise exposes the model's computer/drives root.
            self.tree.hide()
            return
        self.tree.show()
        folders = sum(self.model.isDir(self.model.index(row, 0, root))
                      for row in range(self.model.rowCount(root)))
        files = self.model.rowCount(root) - folders
        self.count.setText(t("文件 {0} · 文件夹 {1}").format(files, folders))
        self.count.setToolTip(t("当前项目根目录的直接子项，不含子文件夹内部文件"))

    def _open_index(self, index):
        if not self.model or not index.isValid():
            return
        if self.model.isDir(index):
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
        else:
            self.fileRequested.emit(self.model.filePath(index))

    def reveal_file(self, path):
        if not self.model:
            return
        path = os.path.abspath(path) if path else ""
        try:
            inside = path and os.path.normcase(os.path.commonpath([path, self.root_path])) == os.path.normcase(self.root_path)
        except ValueError:
            inside = False
        if not inside:
            self.tree.clearSelection()
            self.tree.setCurrentIndex(QModelIndex())
            return
        index = self.model.index(path)
        if not index.isValid() or index == self.tree.currentIndex():
            return
        parent = index.parent()
        while parent.isValid() and parent != self.tree.rootIndex():
            self.tree.expand(parent)
            parent = parent.parent()
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index)

    def set_icons(self, icon_factory, muted):
        self.collapse_button.setIcon(icon_factory("collapse"))
        self.close_button.setIcon(icon_factory("close"))
        if self.model:
            self.model.icons = {name: icon_factory(name) for name in ("folder", "file")}
            self.model.muted = QColor(muted)
            self.tree.viewport().update()

    def retranslate(self):
        self.collapse_button.setToolTip(t("折叠所有文件夹"))
        self.collapse_button.setAccessibleName(t("折叠所有文件夹"))
        self.close_button.setToolTip(t("关闭项目文件夹（保留已打开的文档）"))
        self.close_button.setAccessibleName(t("关闭项目文件夹"))
        self.tree.setAccessibleName(t("项目文件树"))
        self._update_title()
        self._update_count()

    def _update_title(self):
        name = os.path.basename(self.root_path) or self.root_path
        self.title.setText(self.title.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideMiddle, self.title.width()))
        self.title.setToolTip(self.root_path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_title()
