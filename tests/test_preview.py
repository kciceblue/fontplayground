"""MixPreview: every character in the font that draws it, honest about the ones no font draws."""
import time

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QFont, QTextCursor, QTextFormat

from fontplayground.catalog.face import read_faces
from fontplayground.ui.mix import EMPTY_MIX, Mix, MixFont
from fontplayground.ui.preview import DEFAULT_POINT_SIZE, PLACEHOLDER_TEXT, MixHighlighter, MixPreview
from fontplayground.ui.theme import DARK, LIGHT


def _face(font_dir, name):
    (face,) = read_faces(font_dir / name)
    return face


def _mix(*fonts, rules=None) -> Mix:
    """A Mix of faces or MixFonts (a bare face is drawn as it is, at 100 %)."""
    return Mix(tuple(f if isinstance(f, MixFont) else MixFont(f) for f in fonts), rules or {}, 0)


def _preview(qtbot, mix=None, text=None, theme=LIGHT) -> MixPreview:
    w = MixPreview(theme=theme)
    qtbot.addWidget(w)
    if mix is not None:
        w.set_mix(mix)
    if text is not None:
        w.set_text(text)
    return w


def _bg(fmt) -> str | None:
    return fmt.background().color().name() if fmt.hasProperty(QTextFormat.Property.BackgroundBrush) else None


def _fg(fmt) -> str | None:
    return fmt.foreground().color().name() if fmt.hasProperty(QTextFormat.Property.ForegroundBrush) else None


def _ranges(w: MixPreview, block_number: int = 0) -> list[tuple[int, int, str]]:
    """(start, length, family) of the highlighter's format ranges in one block, in UTF-16 units."""
    block = w.document().findBlockByNumber(block_number)
    return [(r.start, r.length, r.format.font().family()) for r in block.layout().formats()]


# ----- the basics --------------------------------------------------------------------------------
def test_preview_is_a_plain_text_editor_with_a_placeholder(qtbot):
    w = _preview(qtbot)
    assert isinstance(w.highlighter, MixHighlighter)
    assert w.objectName() == "preview"
    assert not w.acceptRichText()
    assert w.placeholderText() == PLACEHOLDER_TEXT == "Type something to see it in your font"
    assert w.point_size() == DEFAULT_POINT_SIZE == 30
    assert not w.colour_by_font()
    assert w.shown_mix() == EMPTY_MIX and w.text() == ""


def test_each_character_is_drawn_in_the_font_that_draws_it(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b), "ab漢c")
    assert [w.format_at(i).font().family() for i in range(4)] == ["Fixture A", "Fixture A", "Fixture B", "Fixture A"]
    assert [w.source_at(i) for i in range(4)] == [0, 0, 1, 0]
    assert w.missing_characters() == []
    assert all(_bg(w.format_at(i)) is None for i in range(4))
    assert w.format_at(0).font().styleStrategy() & QFont.StyleStrategy.NoFontMerging
    assert _ranges(w) == [(0, 2, "Fixture A"), (2, 1, "Fixture B"), (3, 1, "Fixture A")]   # runs merged
    assert w.document().defaultFont().family() == "Fixture A"                              # caret, empty lines


def test_a_rule_decides_who_draws_a_character_two_fonts_have(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b, rules={"latin": 1}), "ab")
    assert [w.source_at(i) for i in range(2)] == [1, 1]
    assert w.format_at(0).font().family() == "Fixture B"


def test_size_and_scale_reach_the_formats(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, MixFont(b, None, 0.8)), "a漢")
    assert w.format_at(0).font().pointSizeF() == 30
    assert w.format_at(1).font().pointSizeF() == 30 * 0.8
    w.set_point_size(20)
    assert w.point_size() == 20
    assert w.format_at(0).font().pointSizeF() == 20 and w.format_at(1).font().pointSizeF() == 16
    assert w.document().defaultFont().pointSizeF() == 20


def test_a_variable_font_is_drawn_at_its_weight(qtbot, font_dir):
    v = _face(font_dir, "V.ttf")
    w = _preview(qtbot, _mix(MixFont(v, 700)), "ab")
    assert w.format_at(0).font().family() == "Fixture V"
    assert w.format_at(0).font().variableAxisValue(QFont.Tag("wght")) == 700.0


