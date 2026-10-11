"""
Characterization test for the weather panel's layout + paint.

This renders the weather block against a fixed, fully-populated report and
compares the resulting pixels against a snapshot captured from the current
implementation. It exists to prove the measure/paint refactor is
behaviour-preserving: if the drawn output changes, this test fails.

The weather data is faked (no network): we monkeypatch ``weather.get_weather``
to return a deterministic report, and we also pin lunar-date resolution so the
moon glyph is stable regardless of the ``lunardate`` package being installed.
"""

import hashlib
from datetime import date, datetime

import pytest
from PIL import Image, ImageDraw

import renderer.weather_layout as wl
import renderer.weather_panel as wp
import weather as weather_mod
from config import Settings, Theme
from weather import HourForecast, WeatherReport


# A fixed canvas large enough to hold the panel comfortably.
CANVAS_W = 1400
ZONE_Y = 1000
ZONE_H = 400
BASE_FONT = 14


def _fixed_report() -> WeatherReport:
    hours = [
        HourForecast(label=f"{h:02d}:00", temperature=t,
                     precip_probability=p, precip_amount=mm, weather_code=code)
        for h, t, p, mm, code in [
            (14, 31.0, 10, 0.0, 1),
            (15, 32.0, 20, 0.0, 2),
            (16, 30.0, 55, 0.4, 61),
            (17, 29.0, 80, 1.4, 65),
            (18, 27.0, 40, 0.2, 80),
            (19, 26.0, 15, 0.0, 3),
        ]
    ]
    return WeatherReport(
        location="Ho Chi Minh City",
        temperature=31.0,
        temperature_unit="°C",
        hours=hours,
        fetched_at=0.0,
        temp_low=25.0,
        temp_high=33.0,
        utc_offset_seconds=25200,
        weather_code=2,
        uv_index=7.0,
        uv_index_max=9.0,
        sunrise_today="2026-10-11T05:42",
        sunset_today="2026-10-11T18:03",
        sunrise_tomorrow="2026-10-12T05:42",
        weekly_codes=[1, 2, 61, 65, 80, 3, 0],
        requested_location="Ho Chi Minh City",
    )


@pytest.fixture
def pinned_weather(monkeypatch):
    """Fake the network fetch and pin the lunar date for deterministic output."""
    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: _fixed_report())
    # Pin the lunar date so the moon phase + observance box don't depend on
    # whether lunardate is installed or on the real calendar. The layout pass
    # resolves the date through weather_layout, so patch it there (its real
    # lookup site), not just on weather_panel.
    pinned = lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16)
    monkeypatch.setattr(wl, "format_dates", pinned)


def _render_panel(settings: Settings) -> Image.Image:
    img = Image.new("RGB", (CANVAS_W, ZONE_Y + ZONE_H), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    stat_font = wp.resolve_font(BASE_FONT)
    wp.draw_weather(
        draw, CANVAS_W, ZONE_Y, ZONE_H,
        settings, Theme(name="test"), stat_font, BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    return img


def _digest(img: Image.Image) -> str:
    return hashlib.sha256(img.tobytes()).hexdigest()


def test_weather_panel_pie_mode_is_stable(pinned_weather):
    settings = Settings(show_weather=True, weather_rain_as_pie=True,
                        weather_location="Ho Chi Minh City")
    img = _render_panel(settings)
    # Snapshot: the panel is drawn (not blank) and matches the recorded hash.
    assert _digest(img) == PIE_MODE_DIGEST


def test_weather_panel_percentage_mode_is_stable(pinned_weather):
    settings = Settings(show_weather=True, weather_rain_as_pie=False,
                        weather_location="Ho Chi Minh City")
    img = _render_panel(settings)
    assert _digest(img) == PCT_MODE_DIGEST


def test_weather_panel_blank_when_no_report(monkeypatch):
    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: None)
    settings = Settings(show_weather=True)
    blank = Image.new("RGB", (CANVAS_W, ZONE_Y + ZONE_H), (10, 10, 20))
    img = _render_panel(settings)
    assert _digest(img) == _digest(blank)


# Snapshot digests captured from the pre-refactor implementation. See
# tests/conftest or the generating command in the PR notes.
PIE_MODE_DIGEST = "a5344738bfe3dba17f6589e3d560353146fbba38dba9db185a3672b4e5312c87"
PCT_MODE_DIGEST = "671ca6d5c90b2d69ebbcebf7404ad129b2e45ad010199b3862c94a7bd50396e9"
