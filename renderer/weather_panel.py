"""
weather_panel.py — Draw the weather block in the bottom zone of the wallpaper.

The panel's geometry is computed once by ``weather_layout.build_weather_layout``
into plain dataclasses holding absolute positions; this module's ``draw_weather``
is a thin paint pass that walks those objects and draws them. The pure
data/formatting helpers live in ``weather_panel_text``.

Layout (as produced by the layout pass):

  • a date line on top — Gregorian date centered over the left column, a
    moon-phase glyph aligned to the forecast column, and the lunar date,
  • a two-column body sharing a top:
      left  — a current-conditions hero (icon + big temperature + low/high),
              then a UV bar, the next sun event, and the 7-day overview,
      right — one row per upcoming hour (icon, time, temperature, rain),
  • a full-width footer — location · timezone.
"""

from datetime import date, datetime

from PIL import ImageDraw

from config import Settings, Theme

from .draw_utils import blend, ramp_color, resolve_font, text_size
from .icons import (
    draw_moon_phase,
    draw_planet_symbol,
    draw_rain_pie,
    draw_weather_icon,
)
from .weather_layout import WeatherLayout, build_weather_layout
from .weather_panel_text import (
    FLARE_BANDS,
    KP_BANDS,
    UV_BANDS,
    flare_band_index,
    flare_label,
    kp_band_index,
    uv_band_index,
)

# Re-exported so the package's historical API (renderer._weather_condition etc.)
# and tests can keep importing these names from here.
from .weather_panel_text import (  # noqa: F401
    code_bucket,
    format_dates,
    format_gmt_offset,
    format_hour_rain,
    kp_label,
    next_solar_event,
    parse_flare_class,
    summarize_week,
    uv_label,
    weather_condition,
)


# ---------------------------------------------------------------------------
# Segmented bar widget — shared by the UV and Kp indicators
# ---------------------------------------------------------------------------

def _draw_segmented_bar(draw, x, y, width, bands, active, value_text,
                        caption, detail_font, theme, center_label: bool) -> int:
    """
    Draw a banded indicator at (x, y): one rounded segment per band, the active
    band highlighted (others dimmed toward the background), *value_text* shown
    inside the active segment, and *caption* underneath (centered, or
    left-aligned when center_label is False). Returns the total height drawn.

    This backs both the UV and the geomagnetic-Kp widgets so they share one
    look and one implementation.
    """
    n = len(bands)
    seg_gap = 2
    seg_h = max(8, text_size(draw, "0", detail_font)[1] + 4)
    seg_w = (width - (n - 1) * seg_gap) / n

    for i, (_upper, _label, color) in enumerate(bands):
        sx0 = x + i * (seg_w + seg_gap)
        sx1 = sx0 + seg_w
        fill = color if i == active else blend(theme.background, color, 0.35)
        draw.rounded_rectangle([sx0, y, sx1, y + seg_h], radius=2, fill=fill)

        if i == active and value_text:
            vw, vh = text_size(draw, value_text, detail_font)
            color = bands[active][2]
            luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            txt_color = (20, 20, 20) if luma > 140 else (245, 245, 245)
            draw.text((sx0 + (seg_w - vw) / 2, y + (seg_h - vh) / 2 - 1),
                      value_text, fill=txt_color, font=detail_font)

    lw, lh = text_size(draw, caption, detail_font)
    label_y = y + seg_h + 4
    label_x = x + (width - lw) / 2 if center_label else x
    draw.text((label_x, label_y), caption, fill=theme.label_color, font=detail_font)
    return seg_h + 4 + lh


def draw_uv_bar(draw, x, y, width, uv_value, detail_font, theme,
                center_label: bool = True) -> int:
    """Draw the WHO UV-index widget as a segmented bar. Returns its height."""
    active = uv_band_index(uv_value)
    return _draw_segmented_bar(
        draw, x, y, width, UV_BANDS, active, f"{uv_value:.0f}",
        f"UV  {UV_BANDS[active][1]}", detail_font, theme, center_label)


def draw_kp_bar(draw, x, y, width, kp_value, detail_font, theme,
                center_label: bool = False) -> int:
    """Draw the geomagnetic Kp-index widget as a segmented bar. Returns height."""
    active = kp_band_index(kp_value)
    return _draw_segmented_bar(
        draw, x, y, width, KP_BANDS, active, f"{kp_value:.0f}",
        f"Kp  {KP_BANDS[active][1]}", detail_font, theme, center_label)


