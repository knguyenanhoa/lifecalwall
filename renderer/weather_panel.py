"""
weather_panel.py — The weather block drawn in the bottom zone of the wallpaper.

This module owns everything specific to the weather report: mapping WMO codes
to icons and summaries, UV bands, date/sun/rain formatting, and the two-column
layout (current-conditions hero + hourly forecast) with a date header and a
location/timezone footer.

The weather data itself comes from the `weather` module; this file only
formats and draws it.
"""

import math
from datetime import date, datetime
from typing import Optional, Tuple

from PIL import ImageDraw

from config import Settings, Theme

from .draw_utils import blend, ramp_color, resolve_font, text_size
from .icons import draw_moon_phase, draw_rain_pie, draw_weather_icon


# ---------------------------------------------------------------------------
# Date formatting (Gregorian + lunar)
# ---------------------------------------------------------------------------

def format_dates(today: date) -> Tuple[str, str, Optional[int]]:
    """
    Return (gregorian, lunar_string, lunar_day) for *today*.

    Gregorian is always available. The lunar date uses the Chinese lunar
    calendar via the `lunardate` package (which the Vietnamese calendar
    tracks, up to an occasional one-day timezone offset). If that package is
    unavailable, the lunar string comes back empty and lunar_day is None so
    the caller can simply omit it rather than fail. lunar_day is the day number
    within the lunar month (1–30), used to mark observance days.
    """
    gregorian = today.strftime("%a, %d %b %Y")

    # Lunar months are numbered 1–12; reuse the Gregorian month abbreviations
    # so the lunar date reads like "07 Jul" (day 7 of the 7th lunar month).
    month_abbrev = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    try:
        from lunardate import LunarDate
        lunar = LunarDate.from_solar_date(today.year, today.month, today.day)
        name = month_abbrev[(lunar.month - 1) % 12]
        leap = "+" if getattr(lunar, "isLeapMonth", False) else ""
        lunar_str = f"{lunar.day:02d} {name}{leap}"
        return gregorian, lunar_str, lunar.day
    except Exception:
        return gregorian, "", None


# ---------------------------------------------------------------------------
# WMO weather-code interpretation
# ---------------------------------------------------------------------------

def weather_condition(code: Optional[int]) -> Tuple[str, str]:
    """
    Map a WMO weather code to an (icon_key, label) pair. The icon_key selects
    which vector icon draw_weather_icon draws; the label is a short caption.
    """
    if code is None:
        return "unknown", ""
    if code == 0:
        return "clear", "Clear"
    if code in (1, 2):
        return "partly", "Partly cloudy"
    if code == 3:
        return "cloudy", "Overcast"
    if code in (45, 48):
        return "fog", "Fog"
    if 51 <= code <= 57:
        return "rain", "Drizzle"
    if 61 <= code <= 67:
        return "rain", "Rain"
    if 71 <= code <= 77:
        return "snow", "Snow"
    if 80 <= code <= 82:
        return "rain", "Rain showers"
    if code in (85, 86):
        return "snow", "Snow showers"
    if 95 <= code <= 99:
        return "thunder", "Thunderstorm"
    return "cloudy", "Cloudy"


# WHO UV-index exposure bands: (upper_bound_exclusive, label, color). The last
# band's bound is infinite. These drive both the text label and the segmented
# UV bar, so the two always agree.
_UV_BANDS = [
    (3,            "Low",       (90, 190, 90)),
    (6,            "Moderate",  (230, 200, 60)),
    (8,            "High",      (235, 150, 50)),
    (11,           "Very high", (220, 70, 60)),
    (float("inf"), "Extreme",   (160, 90, 200)),
]


def uv_band_index(uv: float) -> int:
    """Index into _UV_BANDS for a UV value."""
    for i, (upper, _label, _color) in enumerate(_UV_BANDS):
        if uv < upper:
            return i
    return len(_UV_BANDS) - 1


