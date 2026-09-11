"""Fonts tab: searchable family/face tree with tick-to-select, live preview and an info strip."""
from __future__ import annotations

from bisect import bisect_right

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace
from fontplayground.catalog.scanner import ScanResult
from fontplayground.engine.scripts import LABELS
from fontplayground.ui.preview import PreviewWidget

FaceKey = tuple[str, int]


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _face_sort_key(face: FontFace) -> tuple[int, bool, str]:
    return (face.weight_class, face.italic, face.style.lower())


def face_info_text(face: FontFace) -> str:
    """The multi-line description shown under the preview for one face."""
    if face.axes:
        axes = ", ".join(f"{tag} {lo:g}–{hi:g} (default {default:g})" for tag, lo, default, hi in face.axes)
    else:
        axes = "none"
    scripts = ", ".join(LABELS[g] for g in face.scripts) or "none"
    return "\n".join([
        f"{face.path} (face {face.index})",
        f"Format: {face.format_tag} / {face.outline} outlines",
        f"Glyphs: {face.glyph_count}",
        f"Axes: {axes}",
        f"Scripts: {scripts}",
        f"Embedding: {face.embedding}",
    ])


class FontsTab(QWidget):
    selectionChanged = Signal(list)   # list[FontFace] in tick order
    goToForge = Signal()
    rescanRequested = Signal()
    addFolderRequested = Signal()

    def __init__(self, preview: PreviewWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview = preview
        self._faces: dict[FaceKey, FontFace] = {}
        self._face_items: dict[FaceKey, QTreeWidgetItem] = {}
        self._families: dict[str, QTreeWidgetItem] = {}
        self._family_order: list[str] = []   # lower-cased family names, parallel to the top-level items
        self._tick_order: list[FaceKey] = []
        self._pending_ticks: list[FaceKey] = []   # ticks to restore once a rescan has finished
        self._restoring = False
        self._filter = ""

        # ----- left pane -----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search fonts…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        left_layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Font", "Format"])
        self.tree.setSortingEnabled(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        left_layout.addWidget(self.tree, 1)

        status_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        self.status_label = QLabel("")
        status_row.addWidget(self.progress, 1)
        status_row.addWidget(self.status_label, 1)
        left_layout.addLayout(status_row)

        button_row = QHBoxLayout()
        self.selected_label = QLabel("Selected: 0")
        self.rescan_button = QPushButton("Rescan")
        self.add_folder_button = QPushButton("Add folder…")
        self.forge_button = QPushButton("Go to Forge →")
        self.rescan_button.clicked.connect(self.rescanRequested)
        self.add_folder_button.clicked.connect(self.addFolderRequested)
        self.forge_button.clicked.connect(self.goToForge)
        button_row.addWidget(self.selected_label)
        button_row.addStretch(1)
        for b in (self.rescan_button, self.add_folder_button, self.forge_button):
            button_row.addWidget(b)
        left_layout.addLayout(button_row)

        # ----- right pane -----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.preview, 1)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_layout.addWidget(self.info_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    # ----- scan lifecycle -----
    def begin_scan(self) -> None:
        """Clear the tree; ticks are remembered and restored (where still present) by end_scan."""
        self._pending_ticks = list(self._tick_order) or self._pending_ticks
        self.tree.clear()
        self._faces.clear()
        self._face_items.clear()
        self._families.clear()
        self._family_order.clear()
        self._tick_order.clear()
        self._update_selected_label()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("Scanning fonts…")
        self.status_label.setToolTip("")
        self.rescan_button.setEnabled(False)
        self.add_folder_button.setEnabled(False)

    def add_face(self, face: FontFace) -> None:
        if face.key in self._face_items:
            return
        self._faces[face.key] = face
        family_item = self._family_item(face.family)

        item = QTreeWidgetItem([face.style, face.format_tag])
        item.setData(0, Qt.ItemDataRole.UserRole, face.key)
        item.setToolTip(1, face.path)
        if face.supported:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            # Still selectable, so it can be previewed and inspected; only ticking is off (no checkbox at all).
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            grey = QBrush(self.tree.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
            item.setForeground(0, grey)
            item.setForeground(1, grey)
            item.setToolTip(0, face.unsupported_reason)
        item.setHidden(False)
        self._face_items[face.key] = item

        sort_key = _face_sort_key(face)
        position = family_item.childCount()
        for i in range(family_item.childCount()):
            sibling = self._faces[family_item.child(i).data(0, Qt.ItemDataRole.UserRole)]
            if sort_key < _face_sort_key(sibling):
                position = i
                break
        family_item.insertChild(position, item)
        if self._filter:
            item.setHidden(not self._matches(face))
            self._update_family_visibility(family_item)

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status_label.setText(f"Scanning fonts… {done} / {total}")

    def end_scan(self, result: ScanResult) -> None:
        self.progress.hide()
        text = f"{_plural(len(self._faces), 'face')} in {_plural(len(self._families), 'family', 'families')}"
        if result.failed:
            text += f", {_plural(len(result.failed), 'unreadable file')}"
            self.status_label.setToolTip("\n".join(f"{path}: {error}" for path, error in result.failed))
        else:
            self.status_label.setToolTip("")
        self.status_label.setText(text)
        self.rescan_button.setEnabled(True)
        self.add_folder_button.setEnabled(True)
        pending, self._pending_ticks = self._pending_ticks, []
        if pending:
            self.set_ticked(pending)

    # ----- queries -----
    def faces_by_key(self) -> dict[FaceKey, FontFace]:
        return dict(self._faces)

    def item_for(self, key: FaceKey) -> QTreeWidgetItem | None:
        return self._face_items.get(tuple(key))

    def selected_faces(self) -> list[FontFace]:
        return [self._faces[k] for k in self._tick_order if k in self._faces]

    # ----- filtering -----
    def apply_filter(self, text: str) -> None:
        self._filter = text.strip().lower()
        for family_item in self._families.values():
            for i in range(family_item.childCount()):
                child = family_item.child(i)
                face = self._faces[child.data(0, Qt.ItemDataRole.UserRole)]
                child.setHidden(not self._matches(face))
            self._update_family_visibility(family_item)
            if self._filter and not family_item.isHidden():
                family_item.setExpanded(True)

    def _matches(self, face: FontFace) -> bool:
        return not self._filter or self._filter in face.display_name.lower()

    def _update_family_visibility(self, family_item: QTreeWidgetItem) -> None:
        any_visible = any(not family_item.child(i).isHidden() for i in range(family_item.childCount()))
        family_item.setHidden(not any_visible)

    # ----- ticking -----
    def set_ticked(self, keys: list[FaceKey]) -> None:
        """Replace the ticks with `keys` (in that order); unknown and unsupported faces are skipped."""
        wanted: list[FaceKey] = []
        for k in keys:
            k = tuple(k)
            if k in self._face_items and k not in wanted and self._faces[k].supported:
                wanted.append(k)
        self._restoring = True
        try:
            for k in self._tick_order:
                if k not in wanted and k in self._face_items:
                    self._face_items[k].setCheckState(0, Qt.CheckState.Unchecked)
            for k in wanted:
                self._face_items[k].setCheckState(0, Qt.CheckState.Checked)
        finally:
            self._restoring = False
        self._tick_order = wanted
        self._update_selected_label()
        self.selectionChanged.emit(self.selected_faces())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._restoring or column != 0:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key is None:
            return
        key = tuple(key)
        face = self._faces.get(key)
        if face is not None and not face.supported:
            if item.data(0, Qt.ItemDataRole.CheckStateRole) is not None:  # a programmatic tick: take it back
                self._restoring = True
                try:
                    item.setData(0, Qt.ItemDataRole.CheckStateRole, None)
                finally:
                    self._restoring = False
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if checked and key not in self._tick_order:
            self._tick_order.append(key)
        elif not checked and key in self._tick_order:
            self._tick_order.remove(key)
        else:
            return  # tooltip/flag change, or state already reflected in _tick_order
        self._update_selected_label()
        self.selectionChanged.emit(self.selected_faces())

    def _update_selected_label(self) -> None:
        self.selected_label.setText(f"Selected: {len(self._tick_order)}")

    # ----- preview / info -----
    def _on_current_item_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        key = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        face = self._faces.get(tuple(key)) if key is not None else None
        if face is None:
            self.preview.clear()
            self.info_label.setText("")
            return
        self.preview.set_face(face)
        self.info_label.setText(face_info_text(face))

    # ----- internals -----
    def _family_item(self, family: str) -> QTreeWidgetItem:
        item = self._families.get(family)
        if item is None:
            item = QTreeWidgetItem([family, ""])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            lowered = family.lower()
            position = bisect_right(self._family_order, lowered)
            self._family_order.insert(position, lowered)
            self._families[family] = item
            self.tree.insertTopLevelItem(position, item)
            item.setExpanded(True)
        return item
