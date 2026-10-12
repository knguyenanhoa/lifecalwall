"""
Tests for astro.py — solar cycle phase, day length, and the low-precision
planet-visibility math. These are pure computations (no network).

The planet checks are tolerance-based: low-precision Keplerian elements are
good to about a degree, which is validated indirectly by physical invariants
(max elongations of Mercury and Venus, the Sun's longitude at the equinoxes)
rather than by hard-coding ephemeris values.
"""

from datetime import date, datetime, timedelta

import pytest

import astro


# ---------------------------------------------------------------------------
# Solar cycle phase
# ---------------------------------------------------------------------------

def test_solar_cycle_number_is_25_in_mid_cycle():
    number, label, frac = astro.solar_cycle_phase(date(2024, 6, 1))
    assert number == 25
    assert 0.0 <= frac <= 1.0


def test_solar_cycle_phase_labels_progress():
    # Just after the 2019 minimum → near minimum / rising.
    _, early, _ = astro.solar_cycle_phase(date(2020, 3, 1))
    assert early in ("near minimum", "rising")
    # ~5 years in (~2024/25) is near the maximum.
    _, mid, _ = astro.solar_cycle_phase(date(2024, 12, 1))
    assert mid in ("near maximum", "rising", "declining")


def test_solar_cycle_text_format():
    text = astro.solar_cycle_text(date(2024, 6, 1))
    assert text.startswith("Solar cycle 25")
    assert "·" in text


# ---------------------------------------------------------------------------
# Day length
# ---------------------------------------------------------------------------

def test_day_length_basic():
    assert astro.day_length_text("2026-10-12T06:00", "2026-10-12T18:30") == "12h 30m"


def test_day_length_pads_minutes():
    assert astro.day_length_text("2026-10-12T07:00", "2026-10-12T17:05") == "10h 05m"


def test_day_length_blank_when_missing():
    assert astro.day_length_text("", "2026-10-12T18:00") == ""
    assert astro.day_length_text("2026-10-12T06:00", "") == ""
    assert astro.day_length_text("bad", "also-bad") == ""


# ---------------------------------------------------------------------------
# Planet positions — physical invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "when, expected_lon",
    [
        (datetime(2026, 3, 20, 12), 0),
        (datetime(2026, 6, 21, 12), 90),
        (datetime(2026, 9, 22, 12), 180),
        (datetime(2026, 12, 21, 12), 270),
    ],
)
def test_sun_longitude_near_cardinal_points(when, expected_lon):
    t = astro._julian_centuries(when)
    lon = astro._sun_ecliptic_longitude(t)
    diff = (lon - expected_lon + 180) % 360 - 180
    assert abs(diff) < 2.0, f"Sun lon off by {diff:.1f}° at {when}"


def test_inner_planet_elongation_ceilings():
    # Over a year, Mercury's max elongation stays near ~28°, Venus near ~47°.
    start = datetime(2026, 1, 1)
    max_merc = max(astro.planet_visibility("Mercury", start + timedelta(days=d))[0]
                   for d in range(0, 365, 2))
    max_venus = max(astro.planet_visibility("Venus", start + timedelta(days=d))[0]
                    for d in range(0, 365, 2))
    assert 18 <= max_merc <= 30, f"Mercury max elongation {max_merc:.1f}"
    assert 44 <= max_venus <= 49, f"Venus max elongation {max_venus:.1f}"


def test_outer_planet_can_reach_opposition():
    # Over ~2 years some outer planet reaches a large elongation (near opposition).
    start = datetime(2026, 1, 1)
    peak = max(astro.planet_visibility("Jupiter", start + timedelta(days=d))[0]
               for d in range(0, 730, 5))
    assert peak > 150


def test_visibility_labels_are_valid():
    valid = {"not visible", "evening sky", "morning sky", "visible all night"}
    for planet in astro.NAKED_EYE_PLANETS:
        _, label = astro.planet_visibility(planet, datetime(2026, 10, 12, 20))
        assert label in valid


def test_planets_text_is_empty_or_prefixed():
    text = astro.planets_text(datetime(2026, 10, 12, 20))
    assert text == "" or text.startswith("Planets: ")


def test_conjunction_text_format_when_present():
    # Scan a long window to find at least one close pairing, then check format.
    start = datetime(2026, 1, 1)
    found = ""
    for d in range(0, 365, 1):
        found = astro.conjunction_text(start + timedelta(days=d))
        if found:
            break
    # Either no conjunction in the window (rare) or a well-formed string.
    assert found == "" or ("°" in found and "apart" in found)
