"""Languages the UI talks about, and the plain words it uses for what a font draws.

A Language says which script groups it pins when a font is added for it, what a font needs to draw it well (the
picker's filter), and the sample lines the picker and the preview show. Nothing here touches Qt.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from fontplayground.catalog.face import FontFace
from fontplayground.engine.scripts import GROUP_IDS, LABELS, group_of
from fontplayground.ui.textutil import visible_chars

ANY = "any"
LATIN = "latin"
MIN_SHARE = 0.01          # a group below this share of a font's characters is not worth naming
MAX_PHRASES = 5           # phrases in a "Draws …" sentence before "and more"
MAX_ROLE_LANGUAGES = 2    # languages named in a card's role title
DRAWS_NOTHING = "Draws nothing — the fonts above already cover everything it has."


@dataclass(frozen=True)
class Language:
    id: str
    label: str
    groups: tuple[str, ...]                     # script groups pinned to a font added for this language
    min_counts: tuple[tuple[str, int], ...]     # every (group, n) must hold for "draws it well"
    markers: str                                # characters a font must all have ("" = none)
    picker_sample: str                          # the line each picker row shows in its font
    text_sample: str                            # the line added to the preview sample when it has none of these

    @property
    def short_label(self) -> str:
        return SHORT_LABELS.get(self.id, self.label)


LANGUAGES: tuple[Language, ...] = (
    Language("latin", "Letters (Latin)", ("latin",), (("latin", 90),), "", "Aa Bb Cc 0123",
             "The quick brown fox jumps over the lazy dog 0123456789"),
    Language("chinese_s", "Chinese (Simplified)", ("han",), (("han", 2500),), "们这说国门来", "你好世界 永和九年 Aa 123",
             "你好，世界！欢迎使用字体游乐场。"),
    Language("chinese_t", "Chinese (Traditional)", ("han",), (("han", 2500),), "們這說國門來", "你好世界 永和九年 Aa 123",
             "歡迎使用字體遊樂場。"),
    Language("japanese", "Japanese", ("kana",), (("kana", 150), ("han", 1000)), "", "あいうえお 漢字 Aa",
             "こんにちは、カタカナとひらがな。"),
    Language("korean", "Korean", ("hangul",), (("hangul", 2000),), "", "한글 안녕 Aa", "안녕하세요, 세계!"),
    Language("greek", "Greek", ("greek",), (("greek", 60),), "", "Αα Ββ Γγ Δδ", "Γειά σου Κόσμε"),
    Language("cyrillic", "Cyrillic", ("cyrillic",), (("cyrillic", 60),), "", "Аа Бб Вв Гг", "Привет, мир"),
    Language("armenian_georgian", "Armenian & Georgian", ("armenian_georgian",), (("armenian_georgian", 40),), "",
             "Աա Բբ ა ბ", "Բարեւ աշխարհ გამარჯობა"),
    Language("hebrew", "Hebrew", ("hebrew",), (("hebrew", 27),), "", "שלום Aa", "שלום עולם"),
    Language("arabic", "Arabic", ("arabic",), (("arabic", 40),), "", "مرحبا Aa", "مرحبا بالعالم"),
    Language("indic", "Hindi & Indic", ("indic",), (("indic", 60),), "", "नमस्ते Aa", "नमस्ते दुनिया"),
    Language("southeast_asian", "Thai, Lao, Khmer, Myanmar", ("southeast_asian",), (("southeast_asian", 60),), "",
             "สวัสดี Aa", "สวัสดีชาวโลก"),
    Language("symbols", "Symbols & emoji", ("symbols", "emoji"), (("symbols", 300),), "", "→ ✓ ☺ ★ ①",
             "→ ✓ ☺ ★ ♫ ① ②"),
    Language(ANY, "Any language", (), (), "", "Aa 你好 あ 한", ""),
)
SHORT_LABELS = {"latin": "Letters", "chinese_s": "Chinese", "chinese_t": "Chinese", "indic": "Indic",
                "southeast_asian": "Thai & SE Asian"}
_BY_ID = {lang.id: lang for lang in LANGUAGES}
_ORDER = {lang.id: i for i, lang in enumerate(LANGUAGES)}
# The language a missing character or a supplied group points to ("other" points nowhere).
GROUP_LANGUAGE = {
    "latin": "latin", "greek": "greek", "cyrillic": "cyrillic", "armenian_georgian": "armenian_georgian",
    "hebrew": "hebrew", "arabic": "arabic", "indic": "indic", "southeast_asian": "southeast_asian",
    "hangul": "korean", "kana": "japanese", "han": "chinese_s", "cjk_symbols": "chinese_s",
    "symbols": "symbols", "emoji": "symbols",
}
GROUP_PHRASES = {
    "latin": "letters, numbers and punctuation", "han": "Chinese characters", "kana": "Japanese kana",
    "hangul": "Korean Hangul", "cjk_symbols": "CJK punctuation", "symbols": "symbols", "emoji": "emoji",
    "indic": "Indic scripts", "southeast_asian": "Thai and Southeast Asian scripts", "other": "other characters",
}

OLD_DEFAULT_SAMPLE = (   # the default before the mixer; a stored sample equal to it is replaced by DEFAULT_SAMPLE
    "The quick brown fox jumps over the lazy dog 0123456789\n"
    "Ärger Œuvre Ñandú Ωμέγα Привет, мир\n"
    "漢字 かな カナ 한글 你好，世界\n"
    "مرحبا بالعالم  שלום עולם  नमस्ते\n"
    "€ £ ¥ § ¶ → ✓ ☺ ①"
)
DEFAULT_SAMPLE = (
    "The quick brown fox jumps over the lazy dog 0123456789\n"
    "你好，世界！欢迎使用字体游乐场。\n"
    "こんにちは、カタカナとひらがな。\n"
    "“Quotes” — dashes… ① → €"
)
SAMPLES: dict[str, tuple[str, str]] = {   # preset id -> (menu label, text)
    "mixed": ("Mixed (English, Chinese, Japanese)", DEFAULT_SAMPLE),
    "english": ("English", "The quick brown fox jumps over the lazy dog.\n"
                           "Sphinx of black quartz, judge my vow! 0123456789\n"
                           "“Quotes” ‘apostrophes’ — dashes… (1/2) @ # & € £ %"),
    "chinese_s": ("Chinese (Simplified)", "你好，世界！欢迎使用字体游乐场。\n天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。\n"
                                          "“引号”——破折号……《书名号》①②③"),
    "chinese_t": ("Chinese (Traditional)", "你好，世界！歡迎使用字體遊樂場。\n天地玄黃，宇宙洪荒。日月盈昃，辰宿列張。"),
    "japanese": ("Japanese", "こんにちは、世界！フォントの遊び場へようこそ。\nいろはにほへと ちりぬるを わかよたれそ つねならむ\n"
                             "カタカナ ひらがな 漢字「かぎかっこ」"),
    "korean": ("Korean", "안녕하세요, 세계! 글꼴 놀이터에 오신 것을 환영합니다.\n다람쥐 헌 쳇바퀴에 타고파"),
    "all": ("All languages", OLD_DEFAULT_SAMPLE),
}


def language(language_id: str) -> Language:
    """The Language with this id (KeyError for an unknown one)."""
    return _BY_ID[language_id]


def covers_well(face: FontFace, lang: Language) -> bool:
    """True when the face has at least min_counts characters of each group and every marker character."""
    counts = face.counts
    return (all(counts.get(g, 0) >= n for g, n in lang.min_counts)
            and all(ord(c) in face.codepoints for c in lang.markers))


def languages_for_missing(chars: Iterable[str]) -> list[Language]:
    """The languages the characters belong to, most characters first (ties in LANGUAGES order)."""
    tally: dict[str, int] = {}
    for c in chars:
        lang_id = GROUP_LANGUAGE.get(group_of(ord(c)))
        if lang_id is not None:
            tally[lang_id] = tally.get(lang_id, 0) + 1
    return [_BY_ID[i] for i in sorted(tally, key=lambda i: (-tally[i], _ORDER[i]))]


def join_labels(langs: Iterable[Language], limit: int = MAX_ROLE_LANGUAGES, joiner: str = " and ") -> str:
    """'Chinese and Japanese': the short labels without repeats, at most `limit` of them."""
    labels = list(dict.fromkeys(lang.short_label for lang in langs))[:limit]
    return joiner.join(labels)


def _named_groups(tally: Mapping[str, int]) -> list[str]:
    """Groups of the tally worth naming: largest first (GROUPS order on ties), those under MIN_SHARE dropped."""
    total = sum(tally.values())
    ranked = sorted((g for g, n in tally.items() if n > 0), key=lambda g: (-tally[g], GROUP_IDS.index(g)))
    return [g for i, g in enumerate(ranked) if i == 0 or tally[g] >= MIN_SHARE * total]


def role_title(tally: Mapping[str, int]) -> str:
    """The upper-case role line of a font that is not the main one: 'FOR CHINESE & JAPANESE', 'ADDS NOTHING'…"""
    groups = _named_groups(tally)
    if not groups:
        return "ADDS NOTHING"
    langs = [_BY_ID[GROUP_LANGUAGE[g]] for g in groups if g in GROUP_LANGUAGE]
    named = [lang for lang in langs if lang.id != "symbols"] or langs   # symbols only when that is all it does
    if not named:
        return "FILLS IN THE REST"
    return "FOR " + join_labels(named, joiner=" & ").upper()


def _join_and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def draws_text(tally: Mapping[str, int]) -> str:
    """'Draws Chinese characters, Japanese kana and CJK punctuation.' for a font's share of the result."""
    groups = _named_groups(tally)
    if not groups:
        return DRAWS_NOTHING
    phrases = [GROUP_PHRASES.get(g, LABELS.get(g, g)) for g in groups]
    if "latin" in groups:
        rest = [p for g, p in zip(groups, phrases) if g != "latin"]
        head = GROUP_PHRASES["latin"]
        if not rest:
            return f"Draws {head}."
        shown = rest[:MAX_PHRASES - 1] + (["more"] if len(rest) > MAX_PHRASES - 1 else [])
        return f"Draws {head}, plus {_join_and(shown)}."
    shown = phrases[:MAX_PHRASES] + (["more"] if len(phrases) > MAX_PHRASES else [])
    return f"Draws {_join_and(shown)}."


def sample_has_language(text: str, lang: Language) -> bool:
    """True when the text has a visible character of one of the language's groups (always for Any language)."""
    if not lang.groups:
        return True
    return any(group_of(ord(c)) in lang.groups for c in visible_chars(text))


def with_language_line(text: str, lang: Language) -> str:
    """The text with the language's sample line added at the end when it has none of the language's characters."""
    if not lang.text_sample or sample_has_language(text, lang):
        return text
    body = text.rstrip("\n")
    return f"{body}\n{lang.text_sample}" if body else lang.text_sample