def draw_flare_bar(draw, x, y, width, flare_class, detail_font, theme,
                   center_label: bool = False) -> int:
    """
    Draw the solar X-ray flare-class widget (A/B/C/M/X) as a segmented bar.
    The active segment is the current class's letter; the caption shows the
    full class (e.g. "Flare  C3.6"). Returns the total height drawn.
    """
    active = flare_band_index(flare_class)
    # FLARE_BANDS are (letter, color); adapt to the (upper, label, color) shape
    # the shared bar drawer expects, and show the letter inside the segment.
    bands = [(None, letter, color) for letter, color in FLARE_BANDS]
    return _draw_segmented_bar(
        draw, x, y, width, bands, active, FLARE_BANDS[active][0],
        flare_label(flare_class), detail_font, theme, center_label)


# ---------------------------------------------------------------------------
# Paint pass
# ---------------------------------------------------------------------------

def _paint_weather(
    draw: ImageDraw.ImageDraw,
    layout: WeatherLayout,
    theme: Theme,
    base_font_size: int,
) -> None:
    """Draw a measured WeatherLayout. All positions are absolute; no arithmetic."""
    detail_font = resolve_font(max(9, base_font_size - 1))
    big_temp_font = resolve_font(max(22, int(base_font_size * 2.6)))

    pill_color = blend(theme.background, theme.label_color, 0.10)
    bright = blend(theme.label_color, (255, 255, 255), 0.15)
    icon_accent = blend(theme.elapsed_period_colors[1], (255, 255, 255), 0.3)
    label_color = theme.label_color

    def _at(piece, font, fill):
        draw.text((piece.x, piece.y), piece.text, fill=fill, font=font)

    # Pill ---------------------------------------------------------------
    draw.rounded_rectangle(list(layout.pill_box), radius=6, fill=pill_color)

    # Date line ----------------------------------------------------------
    dl = layout.date_line
    _at(dl.gregorian, detail_font, label_color)
    if dl.has_lunar:
        draw_moon_phase(draw, dl.moon_x, dl.moon_y, dl.moon_radius,
                        bright, pill_color, dl.lunar_day)
        if dl.lunar_box is not None:
            draw.rounded_rectangle(list(dl.lunar_box), radius=3, outline=bright,
                                   width=max(1, base_font_size // 8))
        _at(dl.lunar, detail_font, label_color)

    # Space-weather column (leftmost, optional) --------------------------
    if layout.space is not None:
        sp = layout.space
        _at(sp.heading, detail_font, bright)
        draw_kp_bar(draw, sp.kp_bar.x, sp.kp_bar.y, sp.kp_bar.width,
                    sp.kp_bar.value, detail_font, theme, center_label=False)
        # Solar activity as a flare-class segmented bar (A/B/C/M/X).
        if sp.flare_bar is not None:
            fb = sp.flare_bar
            draw_flare_bar(draw, fb.x, fb.y, fb.width, fb.flare_class,
                           detail_font, theme, center_label=False)
        if sp.solar_cycle is not None:
            _at(sp.solar_cycle, detail_font, bright)
        # Visible planets: vector symbol + short tag per planet, not names.
        if sp.planets is not None:
            for entry in sp.planets.entries:
                draw_planet_symbol(draw, entry.glyph.planet, entry.glyph.x,
                                   entry.glyph.y, entry.glyph.size, bright)
                _at(entry.tag, detail_font, bright)
        # The conjunction is drawn as two vector planet symbols + a "N°" label,
        # rather than planet names, to stay compact.
        if sp.conjunction is not None:
            cj = sp.conjunction
            draw_planet_symbol(draw, cj.glyph_a.planet, cj.glyph_a.x,
                               cj.glyph_a.y, cj.glyph_a.size, bright)
            draw_planet_symbol(draw, cj.glyph_b.planet, cj.glyph_b.x,
                               cj.glyph_b.y, cj.glyph_b.size, bright)
            _at(cj.sep, detail_font, bright)

    # Hero ---------------------------------------------------------------
    hero = layout.hero
    if hero.has_icon:
        draw_weather_icon(draw, hero.icon_key, hero.icon_x, hero.icon_y,
                          hero.icon_size, bright, icon_accent, pill_color)
    _at(hero.temp, big_temp_font, bright)
    if hero.has_lowhigh:
        _at(hero.high_label, detail_font, ramp_color(theme, 1.0))
        _at(hero.high_num, detail_font, ramp_color(theme, 1.0))
        _at(hero.low_label, detail_font, ramp_color(theme, 0.0))
        _at(hero.low_num, detail_font, ramp_color(theme, 0.0))

    # UV bar -------------------------------------------------------------
    if layout.uv_bar is not None:
        uv = layout.uv_bar
        draw_uv_bar(draw, uv.x, uv.y, uv.width, uv.value, detail_font, theme,
                    center_label=False)

    # Sun event + day length + 7-day overview ---------------------------
    if layout.solar is not None:
        _at(layout.solar, detail_font, bright)
    if layout.week is not None:
        _at(layout.week, detail_font, bright)

    # Forecast rows ------------------------------------------------------
    pie_track = blend(theme.background, theme.label_color, 0.18)
    pie_outline = blend(theme.background, theme.label_color, 0.45)
    for row in layout.forecast_rows:
        if row.icon_key != "unknown":
            draw_weather_icon(draw, row.icon_key, row.icon_x, row.icon_y,
                              row.icon_size, label_color, icon_accent, pill_color)
        _at(row.time, detail_font, label_color)
        _at(row.temp, detail_font, row.temp_color)
        if layout.rain_as_pie:
            draw_rain_pie(draw, row.pie_cx, row.pie_cy, row.pie_r,
                          row.rain_fraction, fill=row.rain_color,
                          track=pie_track, outline=pie_outline)
            if row.rain_text is not None:
                _at(row.rain_text, detail_font, row.rain_color)
        elif row.rain_text is not None:
            _at(row.rain_text, detail_font, row.rain_color)

    # Footer -------------------------------------------------------------
    if layout.footer is not None:
        _at(layout.footer, detail_font, label_color)


def _fetch_report(settings: Settings):
    """
    Fetch the weather report for *settings*, returning None on any failure.

    Imported lazily so a missing weather module or network stack can never
    prevent a render.
    """
    try:
        from weather import get_weather
        return get_weather(
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
            location=settings.weather_location,
            fahrenheit=settings.weather_fahrenheit,
            space_weather=getattr(settings, "show_space_weather", False),
        )
    except Exception:
        return None


def draw_weather(
    draw: ImageDraw.ImageDraw,
    canvas_w: int, zone_y: int, zone_h: int,
    settings: Settings,
    theme: Theme,
    stat_font,
    base_font_size: int,
    today: date,
    now: datetime,
) -> None:
    """
    Fetch the weather, measure the panel, and paint it centered in the bottom
    zone. If no weather data is available (offline with no cache), nothing is
    drawn.
    """
    report = _fetch_report(settings)
    if report is None:
        return

    layout = build_weather_layout(
        draw, report, canvas_w, zone_y, zone_h,
        settings, theme, base_font_size, today, now,
    )
    _paint_weather(draw, layout, theme, base_font_size)


def render_weather_panel(
    img,
    settings: Settings,
    theme: Theme,
    base_font_size: int,
    today: date,
    now: datetime,
) -> bool:
    """
    Draw the weather panel on its own, centered (both axes) in *img*.

    Unlike draw_weather — which bottom-anchors the panel inside a wallpaper's
    stats zone — this centers the standalone widget in the whole frame, for the
    "Open Weather" quick view. Returns True if the panel was drawn, False when
    there was no weather data (the caller leaves the background as-is).
    """
    report = _fetch_report(settings)
    if report is None:
        return False

    draw = ImageDraw.Draw(img)
    canvas_w, canvas_h = img.size

    def _pill(size: int):
        return build_weather_layout(
            draw, report, canvas_w, 0, canvas_h,
            settings, theme, size, today, now,
        ).pill_box

    # Shrink the base font until the whole block fits the frame width. With the
    # optional space-weather column the panel is three columns wide and can
    # overflow a small quick-view frame; scaling the font down keeps every
    # column on-screen instead of clipping the leftmost one. Stop at a legible
    # floor even if it still won't fit (better small than clipped).
    fitted = base_font_size
    while fitted > 10:
        px0, _, px1, _ = _pill(fitted)
        if (px1 - px0) <= canvas_w:
            break
        fitted -= 1
    base_font_size = fitted

    # Lay out once at the fitted size to read the pill height, then re-lay-out
    # into a zone that vertically centers it. build_weather_layout bottom-
    # anchors within the zone with a fixed margin, so a zone of exactly
    # (panel height + 2*margin) centred in the frame places the panel mid-frame.
    x0, y0, x1, y1 = _pill(base_font_size)
    panel_h = y1 - y0
    margin = 18
    zone_h = panel_h + 2 * margin
    zone_y = max(0, (canvas_h - zone_h) // 2)

    layout = build_weather_layout(
        draw, report, canvas_w, zone_y, zone_h,
        settings, theme, base_font_size, today, now,
    )
    _paint_weather(draw, layout, theme, base_font_size)
    return True
