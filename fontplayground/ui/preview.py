"""Sample-text preview that is honest about missing characters.

Two modes:
- single-font mode (set_face / set_font_file): the whole sample in one font, red where the font has no glyph;
- plan mode (set_plan): each character in the font that will supply it, red where no font does.
"""
from __future__ import annotations

import html
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QSlider, QSpinBox, QTextBrowser,
                               QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace

DEFAULT_SAMPLE = (
    "The quick brown fox jumps over the lazy dog 0123456789\n"
    "Ärger Œuvre Ñandú Ωμέγα Привет, мир\n"
    "漢字 かな カナ 한글 你好，世界\n"
    "مرحبا بالعالم  שלום עולם  नमस्ते\n"
    "€ £ ¥ § ¶ → ✓ ☺ ①"
)
MISSING_COLOR = "#ffb3b3"
MISSING_STYLE = f"background-color:{MISSING_COLOR};"
PLACEHOLDER_HTML = '<span style="color:gray">Select a font to preview</span>'

FaceKey = tuple[str, int]
# (path, style or None, preferred family or None, axes as (tag, min, default, max) tuples)
PlanFont = tuple[str, "str | None", "str | None", tuple]
SourceOf = Callable[[int], "FaceKey | None"]


class FontLoader:
    """Loads font files into Qt's font database once and maps path -> family name."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._families: dict[str, list[str]] = {}

    def family_for(self, path: str, preferred: str | None = None) -> str | None:
        if path not in self._ids:
            fid = QFontDatabase.addApplicationFont(path)
            self._ids[path] = fid
            self._families[path] = list(QFontDatabase.applicationFontFamilies(fid)) if fid >= 0 else []
        families = self._families[path]
        if not families:
            return None
        return preferred if preferred in families else families[0]

    def unload(self, path: str) -> None:
        fid = self._ids.pop(path, None)
        self._families.pop(path, None)
        if fid is not None and fid >= 0:
            QFontDatabase.removeApplicationFont(fid)


_LOADER: FontLoader | None = None


def font_loader() -> FontLoader:
    global _LOADER
    if _LOADER is None:
        _LOADER = FontLoader()
    return _LOADER


def make_font(path: str, style: str | None, family: str | None, size: int, wght: float | None = None) -> QFont:
    """A QFont for one font file (loaded through font_loader) that never borrows glyphs from other fonts."""
    resolved = font_loader().family_for(path, family) or family or ""
    font = QFontDatabase.font(resolved, style, size) if style else QFont(resolved, size)
    if font.family() != resolved:  # Qt did not know the style: keep at least the family
        font = QFont(resolved, size)
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    if wght is not None:
        font.setVariableAxis(QFont.Tag("wght"), float(wght))
    return font


def default_wght(axes) -> float | None:
    """The default weight of a variable font's weight axis, or None when it has none."""
    return next((float(a[2]) for a in axes if a[0] == "wght"), None)


