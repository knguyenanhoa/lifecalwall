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


# ---------------------------------------------------------------------------
# render_weather_only — the standalone "Open Weather" quick view
# ---------------------------------------------------------------------------

def _has_content(img: Image.Image) -> bool:
    """True if any pixel differs from the top-left (background) pixel."""
    from PIL import ImageChops
    flat = Image.new(img.mode, img.size, img.getpixel((0, 0)))
    return ImageChops.difference(img, flat).getbbox() is not None


def test_render_weather_only_draws_panel(pinned_weather):
    from renderer import render_weather_only
    settings = Settings(show_weather=True, weather_location="Ho Chi Minh City")
    img = render_weather_only(settings, 620, 420,
                              today=date(2026, 10, 11),
                              now=datetime(2026, 10, 11, 14, 30))
    assert img.size == (620, 420)
    # The widget should actually be drawn, not left as a blank background.
    assert _has_content(img)


def test_render_weather_only_is_blank_without_report(monkeypatch):
    from renderer import render_weather_only
    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: None)
    settings = Settings(show_weather=True)
    img = render_weather_only(settings, 620, 420,
                              today=date(2026, 10, 11),
                              now=datetime(2026, 10, 11, 14, 30))
    # No weather → plain theme background, nothing painted.
    assert not _has_content(img)


# ---------------------------------------------------------------------------
# Regression: a long 7-day summary must not push the forecast off the canvas
# ---------------------------------------------------------------------------

def _long_summary_report() -> WeatherReport:
    """A report whose weekly codes yield the longest summary phrasing."""
    rep = _fixed_report()
    # Equal rainy/cloudy counts → "an even mix of rainy and cloudy".
    rep.weekly_codes = [61, 63, 2, 3]
    return rep


def test_long_week_summary_does_not_clip_forecast(monkeypatch):
    from renderer.draw_utils import resolve_font, text_size
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: _long_summary_report())

    # A deliberately narrow canvas: before the fix, the long summary widened
    # the left column and ran the forecast's rain mm text off the right edge.
    narrow_w = 460
    img = Image.new("RGB", (narrow_w, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, _long_summary_report(), narrow_w, 0, 420,
        Settings(weather_rain_as_pie=True, weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )

    detail_font = resolve_font(max(9, BASE_FONT - 1))

    def row_right_edge(row):
        if row.rain_text is not None:
            return row.rain_text.x + text_size(draw, row.rain_text.text, detail_font)[0]
        return row.pie_cx + row.pie_r

    rightmost = max(row_right_edge(r) for r in layout.forecast_rows)
    # The forecast's rightmost content must stay within the canvas.
    assert rightmost <= narrow_w, f"forecast content clipped: {rightmost} > {narrow_w}"

    # And the summary should have been truncated (ellipsis) to make it fit.
    assert layout.week is not None
    assert layout.week.text.endswith("…")


def test_week_summary_shown_in_full_on_wide_canvas(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: _long_summary_report())

    wide_w = 1600
    img = Image.new("RGB", (wide_w, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, _long_summary_report(), wide_w, 0, 420,
        Settings(weather_rain_as_pie=True, weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    # Plenty of room → full phrase, no ellipsis.
    assert layout.week is not None
    assert layout.week.text == "7-day: an even mix of rainy and cloudy"
    assert not layout.week.text.endswith("…")
