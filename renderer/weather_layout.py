"""
weather_layout.py — Geometry for the weather panel, computed up front.

The weather panel has a fiddly two-column layout whose pieces must line up
(the Gregorian date centers over the left column, the moon aligns to the
forecast column, the low/high numbers right-align to a shared edge, the two
columns justify to a common height). Historically the measuring and the
drawing were interleaved in one function, so a size computed in the "measure"
half had to be mirrored by hand in the "paint" half 150 lines later.

This module splits that apart. ``build_weather_layout`` does all the
measurement and arithmetic once and returns a ``WeatherLayout`` of plain
dataclasses holding *absolute* pixel positions. The paint pass in
``weather_panel`` then just reads those positions — there is no second place
that recomputes an offset, so the two halves cannot drift.

Nothing here draws; it only measures (via a Pillow ``ImageDraw`` used purely
for text metrics) and positions.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple

from PIL import ImageDraw

from config import Settings, Theme

from .draw_utils import resolve_font, text_size
from .weather_panel_text import (
    aurora_outlook,
    format_dates,
    format_gmt_offset,
    format_hour_rain,
    next_solar_event,
    solar_activity_outlook,
    summarize_week,
    uv_band_index,
    weather_condition,
)

RGB = Tuple[int, int, int]


def _truncate_to_width(draw, text: str, font, max_width: int) -> str:
    """
    Return *text* shortened with a trailing "…" so it fits within *max_width*
    pixels in *font*. Returns the text unchanged when it already fits (or when
    max_width is non-positive, since there's nothing sensible to fit it to).
    Whole words are dropped before falling back to trimming characters, so the
    result still reads naturally.
    """
    if max_width <= 0 or text_size(draw, text, font)[0] <= max_width:
        return text

    ellipsis = "…"
    # Prefer dropping whole trailing words first.
    words = text.split(" ")
    while len(words) > 1:
        words.pop()
        candidate = " ".join(words) + ellipsis
        if text_size(draw, candidate, font)[0] <= max_width:
            return candidate

    # Still too wide (a single long word, or even one word won't fit): trim
    # characters until the text plus the ellipsis fits.
    base = words[0] if words else text
    while base:
        base = base[:-1]
        candidate = base + ellipsis
        if text_size(draw, candidate, font)[0] <= max_width:
            return candidate
    return ellipsis


# ---------------------------------------------------------------------------
# Positioned pieces — each carries the absolute coordinates the paint pass uses
# ---------------------------------------------------------------------------

@dataclass
class TextPiece:
    """A string positioned at an absolute (x, y), to be drawn in a given font."""
    text: str
    x: int
    y: int


@dataclass
class DateLine:
    """The header row: Gregorian date, optional moon glyph + lunar date."""
    gregorian: TextPiece
    # Lunar side is present only when the lunar date resolved.
    has_lunar: bool
    lunar: Optional[TextPiece] = None
    moon_x: int = 0
    moon_y: int = 0
    moon_radius: int = 0
    lunar_day: Optional[int] = None
    # Observance-day box around the lunar date (lunar 2nd/16th).
    lunar_box: Optional[Tuple[int, int, int, int]] = None


@dataclass
class Hero:
    """Current-conditions hero: icon + big temperature + stacked low/high."""
    has_icon: bool
    icon_key: str
    icon_x: int
    icon_y: int
    icon_size: int

    temp: TextPiece              # big current temperature

    has_lowhigh: bool
    high_label: Optional[TextPiece] = None   # "H"
    high_num: Optional[TextPiece] = None
    low_label: Optional[TextPiece] = None    # "L"
    low_num: Optional[TextPiece] = None


@dataclass
class UVBar:
    """The segmented UV widget's placement (the widget draws its own segments)."""
    x: int
    y: int
    width: int
    value: float


@dataclass
class KpBar:
    """The segmented Kp (geomagnetic) widget's placement, UV-bar style."""
    x: int
    y: int
    width: int
    value: float


@dataclass
class SpaceColumn:
    """
    The optional space-weather column (leftmost): a heading, the Kp bar, and a
    stack of one-line readouts (aurora, solar activity, solar cycle, planets,
    conjunction). All positions absolute; present only when enabled. Each text
    line is optional so the column collapses cleanly when data is missing.
    """
    heading: TextPiece
    kp_bar: KpBar
    aurora: Optional[TextPiece] = None
    solar_activity: Optional[TextPiece] = None
    solar_cycle: Optional[TextPiece] = None
    planets: Optional[TextPiece] = None
    conjunction: Optional[TextPiece] = None


@dataclass
class ForecastRow:
    """One hourly forecast row with each cell positioned absolutely."""
    icon_key: str
    icon_x: int
    icon_y: int
    icon_size: int
    time: TextPiece
    temp: TextPiece
    temp_color: RGB
    rain_fraction: float          # 0–1, for the pie
    rain_text: Optional[TextPiece]  # mm (pie mode) or "NN%" text
    rain_color: RGB
    # Pie geometry (pie mode only).
    pie_cx: int = 0
    pie_cy: int = 0
    pie_r: int = 0


@dataclass
class WeatherLayout:
    """Everything the paint pass needs, with absolute coordinates throughout."""
    # Outer pill.
    pill_box: Tuple[int, int, int, int]

    date_line: DateLine
    hero: Hero
    forecast_rows: List[ForecastRow]

    uv_bar: Optional[UVBar] = None
    solar: Optional[TextPiece] = None
    daylen: Optional[TextPiece] = None
    week: Optional[TextPiece] = None
    footer: Optional[TextPiece] = None
    space: Optional[SpaceColumn] = None

    rain_as_pie: bool = True


# ---------------------------------------------------------------------------
# Layout construction
# ---------------------------------------------------------------------------

def build_weather_layout(
    draw: ImageDraw.ImageDraw,
    report,
    canvas_w: int,
    zone_y: int,
    zone_h: int,
    settings: Settings,
    theme: Theme,
    base_font_size: int,
    today: date,
    now: datetime,
) -> WeatherLayout:
    """
    Measure every piece of the weather panel and return a WeatherLayout with
    absolute pixel positions. Pure geometry — no drawing beyond text metrics.
    """
    from .draw_utils import ramp_color

    detail_font = resolve_font(max(9, base_font_size - 1))
    big_temp_font = resolve_font(max(22, int(base_font_size * 2.6)))

    def tsize(text, font):
        return text_size(draw, text, font)

    # Vertical rhythm.
    line_gap = base_font_size
    row_gap = max(6, base_font_size // 2)
    column_gap = base_font_size * 4

    # Block framing: the pill's inner padding and the gap from the zone edge.
    # Defined here (not just at the anchor step) because the 7-day summary's
    # width budget depends on the pad.
    margin = 18
    pad = 14

    unit = report.temperature_unit
    deg = unit[0] if unit else "°"

    # ---- Content strings ----------------------------------------------------
    gregorian, lunar, lunar_day = format_dates(today)
    moon_r = max(4, base_font_size // 2)
    moon_gap = 5
    lunar_boxed = lunar_day in (2, 16)

    temp_text = f"{report.temperature:.0f}{unit}"
    has_lowhigh = report.temp_low is not None and report.temp_high is not None
    high_num_text = f"{report.temp_high:.0f}{deg}" if has_lowhigh else ""
    low_num_text = f"{report.temp_low:.0f}{deg}" if has_lowhigh else ""

    place = report.location or ""
    gmt = format_gmt_offset(report.utc_offset_seconds)
    tz = f"GMT{gmt}" if gmt else ""
    footer_text = "  ·  ".join(t for t in (place, tz) if t)

    solar = next_solar_event(report, now)
    solar_text = f"{solar[0]}  {solar[1]}" if solar else ""

    # Day length for the current day, shown under the sun event in the main
    # column. Derived from today's sunrise/sunset the report already carries.
    import astro
    daylen = astro.day_length_text(report.sunrise_today, report.sunset_today)
    daylen_text = f"Daylight  {daylen}" if daylen else ""

    icon_key, _ = weather_condition(report.weather_code)
    has_icon = icon_key != "unknown"

    uv_value = report.uv_index if report.uv_index is not None else report.uv_index_max
    show_uv = uv_value is not None

    # Space weather: show the column only when the setting is on AND we have a
    # Kp value (the fetch may have failed or the cache may predate the field).
    kp_value = report.kp_index if report.kp_index is not None else report.kp_forecast_max
    show_space = bool(getattr(settings, "show_space_weather", False)) and kp_value is not None
    space_heading_text = "Space weather" if show_space else ""
    aurora_text = aurora_outlook(kp_value) if show_space else ""
    # Extra space-weather lines (any may be blank → omitted from the column).
    solar_activity_text = solar_activity_outlook(report.r_scale) if show_space else ""
    solar_cycle_text = astro.solar_cycle_text(today) if show_space else ""
    planets_text = astro.planets_text(now) if show_space else ""
    conjunction_text = astro.conjunction_text(now) if show_space else ""

    week_summary = summarize_week(report.weekly_codes)
    week_text = f"7-day: {week_summary}" if week_summary else ""

    rain_as_pie = settings.weather_rain_as_pie
    rows_text = [
        (h.label, f"{h.temperature:.0f}{deg}", format_hour_rain(h, rain_as_pie))
        for h in report.hours
    ]

    # ---- Measure ------------------------------------------------------------
    greg_w, date_h = tsize(gregorian, detail_font)
    lunar_w, lunar_h = tsize(lunar, detail_font) if lunar else (0, 0)
    date_sep_w, _ = tsize("    " if lunar else "", detail_font)
    moon_w = (2 * moon_r + moon_gap) if lunar else 0
    date_line_w = greg_w + date_sep_w + moon_w + lunar_w
    date_line_h = max(date_h, lunar_h, 2 * moon_r if lunar else 0)

    detail_line_h = tsize("Ag", detail_font)[1]
    temp_w, temp_h = tsize(temp_text, big_temp_font)

    lh_label_w = max(tsize("H", detail_font)[0],
                     tsize("L", detail_font)[0]) if has_lowhigh else 0
    high_num_w, high_h = tsize(high_num_text, detail_font) if has_lowhigh else (0, 0)
    low_num_w, low_h = tsize(low_num_text, detail_font) if has_lowhigh else (0, 0)
    lh_num_w = max(high_num_w, low_num_w)
    lh_label_num_gap = base_font_size // 2
    solar_w, solar_h = tsize(solar_text, detail_font) if solar_text else (0, 0)
    daylen_w, daylen_h = tsize(daylen_text, detail_font) if daylen_text else (0, 0)
    _, row_h = tsize("0:00", detail_font)

    icon_size = int(temp_h * 1.5) if has_icon else 0
    icon_block_w = icon_size

    hero_gap = base_font_size
    lh_line_gap = max(2, line_gap // 3)
    lowhigh_w = lh_label_w + lh_label_num_gap + lh_num_w
    lowhigh_h = (high_h + lh_line_gap + low_h) if has_lowhigh else 0
    lowhigh_gap = base_font_size // 2

    hero_h = max(temp_h, lowhigh_h, icon_size)
    hero_w = (icon_block_w + (hero_gap if has_icon else 0)
              + temp_w + (lowhigh_gap + lowhigh_w if has_lowhigh else 0))

    uv_w = max(base_font_size * 10, hero_w) if show_uv else 0
    uv_seg_h = max(8, detail_line_h + 4) if show_uv else 0
    uv_h = (uv_seg_h + 4 + detail_line_h) if show_uv else 0

    # Space-weather column: a heading, a Kp segmented bar (same build as the UV
    # bar — one segment per band, value + label), then a stack of one-line
    # readouts (aurora, solar activity, solar cycle, planets, conjunction).
    # Blank lines are dropped so the column collapses cleanly.
    space_seg_h = max(8, detail_line_h + 4) if show_space else 0
    kp_bar_h = (space_seg_h + 4 + detail_line_h) if show_space else 0  # bar + label
    space_head_w, space_head_h = tsize(space_heading_text, detail_font) if show_space else (0, 0)
    # The text lines below the Kp bar, in display order, keyed so the paint
    # pass can place each into the right SpaceColumn slot.
    space_lines = []
    if show_space:
        for key, txt in (("aurora", aurora_text),
                         ("solar_activity", solar_activity_text),
                         ("solar_cycle", solar_cycle_text),
                         ("planets", planets_text),
                         ("conjunction", conjunction_text)):
            if txt:
                lw, lh = tsize(txt, detail_font)
                space_lines.append((key, txt, lw, lh))
    # Width is driven by the widest line; give the Kp bar a sensible minimum so
    # its six segments stay legible, matching the UV bar's floor.
    space_lines_w = max((lw for _k, _t, lw, _lh in space_lines), default=0)
    space_w = max(space_head_w, space_lines_w, base_font_size * 10) if show_space else 0
    if show_space:
        space_h = space_head_h + line_gap + kp_bar_h
        for _k, _t, _lw, lh in space_lines:
            space_h += line_gap + lh
    else:
        space_h = 0

    # The right column (forecast table) width is independent of the left
    # column, so measure it first — it anchors how much room the left column,
    # and the 7-day summary in particular, may use.
    col_gap = 10
    hour_icon_size = row_h + base_font_size // 2
    pie_d = row_h + base_font_size // 2
    pie_gap = 6
    time_col_w = max((tsize(r[0], detail_font)[0] for r in rows_text), default=0)
    temp_col_w = max((tsize(r[1], detail_font)[0] for r in rows_text), default=0)
    rain_text_w = max((tsize(r[2], detail_font)[0] for r in rows_text), default=0)
    if rain_as_pie:
        rain_col_w = pie_d + (pie_gap + rain_text_w if rain_text_w else 0)
    else:
        rain_col_w = rain_text_w
    forecast_w = (hour_icon_size + col_gap + time_col_w + col_gap
                  + temp_col_w + col_gap + rain_col_w)
    hour_row_h = max(row_h, hour_icon_size, pie_d if rain_as_pie else 0)
    forecast_h = len(rows_text) * hour_row_h + max(0, len(rows_text) - 1) * row_gap

    right_w = forecast_w
    right_h = forecast_h

    # The 7-day summary is a supplementary one-liner. Left unchecked, a long
    # phrase widens the left column, pushes the forecast table right, and runs
    # the whole block off the canvas edge — clipping the rain mm text. So the
    # structural left-column width comes from the hero/UV/sun only, and the
    # summary is capped to the horizontal room actually available: it may use
    # up to the structural width, extended by whatever slack remains before the
    # block would exceed the canvas (block = pad + left + column_gap + right +
    # pad). On a wide display that lets the summary show in full; on a narrow
    # one it is truncated with an ellipsis rather than overflowing.
    # The optional space column (plus its gap) also eats horizontal room, so
    # fold it into the slack the 7-day summary may use before overflow.
    space_prefix_w = (space_w + column_gap) if show_space else 0

    structural_left_w = max(hero_w, uv_w, solar_w, daylen_w)
    if week_text:
        available = canvas_w - 2 * pad - space_prefix_w - column_gap - right_w
        week_budget = max(structural_left_w, available)
        week_text = _truncate_to_width(draw, week_text, detail_font, week_budget)
    week_w, week_h = tsize(week_text, detail_font) if week_text else (0, 0)

    left_w = max(structural_left_w, week_w)
    left_h = hero_h
    if show_uv:
        left_h += line_gap + uv_h
    if solar_text:
        left_h += line_gap + solar_h
    if daylen_text:
        left_h += line_gap + daylen_h
    if week_text:
        left_h += line_gap + week_h

    body_w = space_prefix_w + left_w + column_gap + right_w
    body_h = max(space_h, left_h, right_h)

    def justified_gap(content_h: int, n_gaps: int, base_gap: int) -> int:
        if n_gaps <= 0:
            return base_gap
        return max(base_gap, (body_h - content_h) // n_gaps)

    left_row_heights = [hero_h]
    if show_uv:
        left_row_heights.append(uv_h)
    if solar_text:
        left_row_heights.append(solar_h)
    if daylen_text:
        left_row_heights.append(daylen_h)
    if week_text:
        left_row_heights.append(week_h)
    left_gap = justified_gap(sum(left_row_heights), len(left_row_heights) - 1, line_gap)
    right_gap = justified_gap(len(rows_text) * hour_row_h,
                              max(0, len(rows_text) - 1), row_gap)

    footer_w, footer_h = tsize(footer_text, detail_font) if footer_text else (0, 0)

    block_w = max(date_line_w, body_w, footer_w)
    block_h = date_line_h + line_gap + body_h
    if footer_text:
        block_h += line_gap + footer_h

    # ---- Absolute anchors ---------------------------------------------------
    # Center horizontally, but never let the (pill-padded) block run off the
    # left edge: if the block is wider than the canvas, pin its left pad to 0
    # rather than centering, so the leftmost column stays visible. (The right
    # side may still extend past a too-narrow canvas, but the standalone widget
    # sizes its font to avoid that; the wallpaper is far wider than the block.)
    bx = max(pad, (canvas_w - block_w) // 2)
    by = zone_y + zone_h - block_h - margin
    pill_box = (bx - pad, by - pad, bx + block_w + pad, by + block_h + pad)

    col_left_x = bx + (block_w - body_w) // 2
    body_y = by + date_line_h + line_gap
    # The space column (when shown) is leftmost; the hero/left column and the
    # forecast/right column shift right by its width + gap.
    space_x = col_left_x
    left_x = col_left_x + space_prefix_w
    right_x = left_x + left_w + column_gap

    # ---- Date line ----------------------------------------------------------
    date_y = by + (date_line_h - date_h) // 2
    if lunar:
        greg_piece = TextPiece(gregorian,
                               left_x + (left_w - greg_w) // 2, date_y)
        moon_x = left_x + left_w + column_gap
        moon_y = by + (date_line_h - 2 * moon_r) // 2
        lunar_y = by + (date_line_h - lunar_h) // 2
        moon_right = moon_x + 2 * moon_r
        lunar_x = moon_right + moon_gap
        lunar_box = None
        if lunar_boxed:
            box_pad_x, box_pad_y = 5, 3
            box_left = max(lunar_x - box_pad_x, moon_right + moon_gap)
            lunar_x = box_left + box_pad_x
            lunar_box = (box_left, lunar_y - box_pad_y,
                         lunar_x + lunar_w + box_pad_x, lunar_y + lunar_h + box_pad_y)
        date_line = DateLine(
            gregorian=greg_piece, has_lunar=True,
            lunar=TextPiece(lunar, lunar_x, lunar_y),
            moon_x=moon_x, moon_y=moon_y, moon_radius=moon_r,
            lunar_day=lunar_day, lunar_box=lunar_box,
        )
    else:
        date_line = DateLine(
            gregorian=TextPiece(gregorian, bx + (block_w - greg_w) // 2, date_y),
            has_lunar=False,
        )

    # ---- Space-weather column (leftmost, optional) --------------------------
    space_column = None
    if show_space:
        sy = body_y
        heading = TextPiece(space_heading_text, space_x, sy)
        sy += space_head_h + line_gap
        kp_bar = KpBar(x=space_x, y=sy, width=space_w, value=kp_value)
        sy += kp_bar_h
        space_column = SpaceColumn(heading=heading, kp_bar=kp_bar)
        for key, txt, _lw, lh in space_lines:
            sy += line_gap
            setattr(space_column, key, TextPiece(txt, space_x, sy))
            sy += lh

    # ---- Hero ---------------------------------------------------------------
    ly = body_y
    icon_x = icon_y = 0
    if has_icon:
        icon_inset = int(icon_size * 0.05)
        icon_x = left_x - icon_inset
        icon_y = ly + (hero_h - icon_size) // 2 + int(icon_size * 0.15)
    temp_x = left_x + (icon_block_w + hero_gap if has_icon else 0)
    temp_y = ly + (hero_h - temp_h) // 2

    hero = Hero(
        has_icon=has_icon, icon_key=icon_key,
        icon_x=icon_x, icon_y=icon_y, icon_size=icon_size,
        temp=TextPiece(temp_text, temp_x, temp_y),
        has_lowhigh=has_lowhigh,
    )
    if has_lowhigh:
        lh_x = temp_x + temp_w + lowhigh_gap
        lh_right = lh_x + lowhigh_w
        lh_y = ly + (hero_h - lowhigh_h) // 2
        low_y = lh_y + high_h + lh_line_gap
        hero.high_label = TextPiece("H", lh_x, lh_y)
        hero.high_num = TextPiece(high_num_text, lh_right - high_num_w, lh_y)
        hero.low_label = TextPiece("L", lh_x, low_y)
        hero.low_num = TextPiece(low_num_text, lh_right - low_num_w, low_y)
    ly += hero_h

    uv_bar = None
    if show_uv:
        ly += left_gap
        uv_bar = UVBar(x=left_x, y=ly, width=uv_w, value=uv_value)
        ly += uv_h

    solar_piece = None
    if solar_text:
        ly += left_gap
        solar_piece = TextPiece(solar_text, left_x, ly)
        ly += solar_h

    daylen_piece = None
    if daylen_text:
        ly += left_gap
        daylen_piece = TextPiece(daylen_text, left_x, ly)
        ly += daylen_h

    week_piece = None
    if week_text:
        ly += left_gap
        week_piece = TextPiece(week_text, left_x, ly)

    # ---- Forecast rows ------------------------------------------------------
    hourly_temps = [h.temperature for h in report.hours]
    t_min = report.temp_low if report.temp_low is not None else (min(hourly_temps) if hourly_temps else 0.0)
    t_max = report.temp_high if report.temp_high is not None else (max(hourly_temps) if hourly_temps else 1.0)
    t_span = (t_max - t_min) or 1.0

    f_icon_x = right_x
    f_time_x = f_icon_x + hour_icon_size + col_gap
    f_temp_x = f_time_x + time_col_w + col_gap
    f_rain_x = f_temp_x + temp_col_w + col_gap

    forecast_rows: List[ForecastRow] = []
    ry = body_y
    for (time_lbl, temp_lbl, rain_lbl), hour in zip(rows_text, report.hours):
        temp_color = ramp_color(theme, (hour.temperature - t_min) / t_span)
        rain_frac = hour.precip_probability / 100.0
        rain_color = ramp_color(theme, rain_frac)
        hour_key, _ = weather_condition(hour.weather_code)
        text_y = ry + (hour_row_h - row_h) // 2

        rain_piece = None
        pie_cx = pie_cy = pie_r = 0
        if rain_as_pie:
            pie_cx = f_rain_x + pie_d // 2
            pie_cy = ry + hour_row_h // 2
            pie_r = pie_d // 2
            if rain_lbl:
                rain_piece = TextPiece(rain_lbl, f_rain_x + pie_d + pie_gap, text_y)
        else:
            rain_piece = TextPiece(rain_lbl, f_rain_x, text_y)

        forecast_rows.append(ForecastRow(
            icon_key=hour_key, icon_x=f_icon_x, icon_y=ry, icon_size=hour_icon_size,
            time=TextPiece(time_lbl, f_time_x, text_y),
            temp=TextPiece(temp_lbl, f_temp_x, text_y), temp_color=temp_color,
            rain_fraction=rain_frac, rain_text=rain_piece, rain_color=rain_color,
            pie_cx=pie_cx, pie_cy=pie_cy, pie_r=pie_r,
        ))
        ry += hour_row_h + right_gap

    # ---- Footer -------------------------------------------------------------
    footer_piece = None
    if footer_text:
        footer_y = by + block_h - footer_h
        footer_piece = TextPiece(footer_text, bx + (block_w - footer_w) // 2, footer_y)

    return WeatherLayout(
        pill_box=pill_box,
        date_line=date_line,
        hero=hero,
        forecast_rows=forecast_rows,
        uv_bar=uv_bar,
        solar=solar_piece,
        daylen=daylen_piece,
        week=week_piece,
        footer=footer_piece,
        space=space_column,
        rain_as_pie=rain_as_pie,
    )
