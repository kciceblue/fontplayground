"""The preview: the sample text drawn the way the recipe would draw it, editable in place.

MixPreview is a plain-text editor. Nothing it shows is written into the document: MixHighlighter (a
QSyntaxHighlighter) lays a format over every character — the font that draws it, by Mix.source_of, the very rule
the build uses — so typing, IME composition and undo work on untouched text. A character no font draws is shown
in the main font (a box) on the `missing` colour; whitespace and invisible characters join the run before them
and are never missing.

What is drawn, first match wins: a trial (the picker's candidate tried in), the built font (one file, missing
where the result lacks the character), the recipe's mix. The empty mix draws the text faintly in the application
font, where Qt may borrow glyphs from any font, since there is nothing to be honest about yet.
"""
from __future__ import annotations

from itertools import groupby
from operator import itemgetter

from PySide6.QtCore import QEvent, QMimeData, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QSyntaxHighlighter, QTextBlock, QTextCharFormat, QTextCursor,
                           QTextDocument, QTextDocumentFragment)
from PySide6.QtWidgets import QTextEdit, QWidget

from fontplayground.ui.fonts import make_font, mix_font
from fontplayground.ui.mix import EMPTY_MIX, Mix
from fontplayground.ui.textutil import is_ignorable, visible_chars
from fontplayground.ui.theme import LIGHT, Theme

DEFAULT_POINT_SIZE = 30
PLACEHOLDER_TEXT = "Type something to see it in your font"

STYLE = """
QTextEdit#preview { background: $surface; color: $text; border: 1px solid $border; border-radius: 10px;
                    padding: 14px; selection-background-color: $accent; selection-color: $on_accent; }
"""

Built = tuple[str, frozenset[int]]     # a built font: its file and the code points it has


def _units(ch: str) -> int:
    """UTF-16 code units of one character — what Qt counts positions in: 2 above U+FFFF, else 1."""
    return 2 if ord(ch) > 0xFFFF else 1


