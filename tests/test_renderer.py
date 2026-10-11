"""
Tests for renderer.py pure helpers — colour blending, elapsed-week counting,
period indexing, week progress, moon illumination, and WMO condition mapping.
These avoid Pillow drawing entirely.
"""

import math
from datetime import date, datetime

import pytest

from renderer import (
    _blend,
    _moon_illumination,
    _period_index,
    _ramp_color,
    _weather_condition,
    _week_progress,
    _weeks_elapsed,
)
from config import PERIOD_YEARS, Theme


# ---------------------------------------------------------------------------
# _blend — linear interpolation between two RGB colours
# ---------------------------------------------------------------------------

def test_blend_endpoints():
    a, b = (0, 0, 0), (255, 255, 255)
    assert _blend(a, b, 0.0) == (0, 0, 0)
    assert _blend(a, b, 1.0) == (255, 255, 255)


def test_blend_midpoint():
    assert _blend((0, 0, 0), (100, 200, 50), 0.5) == (50, 100, 25)


def test_blend_returns_integers():
    assert all(isinstance(c, int) for c in _blend((1, 2, 3), (9, 8, 7), 0.3))


# ---------------------------------------------------------------------------
# _weeks_elapsed — whole weeks between birthday and today
# ---------------------------------------------------------------------------

def test_weeks_elapsed_zero_before_or_on_birthday():
    bday = date(2000, 1, 1)
    assert _weeks_elapsed(bday, bday) == 0
    assert _weeks_elapsed(bday, date(1999, 12, 31)) == 0


def test_weeks_elapsed_counts_whole_weeks():
    bday = date(2000, 1, 1)
    assert _weeks_elapsed(bday, date(2000, 1, 8)) == 1    # exactly 7 days
    assert _weeks_elapsed(bday, date(2000, 1, 14)) == 1   # 13 days → still 1
    assert _weeks_elapsed(bday, date(2000, 1, 15)) == 2   # 14 days → 2


# ---------------------------------------------------------------------------
# _period_index — which 30-year colour band a year falls in, capped at 2
# ---------------------------------------------------------------------------

def test_period_index_bands():
    assert _period_index(0) == 0
    assert _period_index(PERIOD_YEARS - 1) == 0
    assert _period_index(PERIOD_YEARS) == 1
    assert _period_index(2 * PERIOD_YEARS) == 2


def test_period_index_capped_at_two():
    assert _period_index(3 * PERIOD_YEARS) == 2
    assert _period_index(10 * PERIOD_YEARS) == 2


# ---------------------------------------------------------------------------
# _week_progress — day index and fraction of week elapsed
# ---------------------------------------------------------------------------

def test_week_progress_monday_midnight_is_start():
    monday_midnight = datetime(2024, 1, 1, 0, 0, 0)  # 2024-01-01 is a Monday
    day_idx, frac = _week_progress(monday_midnight)
    assert day_idx == 0
    assert frac == pytest.approx(0.0)


def test_week_progress_sunday_end_near_full():
    sunday_late = datetime(2024, 1, 7, 23, 59, 59)
    day_idx, frac = _week_progress(sunday_late)
    assert day_idx == 6
    assert frac == pytest.approx(1.0, abs=1e-4)


def test_week_progress_midweek_fraction():
    # Thursday noon: 3 full days + half a day = 3.5 / 7 = 0.5.
    thursday_noon = datetime(2024, 1, 4, 12, 0, 0)
    day_idx, frac = _week_progress(thursday_noon)
    assert day_idx == 3
    assert frac == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _moon_illumination — lunar-day → (fraction lit, waxing?)
# ---------------------------------------------------------------------------

def test_moon_illumination_unknown_day_is_neutral():
    assert _moon_illumination(None) == (0.5, True)
    assert _moon_illumination(0) == (0.5, True)


def test_moon_new_moon_is_dark_and_waxing():
    illum, waxing = _moon_illumination(1)
    assert illum == pytest.approx(0.0, abs=1e-6)
    assert waxing is True


def test_moon_full_moon_is_bright():
    # ~day 15 of a 29.53-day cycle is near full.
    illum, _ = _moon_illumination(15)
    assert illum > 0.95


def test_moon_waning_after_midcycle():
    _, waxing = _moon_illumination(25)
    assert waxing is False


# ---------------------------------------------------------------------------
# _weather_condition — WMO code → (icon key, label)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "code, key",
    [
        (None, "unknown"),
        (0, "clear"),
        (1, "partly"), (2, "partly"),
        (3, "cloudy"),
        (45, "fog"), (48, "fog"),
        (55, "rain"), (65, "rain"), (82, "rain"),
        (73, "snow"), (86, "snow"),
        (96, "thunder"),
    ],
)
def test_weather_condition_icon_key(code, key):
    assert _weather_condition(code)[0] == key


# ---------------------------------------------------------------------------
# _ramp_color — brightness ramp with a legibility floor at t=0
# ---------------------------------------------------------------------------

def test_ramp_color_clamps_out_of_range():
    theme = Theme(name="t")
    assert _ramp_color(theme, -1.0) == _ramp_color(theme, 0.0)
    assert _ramp_color(theme, 2.0) == _ramp_color(theme, 1.0)


def test_ramp_color_brighter_at_higher_t():
    theme = Theme(name="t")
    dark = _ramp_color(theme, 0.0)
    light = _ramp_color(theme, 1.0)
    assert sum(light) > sum(dark)
