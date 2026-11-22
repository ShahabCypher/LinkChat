"""Tests for Windows i18n catalog, BiDi detection, Vazirmatn font selection, and prefs."""

from __future__ import annotations

from pathlib import Path

from linkchat_win import i18n, prefs
from linkchat_win.ui import theme


def test_default_language_is_persian_and_catalogs_match() -> None:
    assert i18n.DEFAULT_LANG == "fa"
    assert i18n.tr("fa", "id_prefix") == "ID:"
    assert "Mesh Broadcast" in i18n.tr("fa", "public_channel_btn")
    assert "Mesh Broadcast" in i18n.tr("fa", "public_channel_title")
    assert set(i18n.STRINGS["fa"].keys()) == set(i18n.STRINGS["en"].keys())
    for lang, catalog in i18n.STRINGS.items():
        for key, value in catalog.items():
            assert isinstance(value, str) and value.strip(), f"{lang}.{key} is empty"


def test_persian_detection_and_bidi_helpers() -> None:
    assert i18n.contains_persian("سلام دنیا")
    assert i18n.contains_persian("Hello سلام")
    assert not i18n.contains_persian("Hello #public 123")

    assert i18n.detect_rtl("سلام") is True
    assert i18n.detect_rtl("Hello سلام") is False
    assert i18n.detect_rtl("123 سلام") is True
    assert i18n.detect_rtl("123", default_rtl=True) is True

    assert i18n.is_rtl_text("Hello سلام:", default_rtl=False) is True
    assert i18n.is_rtl_text("Hello world", default_rtl=True) is False
    assert i18n.is_rtl_text("123", default_rtl=True) is True

    assert i18n.bidi_text("نام:", True) == "\u202Bنام:\u202C"
    assert i18n.bidi_text("سلام:\nخوبی؟", True) == "\u202Bسلام:\u202C\n\u202Bخوبی؟\u202C"
    assert i18n.bidi_text("Hello", False) == "Hello"
    assert i18n.wrap_text_for_width("aa bb cc", len, 5) == "aa bb\ncc"


def test_message_font_uses_vazirmatn_for_persian_chars_in_both_modes() -> None:
    assert theme.message_font("Hello", "en", 13)[0] == theme.FONT_FAMILY
    assert theme.message_font("سلام", "en", 13)[0] == theme.FONT_PERSIAN
    assert theme.message_font("Hello سلام", "en", 13)[0] == theme.FONT_PERSIAN
    assert theme.message_font("Hello", "fa", 13)[0] == theme.FONT_PERSIAN
    assert theme.message_font("سلام", "fa", 13)[0] == theme.FONT_PERSIAN


def test_language_preference_persists_and_survives_corrupt_file(tmp_path: Path) -> None:
    assert prefs.load_language(tmp_path) == "fa"

    prefs.save_language(tmp_path, "en")
    assert prefs.load_language(tmp_path) == "en"

    prefs.save_language(tmp_path, "fa")
    assert prefs.load_language(tmp_path) == "fa"

    (tmp_path / prefs.PREFS_FILENAME).write_text("{bad json", encoding="utf-8")
    assert prefs.load_language(tmp_path) == "fa"