class MixHighlighter(QSyntaxHighlighter):
    """Gives each character of a document the format of the font that draws it, without editing the document.

    Modes: MIX (format i = font i of the Mix), BUILT (format 0 = the built font file, missing where its code points
    lack the character) and EMPTY (format 0 = the application font in `faint`; nothing is missing). One format per
    font is made per configuration, plus the missing format: the main font on the `missing` colour.
    """
    MIX, BUILT, EMPTY = "mix", "built", "empty"

    def __init__(self, document: QTextDocument, theme: Theme = LIGHT) -> None:
        super().__init__(document)
        self._mix = EMPTY_MIX
        self._built: Built | None = None
        self._size = float(DEFAULT_POINT_SIZE)
        self._colour = False
        self._theme = theme
        self._formats: list[QTextCharFormat] = []
        self._missing = QTextCharFormat()
        self._index_of: dict[int, int | None] = {}    # code point -> format index (None: missing), this configuration
        self._make_formats()

    # ----- configuration -----
    def configure(self, mix: Mix = EMPTY_MIX, built: Built | None = None, size: float = DEFAULT_POINT_SIZE,
                  colour_by_font: bool = False, theme: Theme = LIGHT) -> None:
        """Draw `mix` — or the built font when `built` is given — with these settings; re-highlights at once."""
        self._mix, self._built = mix, built
        self._size, self._colour, self._theme = float(size), bool(colour_by_font), theme
        self._index_of = {}
        self._make_formats()
        self.rehighlight()

    @property
    def mode(self) -> str:
        if self._built is not None:
            return self.BUILT
        return self.MIX if self._mix.fonts else self.EMPTY

    def base_font(self) -> QFont:
        """Format 0's font at the size: the main font, the built font or the placeholder font."""
        return self._formats[0].font()

    # ----- who draws what -----
    def is_missing(self, cp: int) -> bool:
        return self._index(cp) is None

    def sources(self, line: str) -> list[int | None]:
        """Per character of one line: the index of the format it takes (the font drawing it), None where missing.

        Whitespace and invisible characters take the run before them — at the start of a line the next visible
        character's font, font 0 when that one is missing or there is none — and are never missing.
        """
        out: list[int | None] = []
        before: int | None = None           # the font of the run before (0 after a missing character)
        for i, ch in enumerate(line):
            if is_ignorable(ch):
                if before is None:
                    before = self._lookahead(line, i)
                out.append(before)
            else:
                index = self._index(ord(ch))
                out.append(index)
                before = 0 if index is None else index
        return out

    def _lookahead(self, line: str, start: int) -> int:
        for ch in line[start:]:
            if not is_ignorable(ch):
                index = self._index(ord(ch))
                return 0 if index is None else index
        return 0

    def _index(self, cp: int) -> int | None:
        if cp in self._index_of:
            return self._index_of[cp]
        if self._built is not None:
            index = 0 if cp in self._built[1] else None
        elif self._mix.fonts:
            index = self._mix.source_of(cp)
        else:
            index = 0
        self._index_of[cp] = index
        return index

    # ----- drawing -----
    def highlightBlock(self, text: str) -> None:  # noqa: N802
        pos = 0                                           # UTF-16 units: setFormat's positions
        for index, run in groupby(zip(text, self.sources(text)), key=itemgetter(1)):
            length = sum(_units(ch) for ch, _index in run)
            self.setFormat(pos, length, self._missing if index is None else self._formats[index])
            pos += length

    def _make_formats(self) -> None:
        size, theme = self._size, self._theme
        if self._built is not None:
            fonts = [make_font(self._built[0], None, None, size)]   # the family comes from the file
        elif self._mix.fonts:
            fonts = [mix_font(mf, size) for mf in self._mix.fonts]
        else:
            placeholder = QFont(QGuiApplication.font())             # font merging allowed: legible, not honest
            placeholder.setPointSizeF(size)
            fonts = [placeholder]
        self._formats = []
        for i, font in enumerate(fonts):
            fmt = QTextCharFormat()
            fmt.setFont(font)
            if self.mode == self.EMPTY:
                fmt.setForeground(QColor(theme.faint))
            elif self._colour and self.mode == self.MIX:
                fmt.setForeground(QColor(theme.mix_colour(i)))
            self._formats.append(fmt)
        self._missing = QTextCharFormat()
        self._missing.setFont(fonts[0])
        self._missing.setBackground(QColor(theme.missing))