def uv_label(uv: float) -> str:
    """WHO UV-index exposure band label for a UV value."""
    return _UV_BANDS[uv_band_index(uv)][1]


def code_bucket(code: int) -> str:
    """Collapse a WMO code into a coarse weekly-summary bucket."""
    if code in (0, 1):
        return "sunny"
    if code in (2, 3, 45, 48):
        return "cloudy"
    if 71 <= code <= 77 or code in (85, 86):
        return "snowy"
    if 95 <= code <= 99:
        return "stormy"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rainy"
    return "cloudy"


def summarize_week(codes) -> str:
    """
    Aggregate up-to-7 daily WMO codes into a one-line outlook, e.g.
    "mostly rainy", "mostly sunny and cloudy", or "an even mix of rain and
    shine". Returns "" when there are no codes to summarize.
    """
    if not codes:
        return ""

    from collections import Counter
    counts = Counter(code_bucket(c) for c in codes)
    total = sum(counts.values())
    # Most common buckets, tie-broken by a stable severity order so the phrase
    # reads naturally rather than depending on dict insertion quirks.
    severity = {"stormy": 0, "snowy": 1, "rainy": 2, "cloudy": 3, "sunny": 4}
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], severity[kv[0]]))

    top_bucket, top_n = ranked[0]

    # A single bucket dominates the week.
    if len(ranked) == 1 or top_n >= total * 0.7:
        return f"mostly {top_bucket}"

    second_bucket, second_n = ranked[1]

    # Two comparable buckets — call it an even mix or pair them up.
    if top_n == second_n:
        pair = {top_bucket, second_bucket}
        if pair == {"rainy", "sunny"}:
            return "an even mix of rain and shine"
        return f"an even mix of {top_bucket} and {second_bucket}"

    # One leads but another is clearly present.
    if second_n >= total * 0.25:
        return f"mostly {top_bucket} and {second_bucket}"

    return f"mostly {top_bucket}"


def next_solar_event(report, now: datetime) -> Optional[Tuple[str, str]]:
    """
    Pick the next sunrise/sunset to show, as (label, "HH:MM"):

      • before today's sunrise → today's sunrise
      • between sunrise and sunset → today's sunset
      • after today's sunset → tomorrow's sunrise

    Returns None if the needed sun times are missing (e.g. offline with an old
    cache), so the caller can omit the line.
    """
    def _parse(iso: str) -> Optional[datetime]:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            return None

    sunrise = _parse(report.sunrise_today)
    sunset = _parse(report.sunset_today)
    next_sunrise = _parse(report.sunrise_tomorrow)

    if sunrise and now < sunrise:
        return "Sunrise", sunrise.strftime("%H:%M")
    if sunset and now < sunset:
        return "Sunset", sunset.strftime("%H:%M")
    if next_sunrise:
        return "Sunrise", next_sunrise.strftime("%H:%M")
    # Fall back to today's sunrise if tomorrow's is unavailable.
    if sunrise:
        return "Sunrise", sunrise.strftime("%H:%M")
    return None


def format_hour_rain(hour, as_pie: bool) -> str:
    """
    Text shown in the rain cell of a forecast row.

    In pie mode the probability is drawn as a pie, so this returns only the
    expected amount (e.g. "1.4mm"), or "" when there's no measurable rain.

    In percentage mode this returns the chance, plus the amount when
    measurable — e.g. "65%  1.4mm" or just "20%".
    """
    has_mm = hour.precip_amount >= 0.1
    mm = f"{hour.precip_amount:.1f}mm" if has_mm else ""
    if as_pie:
        return mm
    if has_mm:
        return f"{hour.precip_probability}%  {mm}"
    return f"{hour.precip_probability}%"


def format_gmt_offset(utc_offset_seconds: Optional[int]) -> str:
    """
    Format a UTC offset in seconds as a compact "±H[:MM]" string, or ""
    when the offset is unknown. E.g. 25200 → "+7", 19800 → "+5:30".
    """
    if utc_offset_seconds is None:
        return ""
    total_minutes = utc_offset_seconds // 60
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours}:{minutes:02d}" if minutes else f"{sign}{hours}"