class PreviewWidget(QWidget):
    sampleChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, sizes=(12, 24, 48)) -> None:
        super().__init__(parent)
        # single-font mode
        self._path: str | None = None
        self._preferred: str | None = None
        self._family: str | None = None
        self._style: str | None = None
        self._codepoints: frozenset[int] = frozenset()
        self._has_wght = False
        # plan mode
        self._plan_mode = False
        self._plan: dict[FaceKey, PlanFont] = {}
        self._source_of: SourceOf | None = None
        self._plan_family: str | None = None

        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit(DEFAULT_SAMPLE)
        self.editor.setMaximumHeight(110)
        self.editor.textChanged.connect(lambda: self.sampleChanged.emit(self.sample_text()))
        self.editor.textChanged.connect(self._render)
        layout.addWidget(self.editor)

        slider_row = QHBoxLayout()
        self.weight_label = QLabel("Weight")
        self.weight_slider = QSlider(Qt.Orientation.Horizontal)
        self.weight_slider.valueChanged.connect(self._on_weight)
        self.weight_value = QLabel("")
        slider_row.addWidget(self.weight_label)
        slider_row.addWidget(self.weight_slider, 1)
        slider_row.addWidget(self.weight_value)
        layout.addLayout(slider_row)
        self._show_weight_row(False)

        # The size rows live in a scroll area so large sizes never get clipped.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        rows_host = QWidget()
        rows_layout = QVBoxLayout(rows_host)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(rows_host)
        layout.addWidget(self.scroll, 1)

        self.size_spins: list[QSpinBox] = []
        self.browsers: list[QTextBrowser] = []
        for size in sizes:
            row = QHBoxLayout()
            spin = QSpinBox()
            spin.setRange(6, 200)
            spin.setValue(size)
            spin.setSuffix(" pt")
            spin.valueChanged.connect(self._render)
            browser = QTextBrowser()
            browser.setOpenLinks(False)
            browser.setFrameShape(QTextBrowser.Shape.NoFrame)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            row.addWidget(spin, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(browser, 1)
            rows_layout.addLayout(row)
            self.size_spins.append(spin)
            self.browsers.append(browser)
        rows_layout.addStretch(1)
        self._render()

    # ----- public API: single-font mode -----
    def set_face(self, face: FontFace) -> None:
        self.set_font_file(face.path, face.style, face.codepoints, face.axes, face.family)

    def set_font_file(self, path: str, style: str | None, codepoints, axes=(), preferred_family: str | None = None) -> None:
        self._leave_plan_mode()
        self._path, self._preferred = path, preferred_family
        self._family = font_loader().family_for(path, preferred_family)
        self._style = style
        self._codepoints = frozenset(codepoints)
        wght = next((a for a in axes if a[0] == "wght"), None)
        self._has_wght = wght is not None
        self._show_weight_row(self._has_wght)
        if wght:
            self.weight_slider.blockSignals(True)
            self.weight_slider.setRange(int(wght[1]), int(wght[3]))
            self.weight_slider.setValue(int(wght[2]))
            self.weight_slider.blockSignals(False)
            self.weight_value.setText(str(int(wght[2])))
        self._render()

    # ----- public API: plan mode -----
    def set_plan(self, fonts: dict[FaceKey, PlanFont], source_of: SourceOf) -> None:
        """Show each character in the font that supplies it.

        fonts: key -> (path, style, preferred family, axes) for every material, in priority order.
        source_of(codepoint) -> the key of the material that draws it, or None when no material does.
        """
        self._path = self._preferred = self._family = self._style = None
        self._codepoints = frozenset()
        self._has_wght = False
        self._show_weight_row(False)
        self._plan_mode = True
        self._plan = {key: tuple(value) for key, value in fonts.items()}
        self._source_of = source_of
        first = next(iter(self._plan.values()), None)
        self._plan_family = font_loader().family_for(first[0], first[2]) if first else None
        self._render()

    def in_plan_mode(self) -> bool:
        return self._plan_mode

    # ----- public API: both modes -----
    def clear(self) -> None:
        self._leave_plan_mode()
        self._path = self._preferred = self._family = self._style = None
        self._codepoints = frozenset()
        self._has_wght = False
        self._show_weight_row(False)
        self._render()

    def current_family(self) -> str | None:
        return self._plan_family if self._plan_mode else self._family

    def sample_text(self) -> str:
        return self.editor.toPlainText()

    def set_sample_text(self, text: str) -> None:
        if text != self.sample_text():
            self.editor.blockSignals(True)
            self.editor.setPlainText(text)
            self.editor.blockSignals(False)
            self._render()

    def missing_characters(self) -> list[str]:
        """Sample characters (sorted, unique, no spaces) that the shown font(s) cannot draw."""
        if not self._has_content():
            return []
        chars = {c for c in self.sample_text() if not c.isspace()}
        if self._plan_mode:
            return sorted(c for c in chars if self._source_of(ord(c)) is None)
        return sorted(c for c in chars if ord(c) not in self._codepoints)

    # ----- internals -----
    def _leave_plan_mode(self) -> None:
        self._plan_mode = False
        self._plan = {}
        self._source_of = None
        self._plan_family = None

    def _show_weight_row(self, visible: bool) -> None:
        for w in (self.weight_label, self.weight_slider, self.weight_value):
            w.setVisible(visible)

    def _has_content(self) -> bool:
        return bool(self._plan) if self._plan_mode else self._family is not None

    def _on_weight(self, value: int) -> None:
        self.weight_value.setText(str(value))
        self._render()

    def _make_font(self, size: int) -> QFont:
        wght = float(self.weight_slider.value()) if self._has_wght else None
        return make_font(self._path, self._style, self._preferred, size, wght)

    def _html(self) -> str:
        lines = []
        for line in self.sample_text().split("\n"):
            parts = []
            for ch in line:
                esc = html.escape(ch)
                if not ch.isspace() and ord(ch) not in self._codepoints:
                    esc = f'<span style="{MISSING_STYLE}">{esc}</span>'
                parts.append(esc)
            lines.append("".join(parts).replace("  ", "&nbsp; "))
        return "<br>".join(lines) or "&nbsp;"

    def _runs(self, line: str) -> list[tuple[FaceKey | None, bool, str]]:
        """Split one line into (key, missing, text) runs of consecutive characters drawn by the same material.

        Spaces are never "missing": they join the run before them (or the material of the next character).
        """
        runs: list[list] = []
        for ch in line:
            key = self._source_of(ord(ch))
            if ch.isspace():
                missing = False
                if key is None:
                    key = runs[-1][0] if runs else None
            else:
                missing = key is None
            if runs and runs[-1][0] == key and runs[-1][1] == missing:
                runs[-1][2].append(ch)
            else:
                runs.append([key, missing, [ch]])
        return [(key, missing, "".join(chars)) for key, missing, chars in runs]

    def _fill_plan_document(self, browser: QTextBrowser, size: int) -> None:
        fonts = {key: make_font(path, style, family, size, default_wght(axes))
                 for key, (path, style, family, axes) in self._plan.items()}
        fallback = next(iter(fonts.values()))
        browser.clear()
        doc = browser.document()
        doc.setDefaultFont(fallback)
        cursor = QTextCursor(doc)
        missing_brush = QColor(MISSING_COLOR)
        block_format = QTextBlockFormat()
        block_format.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)  # RTL lines stay on the left too
        for line_no, line in enumerate(self.sample_text().split("\n")):
            if line_no:
                cursor.insertBlock()
            cursor.setBlockFormat(block_format)
            for key, missing, text in self._runs(line):
                fmt = QTextCharFormat()
                fmt.setFont(fonts.get(key, fallback))
                if missing:
                    fmt.setBackground(missing_brush)
                cursor.insertText(text, fmt)

    def _render(self) -> None:
        for spin, browser in zip(self.size_spins, self.browsers):
            if not self._has_content():
                browser.setHtml(PLACEHOLDER_HTML)
            elif self._plan_mode:
                self._fill_plan_document(browser, spin.value())
            else:
                browser.document().setDefaultFont(self._make_font(spin.value()))
                browser.setHtml(self._html())
            doc = browser.document()
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(opt)
            doc.setTextWidth(max(browser.viewport().width(), 200))
            browser.setFixedHeight(int(doc.size().height()) + 12)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._render()