class MixPreview(QTextEdit):
    """The editable sample, drawn by MixHighlighter. The model owns the text; this widget reports edits."""
    textEdited = Signal(str)     # the user changed the text: typing, pasting, undo, a sample preset
    shownChanged = Signal()      # the text or what draws it changed: missing_characters() may differ

    def __init__(self, parent: QWidget | None = None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.setObjectName("preview")
        self.setAcceptRichText(False)
        self.setPlaceholderText(PLACEHOLDER_TEXT)
        self._theme = theme
        self._mix: Mix = EMPTY_MIX
        self._trial: Mix | None = None
        self._built: Built | None = None
        self._size: float = DEFAULT_POINT_SIZE
        self._colour = False
        self._text = ""              # the text as last seen: re-highlighting reports a change that is none
        self._quiet = False          # set_text is replacing the text: not the user's edit
        self.highlighter = MixHighlighter(self.document(), theme)
        self.textChanged.connect(self._on_text_changed)
        self.setStyleSheet(theme.render(STYLE))
        self._redraw()

    # ----- text -----
    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """Show `text` (the model's sample). Not an edit: no textEdited, and nothing at all when it is shown already."""
        if text == self.toPlainText():
            return
        self._quiet = True
        try:
            self.setPlainText(text)
        finally:
            self._quiet = False

    def replace_text(self, text: str) -> None:
        """Replace the whole text as one edit the user can undo (Ctrl+Z); emits textEdited like typing does."""
        if text == self.toPlainText():
            return
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        return source.hasText() or source.hasHtml()

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        """Paste and drop as plain text: the fonts come from the mix, never from the clipboard."""
        if source.hasText():
            text = source.text()
        elif source.hasHtml():
            text = QTextDocumentFragment.fromHtml(source.html()).toPlainText()
        else:
            return
        if text:
            cursor = self.textCursor()
            cursor.insertText(text)
            self.setTextCursor(cursor)

    # ----- what is drawn -----
    def set_mix(self, mix: Mix) -> None:
        self._mix = mix
        self._redraw()

    def set_trial(self, mix: Mix | None) -> None:
        """Draw a candidate mix instead of the recipe (and of the built font) until it is cleared with None."""
        self._trial = mix
        self._redraw()

    def set_built(self, path: str | None, codepoints=frozenset()) -> None:
        """Draw the built font file instead of the mix (None: back to the mix); `codepoints` are what it has."""
        self._built = (path, frozenset(codepoints)) if path else None
        self._redraw()

    def shown_mix(self) -> Mix:
        """The trial when there is one, else the recipe's mix."""
        return self._trial if self._trial is not None else self._mix

    def set_point_size(self, pt: float) -> None:
        self._size = pt
        self._redraw()

    def point_size(self) -> float:
        return self._size

    def set_colour_by_font(self, on: bool) -> None:
        self._colour = bool(on)
        self._redraw()

    def colour_by_font(self) -> bool:
        return self._colour

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        self._redraw()

    # ----- reading -----
    def missing_characters(self) -> list[str]:
        """Visible characters of the text (sorted, unique) that nothing shown draws; [] for the empty mix."""
        return [c for c in visible_chars(self.toPlainText()) if self.highlighter.is_missing(ord(c))]

    def source_at(self, i: int) -> int | None:
        """The index of the font drawing text()[i] in what is shown (0 for the built font); None when no font
        draws it — or when there are no fonts at all (the empty mix)."""
        block, k = self._block_at(i)
        if self.highlighter.mode == MixHighlighter.EMPTY:
            return None
        return self.highlighter.sources(block.text() + "\n")[k]

    def format_at(self, i: int) -> QTextCharFormat:
        """The format the highlighter laid over text()[i] (an empty format for a line break)."""
        block, k = self._block_at(i)
        pos = sum(_units(ch) for ch in block.text()[:k])
        for r in block.layout().formats():
            if r.start <= pos < r.start + r.length:
                return QTextCharFormat(r.format)   # a copy: the range's own format dies with the list
        return QTextCharFormat()

    # ----- internals -----
    def _block_at(self, i: int) -> tuple[QTextBlock, int]:
        """The block holding text()[i] and i's index in that block's text (its length: the line break after it)."""
        if not 0 <= i < len(self.toPlainText()):
            raise IndexError(i)
        block, start = self.document().begin(), 0
        while block.isValid():
            n = len(block.text())
            if i <= start + n:
                return block, i - start
            start += n + 1
            block = block.next()
        raise IndexError(i)

    def _redraw(self) -> None:
        if self._trial is not None:
            mix, built = self._trial, None
        else:
            mix, built = self._mix, self._built
        self.highlighter.configure(mix, built, self._size, self._colour, self._theme)
        self.document().setDefaultFont(self.highlighter.base_font())   # the caret and empty lines
        self.shownChanged.emit()

    def _on_text_changed(self) -> None:
        text = self.toPlainText()
        if text == self._text:
            return
        self._text = text
        if not self._quiet:
            self.textEdited.emit(text)
        self.shownChanged.emit()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)   # QTextEdit hands its own font to the document here: the mix's is wanted
        if not hasattr(self, "highlighter"):
            return                   # still being built
        if event.type() == QEvent.Type.ApplicationFontChange:
            self._redraw()           # the empty mix's placeholder font is the application font
        elif event.type() == QEvent.Type.FontChange:
            self.document().setDefaultFont(self.highlighter.base_font())
