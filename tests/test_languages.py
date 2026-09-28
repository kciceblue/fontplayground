import pytest

from fontplayground.ui import languages
from fontplayground.ui.languages import (ANY, DEFAULT_SAMPLE, LANGUAGES, OLD_DEFAULT_SAMPLE, SAMPLES, covers_well,
                                         draws_text, join_labels, language, languages_for_missing, role_title,
                                         sample_has_language, with_language_line)
from tests.fixtures import cps, fake_face

HAN_3000 = set(range(0x4E00, 0x4E00 + 3000))
KANA = set(range(0x3041, 0x3097)) | set(range(0x30A1, 0x30FB))   # 86 + 90 = 176


def test_languages_have_unique_ids_and_known_groups():
    from fontplayground.engine.scripts import GROUP_IDS
    ids = [lang.id for lang in LANGUAGES]
    assert len(ids) == len(set(ids)) and ids[0] == "latin" and ids[-1] == ANY
    for lang in LANGUAGES:
        assert set(lang.groups) <= set(GROUP_IDS)
        assert {g for g, _n in lang.min_counts} <= set(GROUP_IDS)
    assert language("korean").groups == ("hangul",) and language("japanese").groups == ("kana",)
    with pytest.raises(KeyError):
        language("klingon")


def test_covers_well_needs_the_counts_and_the_markers():
    simplified = fake_face(HAN_3000 | cps(language("chinese_s").markers))
    assert covers_well(simplified, language("chinese_s"))
    assert not covers_well(fake_face(HAN_3000), language("chinese_s"))            # markers missing
    assert not covers_well(fake_face(set(range(0x4E00, 0x4E00 + 100)) | cps("们这说国门来")), language("chinese_s"))
    japanese = fake_face(KANA | set(range(0x4E00, 0x4E00 + 1000)))
    assert covers_well(japanese, language("japanese"))
    assert not covers_well(fake_face(KANA), language("japanese"))                 # kana alone is not enough
    assert covers_well(fake_face(cps("a")), language(ANY))


def test_languages_for_missing_orders_by_count_and_skips_other():
    found = languages_for_missing(list("한글漢字字あ") + ["\U000E0001"])
    assert [lang.id for lang in found] == ["chinese_s", "korean", "japanese"]
    assert [lang.id for lang in languages_for_missing(list("，☺"))] == ["chinese_s", "symbols"]  # tie: table order
    assert languages_for_missing([]) == []


def test_join_labels_uses_short_labels_without_repeats():
    assert join_labels([language("chinese_s"), language("japanese")]) == "Chinese and Japanese"
    assert join_labels([language("chinese_s"), language("chinese_t"), language("korean")]) == "Chinese and Korean"
    assert join_labels([language("korean")]) == "Korean"
    assert join_labels([]) == ""


def test_draws_text_in_plain_words():
    assert draws_text({"han": 28195, "cjk_symbols": 465, "kana": 300, "symbols": 100}) == \
        "Draws Chinese characters, CJK punctuation and Japanese kana."
    assert draws_text({"latin": 1386, "arabic": 674, "symbols": 481, "cyrillic": 432, "greek": 368,
                       "armenian_georgian": 269}) == \
        "Draws letters, numbers and punctuation, plus Arabic, symbols, Cyrillic, Greek and more."
    assert draws_text({"latin": 95}) == "Draws letters, numbers and punctuation."
    assert draws_text({"hangul": 3}) == "Draws Korean Hangul."
    assert draws_text({}) == languages.DRAWS_NOTHING


def test_role_title_names_languages_or_says_what_it_does():
    assert role_title({"han": 28195, "cjk_symbols": 465, "kana": 300, "symbols": 340}) == "FOR CHINESE & JAPANESE"
    assert role_title({"hangul": 11000, "han": 20}) == "FOR KOREAN"            # below 1 %: not a role
    # Microsoft YaHei next to Segoe UI: 198 kana are under 1 %, but enough to count for Japanese
    assert role_title({"han": 28195, "cjk_symbols": 465, "symbols": 340, "kana": 198}) == "FOR CHINESE & JAPANESE"
    assert role_title({"symbols": 40}) == "FOR SYMBOLS & EMOJI"               # symbols count when they are all it does
    assert role_title({}) == "ADDS NOTHING"
    assert role_title({"other": 5}) == "FILLS IN THE REST"


def test_sample_lines_are_added_only_when_the_language_is_missing():
    korean = language("korean")
    assert with_language_line("Hello", korean) == "Hello\n" + korean.text_sample
    assert with_language_line("Hello\n", korean) == "Hello\n" + korean.text_sample
    assert with_language_line("", korean) == korean.text_sample
    assert with_language_line("안녕", korean) == "안녕"
    assert sample_has_language("x 漢", language("chinese_s")) and not sample_has_language("x", language("chinese_s"))
    assert sample_has_language("", language(ANY)) and with_language_line("x", language(ANY)) == "x"


def test_samples():
    assert SAMPLES["mixed"][1] == DEFAULT_SAMPLE and SAMPLES["all"][1] == OLD_DEFAULT_SAMPLE
    assert "한글" in OLD_DEFAULT_SAMPLE and "한" not in DEFAULT_SAMPLE
    assert all(label and text for label, text in SAMPLES.values())
