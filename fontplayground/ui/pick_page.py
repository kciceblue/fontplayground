"""Step 1 — Pick fonts.

Left: search, script quick-filters and the font tree (one collapsed row per family with script badges; faces
underneath). Right: the family's title and Style combo, a licence badge, the PreviewWidget, a coverage line
computed against the tray, a collapsible Details strip and a large "Add to materials" toggle.

Everything the page changes goes through the ForgeModel (add / remove / set_sample_text); the ✓ marks, the
add button and the coverage line follow the model's signals.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QSizePolicy, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace
from fontplayground.catalog.scanner import ScanResult
from fontplayground.engine.scripts import GROUP_IDS, LABELS
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.preview import PreviewWidget

FaceKey = tuple[str, int]

FAMILY_ROLE = Qt.ItemDataRole.UserRole + 1     # family rows carry their name here (UserRole stays None)
COL_NAME, COL_SCRIPTS, COL_FORMAT = range(3)
COLUMNS = ["Font", "Scripts", ""]

# (button label, script group id or None for "no filter")
QUICK_FILTERS: tuple[tuple[str, str | None], ...] = (
    ("Any script", None), ("Chinese", "han"), ("Japanese", "kana"), ("Korean", "hangul"), ("Arabic", "arabic"),
    ("Hebrew", "hebrew"), ("Indic", "indic"), ("Thai", "southeast_asian"), ("Symbols", "symbols"),
)
# Shorter labels for the tree badges; the coverage line and Details keep the full LABELS.
BADGE_LABELS = {**LABELS, "cjk_symbols": "CJK symbols", "symbols": "Symbols", "southeast_asian": "Thai & SE Asian",
                "emoji": "Emoji", "other": "Other"}
MAX_BADGE_GROUPS = 4
MAX_MISSING_CHARS = 20          # sample characters listed in the coverage line before "…" (the tooltip has them all)
DEFAULT_WEIGHT_CLASS = 400
ADD_TEXT = "Add to materials"
ADDED_TEXT = "✓ Added to materials (click to remove)"
ADDED_MARK = " ✓"
COLOR_MISSING, COLOR_OK, COLOR_MUTED, COLOR_TEXT = "#b3261e", "#2f8f46", "#777777", "#444444"

STYLE = """
QWidget#pickPage { background: #f4f6f9; }
QLineEdit#search { border: 1px solid #d3dae6; border-radius: 6px; padding: 5px 8px; background: #ffffff; }
QLineEdit#search:focus { border-color: #1a6bd8; }
QPushButton#filterChip { border: 1px solid #d3dae6; border-radius: 12px; background: #ffffff; color: #444444;
                         padding: 2px 10px; }
QPushButton#filterChip:hover { border-color: #1a6bd8; color: #1a6bd8; }
QPushButton#filterChip:checked { background: #1a6bd8; border-color: #1a6bd8; color: #ffffff; }
QTreeWidget#fontTree { background: #ffffff; border: 1px solid #d3dae6; border-radius: 6px; }
QTreeWidget#fontTree::item { padding: 2px 0; }
QProgressBar#scanProgress { border: 1px solid #d3dae6; border-radius: 6px; background: #ffffff; text-align: center;
                            max-height: 14px; }
QProgressBar#scanProgress::chunk { background: #1a6bd8; border-radius: 5px; }
QLabel#status { color: #777777; }
QWidget#card { background: #ffffff; border: 1px solid #d3dae6; border-radius: 8px; }
QLabel#familyTitle { font-size: 16px; font-weight: 600; color: #1f2933; background: transparent; }
QLabel#styleCaption { color: #777777; background: transparent; }
QLabel#licence { color: #777777; border: 1px solid #d3dae6; border-radius: 10px; padding: 1px 8px;
                 background: transparent; }
QLabel#licence[restricted="true"] { color: #b3261e; border-color: #e8b4b0; background: #fff5f5; }
QLabel#coverage { background: transparent; }
QToolButton#detailsToggle { border: none; background: transparent; color: #1a6bd8; padding: 2px 0; }
QLabel#details { color: #777777; background: transparent; }
QPushButton#addButton { background: #1a6bd8; color: #ffffff; border: 1px solid #1a6bd8; border-radius: 8px;
                        padding: 10px 18px; font-size: 14px; font-weight: 600; }
