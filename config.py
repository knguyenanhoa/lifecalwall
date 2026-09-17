"""
config.py — User settings and theme loading for the life calendar wallpaper.

Themes are loaded from JSON files in the themes/ directory (relative to this
file). Each .json file defines one theme. If a requested theme is not found,
the fallback is "dark".
"""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = os.path.expanduser("~/.lifecal")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Theme directory — lives alongside the source code
THEMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")

# ---------------------------------------------------------------------------
# Grid constants — change these to reshape the calendar
# ---------------------------------------------------------------------------

YEARS = 90          # total lifespan in years (number of columns)
WEEKS_PER_YEAR = 52 # rows in the grid

# How many years make a "period" for colour-banding
PERIOD_YEARS = 30

# ---------------------------------------------------------------------------
# Theme definition
# ---------------------------------------------------------------------------

FALLBACK_THEME_NAME = "dark"


@dataclass
class Theme:
    name: str

    # Canvas background
    background: Tuple[int, int, int] = (10, 10, 20)

    # Elapsed cell colours per 30-year period (filled)
    elapsed_period_colors: Tuple[
        Tuple[int, int, int],
        Tuple[int, int, int],
        Tuple[int, int, int],
    ] = (
        (180,  60,  60),
        ( 60, 140, 180),
        ( 80, 180,  90),
    )

    # Future cell colours per 30-year period (empty)
    future_period_colors: Tuple[
        Tuple[int, int, int],
        Tuple[int, int, int],
        Tuple[int, int, int],
    ] = (
        ( 60,  25,  25),
        ( 20,  45,  65),
        ( 25,  55,  30),
    )

    # Cell border / gap colour
    border_color: Tuple[int, int, int] = (30, 30, 45)

    # Label text colour
    label_color: Tuple[int, int, int] = (160, 160, 180)

    # Elapsed cell style: "solid" | "hatched"
    elapsed_style: str = "solid"

    # Future cell style: "solid" | "outline"
    future_style: str = "solid"

    # Gradient mode: if True, elapsed cells ramp from start to end colour
    gradient: bool = False

    # Per-period gradient end colours (used only when gradient=True)
    elapsed_period_end_colors: Tuple[
        Tuple[int, int, int],
        Tuple[int, int, int],
        Tuple[int, int, int],
    ] = (
        (180,  60,  60),
        ( 60, 140, 180),
        ( 80, 180,  90),
    )


# ---------------------------------------------------------------------------
# Theme loading from JSON files
# ---------------------------------------------------------------------------

def _json_to_theme(data: dict) -> Theme:
    """
    Convert a parsed JSON dict into a Theme instance.

    JSON stores colours as [r, g, b] arrays; we convert to tuples.
    Missing keys fall back to Theme defaults.
    """
    defaults = Theme(name=data.get("name", "unknown"))

    def _to_rgb(val, default):
        if val is None:
            return default
        return tuple(val)

    def _to_rgb_triple(val, default):
        if val is None:
            return default
        return tuple(tuple(c) for c in val)

    return Theme(
        name=data.get("name", defaults.name),
        background=_to_rgb(data.get("background"), defaults.background),
        elapsed_period_colors=_to_rgb_triple(
            data.get("elapsed_period_colors"), defaults.elapsed_period_colors),
        future_period_colors=_to_rgb_triple(
            data.get("future_period_colors"), defaults.future_period_colors),
        border_color=_to_rgb(data.get("border_color"), defaults.border_color),
        label_color=_to_rgb(data.get("label_color"), defaults.label_color),
        elapsed_style=data.get("elapsed_style", defaults.elapsed_style),
        future_style=data.get("future_style", defaults.future_style),
        gradient=data.get("gradient", defaults.gradient),
        elapsed_period_end_colors=_to_rgb_triple(
            data.get("elapsed_period_end_colors"), defaults.elapsed_period_end_colors),
    )


def _load_theme_file(path: str) -> Theme:
    """Load a single theme JSON file and return a Theme object."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _json_to_theme(data)


def load_all_themes() -> Dict[str, Theme]:
    """
    Scan the themes/ directory for .json files and return a dict of
    theme_name → Theme. If the directory is missing or empty, returns
    a dict with just the hardcoded fallback theme.
    """
    themes: Dict[str, Theme] = {}

    if os.path.isdir(THEMES_DIR):
        for filename in sorted(os.listdir(THEMES_DIR)):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(THEMES_DIR, filename)
            try:
                theme = _load_theme_file(filepath)
                themes[theme.name] = theme
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                # Skip malformed theme files silently
                continue

    # Ensure the fallback theme always exists
    if FALLBACK_THEME_NAME not in themes:
        themes[FALLBACK_THEME_NAME] = Theme(name=FALLBACK_THEME_NAME)

    return themes


def list_theme_names() -> List[str]:
    """Return a sorted list of all available theme names."""
    return sorted(load_all_themes().keys())


# Module-level cache — loaded once on import, can be refreshed with reload_themes()
THEMES: Dict[str, Theme] = load_all_themes()


def reload_themes() -> None:
    """Re-scan the themes/ directory and refresh the module-level THEMES dict."""
    global THEMES
    THEMES = load_all_themes()


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    birthday: str = "2000-01-01"
    theme: str = "gradient_crimson"
    update_interval_seconds: int = 3600
    canvas_width: int = 0
    canvas_height: int = 0
    padding_top: int = 80
    padding_bottom: int = 80
    padding_left: int = 80
    padding_right: int = 80
    cell_gap: int = 2
    show_year_labels: bool = True
    show_week_labels: bool = True

    # Weather report (bottom-left of the wallpaper)
    show_weather: bool = True
    # Temperature unit: True → Fahrenheit, False → Celsius
    weather_fahrenheit: bool = False
    # Location as a place name (e.g. "Ho Chi Minh City"). When blank, the
    # weather module falls back to DEFAULT_WEATHER_LOCATION.
    weather_location: str = ""
    # Cached coordinates for weather_location, filled in by the weather module
    # after geocoding so we don't re-geocode on every render.
    weather_latitude: Optional[float] = None
    weather_longitude: Optional[float] = None


def load_settings() -> Settings:
    """Load settings from disk, returning defaults if the file doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        return Settings()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        s = Settings()
        for key, value in data.items():
            if hasattr(s, key):
                setattr(s, key, value)
        return s
    except (json.JSONDecodeError, OSError):
        return Settings()


def save_settings(settings: Settings) -> None:
    """Persist settings to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2)


def get_theme(settings: Settings) -> Theme:
    """
    Return the Theme for the current settings.

    Falls back to the default theme if the requested theme is not found.
    """
    return THEMES.get(settings.theme, THEMES[FALLBACK_THEME_NAME])
