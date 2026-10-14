"""Tests for the i18n layer (default English, easy switch, persistence)."""
from __future__ import annotations

import i18n


def _restore():
    prev = i18n.get_lang()

    def _inner():
        i18n.set_lang(prev)
    return _inner


def test_default_is_english():
    assert i18n.DEFAULT_LANG == "en"
    assert i18n.LANG_NAMES["en"] == "English"


def test_set_get_switch():
    restore = _restore()
    try:
        for code, _name in i18n.LANGS:
            assert i18n.set_lang(code) == code
            assert i18n.get_lang() == code
    finally:
        restore()


def test_unknown_language_falls_back_to_english():
    restore = _restore()
    try:
        assert i18n.set_lang("xx") == "en"
        assert i18n.set_lang(None) == "en"
        assert i18n.set_lang("fr_FR") == "fr"      # locale-style normalized
    finally:
        restore()


def test_t_translates_and_falls_back():
    restore = _restore()
    try:
        i18n.set_lang("fr")
        assert i18n.t("menu_scan") == "Analyse complète"
        i18n.set_lang("en")
        assert i18n.t("menu_scan") == "Full analysis"
        # a missing key returns the key itself, never raises
        assert i18n.t("this_key_does_not_exist") == "this_key_does_not_exist"
    finally:
        restore()


def test_t_interpolation_and_bad_placeholder():
    i18n.set_lang("en")
    assert i18n.t("rep_apps", n=7) == "Applications detected : 7"
    # passing a placeholder that the template does not use must not crash
    assert i18n.t("rep_none", unexpected="x") == "None"


def test_every_language_has_the_core_keys():
    core = ("menu_scan", "settings_line", "rep_recommendations", "ins_full",
            "st_title", "selftest_ready")
    for code, _name in i18n.LANGS:
        for key in core:
            assert key in i18n._CATALOG[code], f"{code} missing {key}"


def test_age_units_switch():
    restore = _restore()
    try:
        i18n.set_lang("en")
        assert i18n.age_units() == ("min", "h", "d", "mo", "y")
        i18n.set_lang("fr")
        assert i18n.age_units()[2] == "j"
    finally:
        restore()


def test_persistence_roundtrip(tmp_path, monkeypatch):
    restore = _restore()
    monkeypatch.delenv("DISKTOP_LANG", raising=False)
    monkeypatch.setattr(i18n, "config_path",
                        lambda: str(tmp_path / "config.json"))
    try:
        # no file yet -> default english
        assert i18n.load_lang() == "en"
        # choose a language and persist
        assert i18n.save_lang("de") == "de"
        assert i18n.get_lang() == "de"
        # simulate a fresh process: reset then load from disk
        i18n.set_lang("en")
        assert i18n.load_lang() == "de"
    finally:
        restore()