QPushButton#addButton:hover { background: #155bb8; border-color: #155bb8; }
QPushButton#addButton:checked { background: #e9f5ec; color: #2f8f46; border-color: #2f8f46; }
QPushButton#addButton:checked:hover { background: #fdecea; color: #b3261e; border-color: #b3261e; }
QPushButton#addButton:disabled { background: #e5e7eb; color: #9aa0a6; border-color: #e5e7eb; }
"""


# ----- pure helpers ------------------------------------------------------------------------------
def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _face_sort_key(face: FontFace) -> tuple[int, bool, str]:
    return (face.weight_class, face.italic, face.style.lower())


def family_badge(scripts: Iterable[str]) -> str:
    """'Han · Kana · CJK symbols · Latin': non-Latin groups first (GROUPS order, at most four then '+n'), Latin last."""
    present = set(scripts)
    non_latin = [g for g in GROUP_IDS if g != "latin" and g in present]
    parts = [BADGE_LABELS[g] for g in non_latin[:MAX_BADGE_GROUPS]]
    if len(non_latin) > MAX_BADGE_GROUPS:
        parts.append(f"+{len(non_latin) - MAX_BADGE_GROUPS}")
    if "latin" in present:
        parts.append(BADGE_LABELS["latin"])
    return " · ".join(parts)


def family_scripts(faces: Iterable[FontFace]) -> list[str]:
    """Group ids (GROUPS order) that at least one of the faces covers."""
    present = set().union(*(f.scripts for f in faces)) if faces else set()
    return [g for g in GROUP_IDS if g in present]


def family_format(faces: Iterable[FontFace]) -> str:
    """The faces' format tags without repeats, joined by '/': 'TTF', 'TTF/TTC'."""
    tags: list[str] = []
    for face in faces:
        if face.format_tag not in tags:
            tags.append(face.format_tag)
    return "/".join(tags)


def default_face(faces: Sequence[FontFace], main: FontFace | None) -> FontFace | None:
    """The face of a family to preview first: supported, italic like Main, weight closest to Main's (400 without Main).

    Ties keep the given order. A family with no supported face yields its first face (so it can still be inspected).
    """
    if not faces:
        return None
    want_italic = main.italic if main is not None else False
    want_weight = main.weight_class if main is not None else DEFAULT_WEIGHT_CLASS
    candidates = [f for f in faces if f.supported] or list(faces)
    ranked = min(enumerate(candidates),
                 key=lambda p: (p[1].italic != want_italic, abs(p[1].weight_class - want_weight), p[0]))
    return ranked[1]


def face_info_text(face: FontFace) -> str:
    """The multi-line description shown under Details for one face."""
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