# ---------------------------------------------------------------------------
# UV bar widget
# ---------------------------------------------------------------------------

def draw_uv_bar(draw, x, y, width, uv_value, detail_font, theme,
                center_label: bool = True) -> int:
    """
    Draw the UV widget at (x, y): a segmented bar with one segment per WHO UV
    band, the current numeric value shown inside its band's segment, and the
    band description underneath (centered, or left-aligned when
    center_label is False). Returns the total height drawn.
    """
    n = len(_UV_BANDS)
    seg_gap = 2
    seg_h = max(8, text_size(draw, "0", detail_font)[1] + 4)
    seg_w = (width - (n - 1) * seg_gap) / n
    active = uv_band_index(uv_value)

    for i, (_upper, _label, color) in enumerate(_UV_BANDS):
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
    label = f"UV  {_UV_BANDS[active][1]}"
    lw, lh = text_size(draw, label, detail_font)
    label_y = y + seg_h + 4
    label_x = x + (width - lw) / 2 if center_label else x
    draw.text((label_x, label_y), label, fill=theme.label_color, font=detail_font)

    return seg_h + 4 + lh


# ---------------------------------------------------------------------------
# The weather block
# ---------------------------------------------------------------------------

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
    Draw the weather block centered in the bottom zone. Layout:

      • a date line on top — Gregorian date centered over the left column, a
        moon-phase glyph aligned to the forecast column, and the lunar date,
      • a two-column body (both anchored to the same top):
          left  — a "current conditions" hero (condition icon beside the big
                  temperature, with low/high under the temp and the condition
                  word under the icon), then a UV bar, then the next sun event,
          right — one row per upcoming hour, then the 7-day overview,
      • a full-width footer — location · timezone.

    If no weather data is available (offline with no cache), nothing is drawn.
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

    detail_font = resolve_font(max(9, base_font_size - 1))
    # Taller so the stacked low/high beside it reads as two balanced lines.
    big_temp_font = resolve_font(max(22, int(base_font_size * 2.6)))

    # Vertical rhythm — roomier than before so lines don't feel packed.
    line_gap = base_font_size          # gap between stacked lines
    row_gap = max(6, base_font_size // 2)  # gap between hourly rows
    column_gap = base_font_size * 4    # gap between the temp and forecast columns

    unit = report.temperature_unit
    # Degrees without the unit letter, for the compact low/high pair.
    deg = unit[0] if unit else "°"

    # Date line: Gregorian text, then a drawn moon + lunar "DD Mon" -----------
    gregorian, lunar, lunar_day = format_dates(today)
    moon_r = max(4, base_font_size // 2)   # crescent radius
    moon_gap = 5                           # space between moon and lunar text
    # Highlight observance days (2nd and 16th of the lunar month) with a box.
    lunar_boxed = lunar_day in (2, 16)

    # Left column — a "current conditions" hero: condition icon beside the big
    # temperature, with low/high under the temperature and the condition word
    # under the icon. Then a UV row and a sun-event row beneath, left-aligned.
    temp_text = f"{report.temperature:.0f}{unit}"
    # Split label from number so the numbers can be right-aligned as a column.
    high_num = low_num = ""
    has_lowhigh = report.temp_low is not None and report.temp_high is not None
    if has_lowhigh:
        high_num = f"{report.temp_high:.0f}{deg}"
        low_num = f"{report.temp_low:.0f}{deg}"

    # Location and timezone sit on a full-width footer, e.g.
    # "Ho Chi Minh City  ·  GMT+7".
    place = report.location or ""
    gmt = format_gmt_offset(report.utc_offset_seconds)
    tz = f"GMT{gmt}" if gmt else ""
    footer_text = "  ·  ".join(t for t in (place, tz) if t)

    # Next solar event (sunrise before dawn, sunset by day, tomorrow's sunrise
    # after dusk).
    solar = next_solar_event(report, now)
    solar_text = f"{solar[0]}  {solar[1]}" if solar else ""

    icon_key, _condition_label = weather_condition(report.weather_code)

    # UV: live current value preferred, daily peak as fallback.
    uv_value = report.uv_index if report.uv_index is not None else report.uv_index_max
    show_uv = uv_value is not None

    # Running 7-day overview — shown under the forecast table.
    week_summary = summarize_week(report.weekly_codes)
    week_text = f"7-day: {week_summary}" if week_summary else ""

    # Right column — one row per hour: time, temperature, rain. Rain chance is
    # shown either as a mini pie chart or as "NN%" text per the user setting.
    rain_as_pie = settings.weather_rain_as_pie
    rows = [
        # Hourly temps use just the degree sign (like low/high); the big
        # current temperature already shows the full unit.
        (h.label, f"{h.temperature:.0f}{deg}", format_hour_rain(h, rain_as_pie))
        for h in report.hours
    ]

    # ---- Measure everything -------------------------------------------------
    greg_w, date_h = text_size(draw, gregorian, detail_font)
    lunar_w, lunar_h = text_size(draw, lunar, detail_font) if lunar else (0, 0)
    date_sep = "    " if lunar else ""
    date_sep_w, _ = text_size(draw, date_sep, detail_font)
    moon_w = (2 * moon_r + moon_gap) if lunar else 0
    date_line_w = greg_w + date_sep_w + moon_w + lunar_w
    date_line_h = max(date_h, lunar_h, 2 * moon_r if lunar else 0)

    detail_line_h = text_size(draw, "Ag", detail_font)[1]
    temp_w, temp_h = text_size(draw, temp_text, big_temp_font)
    # Low/high as a two-row mini-table: "H"/"L" labels left, numbers right-aligned.
    lh_label_w = max(text_size(draw, "H", detail_font)[0],
                     text_size(draw, "L", detail_font)[0]) if has_lowhigh else 0
    high_num_w, high_h = text_size(draw, high_num, detail_font) if has_lowhigh else (0, 0)
    low_num_w, low_h = text_size(draw, low_num, detail_font) if has_lowhigh else (0, 0)
    lh_num_w = max(high_num_w, low_num_w)
    lh_label_num_gap = base_font_size // 2  # gap between label and number
    solar_w, solar_h = text_size(draw, solar_text, detail_font) if solar_text else (0, 0)
    has_icon = icon_key != "unknown"
    _, row_h = text_size(draw, "0:00", detail_font)

    # Hero condition icon, sized a touch larger than the temperature so its
    # (lower-weighted) cloud glyph reads as vertically centered.
    icon_size = int(temp_h * 1.5) if has_icon else 0
    icon_block_w = icon_size

    # ---- Hero block: [icon] [big temperature] [low/high table] -------------
    hero_gap = base_font_size              # gap between icon and temperature
    lh_line_gap = max(2, line_gap // 3)    # gap between the stacked H and L rows
    lowhigh_w = lh_label_w + lh_label_num_gap + lh_num_w
    lowhigh_h = (high_h + lh_line_gap + low_h) if has_lowhigh else 0
    lowhigh_gap = base_font_size // 2      # gap between temp and the L/H table

    hero_h = max(temp_h, lowhigh_h, icon_size)
    hero_w = (icon_block_w + (hero_gap if has_icon else 0)
              + temp_w + (lowhigh_gap + lowhigh_w if has_lowhigh else 0))

    # ---- UV widget: a segmented bar with its band description beneath -------
    # Widen it so its right edge lines up roughly with the hero's right edge
    # (the right edge of the low/high numbers).
    uv_w = max(base_font_size * 10, hero_w) if show_uv else 0
    uv_seg_h = max(8, detail_line_h + 4) if show_uv else 0
    uv_h = (uv_seg_h + 4 + detail_line_h) if show_uv else 0  # bar + description

    # 7-day overview lives at the bottom of the left column.
    week_w, week_h = text_size(draw, week_text, detail_font) if week_text else (0, 0)

    # Left column geometry — hero, UV, sun event, then 7-day (all left-aligned).
    left_w = max(hero_w, uv_w, solar_w, week_w)
    left_h = hero_h
    if show_uv:
        left_h += line_gap + uv_h
    if solar_text:
        left_h += line_gap + solar_h
    if week_text:
        left_h += line_gap + week_h

    # Right column (forecast table) geometry. A small condition icon leads
    # each row, followed by the time, temperature, and rain columns.
    col_gap = 10
    hour_icon_size = row_h + base_font_size // 2
    # Rain chance: either a mini pie chart (optionally followed by the mm
    # amount) or plain "NN%" text, depending on the setting.
    pie_d = row_h + base_font_size // 2  # a bit larger than the text height
    pie_gap = 6                         # gap between the pie and the mm text
    time_col_w = max((text_size(draw, r[0], detail_font)[0] for r in rows), default=0)
    temp_col_w = max((text_size(draw, r[1], detail_font)[0] for r in rows), default=0)
    rain_text_w = max((text_size(draw, r[2], detail_font)[0] for r in rows), default=0)
    if rain_as_pie:
        rain_col_w = pie_d + (pie_gap + rain_text_w if rain_text_w else 0)
    else:
        rain_col_w = rain_text_w
    forecast_w = (hour_icon_size + col_gap + time_col_w + col_gap
                  + temp_col_w + col_gap + rain_col_w)
    # Rows are as tall as their tallest element (icon, and the pie in pie mode)
    # so nothing is clipped.
    hour_row_h = max(row_h, hour_icon_size, pie_d if rain_as_pie else 0)
    forecast_h = len(rows) * hour_row_h + max(0, len(rows) - 1) * row_gap

    # The right column is just the forecast table now; the 7-day overview has
    # moved to the bottom of the left column.
    right_w = forecast_w
    right_h = forecast_h

    # The two columns sit side by side; the body is as tall as the taller one.
    body_w = left_w + column_gap + right_w
    body_h = max(left_h, right_h)

    # To keep the two columns the same height (so neither looks jagged when
    # content is added to the other), each column justifies its rows to fill
    # body_h: the leftover height is distributed evenly across its inter-row
    # gaps. _justified_gap never returns less than the column's base gap.
    def _justified_gap(content_h: int, n_gaps: int, base_gap: int) -> int:
        if n_gaps <= 0:
            return base_gap
        return max(base_gap, (body_h - content_h) // n_gaps)

    # Left column rows: hero, then UV / sun / 7-day if present.
    left_row_heights = [hero_h]
    if show_uv:
        left_row_heights.append(uv_h)
    if solar_text:
        left_row_heights.append(solar_h)
    if week_text:
        left_row_heights.append(week_h)
    left_gap = _justified_gap(sum(left_row_heights), len(left_row_heights) - 1, line_gap)

    # Right column rows: the forecast hours.
    right_gap = _justified_gap(len(rows) * hour_row_h, max(0, len(rows) - 1), row_gap)

    # Location + timezone footer, spanning the full block width below the body.
    footer_w, footer_h = text_size(draw, footer_text, detail_font) if footer_text else (0, 0)

    block_w = max(date_line_w, body_w, footer_w)
    block_h = date_line_h + line_gap + body_h
    if footer_text:
        block_h += line_gap + footer_h

    # Center the block horizontally in the bottom zone; keep it near the
    # bottom edge like the stats pill on the right.
    margin = 18
    pad = 14
    bx = (canvas_w - block_w) // 2
    by = zone_y + zone_h - block_h - margin

    pill_color = blend(theme.background, theme.label_color, 0.10)
    draw.rounded_rectangle(
        [bx - pad, by - pad, bx + block_w + pad, by + block_h + pad],
        radius=6, fill=pill_color,
    )

    bright = blend(theme.label_color, (255, 255, 255), 0.15)

    def _text_at(text, font, x, y, fill):
        draw.text((x, y), text, fill=fill, font=font)

    def _centered_in(text, font, col_x, col_w, y, fill):
        w, _ = text_size(draw, text, font)
        _text_at(text, font, col_x + (col_w - w) // 2, y, fill)

    # ---- Date line ----------------------------------------------------------
    # Align each piece with the column below it: the Gregorian date is centered
    # over the left (temperature) column, and the moon's left edge lines up
    # with the forecast icons in the right column. The lunar date trails the
    # moon. When there's no lunar/moon, fall back to centering the line.
    date_y = by + (date_line_h - date_h) // 2
    col_left_x = bx + (block_w - body_w) // 2
    if lunar:
        _text_at(gregorian, detail_font,
                 col_left_x + (left_w - greg_w) // 2, date_y, theme.label_color)
        moon_x = col_left_x + left_w + column_gap  # forecast icons' left edge
        draw_moon_phase(draw, moon_x, by + (date_line_h - 2 * moon_r) // 2,
                        moon_r, bright, pill_color, lunar_day)
        moon_right = moon_x + 2 * moon_r
        lunar_x = moon_right + moon_gap
        lunar_y = by + (date_line_h - lunar_h) // 2
        # On observance days (lunar 2nd/16th), frame the lunar date in a box.
        if lunar_boxed:
            box_pad_x, box_pad_y = 5, 3
            # Keep the box clear of the moon so its outline can't clip the
            # phase glyph; nudge the lunar text right if needed to fit.
            box_left = max(lunar_x - box_pad_x, moon_right + moon_gap)
            lunar_x = box_left + box_pad_x
            draw.rounded_rectangle(
                [box_left, lunar_y - box_pad_y,
                 lunar_x + lunar_w + box_pad_x, lunar_y + lunar_h + box_pad_y],
                radius=3, outline=bright, width=max(1, base_font_size // 8),
            )
        _text_at(lunar, detail_font, lunar_x, lunar_y, theme.label_color)
    else:
        # No lunar date — just center the Gregorian date on the block.
        _text_at(gregorian, detail_font, bx + (block_w - greg_w) // 2, date_y,
                 theme.label_color)

    # ---- Body: two columns, both anchored to the same top -------------------
    body_y = by + date_line_h + line_gap
    left_x = bx + (block_w - body_w) // 2
    right_x = left_x + left_w + column_gap
    icon_accent = blend(theme.elapsed_period_colors[1], (255, 255, 255), 0.3)

    # Left column — left-aligned hero (icon | temp stack), then UV, then sun.
    ly = body_y

    # Hero: [icon] [big temp] [H/L stacked]. Each piece is vertically centered
    # within hero_h. The icon's vector glyphs carry a small internal left
    # margin, so nudge it left to visually align its edge with left_x (and the
    # UV bar below it).
    if has_icon:
        icon_inset = int(icon_size * 0.05)
        # The icon's ink sits in the upper part of its box (the cloud occupies
        # only the top ~60%), so nudge it down to look optically centered.
        icon_y = ly + (hero_h - icon_size) // 2 + int(icon_size * 0.15)
        draw_weather_icon(draw, icon_key, left_x - icon_inset, icon_y, icon_size,
                          bright, icon_accent, pill_color)

    temp_x = left_x + (icon_block_w + hero_gap if has_icon else 0)
    temp_y = ly + (hero_h - temp_h) // 2
    _text_at(temp_text, big_temp_font, temp_x, temp_y, bright)

    if has_lowhigh:
        # Two-row table: "H"/"L" labels left-aligned, numbers right-aligned to
        # a shared right edge (lh_x + lowhigh_w).
        lh_x = temp_x + temp_w + lowhigh_gap
        lh_right = lh_x + lowhigh_w
        lh_y = ly + (hero_h - lowhigh_h) // 2
        # High row (light end of the ramp).
        _text_at("H", detail_font, lh_x, lh_y, ramp_color(theme, 1.0))
        _text_at(high_num, detail_font, lh_right - high_num_w, lh_y,
                 ramp_color(theme, 1.0))
        # Low row (dark end of the ramp).
        low_y = lh_y + high_h + lh_line_gap
        _text_at("L", detail_font, lh_x, low_y, ramp_color(theme, 0.0))
        _text_at(low_num, detail_font, lh_right - low_num_w, low_y,
                 ramp_color(theme, 0.0))
    ly += hero_h

    # UV widget, left-aligned under the hero.
    if show_uv:
        ly += left_gap
        draw_uv_bar(draw, left_x, ly, uv_w, uv_value, detail_font, theme,
                    center_label=False)
        ly += uv_h

    # Next sun event, left-aligned.
    if solar_text:
        ly += left_gap
        _text_at(solar_text, detail_font, left_x, ly, bright)
        ly += solar_h

    # 7-day overview, left-aligned at the bottom of the left column.
    if week_text:
        ly += left_gap
        _text_at(week_text, detail_font, left_x, ly, bright)

    # Right column — forecast table. Temperature and rain figures are tinted
    # by brightness: hotter/wetter reads lighter, cooler/drier reads darker.
    #   • rain:  0% (darkest) → 100% (lightest)
    #   • temp:  day low (darkest) → day high (lightest)
    # The temperature reference range prefers the day's forecast low/high, and
    # falls back to the spread across the displayed hours when those are absent.
    hourly_temps = [h.temperature for h in report.hours]
    t_min = report.temp_low if report.temp_low is not None else (min(hourly_temps) if hourly_temps else 0.0)
    t_max = report.temp_high if report.temp_high is not None else (max(hourly_temps) if hourly_temps else 1.0)
    t_span = (t_max - t_min) or 1.0

    # Pie palette: a dim empty track and a subtle framing ring.
    pie_track = blend(theme.background, theme.label_color, 0.18)
    pie_outline = blend(theme.background, theme.label_color, 0.45)

    icon_x = right_x
    time_x = icon_x + hour_icon_size + col_gap
    temp_x = time_x + time_col_w + col_gap
    rain_x = temp_x + temp_col_w + col_gap
    ry = body_y   # both columns share the same top
    for (time_lbl, temp_lbl, rain_lbl), hour in zip(rows, report.hours):
        temp_color = ramp_color(theme, (hour.temperature - t_min) / t_span)
        rain_color = ramp_color(theme, hour.precip_probability / 100.0)
        # Per-hour condition icon at the row's left edge.
        hour_key, _ = weather_condition(hour.weather_code)
        if hour_key != "unknown":
            draw_weather_icon(draw, hour_key, icon_x, ry, hour_icon_size,
                              theme.label_color, icon_accent, pill_color)
        # Vertically center the text against the taller icon row.
        text_y = ry + (hour_row_h - row_h) // 2
        _text_at(time_lbl, detail_font, time_x, text_y, theme.label_color)
        _text_at(temp_lbl, detail_font, temp_x, text_y, temp_color)
        # Rain chance: pie chart (+ mm text) or plain percentage text.
        if rain_as_pie:
            pie_cx = rain_x + pie_d // 2
            pie_cy = ry + hour_row_h // 2
            draw_rain_pie(draw, pie_cx, pie_cy, pie_d // 2,
                          hour.precip_probability / 100.0,
                          fill=rain_color, track=pie_track, outline=pie_outline)
            if rain_lbl:
                _text_at(rain_lbl, detail_font, rain_x + pie_d + pie_gap, text_y,
                         rain_color)
        else:
            _text_at(rain_lbl, detail_font, rain_x, text_y, rain_color)
        ry += hour_row_h + right_gap

    # ---- Location + timezone footer (full width, centered) ------------------
    if footer_text:
        footer_y = by + block_h - footer_h
        _centered_in(footer_text, detail_font, bx, block_w, footer_y,
                     theme.label_color)
