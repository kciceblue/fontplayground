"""The font picker: the list the left column shows while the user chooses a font (spec §2 "Picker").

One row per family that draws the chosen language well (languages.covers_well on a supported face), drawn in the
font itself; the fonts suggested for the user's text come first. The current row's face is the candidate the preview
tries (debounced), Enter or "Use …" chooses it, Esc or Back cancels. The picker also owns the catalog, as the old
Pick page did: the app feeds it the scan (begin_scan / add_face / set_progress / end_scan) and reads faces_by_key().

Drawing hundreds of families must not load hundreds of files: the delegate draws an installed family by name
(fonts.system_font) and otherwise queues the file, which a timer loads one per event-loop pass while the row shows
in the UI font. Nothing is ever loaded inside paint().
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QEvent, QItemSelectionModel, QModelIndex, QRect, QRectF, QSize, Qt, \
    QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QProgressBar, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace
from fontplayground.catalog.scanner import ScanResult
from fontplayground.ui import fonts, smart
from fontplayground.ui.languages import ANY, LANGUAGES, LATIN, Language, covers_well, language
from fontplayground.ui.requests import PickRequest
from fontplayground.ui.theme import LIGHT, Theme

FaceKey = tuple[str, int]

CANDIDATE_DEBOUNCE_MS = 120     # the preview tries the current row once the user stops moving for this long
REFRESH_MS = 300                # while open during a scan, the rows are rebuilt at most this often
MAX_SUGGESTIONS = 3
USE_NAME_LIMIT = 24             # characters of the family the Use button shows before "…"
COMBO_MIN_CHARS = 13            # the closed language combo is at least this wide; its popup fits every label

# Row geometry (px) and the sizes (pt) the delegate draws at.
HEADER_HEIGHT = 28
ROW_HEIGHT = 64
ROW_MARGIN = 2                  # around a row's rounded box
ROW_PAD = 10                    # inside it, left and right
ROW_RADIUS = 8
NAME_LINE = 24                  # the family-name line; the sample line takes the rest
NAME_PT, NATIVE_PT, SAMPLE_PT = 13, 11, 18
TAG_PT = 8.5
HEADER_PT = 8.5
GAP = 8                         # between the family name, its native name and the tag

MAIN_TITLE = "Choose your main font"
ADD_TITLE = "Choose a font for {}"
ANY_TITLE = "Choose a font"
REPLACE_TITLE = "Replace {}"
SEARCH_PLACEHOLDER = "Search {} — English or native name"
SUGGESTED_TITLE = "SUGGESTED FOR YOUR TEXT"
IN_RECIPE_TAG = "in your font"
SCANNING_TEXT = "Looking for fonts…"
NO_MATCH_TEXT = "No fonts match “{}”."
NONE_DRAW_TEXT = "None of your fonts draw {} well."
FILTER_NOTE = "Only fonts that draw\u00a0it\u00a0well"   # no-break spaces: a wrap falls before "draw"
USE_TEXT = "Use"

# Model roles (Qt.DisplayRole is the header text or the family name).
FACE_ROLE = Qt.ItemDataRole.UserRole + 1      # the row's FontFace (None on a header)
HEADER_ROLE = Qt.ItemDataRole.UserRole + 2    # True on a section header
NATIVE_ROLE = Qt.ItemDataRole.UserRole + 3    # the first native name of the family ("" when none)
TAG_ROLE = Qt.ItemDataRole.UserRole + 4       # IN_RECIPE_TAG or ""
SAMPLE_ROLE = Qt.ItemDataRole.UserRole + 5    # the language's picker sample

SUGGESTED, ALL = "suggested", "all"

STYLE = """
QWidget#picker { background: $surface; }
QLabel { color: $text; background: transparent; }
QLabel#h1 { font-size: 18px; font-weight: 600; }
QLabel#secondary { color: $text_secondary; }
QLabel#muted { color: $muted; }
QPushButton#link { background: transparent; border: none; color: $accent; padding: 0 2px; }
QPushButton#link:hover { color: $accent_hover; }
QPushButton#primary { background: $accent; color: $on_accent; border: none; border-radius: 8px; padding: 9px 22px;
                      font-size: 14px; font-weight: 600; }
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#primary:disabled { background: $accent_disabled; color: $accent_disabled_text; }
QPushButton#secondary { background: transparent; color: $text; border: 1px solid $border; border-radius: 8px;
                        padding: 8px 16px; }