# ----- missing characters ---------------------------------------------------------------------------
def test_a_missing_character_gets_the_missing_background_but_spaces_and_joiners_never_do(qtbot, font_dir):
    a = _face(font_dir, "A.ttf")
    w = _preview(qtbot, _mix(a), "a 漢‍b")
    assert _bg(w.format_at(2)) == LIGHT.missing
    assert w.format_at(2).font().family() == "Fixture A"          # drawn in the main font: a box
    assert _bg(w.format_at(1)) is None and _bg(w.format_at(3)) is None
    assert w.source_at(2) is None
    assert w.source_at(1) == 0 and w.source_at(3) == 0            # they take the run before them
    assert w.missing_characters() == ["漢"]
    w.set_text(" 漢 ")                                             # a leading space is never missing either
    assert _bg(w.format_at(0)) is None and _bg(w.format_at(1)) == LIGHT.missing and _bg(w.format_at(2)) is None


def test_a_space_takes_the_font_of_the_run_before_it(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, MixFont(b, None, 0.5)), " 漢 a")
    assert [w.source_at(i) for i in range(4)] == [1, 1, 1, 0]     # the leading space looks ahead
    assert w.format_at(2).font().pointSizeF() == 15               # the space after 漢 is as small as 漢


def test_characters_above_the_basic_plane_do_not_shift_later_formats(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b), "𠀀ab漢")                       # U+20000 is two UTF-16 units
    assert _ranges(w) == [(0, 2, "Fixture A"), (2, 2, "Fixture A"), (4, 1, "Fixture B")]
    assert _bg(w.format_at(0)) == LIGHT.missing
    assert w.format_at(1).font().family() == "Fixture A" and _bg(w.format_at(1)) is None
    assert w.format_at(3).font().family() == "Fixture B" and _bg(w.format_at(3)) is None
    assert [w.source_at(i) for i in range(4)] == [None, 0, 0, 1]
    assert w.missing_characters() == ["𠀀"]


def test_each_line_is_its_own_block(qtbot, font_dir):
    a = _face(font_dir, "A.ttf")
    w = _preview(qtbot, _mix(a), "a\n漢\nb")
    assert w.document().blockCount() == 3
    assert _bg(w.format_at(2)) == LIGHT.missing
    assert w.format_at(4).font().family() == "Fixture A" and _bg(w.format_at(4)) is None
    assert w.source_at(2) is None and w.source_at(4) == 0


# ----- colour by font -------------------------------------------------------------------------------
def test_colour_by_font_colours_each_font_and_turns_off_again(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b), "a漢한")
    assert _fg(w.format_at(0)) is None
    w.set_colour_by_font(True)
    assert w.colour_by_font()
    assert _fg(w.format_at(0)) == LIGHT.mix_colour(0) and _fg(w.format_at(1)) == LIGHT.mix_colour(1)
    assert _fg(w.format_at(2)) is None and _bg(w.format_at(2)) == LIGHT.missing
    w.set_colour_by_font(False)
    assert all(_fg(w.format_at(i)) is None for i in range(3))


def test_apply_theme_recolours_everything(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b), "a漢한")
    w.set_colour_by_font(True)
    assert DARK.surface not in w.styleSheet() and LIGHT.surface in w.styleSheet()
    w.apply_theme(DARK)
    assert _bg(w.format_at(2)) == DARK.missing
    assert _fg(w.format_at(1)) == DARK.mix_colour(1)
    assert DARK.surface in w.styleSheet()


# ----- trial and built ------------------------------------------------------------------------------
def test_a_trial_overrides_the_mix_until_it_is_cleared(qtbot, font_dir):
    a, b, c = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf"), _face(font_dir, "C.ttf")
    mix, trial = _mix(a), _mix(a, b)
    w = _preview(qtbot, mix, "a漢")
    assert w.source_at(1) is None and w.missing_characters() == ["漢"]
    w.set_trial(trial)
    assert w.shown_mix() is trial
    assert w.source_at(1) == 1 and w.missing_characters() == []
    assert w.format_at(1).font().family() == "Fixture B"
    newer = _mix(a, c)
    w.set_mix(newer)                                   # the recipe moved on while trying: the trial still shows
    assert w.shown_mix() is trial and w.source_at(1) == 1
    w.set_trial(None)
    assert w.shown_mix() is newer
    assert w.source_at(1) is None and _bg(w.format_at(1)) == LIGHT.missing


