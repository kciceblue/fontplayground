"""Sample-text preview of one font file that is honest about missing characters."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QTextOption
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QSlider, QSpinBox, QTextBrowser, QVBoxLayout,
                               QWidget)

from fontplayground.catalog.face import FontFace

DEFAULT_SAMPLE = (
    "The quick brown fox jumps over the lazy dog 0123456789\n"
    "Ärger Œuvre Ñandú Ωμέγα Привет, мир\n"
    "漢字 かな カナ 한글 你好，世界\n"
    "مرحبا بالعالم  שלום עולם  नमस्ते\n"
    "€ £ ¥ § ¶ → ✓ ☺ ①"
)
MISSING_STYLE = "background-color:#ffb3b3;"


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


class PreviewWidget(QWidget):
    sampleChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, sizes=(12, 24, 48)) -> None:
        super().__init__(parent)
        self._family: str | None = None
        self._style: str | None = None
        self._codepoints: frozenset[int] = frozenset()
        self._has_wght = False

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
        for w in (self.weight_label, self.weight_slider, self.weight_value):
            w.hide()

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
            row.addWidget(spin, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(browser, 1)
            layout.addLayout(row)
            self.size_spins.append(spin)
            self.browsers.append(browser)
        layout.addStretch(1)
        self._render()

    # ----- public API -----
    def set_face(self, face: FontFace) -> None:
        self.set_font_file(face.path, face.style, face.codepoints, face.axes, face.family)

    def set_font_file(self, path: str, style: str | None, codepoints, axes=(), preferred_family: str | None = None) -> None:
        self._family = font_loader().family_for(path, preferred_family)
        self._style = style
        self._codepoints = frozenset(codepoints)
        wght = next((a for a in axes if a[0] == "wght"), None)
        self._has_wght = wght is not None
        for w in (self.weight_label, self.weight_slider, self.weight_value):
            w.setVisible(self._has_wght)
        if wght:
            self.weight_slider.blockSignals(True)
            self.weight_slider.setRange(int(wght[1]), int(wght[3]))
            self.weight_slider.setValue(int(wght[2]))
            self.weight_slider.blockSignals(False)
            self.weight_value.setText(str(int(wght[2])))
        self._render()

    def clear(self) -> None:
        self._family = None
        self._codepoints = frozenset()
        self._has_wght = False
        for w in (self.weight_label, self.weight_slider, self.weight_value):
            w.hide()
        self._render()

    def current_family(self) -> str | None:
        return self._family

    def sample_text(self) -> str:
        return self.editor.toPlainText()

    def set_sample_text(self, text: str) -> None:
        if text != self.sample_text():
            self.editor.blockSignals(True)
            self.editor.setPlainText(text)
            self.editor.blockSignals(False)
            self._render()

    def missing_characters(self) -> list[str]:
        if self._family is None:
            return []
        chars = {c for c in self.sample_text() if not c.isspace()}
        return sorted(c for c in chars if ord(c) not in self._codepoints)

    # ----- internals -----
    def _on_weight(self, value: int) -> None:
        self.weight_value.setText(str(value))
        self._render()

    def _make_font(self, size: int) -> QFont:
        if self._style:
            font = QFontDatabase.font(self._family, self._style, size)
        else:
            font = QFont(self._family, size)
        font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        if self._has_wght:
            font.setVariableAxis(QFont.Tag("wght"), float(self.weight_slider.value()))
        return font

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

    def _render(self) -> None:
        for spin, browser in zip(self.size_spins, self.browsers):
            doc = browser.document()
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(opt)
            if self._family is None:
                browser.setHtml('<span style="color:gray">Select a font to preview</span>')
            else:
                doc.setDefaultFont(self._make_font(spin.value()))
                browser.setHtml(self._html())
            doc.setTextWidth(max(browser.viewport().width(), 200))
            browser.setFixedHeight(int(doc.size().height()) + 12)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._render()
