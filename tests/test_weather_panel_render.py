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
PIE_MODE_DIGEST = "8ec51c031b6b3bf883fe948bb85d4902c396192005388ba234325304a4854ce5"
PCT_MODE_DIGEST = "0a6c2e9c172c6a3a6394666a284dda3e19112ece856e61629e35a6418ebd338d"


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


def test_long_week_summary_wraps_within_fixed_column(monkeypatch):
    from renderer.draw_utils import resolve_font, text_size
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: _long_summary_report())

    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, _long_summary_report(), CANVAS_W, 0, 420,
        Settings(weather_rain_as_pie=True, weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )

    detail_font = resolve_font(max(9, BASE_FONT - 1))
    # The summary is a list of wrapped lines (fixed column), not one string.
    assert isinstance(layout.week, list) and layout.week
    assert len(layout.week) <= 2  # WEEK_MAX_LINES
    # Each wrapped line fits the fixed column width (the forecast's left edge is
    # a safe upper bound on the center column's right edge).
    col_right = layout.forecast_rows[0].icon_x
    for piece in layout.week:
        w = text_size(draw, piece.text, detail_font)[0]
        assert piece.x + w <= col_right + 2
    # The full phrase is preserved across the wrapped lines.
    joined = " ".join(p.text for p in layout.week)
    assert "an even mix of rainy and cloudy" in joined


