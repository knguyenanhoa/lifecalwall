"""
Tests for weather.py pure helpers — week summarisation, code bucketing, UV
bands, GMT formatting, cache matching, safe indexing, and next-solar-event
selection. None of these touch the network.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from weather import (
    DEFAULT_WEATHER_LOCATION,
    WeatherReport,
    _at,
    _cache_matches,
)
from renderer import (
    _aurora_outlook,
    _code_bucket,
    _format_gmt_offset,
    _kp_band_index,
    _kp_label,
    _next_solar_event,
    _solar_activity_outlook,
    _summarize_week,
    _uv_band_index,
    _uv_label,
)


# ---------------------------------------------------------------------------
# _code_bucket — collapse WMO codes into coarse weekly buckets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "code, bucket",
    [
        (0, "sunny"), (1, "sunny"),
        (2, "cloudy"), (3, "cloudy"), (45, "cloudy"), (48, "cloudy"),
        (71, "snowy"), (77, "snowy"), (85, "snowy"), (86, "snowy"),
        (95, "stormy"), (99, "stormy"),
        (51, "rainy"), (67, "rainy"), (80, "rainy"), (82, "rainy"),
    ],
)
def test_code_bucket(code, bucket):
    assert _code_bucket(code) == bucket


# ---------------------------------------------------------------------------
# _summarize_week — aggregate up to 7 daily codes into a phrase
# ---------------------------------------------------------------------------

def test_summarize_week_empty_is_blank():
    assert _summarize_week([]) == ""


def test_summarize_week_single_bucket_is_mostly():
    # All sunny codes.
    assert _summarize_week([0, 1, 0, 1]) == "mostly sunny"


def test_summarize_week_dominant_bucket():
    # 6 rainy, 1 sunny → ≥70% rainy.
    codes = [61, 63, 65, 80, 81, 82, 0]
    assert _summarize_week(codes) == "mostly rainy"


def test_summarize_week_even_rain_and_shine_special_cased():
    # Equal rainy and sunny counts get the dedicated phrasing.
    codes = [61, 63, 0, 1]
    assert _summarize_week(codes) == "an even mix of rain and shine"


def test_summarize_week_two_notable_buckets():
    # 3 rainy, 2 cloudy → leads with rainy, cloudy clearly present (≥25%).
    codes = [61, 63, 65, 2, 3]
    result = _summarize_week(codes)
    assert result.startswith("mostly rainy")
    assert "cloudy" in result


# ---------------------------------------------------------------------------
# UV bands (defined in renderer)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "uv, label",
    [
        (0, "Low"), (2.9, "Low"),
        (3, "Moderate"), (5.9, "Moderate"),
        (6, "High"), (7.9, "High"),
        (8, "Very high"), (10.9, "Very high"),
        (11, "Extreme"), (20, "Extreme"),
    ],
)
def test_uv_label_bands(uv, label):
    assert _uv_label(uv) == label


def test_uv_band_index_is_monotonic():
    indices = [_uv_band_index(uv) for uv in (0, 3, 6, 8, 11)]
    assert indices == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Kp (geomagnetic) bands + aurora outlook
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kp, label",
    [
        (0, "Quiet"), (4, "Quiet"), (4.9, "Quiet"),
        (5, "G1 Minor"),
        (6, "G2 Moderate"),
        (7, "G3 Strong"),
        (8, "G4 Severe"),
        (9, "G5 Extreme"), (12, "G5 Extreme"),
    ],
)
def test_kp_label_bands(kp, label):
    assert _kp_label(kp) == label


def test_kp_band_index_is_monotonic():
    indices = [_kp_band_index(kp) for kp in (0, 5, 6, 7, 8, 9)]
    assert indices == [0, 1, 2, 3, 4, 5]


def test_aurora_outlook_escalates_with_kp():
    assert _aurora_outlook(1) == "Aurora unlikely"
    assert "high latitudes" in _aurora_outlook(4)
    assert "mid-latitudes" in _aurora_outlook(6)
    assert _aurora_outlook(8) == "Aurora far from poles"


# ---------------------------------------------------------------------------
# Solar activity (NOAA R-scale → plain-language label)
# ---------------------------------------------------------------------------

def test_solar_activity_outlook_quiet_and_active():
    assert _solar_activity_outlook(0) == "Sun: quiet"
    assert _solar_activity_outlook(3) == "Sun: strong flares"
    assert _solar_activity_outlook(5) == "Sun: extreme flares"


def test_solar_activity_outlook_blank_when_unknown():
    assert _solar_activity_outlook(None) == ""


# ---------------------------------------------------------------------------
# _format_gmt_offset (defined in renderer)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "seconds, expected",
    [
        (None, ""),
        (0, "+0"),
        (25200, "+7"),       # GMT+7
        (19800, "+5:30"),    # India
        (-18000, "-5"),      # US Eastern (standard)
        (-12600, "-3:30"),   # Newfoundland
    ],
)
def test_format_gmt_offset(seconds, expected):
    assert _format_gmt_offset(seconds) == expected


# ---------------------------------------------------------------------------
# _at — safe indexed access
# ---------------------------------------------------------------------------

def test_at_in_range():
    assert _at([10, 20, 30], 1, -1) == 20


def test_at_out_of_range_returns_default():
    assert _at([10], 5, "fallback") == "fallback"
    assert _at([], 0, None) is None


# ---------------------------------------------------------------------------
# _cache_matches — location + unit guard
# ---------------------------------------------------------------------------

def _report(requested_location, unit):
    return WeatherReport(
        location="whatever", temperature=20.0, temperature_unit=unit,
        hours=[], fetched_at=0.0, requested_location=requested_location,
    )


def test_cache_matches_same_location_and_unit():
    cached = _report("Paris", "°C")
    assert _cache_matches(cached, "paris", fahrenheit=False)


def test_cache_matches_rejects_unit_mismatch():
    cached = _report("Paris", "°C")
    assert not _cache_matches(cached, "Paris", fahrenheit=True)


def test_cache_matches_rejects_location_mismatch():
    cached = _report("Paris", "°C")
    assert not _cache_matches(cached, "Berlin", fahrenheit=False)


def test_cache_matches_blank_location_uses_default():
    cached = _report(DEFAULT_WEATHER_LOCATION, "°C")
    assert _cache_matches(cached, "", fahrenheit=False)


# ---------------------------------------------------------------------------
# _next_solar_event — pick the next sunrise/sunset to display
# ---------------------------------------------------------------------------

def _solar_report(sunrise_t="", sunset_t="", sunrise_tmrw=""):
    return SimpleNamespace(
        sunrise_today=sunrise_t,
        sunset_today=sunset_t,
        sunrise_tomorrow=sunrise_tmrw,
    )


def test_next_solar_event_before_sunrise_shows_sunrise():
    report = _solar_report("2026-01-01T06:30", "2026-01-01T18:00",
                           "2026-01-02T06:31")
    now = datetime(2026, 1, 1, 5, 0)
    assert _next_solar_event(report, now) == ("Sunrise", "06:30")


def test_next_solar_event_during_day_shows_sunset():
    report = _solar_report("2026-01-01T06:30", "2026-01-01T18:00",
                           "2026-01-02T06:31")
    now = datetime(2026, 1, 1, 12, 0)
    assert _next_solar_event(report, now) == ("Sunset", "18:00")


def test_next_solar_event_after_sunset_shows_tomorrows_sunrise():
    report = _solar_report("2026-01-01T06:30", "2026-01-01T18:00",
                           "2026-01-02T06:31")
    now = datetime(2026, 1, 1, 20, 0)
    assert _next_solar_event(report, now) == ("Sunrise", "06:31")


def test_next_solar_event_returns_none_when_data_missing():
    assert _next_solar_event(_solar_report(), datetime(2026, 1, 1, 12, 0)) is None


# ---------------------------------------------------------------------------
# _fetch_space_weather — parse NOAA SWPC Kp "table" JSON (no network)
# ---------------------------------------------------------------------------

import weather as weather_mod


def test_fetch_space_weather_parses_current_and_forecast(monkeypatch):
    # NOAA products are arrays of objects. The current product uses "Kp";
    # the forecast product uses "kp" and flags upcoming rows observed="predicted".
    current_rows = [
        {"time_tag": "2026-10-11T09:00:00", "Kp": 3.0},
        {"time_tag": "2026-10-11T12:00:00", "Kp": 6.0},   # latest → current Kp
    ]
    forecast_rows = [
        {"time_tag": "2026-10-10T15:00:00", "kp": 9.0, "observed": "observed"},  # past storm, ignored
        {"time_tag": "2026-10-13T03:00:00", "kp": 5.0, "observed": "predicted"},
        {"time_tag": "2026-10-13T06:00:00", "kp": 7.0, "observed": "predicted"},  # peak of the forecast
        {"time_tag": "2026-10-13T09:00:00", "kp": 4.0, "observed": "predicted"},
    ]

    def fake_get(url):
        return current_rows if "forecast" not in url else forecast_rows

    monkeypatch.setattr(weather_mod, "_http_get_json", fake_get)
    current, forecast_max = weather_mod._fetch_space_weather()
    assert current == 6.0
    # The past observed Kp 9 must be excluded; only predicted rows count.
    assert forecast_max == 7.0


def test_fetch_space_weather_tolerates_failure(monkeypatch):
    def boom(url):
        raise weather_mod.urllib.error.URLError("offline")

    monkeypatch.setattr(weather_mod, "_http_get_json", boom)
    assert weather_mod._fetch_space_weather() == (None, None)


def test_fetch_solar_activity_reads_current_r_scale(monkeypatch):
    # NOAA scales product: "0" is the current entry; R.Scale is the level.
    scales = {
        "0": {"R": {"Scale": "2", "Text": "moderate"}, "S": {"Scale": "0"}, "G": {"Scale": "0"}},
        "1": {"R": {"Scale": None, "MinorProb": "45"}},
    }
    monkeypatch.setattr(weather_mod, "_http_get_json", lambda url: scales)
    assert weather_mod._fetch_solar_activity() == 2


def test_fetch_solar_activity_tolerates_failure(monkeypatch):
    def boom(url):
        raise weather_mod.urllib.error.URLError("offline")

    monkeypatch.setattr(weather_mod, "_http_get_json", boom)
    assert weather_mod._fetch_solar_activity() is None
