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
from .icons import draw_moon_phase, draw_rain_pie, draw_weather_icon
from .weather_layout import WeatherLayout, build_weather_layout
from .weather_panel_text import UV_BANDS, uv_band_index

# Re-exported so the package's historical API (renderer._weather_condition etc.)
# and tests can keep importing these names from here.
from .weather_panel_text import (  # noqa: F401
    code_bucket,
    format_dates,
    format_gmt_offset,
    format_hour_rain,
    next_solar_event,
    summarize_week,
    uv_label,
    weather_condition,
)


# ---------------------------------------------------------------------------
# UV bar widget — draws its own segments, so it stays here rather than in text
# ---------------------------------------------------------------------------

def draw_uv_bar(draw, x, y, width, uv_value, detail_font, theme,
                center_label: bool = True) -> int:
    """
    Draw the UV widget at (x, y): a segmented bar with one segment per WHO UV
    band, the current numeric value shown inside its band's segment, and the
    band description underneath (centered, or left-aligned when
    center_label is False). Returns the total height drawn.
    """
    n = len(UV_BANDS)
    seg_gap = 2
    seg_h = max(8, text_size(draw, "0", detail_font)[1] + 4)
    seg_w = (width - (n - 1) * seg_gap) / n
    active = uv_band_index(uv_value)

    for i, (_upper, _label, color) in enumerate(UV_BANDS):
        sx0 = x + i * (seg_w + seg_gap)
        sx1 = sx0 + seg_w
        # Inactive bands are dimmed toward the background; the active one is
        # drawn at full strength so it stands out.
        fill = color if i == active else blend(theme.background, color, 0.35)
        draw.rounded_rectangle([sx0, y, sx1, y + seg_h], radius=2, fill=fill)

        if i == active:
            val = f"{uv_value:.0f}"
            vw, vh = text_size(draw, val, detail_font)
            # Pick black or white text for contrast against the band colour.
            luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            txt_color = (20, 20, 20) if luma > 140 else (245, 245, 245)
            draw.text((sx0 + (seg_w - vw) / 2, y + (seg_h - vh) / 2 - 1),
                      val, fill=txt_color, font=detail_font)

    # Band description under the bar.
    label = f"UV  {UV_BANDS[active][1]}"
    lw, lh = text_size(draw, label, detail_font)
    label_y = y + seg_h + 4
    label_x = x + (width - lw) / 2 if center_label else x
    draw.text((label_x, label_y), label, fill=theme.label_color, font=detail_font)

    return seg_h + 4 + lh


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

    # Sun event + 7-day overview ----------------------------------------
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
    # Imported lazily so a missing weather module or network stack can never
    # prevent the rest of the wallpaper from rendering.
    try:
        from weather import get_weather
        report = get_weather(
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
            location=settings.weather_location,
            fahrenheit=settings.weather_fahrenheit,
        )
    except Exception:
        report = None

    if report is None:
        return

    layout = build_weather_layout(
        draw, report, canvas_w, zone_y, zone_h,
        settings, theme, base_font_size, today, now,
    )
    _paint_weather(draw, layout, theme, base_font_size)