def test_week_summary_single_line_when_short(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    rep = _fixed_report()
    rep.weekly_codes = [0, 1, 0, 1]  # → "mostly sunny" (short)
    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: rep)

    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, rep, CANVAS_W, 0, 420,
        Settings(weather_rain_as_pie=True, weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    assert isinstance(layout.week, list) and len(layout.week) == 1
    assert layout.week[0].text == "7-day: mostly sunny"


# ---------------------------------------------------------------------------
# Space-weather column (third column, leftmost)
# ---------------------------------------------------------------------------

def _space_report() -> WeatherReport:
    rep = _fixed_report()
    rep.kp_index = 6.0
    rep.kp_forecast_max = 7.0
    return rep


def test_space_column_present_and_leftmost_when_enabled(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, _space_report(), CANVAS_W, 0, 420,
        Settings(show_weather=True, show_space_weather=True,
                 weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )

    assert layout.space is not None
    assert layout.space.kp_bar.value == 6.0
    # Column order left→right: space < hero < forecast.
    space_x = layout.space.heading.x
    hero_x = layout.hero.temp.x
    forecast_x = layout.forecast_rows[0].icon_x
    assert space_x < hero_x < forecast_x


def test_space_column_absent_when_disabled(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, _space_report(), CANVAS_W, 0, 420,
        Settings(show_weather=True, show_space_weather=False,
                 weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    assert layout.space is None


def test_space_column_absent_when_no_kp_data(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    # Toggle on, but the report carries no Kp (fetch failed / old cache).
    rep = _fixed_report()  # kp_index / kp_forecast_max default to None
    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, rep, CANVAS_W, 0, 420,
        Settings(show_weather=True, show_space_weather=True,
                 weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    assert layout.space is None


def test_space_column_paints_without_error(monkeypatch):
    monkeypatch.setattr(weather_mod, "get_weather", lambda **kw: _space_report())
    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))
    settings = Settings(show_weather=True, show_space_weather=True,
                        weather_location="Ho Chi Minh City")
    img = _render_panel(settings)
    # The panel should have drawn (space column adds content, so non-blank).
    blank = Image.new("RGB", (CANVAS_W, ZONE_Y + ZONE_H), (10, 10, 20))
    assert _digest(img) != _digest(blank)


# ---------------------------------------------------------------------------
# Day length (main column) + expanded space column
# ---------------------------------------------------------------------------

def test_sun_line_includes_daylight_in_parentheses(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, _fixed_report(), CANVAS_W, 0, 420,
        Settings(show_weather=True, weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    # Midday → next event is sunset 18:03; daylight 05:42→18:03 ≈ 12h 21m.
    assert layout.solar is not None
    assert layout.solar.text == "Sunset: 18:03 (Ld: 12h 21m)"


def test_sun_line_omits_daylight_without_sun_times(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    rep = _fixed_report()
    rep.sunrise_today = ""
    rep.sunset_today = ""
    rep.sunrise_tomorrow = ""
    img = Image.new("RGB", (CANVAS_W, 420), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, rep, CANVAS_W, 0, 420,
        Settings(show_weather=True, weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 14, 30),
    )
    # No sun times at all → no solar line.
    assert layout.solar is None


def test_space_column_includes_solar_and_cycle_and_planets(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    rep = _fixed_report()
    rep.kp_index = 6.0
    rep.flare_class = "C3.6"
    img = Image.new("RGB", (CANVAS_W, 460), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, rep, CANVAS_W, 0, 460,
        Settings(show_weather=True, show_space_weather=True,
                 weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 20, 30),
    )
    sp = layout.space
    assert sp is not None
    # Solar activity is now a flare-class bar, not a text line.
    assert sp.flare_bar is not None and sp.flare_bar.flare_class == "C3.6"
    # Solar-cycle info is a line below the flare bar.
    assert sp.solar_cycle is not None and sp.solar_cycle.text.startswith("Solar cycle")
    # Planets are now a night-sky strip: a gradient track with coloured dots.
    # (Astronomy-dependent, so only assert the structure when present.)
    from renderer.weather_layout import SkyStrip
    from renderer.icons import PLANET_SYMBOLS
    if sp.sky is not None:
        assert isinstance(sp.sky, SkyStrip)
        assert sp.sky.dots  # at least one visible planet placed
        for dot in sp.sky.dots:
            assert dot.planet in PLANET_SYMBOLS
            assert dot.radius > 0
            tx0, _ty0, tx1, _ty1 = sp.sky.track
            assert tx0 <= dot.cx <= tx1  # dot sits within the track span

    # The space column stacks top→down: Kp bar, flare bar, solar cycle.
    assert sp.kp_bar.y < sp.flare_bar.y < sp.solar_cycle.y


def test_space_column_omits_flare_bar_without_flare_class(monkeypatch):
    from renderer.weather_layout import build_weather_layout

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Sun, 11 Oct 2026", "16 Oct", 16))

    rep = _fixed_report()
    rep.kp_index = 6.0
    rep.flare_class = None  # no solar-activity data
    img = Image.new("RGB", (CANVAS_W, 460), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, rep, CANVAS_W, 0, 460,
        Settings(show_weather=True, show_space_weather=True,
                 weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 10, 11), now=datetime(2026, 10, 11, 20, 30),
    )
    assert layout.space is not None
    assert layout.space.flare_bar is None
    # The Kp bar still shows (space weather is on and Kp is present).
    assert layout.space.kp_bar is not None


# ---------------------------------------------------------------------------
# Conjunction rendered as vector planet symbols (not names)
# ---------------------------------------------------------------------------

def test_sky_strip_dots_sized_by_prominence(monkeypatch):
    import astro
    from renderer.weather_layout import build_weather_layout
    from renderer.weather_panel_text import PLANET_PROMINENCE

    monkeypatch.setattr(wl, "format_dates",
                        lambda today: ("Tue, 17 Mar 2026", "29 Jan", 29))

    when = datetime(2026, 3, 17, 20, 0)
    rep = _fixed_report()
    rep.kp_index = 6.0
    img = Image.new("RGB", (CANVAS_W, 480), (10, 10, 20))
    draw = ImageDraw.Draw(img)
    layout = build_weather_layout(
        draw, rep, CANVAS_W, 0, 480,
        Settings(show_weather=True, show_space_weather=True,
                 weather_location="Ho Chi Minh City"),
        Theme(name="test"), BASE_FONT,
        today=date(2026, 3, 17), now=when,
    )
    sky = layout.space.sky
    assert sky is not None and sky.dots
    radii = {d.planet: d.radius for d in sky.dots}
    # A more-prominent planet never renders smaller than a less-prominent one.
    for a in radii:
        for b in radii:
            if PLANET_PROMINENCE[a] > PLANET_PROMINENCE[b]:
                assert radii[a] >= radii[b]


def test_planet_symbols_draw_without_error():
    from renderer import PLANET_SYMBOLS, draw_planet_symbol
    img = Image.new("RGB", (240, 48), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = 4
    for planet in PLANET_SYMBOLS:
        draw_planet_symbol(draw, planet, x, 4, 24, (240, 240, 240))
        x += 40
    # Something was drawn (symbols produce non-background pixels).
    from PIL import ImageChops
    blank = Image.new("RGB", img.size, (0, 0, 0))
    assert ImageChops.difference(img, blank).getbbox() is not None
