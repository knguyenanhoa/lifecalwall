"""
config.py — User settings and theme definitions for the life calendar wallpaper.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = os.path.expanduser("~/.lifecal")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

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
        (180,  60,  60),   # years  0-29  — warm red
        ( 60, 140, 180),   # years 30-59  — cool blue
        ( 80, 180,  90),   # years 60-89  — soft green
    )

    # Future cell colours per 30-year period (empty)
    future_period_colors: Tuple[
        Tuple[int, int, int],
        Tuple[int, int, int],
        Tuple[int, int, int],
    ] = (
        ( 60,  25,  25),   # years  0-29
        ( 20,  45,  65),   # years 30-59
        ( 25,  55,  30),   # years 60-89
    )

    # Cell border / gap colour
    border_color: Tuple[int, int, int] = (30, 30, 45)

    # Label text colour
    label_color: Tuple[int, int, int] = (160, 160, 180)

    # Elapsed cell style: "solid" | "hatched"
    elapsed_style: str = "solid"

    # Future cell style: "solid" | "outline"
    future_style: str = "solid"

    # Gradient mode: if True, elapsed cells are individually tinted so colour
    # ramps smoothly from the period's start colour to its end colour across
    # the columns of that period.  Ignored when elapsed_style == "hatched".
    gradient: bool = False

    # Per-period gradient end colours (used only when gradient=True).
    # Each entry is the colour at the *right* edge of that period's columns;
    # the left edge uses elapsed_period_colors[i].
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
# Built-in themes
# ---------------------------------------------------------------------------

THEMES: Dict[str, Theme] = {
    "dark": Theme(
        name="dark",
    ),
    "crimson": Theme(
        name="crimson",
        background=(8, 4, 4),
        # Elapsed: three shades of red that deepen across the 30-year periods
        elapsed_period_colors=(
            (220,  40,  40),   # years  0-29 — bright red
            (160,  20,  20),   # years 30-59 — mid crimson
            ( 90,  10,  10),   # years 60-89 — deep wine
        ),
        # Gradient end colours — each period ramps toward a darker/warmer hue
        elapsed_period_end_colors=(
            (255, 100,  50),   # 0-29  ramps from bright red → orange-red
            (200,  50,  10),   # 30-59 ramps from crimson → burnt orange
            (130,  20,   5),   # 60-89 ramps from wine → almost black-red
        ),
        future_period_colors=(
            ( 45,  10,  10),
            ( 35,   8,   8),
            ( 25,   5,   5),
        ),
        border_color=(20, 5, 5),
        label_color=(180, 80, 80),
        elapsed_style="solid",
        future_style="solid",
        gradient=True,
    ),
    "light": Theme(
        name="light",
        background=(240, 240, 235),
        elapsed_period_colors=(
            (200,  70,  70),
            ( 60, 130, 190),
            ( 70, 170,  80),
        ),
        future_period_colors=(
            (220, 190, 190),
            (190, 210, 230),
            (190, 225, 195),
        ),
        border_color=(200, 200, 195),
        label_color=( 80,  80,  90),
        elapsed_style="solid",
        future_style="solid",
    ),
    "monochrome": Theme(
        name="monochrome",
        background=(15, 15, 15),
        elapsed_period_colors=(
            (200, 200, 200),
            (160, 160, 160),
            (120, 120, 120),
        ),
        future_period_colors=(
            ( 50,  50,  50),
            ( 45,  45,  45),
            ( 40,  40,  40),
        ),
        border_color=(30, 30, 30),
        label_color=(100, 100, 100),
        elapsed_style="solid",
        future_style="solid",
    ),
}

# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    birthday: str = "2000-01-01"          # ISO-8601 date string: "YYYY-MM-DD"
    theme: str = "crimson"
    update_interval_seconds: int = 3600   # how often to re-render (default 1 h)
    # Canvas resolution — set to 0 to auto-detect from display
    canvas_width: int = 0
    canvas_height: int = 0
    # Padding around the grid (pixels)
    padding_top: int = 80
    padding_bottom: int = 80
    padding_left: int = 80
    padding_right: int = 80
    # Gap between cells (pixels)
    cell_gap: int = 2
    # Whether to show year / week labels
    show_year_labels: bool = True
    show_week_labels: bool = True


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
    """Return the Theme object for the current settings, falling back to dark."""
    return THEMES.get(settings.theme, THEMES["dark"])