class PickPage(QWidget):
    currentFaceChanged = Signal(object)   # FontFace | None: the face shown in the preview

    def __init__(self, model: ForgeModel, preview: PreviewWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.preview = preview
        self._faces: dict[FaceKey, FontFace] = {}
        self._face_items: dict[FaceKey, QTreeWidgetItem] = {}
        self._families: dict[str, QTreeWidgetItem] = {}
        self._family_order: list[str] = []      # lower-cased family names, parallel to the top-level items
        self._auto_expanded: set[str] = set()   # families the search filter opened (closed again when it stops matching)
        self._filter = ""
        self._script: str | None = None
        self._current_face: FontFace | None = None
        self._current_family_item: QTreeWidgetItem | None = None
        self._pending_key: FaceKey | None = None   # the face to show again once a rescan has finished
        self._syncing = False

        self.setObjectName("pickPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)

        # ----- left pane -----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Type a font name, e.g. Segoe UI or YaHei")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        left_layout.addWidget(self.search)

        self.progress = QProgressBar()
        self.progress.setObjectName("scanProgress")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        left_layout.addWidget(self.progress)

        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for i, (label, group_id) in enumerate(QUICK_FILTERS):
            button = QPushButton(label)
            button.setObjectName("filterChip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip("Show every family" if group_id is None
                              else f"Only families with {LABELS[group_id]} characters")
            button.setChecked(group_id is None)
            self.filter_group.addButton(button, i)
            self.filter_buttons[label] = button
            filters.addWidget(button)
        filters.addStretch(1)
        self.filter_group.idClicked.connect(self._on_filter_clicked)
        left_layout.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setObjectName("fontTree")
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setSortingEnabled(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(16)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_SCRIPTS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_FORMAT, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.itemActivated.connect(self._on_item_activated)
        left_layout.addWidget(self.tree, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        left_layout.addWidget(self.status_label)

        # ----- right pane -----
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        right_layout = QVBoxLayout(self.card)
        right_layout.setContentsMargins(12, 10, 12, 12)
        right_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.family_label = QLabel("")
        self.family_label.setObjectName("familyTitle")
        self.style_caption = QLabel("Style")
        self.style_caption.setObjectName("styleCaption")
        self.style_combo = QComboBox()
        self.style_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.style_combo.setToolTip("Which face of this family to preview and add")
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.licence_label = QLabel("")
        self.licence_label.setObjectName("licence")
        self.licence_label.setToolTip("What the font's licence flags allow")
        title_row.addWidget(self.family_label, 1)
        title_row.addWidget(self.style_caption)
        title_row.addWidget(self.style_combo)
        title_row.addWidget(self.licence_label)
        right_layout.addLayout(title_row)

        right_layout.addWidget(self.preview, 1)

        self.coverage_label = QLabel("")
        self.coverage_label.setObjectName("coverage")
        self.coverage_label.setWordWrap(True)
        right_layout.addWidget(self.coverage_label)

        self.details_button = QToolButton()
        self.details_button.setObjectName("detailsToggle")
        self.details_button.setText("Details")
        self.details_button.setCheckable(True)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.details_button.toggled.connect(self._on_details_toggled)
        self.details_label = QLabel("")
        self.details_label.setObjectName("details")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_label.hide()
        right_layout.addWidget(self.details_button)
        right_layout.addWidget(self.details_label)

        self.add_button = QPushButton(ADD_TEXT)
        self.add_button.setObjectName("addButton")
        self.add_button.setCheckable(True)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.add_button.setMinimumHeight(44)
        self.add_button.clicked.connect(self._on_add_clicked)
        right_layout.addWidget(self.add_button)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.card)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.splitter)

        # ----- wiring -----
        self.preview.set_sample_text(self.model.sample_text)
        self.preview.sampleChanged.connect(self.model.set_sample_text)
        # bound methods (not lambdas): Qt drops these connections when the page is destroyed before the model
        self.model.sampleChanged.connect(self.preview.set_sample_text)
        self.model.sampleChanged.connect(self._on_sample_changed)
        self.model.materialsChanged.connect(self._on_materials_changed)
        self.model.planChanged.connect(self._on_plan_changed)
        self._show_face(None, None)

    # ----- scan lifecycle -----
    def begin_scan(self) -> None:
        """Clear the tree; the previewed face is shown again by end_scan when the rescan still finds it."""
        if self._current_face is not None:
            self._pending_key = self._current_face.key
        self.tree.clear()
        self._faces.clear()
        self._face_items.clear()
        self._families.clear()
        self._family_order.clear()
        self._auto_expanded.clear()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("Scanning fonts…")
        self.status_label.setToolTip("")

    def add_face(self, face: FontFace) -> None:
        if face.key in self._face_items:
            return
        self._faces[face.key] = face
        family_item = self._family_item(face.family)

        item = QTreeWidgetItem([face.style, "", face.format_tag])
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole, face.key)
        item.setToolTip(COL_FORMAT, face.path)
        if not face.supported:
            # Greyed, not disabled: it can still be selected, previewed and inspected.
            grey = QBrush(self.tree.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
            for col in range(len(COLUMNS)):
                item.setForeground(col, grey)
            item.setToolTip(COL_NAME, face.unsupported_reason)
        self._face_items[face.key] = item

        sort_key = _face_sort_key(face)
        position = family_item.childCount()
        for i in range(family_item.childCount()):
            sibling = self._faces[family_item.child(i).data(COL_NAME, Qt.ItemDataRole.UserRole)]
            if sort_key < _face_sort_key(sibling):
                position = i
                break
        family_item.insertChild(position, item)
        self._refresh_family_row(family_item)
        self._refilter_family(family_item)

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status_label.setText(f"Scanning fonts… {done} / {total}")

    def end_scan(self, result: ScanResult) -> None:
        self.progress.hide()
        text = f"{_plural(len(self._faces), 'font')} in {_plural(len(self._families), 'family', 'families')}"
        if result.failed:
            text += f", {_plural(len(result.failed), 'unreadable file')}"
            self.status_label.setToolTip("\n".join(f"{path}: {error}" for path, error in result.failed))
        else:
            self.status_label.setToolTip("")
        self.status_label.setText(text)
        self._apply_filters()
        pending, self._pending_key = self._pending_key, None
        if pending is not None and pending in self._face_items:
            self.select_face(pending)

    # ----- queries -----
    def faces_by_key(self) -> dict[FaceKey, FontFace]:
        return dict(self._faces)

    def item_for(self, key: FaceKey) -> QTreeWidgetItem | None:
        return self._face_items.get(tuple(key))

    def family_item(self, family: str) -> QTreeWidgetItem | None:
        return self._families.get(family)

    def current_face(self) -> FontFace | None:
        return self._current_face

    def script_filter(self) -> str | None:
        return self._script

    def visible_families(self) -> list[str]:
        return [self.tree.topLevelItem(i).data(COL_NAME, FAMILY_ROLE) for i in range(self.tree.topLevelItemCount())
                if not self.tree.topLevelItem(i).isHidden()]

    # ----- selection -----
    def select_face(self, key: FaceKey) -> bool:
        """Expand the family, make the face the current row (previewing it) and scroll to it. False when unknown."""
        item = self._face_items.get(tuple(key))
        if item is None:
            return False
        family_item = item.parent()
        if family_item is not None:
            family_item.setExpanded(True)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        if self._current_face is None or self._current_face.key != tuple(key):  # the row was already current
            self._show_face(self._faces[tuple(key)], family_item)
        return True

    # ----- filtering -----
    def apply_filter(self, text: str) -> None:
        self._filter = text.strip().lower()
        self._apply_filters()

    def set_script_filter(self, group_id: str | None) -> None:
        """Keep only families with at least one face covering `group_id` (None: every family)."""
        for (label, gid), button in zip(QUICK_FILTERS, self.filter_group.buttons()):
            if gid == group_id:
                button.setChecked(True)
                break
        else:
            raise ValueError(f"No quick filter for {group_id!r}")
        if group_id != self._script:
            self._script = group_id
            self._apply_filters()

    def _on_filter_clicked(self, index: int) -> None:
        group_id = QUICK_FILTERS[index][1]
        if group_id != self._script:
            self._script = group_id
            self._apply_filters()

    def _apply_filters(self) -> None:
        for family_item in self._families.values():
            self._refilter_family(family_item)

    def _refilter_family(self, family_item: QTreeWidgetItem) -> None:
        family = family_item.data(COL_NAME, FAMILY_ROLE)
        faces = self._faces_of(family_item)
        script_ok = self._script is None or any(self._script in f.scripts for f in faces)
        any_visible = False
        for i, face in enumerate(faces):
            visible = script_ok and (not self._filter or self._filter in face.display_name.lower())
            family_item.child(i).setHidden(not visible)
            any_visible = any_visible or visible
        family_item.setHidden(not any_visible)
        # A search that matches a style but not the family name opens the family so the match can be seen.
        opened_by_search = bool(self._filter) and any_visible and self._filter not in family.lower()
        if opened_by_search:
            if not family_item.isExpanded():
                family_item.setExpanded(True)
                self._auto_expanded.add(family)
        elif family in self._auto_expanded:
            self._auto_expanded.discard(family)
            family_item.setExpanded(False)

    # ----- model -> widgets -----
    def _on_materials_changed(self) -> None:
        for family_item in self._families.values():
            self._refresh_family_row(family_item)
        self._refresh_add_button()
        self._refresh_coverage()

    def _on_plan_changed(self, _plan) -> None:
        self._refresh_coverage()

    def _on_sample_changed(self, _text: str) -> None:
        self._refresh_coverage()

    # ----- widgets -> model -----
    def _on_add_clicked(self) -> None:
        face = self._current_face
        if face is None or not face.supported:
            self._refresh_add_button()
            return
        if self.model.has(face.key):
            self.model.remove(face.key)
        else:
            self.model.add(face)
        self._refresh_add_button()  # materialsChanged did this too; harmless when nothing changed

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        """Enter / double-click on a face row toggles it in the materials (family rows just expand)."""
        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        if key is None:
            return
        if self._current_face is None or self._current_face.key != tuple(key):
            self._show_face(self._faces[tuple(key)], item.parent())
        self._on_add_clicked()

    # ----- current face -----
    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if self._syncing:
            return
        if current is None:
            self._show_face(None, None)
            return
        key = current.data(COL_NAME, Qt.ItemDataRole.UserRole)
        if key is not None:
            self._show_face(self._faces[tuple(key)], current.parent())
        else:
            self._show_face(default_face(self._faces_of(current), self.model.main), current)

    def _on_style_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        key = self.style_combo.itemData(index)
        face = self._faces.get(tuple(key)) if key is not None else None
        if face is None or (self._current_face is not None and self._current_face.key == face.key):
            return
        self._show_face(face, self._current_family_item, rebuild_combo=False)
        # When a face row (not the family row) is current, the tree follows the combo.
        current = self.tree.currentItem()
        if current is not None and current.data(COL_NAME, Qt.ItemDataRole.UserRole) is not None:
            self._syncing = True
            try:
                self.tree.setCurrentItem(self._face_items[face.key])
            finally:
                self._syncing = False

    def _on_details_toggled(self, checked: bool) -> None:
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.details_label.setVisible(checked)

    def _show_face(self, face: FontFace | None, family_item: QTreeWidgetItem | None, rebuild_combo: bool = True) -> None:
        self._current_face = face
        self._current_family_item = family_item
        if rebuild_combo:
            self._rebuild_combo(family_item, face)
        if face is None:
            self.family_label.setText("")
            self.licence_label.setText("")
            self.licence_label.hide()
            self.style_caption.hide()
            self.style_combo.hide()
            self.preview.clear()
            self.details_label.setText("")
        else:
            self.family_label.setText(face.family)
            self.style_caption.show()
            self.style_combo.show()
            self._set_licence(face)
            self.preview.set_face(face)
            self.details_label.setText(face_info_text(face))
        self._refresh_coverage()
        self._refresh_add_button()
        self.currentFaceChanged.emit(face)

    def _rebuild_combo(self, family_item: QTreeWidgetItem | None, face: FontFace | None) -> None:
        self.style_combo.blockSignals(True)
        try:
            self.style_combo.clear()
            if family_item is not None:
                for f in self._faces_of(family_item):
                    if f.supported:
                        self.style_combo.addItem(f.style, f.key)
            self.style_combo.setCurrentIndex(self._combo_index(face))
        finally:
            self.style_combo.blockSignals(False)

    def _combo_index(self, face: FontFace | None) -> int:
        """The combo row holding `face`, -1 when it has none (findData cannot compare tuple keys)."""
        if face is None:
            return -1
        for i in range(self.style_combo.count()):
            if tuple(self.style_combo.itemData(i)) == face.key:
                return i
        return -1

    def _set_licence(self, face: FontFace) -> None:
        self.licence_label.setText(f"licence: {face.embedding}")
        self.licence_label.show()
        restricted = face.embedding == "restricted"
        if self.licence_label.property("restricted") != restricted:
            self.licence_label.setProperty("restricted", restricted)
            self.licence_label.style().unpolish(self.licence_label)
            self.licence_label.style().polish(self.licence_label)

    def _refresh_add_button(self) -> None:
        face = self._current_face
        button = self.add_button
        button.blockSignals(True)
        try:
            if face is None:
                button.setChecked(False)
                button.setEnabled(False)
                button.setText(ADD_TEXT)
                button.setToolTip("Pick a font on the left first")
            elif not face.supported:
                button.setChecked(False)
                button.setEnabled(False)
                button.setText(f"Can't be used: {face.unsupported_reason}")
                button.setToolTip(face.unsupported_reason)
            elif self.model.has(face.key):
                button.setChecked(True)
                button.setEnabled(True)
                button.setText(ADDED_TEXT)
                button.setToolTip(f"Remove {face.display_name} from your materials")
            else:
                button.setChecked(False)
                button.setEnabled(True)
                button.setText(ADD_TEXT)
                button.setToolTip(f"Add {face.display_name} to your materials")
        finally:
            button.blockSignals(False)

    def _refresh_coverage(self) -> None:
        face = self._current_face
        if face is None:
            self._set_coverage("", COLOR_MUTED, "")
            return
        covers = ", ".join(LABELS[g] for g in face.scripts) or "no characters"
        tooltip = ""
        if self.model.has(face.key):
            tail, color = "In your materials", COLOR_OK
        elif not self.model.rows:
            missing = sorted({c for c in self.model.sample_text if not c.isspace() and ord(c) not in face.codepoints})
            if missing:
                shown = " ".join(missing[:MAX_MISSING_CHARS]) + (" …" if len(missing) > MAX_MISSING_CHARS else "")
                tail, color = f"Missing from your sample: {shown}", COLOR_MISSING
                tooltip = "Not in this font: " + " ".join(missing)
            else:
                tail, color = "Covers your whole sample", COLOR_OK
        else:
            covered = self._tray_groups()
            adds = [g for g in face.scripts if g not in covered]
            if adds:
                tail, color = "Would add to your sample: " + ", ".join(LABELS[g] for g in adds), COLOR_OK
            else:
                tail, color = "Adds nothing your fonts do not already cover", COLOR_MUTED
        self._set_coverage(f"Covers {covers} · {tail}", color, tooltip)

    def _set_coverage(self, text: str, color: str, tooltip: str) -> None:
        self.coverage_label.setText(text)
        self.coverage_label.setStyleSheet(f"color: {color}; background: transparent;")
        self.coverage_label.setToolTip(tooltip)

    def _tray_groups(self) -> set[str]:
        """Script groups the current plan covers: the union of the materials' groups (the planner keeps every
        code point some material has), so this needs no wait for the debounced plan."""
        return set().union(*(r.face.scripts for r in self.model.rows)) if self.model.rows else set()

    # ----- tree internals -----
    def _family_item(self, family: str) -> QTreeWidgetItem:
        item = self._families.get(family)
        if item is None:
            item = QTreeWidgetItem([family, "", ""])
            item.setData(COL_NAME, FAMILY_ROLE, family)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            lowered = family.lower()
            position = bisect_right(self._family_order, lowered)
            self._family_order.insert(position, lowered)
            self._families[family] = item
            self.tree.insertTopLevelItem(position, item)
            item.setExpanded(False)
        return item

    def _faces_of(self, family_item: QTreeWidgetItem) -> list[FontFace]:
        return [self._faces[family_item.child(i).data(COL_NAME, Qt.ItemDataRole.UserRole)]
                for i in range(family_item.childCount())]

    def _refresh_family_row(self, family_item: QTreeWidgetItem) -> None:
        faces = self._faces_of(family_item)
        scripts = family_scripts(faces)
        family_item.setText(COL_SCRIPTS, family_badge(scripts))
        family_item.setToolTip(COL_SCRIPTS, "Covers: " + (", ".join(LABELS[g] for g in scripts) or "no characters"))
        added = any(self.model.has(f.key) for f in faces)
        family_item.setText(COL_FORMAT, family_format(faces) + (ADDED_MARK if added else ""))
        family_item.setToolTip(COL_FORMAT, "In your materials" if added else "")
        if added:
            family_item.setForeground(COL_FORMAT, QBrush(QColor(COLOR_OK)))
        else:
            family_item.setData(COL_FORMAT, Qt.ItemDataRole.ForegroundRole, None)