def test_the_built_font_draws_everything_and_marks_what_it_lacks(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b), "ab漢")
    w.set_built(a.path, a.codepoints)                  # stands in for a built result that lacks 漢
    assert [w.format_at(i).font().family() for i in range(3)] == ["Fixture A"] * 3
    assert [w.source_at(i) for i in range(3)] == [0, 0, None]
    assert _bg(w.format_at(2)) == LIGHT.missing and _bg(w.format_at(0)) is None
    assert w.missing_characters() == ["漢"]
    trial = _mix(a, b)
    w.set_trial(trial)                                 # a trial wins over the built font
    assert w.source_at(2) == 1 and w.missing_characters() == []
    w.set_trial(None)
    assert w.source_at(2) is None                      # back to the built font
    w.set_built(None)
    assert w.source_at(2) == 1 and w.format_at(2).font().family() == "Fixture B"


# ----- editing --------------------------------------------------------------------------------------
def test_typing_emits_text_edited_and_set_text_does_not(qtbot, font_dir):
    w = _preview(qtbot, _mix(_face(font_dir, "A.ttf")))
    seen: list[str] = []
    w.textEdited.connect(seen.append)
    w.set_text("ab")
    w.set_text("ab")                                   # the same text again: nothing at all
    w.set_colour_by_font(True)                         # re-highlighting is not an edit
    w.set_point_size(12)
    assert seen == [] and w.text() == "ab"
    w.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClicks(w, "c1")
    assert seen == ["abc", "abc1"] and w.text() == "abc1"
    assert w.source_at(3) == 0                         # typed text is highlighted as it arrives


def test_replace_text_is_one_undoable_edit(qtbot, font_dir):
    w = _preview(qtbot, _mix(_face(font_dir, "A.ttf")), "mine")
    seen: list[str] = []
    w.textEdited.connect(seen.append)
    w.replace_text("preset\nsecond line")
    assert w.text() == "preset\nsecond line" and seen == ["preset\nsecond line"]
    w.set_colour_by_font(True)
    w.set_point_size(40)
    w.document().undo()
    assert w.text() == "mine" and seen[-1] == "mine"
    assert not w.document().isUndoAvailable()          # exactly one step
    w.document().redo()
    assert w.text() == "preset\nsecond line"


def test_pasting_rich_text_inserts_plain_text(qtbot, font_dir):
    w = _preview(qtbot, _mix(_face(font_dir, "A.ttf")))
    seen: list[str] = []
    w.textEdited.connect(seen.append)
    html_only = QMimeData()
    html_only.setHtml("<b>bold</b> <span style='color:#ff0000; font-size:40pt'>big</span>")
    assert w.canInsertFromMimeData(html_only)
    w.insertFromMimeData(html_only)
    assert w.text() == "bold big" and seen == ["bold big"]
    both = QMimeData()
    both.setText(" plain")
    both.setHtml("<i>ignored</i>")
    w.insertFromMimeData(both)
    assert w.text() == "bold big plain"
    it = w.document().begin().begin()                  # nothing of the HTML's formatting reached the document
    while not it.atEnd():
        fmt = it.fragment().charFormat()
        assert not fmt.hasProperty(QTextFormat.Property.FontWeight)
        assert not fmt.hasProperty(QTextFormat.Property.FontItalic)
        assert not fmt.hasProperty(QTextFormat.Property.ForegroundBrush)
        it += 1


# ----- the empty mix --------------------------------------------------------------------------------
def test_the_empty_mix_draws_a_faint_placeholder_and_misses_nothing(qtbot):
    w = _preview(qtbot, text="abc 漢\n𠀀")
    assert w.shown_mix() == EMPTY_MIX
    assert w.missing_characters() == []
    fmt = w.format_at(0)
    assert _fg(fmt) == LIGHT.faint and _bg(fmt) is None and _bg(w.format_at(4)) is None
    assert not (fmt.font().styleStrategy() & QFont.StyleStrategy.NoFontMerging)   # Qt may borrow glyphs
    assert fmt.font().pointSizeF() == DEFAULT_POINT_SIZE
    assert w.source_at(0) is None
    w.set_colour_by_font(True)
    w.set_point_size(12)
    w.apply_theme(DARK)
    assert _fg(w.format_at(0)) == DARK.faint and w.format_at(0).font().pointSizeF() == 12
    assert _fg(w.format_at(6)) == DARK.faint


def test_many_alternating_characters_highlight_quickly(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    w = _preview(qtbot, _mix(a, b))
    text = "ab漢" * 1000
    started = time.perf_counter()
    w.set_text(text)
    w.set_colour_by_font(True)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"3,000 characters took {elapsed:.2f}s"
    assert len(_ranges(w)) == 2000