QLineEdit, QComboBox { background: $surface; color: $text; border: 1px solid $border; border-radius: 6px;
                       padding: 4px 8px; }
QLineEdit:focus, QComboBox:focus { border-color: $accent; }
QListView#pickerList { background: $surface; border: none; outline: none; }
QProgressBar { border: none; background: $surface_alt; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar::chunk { background: $accent; border-radius: 2px; }
"""


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word if n == 1 else word + 's'}"


def section_title(lang: Language, count: int) -> str:
    """'ALL CHINESE FONTS · 382' ('ALL LATIN FONTS · n' for latin, 'ALL FONTS · n' for Any language)."""
    if lang.id == ANY:
        return f"ALL FONTS · {count:,}"
    name = "LATIN" if lang.id == LATIN else lang.short_label.upper()
    return f"ALL {name} FONTS · {count:,}"


# ----- rows ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Row:
    text: str                       # the header text, or the family name
    face: FontFace | None = None    # the face the row stands for; None on a header
    native: str = ""
    tag: str = ""
    section: str = ALL

    def identity(self) -> tuple[str, str, FaceKey | None]:
        """What 'the same row' means across rebuilds: a family in the list, or one suggested face."""
        return (self.section, self.text, self.face.key if self.section == SUGGESTED and self.face else None)


class PickerRows(QAbstractListModel):
    """The picker's rows, headers included. Headers are neither selectable nor enabled."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[Row] = []
        self.sample = ""

    def set_rows(self, rows: list[Row], sample: str) -> None:
        self.beginResetModel()
        self.rows = rows
        self.sample = sample
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row.text
        if role == FACE_ROLE:
            return row.face
        if role == HEADER_ROLE:
            return row.face is None
        if role == NATIVE_ROLE:
            return row.native
        if role == TAG_ROLE:
            return row.tag
        if role == SAMPLE_ROLE:
            return self.sample
        if role == Qt.ItemDataRole.ToolTipRole and row.face is not None:
            return " · ".join([row.face.display_name, *row.face.local_names])
        return None

    def flags(self, index):
        if not index.isValid() or not 0 <= index.row() < len(self.rows) or self.rows[index.row()].face is None:
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


# ----- drawing -------------------------------------------------------------------------------------
class RowDelegate(QStyledItemDelegate):
    """Paints headers and family rows. Fonts come from system_font or an already loaded file, never from paint().

    A face that Qt does not know by name and whose file is not loaded yet is drawn in the UI font (muted) and its
    file queued; `font_timer` loads the queue one file per event-loop pass and emits `changed` after each.
    """
    changed = Signal()

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._fonts: dict[tuple[FaceKey, float], QFont] = {}
        self._queue: dict[str, str] = {}          # path -> family, oldest first
        self.font_timer = QTimer(self)
        self.font_timer.setInterval(0)
        self.font_timer.timeout.connect(self._load_next)

    def reset(self) -> None:
        """Forget cached fonts and queued files (a rescan may have changed what a key means)."""
        self._fonts.clear()
        self._queue.clear()
        self.font_timer.stop()

    def pending_fonts(self) -> list[str]:
        return list(self._queue)

    def face_font(self, face: FontFace, size: float) -> QFont | None:
        """The face at `size`, cached; None (and the file queued) while its file still has to be loaded."""
        key = (face.key, size)
        font = self._fonts.get(key)
        if font is not None:
            return font
        font = fonts.system_font(face, size)
        if font is None:
            if not fonts.font_loader().is_loaded(face.path):
                self._queue.setdefault(face.path, face.family)
                if not self.font_timer.isActive():
                    self.font_timer.start()
                return None
            font = fonts.make_font(face.path, face.style, face.family, size)   # loaded already: no file read
        self._fonts[key] = font
        return font

    def _load_next(self) -> None:
        if self._queue:
            path = next(iter(self._queue))
            family = self._queue.pop(path)
            fonts.font_loader().family_for(path, family)
        if not self._queue:
            self.font_timer.stop()
        self.changed.emit()

    # ----- QStyledItemDelegate -----
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(100, HEADER_HEIGHT if index.data(HEADER_ROLE) else ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        try:
            painter.setClipRect(option.rect)
            if index.data(HEADER_ROLE):
                self._paint_header(painter, option, index)
            else:
                self._paint_row(painter, option, index)
        finally:
            painter.restore()

    def _paint_header(self, painter: QPainter, option, index) -> None:
        font = QFont(option.font)
        font.setPointSizeF(HEADER_PT)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        painter.setFont(font)
        painter.setPen(QColor(self.theme.muted))
        rect = option.rect.adjusted(ROW_MARGIN + ROW_PAD, 0, -(ROW_MARGIN + ROW_PAD), -5)
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, index.data())

    def _paint_row(self, painter: QPainter, option, index) -> None:
        theme = self.theme
        box = option.rect.adjusted(ROW_MARGIN, ROW_MARGIN, -ROW_MARGIN, -ROW_MARGIN)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor(theme.accent_soft_border), 1))
            painter.setBrush(QColor(theme.accent_soft))
            painter.drawRoundedRect(QRectF(box).adjusted(0.5, 0.5, -0.5, -0.5), ROW_RADIUS, ROW_RADIUS)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.surface_alt))
            painter.drawRoundedRect(QRectF(box), ROW_RADIUS, ROW_RADIUS)
        face: FontFace = index.data(FACE_ROLE)
        left, right = box.left() + ROW_PAD, box.right() - ROW_PAD
        name_line = QRect(left, box.top() + 2, right - left, NAME_LINE)
        sample_line = QRect(left, name_line.bottom() + 1, right - left, box.bottom() - name_line.bottom() - 2)

        tag = index.data(TAG_ROLE)
        if tag:
            tag_font = QFont(option.font)
            tag_font.setPointSizeF(TAG_PT)
            width = QFontMetrics(tag_font).horizontalAdvance(tag)
            painter.setFont(tag_font)
            painter.setPen(QColor(theme.ok))
            painter.drawText(QRect(right - width, name_line.top(), width, name_line.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tag)
            right -= width + GAP
        name_font = self._font_or_ui(face, NAME_PT, option)
        baseline = self._baseline(name_line, QFontMetrics(name_font[0]))
        x = self._draw(painter, name_font, index.data(), left, right, baseline, theme.text)
        native = index.data(NATIVE_ROLE)
        if native and x + GAP < right:
            self._draw(painter, self._font_or_ui(face, NATIVE_PT, option), native, x + GAP, right, baseline,
                       theme.muted)
        sample_font = self._font_or_ui(face, SAMPLE_PT, option)
        self._draw(painter, sample_font, index.data(SAMPLE_ROLE), left, box.right() - ROW_PAD,
                   self._baseline(sample_line, QFontMetrics(sample_font[0])), theme.text)

    def _font_or_ui(self, face: FontFace, size: float, option) -> tuple[QFont, bool]:
        """(font, True) in the face itself, or (the UI font at `size`, False) while its file is queued."""
        font = self.face_font(face, size)
        if font is not None:
            return font, True
        ui = QFont(option.font)
        ui.setPointSizeF(size)
        return ui, False

    @staticmethod
    def _baseline(line: QRect, metrics: QFontMetrics) -> int:
        """The baseline that centres the font's ascent + descent in the line."""
        return line.top() + (line.height() + metrics.ascent() - metrics.descent()) // 2

    def _draw(self, painter: QPainter, font: tuple[QFont, bool], text: str, left: int, right: int, baseline: int,
              colour: str) -> int:
        """Draw `text` elided to [left, right] on the baseline; returns where it ends."""
        qfont, own = font
        metrics = QFontMetrics(qfont)
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, right - left))
        painter.setFont(qfont)
        painter.setPen(QColor(colour if own else self.theme.muted))
        painter.drawText(left, baseline, shown)
        return left + metrics.horizontalAdvance(shown)


