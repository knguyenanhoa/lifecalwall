"""
Tests for config.py — season resolution, theme loading, settings persistence.

These lock in current behaviour so the config module can be refactored safely.
"""

import json
from datetime import date

import pytest

import config
from config import (
    FALLBACK_THEME_NAME,
    SEASON_DYNAMIC_NAME,
    SEASON_THEME_NAMES,
    Settings,
    Theme,
    _json_to_theme,
    _season_for_date,
    get_theme,
    load_settings,
    save_settings,
)


# ---------------------------------------------------------------------------
# _season_for_date — meteorological (whole-month) Northern-Hemisphere seasons
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "month, expected_season",
    [
        (1, "winter"), (2, "winter"),
        (3, "spring"), (4, "spring"), (5, "spring"),
        (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "autumn"), (10, "autumn"), (11, "autumn"),
        (12, "winter"),
    ],
)
def test_season_for_date_covers_every_month(month, expected_season):
    assert _season_for_date(date(2024, month, 15)) == expected_season


def test_season_boundaries_are_inclusive_at_month_start():
    assert _season_for_date(date(2024, 3, 1)) == "spring"
    assert _season_for_date(date(2024, 6, 1)) == "summer"
    assert _season_for_date(date(2024, 9, 1)) == "autumn"
    assert _season_for_date(date(2024, 12, 1)) == "winter"


# ---------------------------------------------------------------------------
# _json_to_theme — JSON dict → Theme, with defaults for missing keys
# ---------------------------------------------------------------------------

def test_json_to_theme_converts_rgb_lists_to_tuples():
    theme = _json_to_theme({
        "name": "custom",
        "background": [1, 2, 3],
        "elapsed_period_colors": [[10, 10, 10], [20, 20, 20], [30, 30, 30]],
    })
    assert theme.name == "custom"
    assert theme.background == (1, 2, 3)
    assert theme.elapsed_period_colors == ((10, 10, 10), (20, 20, 20), (30, 30, 30))
    # Every colour must be a tuple, not a list, so Pillow accepts it directly.
    assert all(isinstance(c, tuple) for c in theme.elapsed_period_colors)


def test_json_to_theme_fills_missing_keys_from_defaults():
    defaults = Theme(name="x")
    theme = _json_to_theme({"name": "x"})
    assert theme.background == defaults.background
    assert theme.elapsed_style == defaults.elapsed_style
    assert theme.gradient == defaults.gradient


def test_json_to_theme_defaults_name_when_absent():
    assert _json_to_theme({}).name == "unknown"


# ---------------------------------------------------------------------------
# get_theme — dynamic season resolution + fallback
# ---------------------------------------------------------------------------

def test_get_theme_resolves_dynamic_season_to_matching_palette():
    settings = Settings(theme=SEASON_DYNAMIC_NAME)
    summer_day = date(2024, 7, 15)
    resolved = get_theme(settings, today=summer_day)
    assert resolved.name == SEASON_THEME_NAMES["summer"]


def test_get_theme_falls_back_when_theme_missing():
    settings = Settings(theme="does-not-exist")
    assert get_theme(settings).name == FALLBACK_THEME_NAME


def test_get_theme_returns_requested_theme_when_present():
    # The fallback theme is always loaded, so it's a safe known-present name.
    settings = Settings(theme=FALLBACK_THEME_NAME)
    assert get_theme(settings).name == FALLBACK_THEME_NAME


# ---------------------------------------------------------------------------
# Settings persistence round-trip
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Point config at a temp file so tests never touch the real ~/.lifecal."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg_file))
    return cfg_file


def test_load_settings_returns_defaults_when_file_missing(temp_config):
    assert not temp_config.exists()
    settings = load_settings()
    assert settings == Settings()


def test_save_then_load_round_trips(temp_config):
    original = Settings(birthday="1990-05-15", theme="dark",
                        weather_location="Paris", weather_fahrenheit=True)
    save_settings(original)
    assert temp_config.exists()
    assert load_settings() == original


def test_load_settings_ignores_unknown_keys(temp_config):
    temp_config.write_text(json.dumps({"birthday": "1980-01-01", "bogus": 42}))
    settings = load_settings()
    assert settings.birthday == "1980-01-01"
    assert not hasattr(settings, "bogus")


def test_load_settings_returns_defaults_on_corrupt_json(temp_config):
    temp_config.write_text("{ not valid json")
    assert load_settings() == Settings()