# ----- the picker ------------------------------------------------------------------------------------
class FontPicker(QWidget):
    """Choose a font for the recipe: open() it with a PickRequest, get chosen(face) or cancelled()."""
    candidateChanged = Signal(object)    # FontFace or None: what the preview should try (debounced)
    chosen = Signal(object)              # FontFace
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.setObjectName("picker")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = theme
        # the catalog
        self._faces: dict[FaceKey, FontFace] = {}
        self._families: dict[str, list[FontFace]] = {}       # family -> faces, in arrival order
        self._haystacks: dict[str, str] = {}                 # family -> casefolded family and native names
        self._scanning = False
        self._scan_text = ""                                 # "Looking for fonts… 340 / 1,101"
        self._catalog_text = ""                              # "1,101 fonts · 1 file couldn't be read"
        # what open() was asked
        self._request = PickRequest(LATIN)
        self._main: FontFace | None = None
        self._recipe_keys: frozenset[FaceKey] = frozenset()
        self._suggestions: list[FontFace] = []
        self._open = False
        self._want: tuple | None = None                      # Row.identity() the current row should be
        self._rebuilding = False
        self._listed = 0                                     # families listed for the language, before the search

        self.back_button = QPushButton("‹ Back")
        self.back_button.setObjectName("link")
        self.back_button.setFlat(True)
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_label = QLabel(MAIN_TITLE)
        self.title_label.setObjectName("h1")
        self.title_label.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setClearButtonEnabled(True)
        self.language_combo = QComboBox()
        for lang in LANGUAGES:
            self.language_combo.addItem(lang.label, lang.id)
        # the left column is 420 px: the closed combo may cut a long label, the popup shows it whole
        self.language_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.language_combo.setMinimumContentsLength(COMBO_MIN_CHARS)
        popup = self.language_combo.view()
        popup.setMinimumWidth(popup.sizeHintForColumn(0) + 2 * popup.frameWidth() + 24)
        self.filter_note = QLabel(FILTER_NOTE)         # wraps onto two lines when the row is short of room
        self.filter_note.setObjectName("muted")
        self.filter_note.setWordWrap(True)
        self.filter_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._model = PickerRows(self)
        self.delegate = RowDelegate(theme, self)
        self.view = QListView()
        self.view.setObjectName("pickerList")
        self.view.setModel(self._model)
        self.view.setItemDelegate(self.delegate)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setMouseTracking(True)                     # hover fills
        self.view.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(120)
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("secondary")
        self.use_button = QPushButton(USE_TEXT)
        self.use_button.setObjectName("primary")
        self.use_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.title_label, 1)
        layout.addLayout(head)
        layout.addWidget(self.search)
        show_row = QHBoxLayout()
        show_row.setSpacing(8)
        show_label = QLabel("Show fonts for")
        show_label.setObjectName("secondary")
        show_row.addWidget(show_label)
        show_row.addWidget(self.language_combo)
        show_row.addWidget(self.filter_note, 1)       # takes the rest of the row, text on the right
        layout.addLayout(show_row)
        layout.addWidget(self.view, 1)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress)
        layout.addLayout(status_row)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)

        self._candidate_timer = QTimer(self)
        self._candidate_timer.setSingleShot(True)
        self._candidate_timer.setInterval(CANDIDATE_DEBOUNCE_MS)
        self._candidate_timer.timeout.connect(self._emit_candidate)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(REFRESH_MS)
        self._refresh_timer.timeout.connect(self._rebuild)

        self.back_button.clicked.connect(self._cancel)
        self.cancel_button.clicked.connect(self._cancel)
        self.use_button.clicked.connect(self._use)
        self.search.textChanged.connect(self._rebuild)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.view.doubleClicked.connect(self._on_double_clicked)
        self.delegate.changed.connect(self.view.viewport().update)
        self.search.installEventFilter(self)
        self.view.installEventFilter(self)
        self._update_placeholder()
        self.apply_theme(theme)

    # ----- catalog -----
    def begin_scan(self) -> None:
        """Forget the catalog; faces arrive through add_face until end_scan."""
        self._faces.clear()
        self._families.clear()
        self._haystacks.clear()
        self.delegate.reset()
        self._scanning = True
        self._scan_text = SCANNING_TEXT
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setToolTip("")
        if self._open:
            self._rebuild()
        else:
            self._update_status()

    def add_face(self, face: FontFace) -> None:
        if face.key in self._faces:
            return
        self._faces[face.key] = face
        self._families.setdefault(face.family, []).append(face)
        names = "\n".join(n.casefold() for n in (face.family, *face.local_names))   # a query never spans two
        known = self._haystacks.get(face.family)
        self._haystacks[face.family] = f"{known}\n{names}" if known else names
        if self._open and not self._refresh_timer.isActive():
            self._refresh_timer.start()           # at most one rebuild per REFRESH_MS while faces pour in

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self._scan_text = f"{SCANNING_TEXT} {done:,} / {total:,}"
        self._update_status()

    def end_scan(self, result: ScanResult) -> None:
        for face in result.faces:                 # normally all known already (add_face ignores repeats)
            self.add_face(face)
        self._scanning = False
        self._refresh_timer.stop()
        self.progress.hide()
        text = _plural(len(self._faces), "font")
        if result.failed:
            text += f" · {_plural(len(result.failed), 'file')} couldn't be read"
        self._catalog_text = text
        self.status_label.setToolTip("\n".join(f"{path}: {error}" for path, error in result.failed))
        if self._open:
            self._rebuild()
        else:
            self._update_status()

    def faces_by_key(self) -> dict[FaceKey, FontFace]:
        """Every face of the catalog, unsupported ones included."""
        return dict(self._faces)

    # ----- opening -----
    def open(self, request: PickRequest, main: FontFace | None, recipe_keys: Iterable[FaceKey],
             suggestions: list[FontFace]) -> None:
        """Show the list for `request`: its language, the suggestions first, the replaced family current."""
        lang = language(request.language)          # KeyError for an unknown language
        self._request = request
        self._main = main
        self._recipe_keys = frozenset(tuple(k) for k in recipe_keys)
        self._suggestions = list(suggestions)
        self.title_label.setText(self._title(lang))
        self.search.blockSignals(True)
        self.language_combo.blockSignals(True)
        try:
            self.search.clear()
            self.language_combo.setCurrentIndex(self.language_combo.findData(lang.id))
        finally:
            self.search.blockSignals(False)
            self.language_combo.blockSignals(False)
        self.filter_note.setVisible(lang.id != ANY)
        replaced = self._family_of(request.replace_key)
        self._want = (ALL, replaced, None) if replaced is not None else None
        self._open = True
        self._rebuild()
        self._candidate_timer.start()             # the preview tries the first candidate even if it is not new
        self.search.setFocus()

    def _title(self, lang: Language) -> str:
        replaced = self._family_of(self._request.replace_key)
        if replaced is not None:
            return REPLACE_TITLE.format(replaced)
        if self._request.replace_key is None and self._main is None:
            return MAIN_TITLE
        return ANY_TITLE if lang.id == ANY else ADD_TITLE.format(lang.short_label)

    def _family_of(self, key) -> str | None:
        if key is None:
            return None
        face = self._faces.get(tuple(key))
        if face is None and self._main is not None and self._main.key == tuple(key):
            face = self._main
        return face.family if face is not None else None

    # ----- queries -----
    def current_face(self) -> FontFace | None:
        index = self.view.currentIndex()
        return index.data(FACE_ROLE) if index.isValid() else None

    def language(self) -> str:
        return self.language_combo.currentData()

    def visible_families(self) -> list[str]:
        """The family names of the 'ALL …' section, in order."""
        return [r.text for r in self._model.rows if r.section == ALL and r.face is not None]

    def row_texts(self) -> list[str]:
        """Header texts and family names in view order."""
        return [r.text for r in self._model.rows]

    def pending_fonts(self) -> list[str]:
        """Font files queued for loading by the delegate (oldest first)."""
        return self.delegate.pending_fonts()

    # ----- theme -----
    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        self.delegate.theme = theme
        self.view.viewport().update()

    # ----- rows -----
    def _matches(self, family: str, query: str, face: FontFace | None = None) -> bool:
        if not query:
            return True
        haystack = self._haystacks.get(family)
        if haystack is None and face is not None:  # a suggestion from outside the catalog
            haystack = "\n".join(n.casefold() for n in (face.family, *face.local_names))
        return haystack is not None and query in haystack

    def _row(self, family: str, face: FontFace, section: str) -> Row:
        faces = self._families.get(family, [face])
        native = next(iter(face.local_names), "") or next((n for f in faces for n in f.local_names), "")
        in_recipe = face.key in self._recipe_keys or any(f.key in self._recipe_keys for f in faces)
        return Row(family, face, native, IN_RECIPE_TAG if in_recipe else "", section)

    def _build_rows(self, lang: Language, query: str) -> list[Row]:
        listed: dict[str, list[FontFace]] = {}
        for family, faces in self._families.items():
            good = [f for f in faces if f.supported and covers_well(f, lang)]
            if good:
                listed[family] = good
        self._listed = len(listed)
        rows: list[Row] = []
        seen: set[FaceKey] = set()
        suggested: list[Row] = []
        for face in self._suggestions:
            if len(suggested) == MAX_SUGGESTIONS:
                break
            if face.key in seen or not face.supported or not covers_well(face, lang) \
                    or not self._matches(face.family, query, face):
                continue
            seen.add(face.key)
            suggested.append(self._row(face.family, face, SUGGESTED))
        if suggested:
            rows += [Row(SUGGESTED_TITLE, section=SUGGESTED), *suggested]
        names = sorted((f for f in listed if self._matches(f, query)), key=lambda f: (f.casefold(), f))
        if names:
            rows.append(Row(section_title(lang, len(names))))
            rows += [self._row(f, smart.default_face(listed[f], self._main), ALL) for f in names]
        return rows

    def _rebuild(self) -> None:
        """Rebuild the rows for the language and the search, keeping the current row when it is still listed."""
        self._refresh_timer.stop()
        lang = language(self.language())
        query = self.search.text().strip().casefold()
        before = self.current_face()
        rows = self._build_rows(lang, query)
        self._rebuilding = True
        try:
            self._model.set_rows(rows, lang.picker_sample)
            target = self._pick_row(rows)
            if target is not None:
                self._set_current(target)
        finally:
            self._rebuilding = False
        self._update_placeholder()
        self._after_move(self.current_face() != before)

    def _pick_row(self, rows: list[Row]) -> int | None:
        """The row to make current: the wanted one, else a row of its family, else the first selectable row.

        A fallback becomes the new wish, except while a scan still runs: the wanted row may yet arrive.
        """
        selectable = [i for i, r in enumerate(rows) if r.face is not None]
        if not selectable:
            return None
        want = self._want
        chosen = None
        if want is not None:
            chosen = next((i for i in selectable if rows[i].identity() == want), None)
            if chosen is None:
                same = [i for i in selectable if rows[i].text == want[1]]
                chosen = next((i for i in same if rows[i].section == ALL), same[0] if same else None)
        if chosen is None:
            chosen = selectable[0]
        if want is None or not self._scanning or rows[chosen].identity() == want:
            self._want = rows[chosen].identity()
        return chosen

    def _set_current(self, row: int) -> None:
        index = self._model.index(row, 0)
        self.view.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.view.scrollTo(index)

    def _selectable(self) -> list[int]:
        return [i for i, r in enumerate(self._model.rows) if r.face is not None]

    def _move(self, delta: int) -> None:
        """Move the current row by `delta` family rows (headers are skipped), stopping at either end."""
        selectable = self._selectable()
        if not selectable:
            return
        current = self.view.currentIndex().row()
        pos = selectable.index(current) + delta if current in selectable else 0
        self._set_current(selectable[max(0, min(pos, len(selectable) - 1))])

    def _page(self) -> int:
        return max(1, self.view.viewport().height() // ROW_HEIGHT)

    # ----- reactions -----
    def _on_language_changed(self, _index: int) -> None:
        self.filter_note.setVisible(self.language() != ANY)
        self._rebuild()

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._rebuilding:
            return
        if current.isValid() and 0 <= current.row() < len(self._model.rows):
            self._want = self._model.rows[current.row()].identity()
        self._after_move(True)

    def _after_move(self, changed: bool) -> None:
        face = self.current_face()
        if face is None:
            self.use_button.setText(USE_TEXT)
            self.use_button.setToolTip("")
        else:
            name = face.family if len(face.family) <= USE_NAME_LIMIT else face.family[:USE_NAME_LIMIT - 1] + "…"
            self.use_button.setText(f"{USE_TEXT} {name}")
            self.use_button.setToolTip(face.display_name)
        self.use_button.setEnabled(face is not None)
        self._update_status()
        if changed and self._open:
            self._candidate_timer.start()         # restarts: one emission once the moves stop

    def _emit_candidate(self) -> None:
        if self._open:
            self.candidateChanged.emit(self.current_face())

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if index.isValid() and index.data(FACE_ROLE) is not None:
            self._set_current(index.row())
            self._use()

    def _use(self) -> None:
        face = self.current_face()
        if face is None:
            return
        self._close()
        self.chosen.emit(face)

    def _cancel(self) -> None:
        self._close()
        self.cancelled.emit()

    def _close(self) -> None:
        """The picker is done: no candidate or refresh may fire any more until the next open()."""
        self._open = False
        self._candidate_timer.stop()
        self._refresh_timer.stop()

    def _update_placeholder(self) -> None:
        self.search.setPlaceholderText(SEARCH_PLACEHOLDER.format(_plural(self._listed, "font")))

    def _update_status(self) -> None:
        if self._scanning:
            text = self._scan_text
        elif self._open and not self._model.rows:
            query = self.search.text().strip()
            lang = language(self.language())
            if query:
                text = NO_MATCH_TEXT.format(query)
            elif lang.id != ANY:
                text = NONE_DRAW_TEXT.format(lang.label)
            else:
                text = self._catalog_text
        else:
            text = self._catalog_text
        self.status_label.setText(text)

    # ----- Qt -----
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and obj in (self.search, self.view):
            key = event.key()
            steps = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1,
                     Qt.Key.Key_PageUp: -self._page(), Qt.Key.Key_PageDown: self._page()}
            if obj is self.view:
                steps.update({Qt.Key.Key_Home: -len(self._model.rows), Qt.Key.Key_End: len(self._model.rows)})
            if key in steps:
                self._move(steps[key])
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._use()
                return True
            if key == Qt.Key.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._open:
            self.search.setFocus()                # open() may have run while the picker was hidden

    def hideEvent(self, event) -> None:  # noqa: N802
        """Hidden by the app (not minimised): the picker is closed, so the preview gets no more candidates."""
        if not event.spontaneous():
            self._close()
        super().hideEvent(event)
