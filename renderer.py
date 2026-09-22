"""
renderer.py — Draws the life calendar grid and returns a Pillow Image.

Layout (left → right):
  [left margin] [week-column + day labels] [gap] [week tick labels] [grid]

The week-column is a narrow vertical bar that fills progressively from
Monday 00:00 (empty) to Sunday 23:59 (full), divided into 7 day-sections.
"""

import math
from datetime import date, datetime
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from config import (
    PERIOD_YEARS,
    WEEKS_PER_YEAR,
    YEARS,
    Settings,
    Theme,
    get_theme,
)

# ---------------------------------------------------------------------------
# Week-column layout constants  (easy to tune)
# ---------------------------------------------------------------------------

# How far from the left screen edge the week column starts
WEEK_COL_LEFT_MARGIN = 60    # pixels from left edge of canvas

# Width of the bar itself
WEEK_COL_MIN_W = 18
WEEK_COL_MAX_W = 40

# Gap between the rightmost day-label character and the start of the grid area
WEEK_COL_TO_GRID_GAP = 48

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weeks_elapsed(birthday: date, today: date) -> int:
    if today <= birthday:
        return 0
    return (today - birthday).days // 7


def _period_index(year_index: int) -> int:
    return min(year_index // PERIOD_YEARS, 2)


def _resolve_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        return draw.textsize(text, font=font)


# ---------------------------------------------------------------------------
# Auto-detect screen resolution
# ---------------------------------------------------------------------------

def _detect_screen_size() -> Tuple[int, int]:
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    try:
        import subprocess, re
        out = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType"], text=True, timeout=5,
        )
        m = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 2560, 1440


# ---------------------------------------------------------------------------
# Week progress
# ---------------------------------------------------------------------------

def _week_progress(now: datetime) -> Tuple[int, float]:
    """Return (day_index 0=Mon…6=Sun, fraction_of_week_elapsed)."""
    day_idx       = now.weekday()
    seconds_today = now.hour * 3600 + now.minute * 60 + now.second
    elapsed       = day_idx * 86400 + seconds_today
    return day_idx, elapsed / (7 * 86400)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render(settings: Settings, today: Optional[date] = None,
           now: Optional[datetime] = None) -> Image.Image:
    if today is None:
        today = date.today()
    if now is None:
        now = datetime.now()

    theme = get_theme(settings)

    # Canvas ------------------------------------------------------------------
    if settings.canvas_width > 0 and settings.canvas_height > 0:
        canvas_w, canvas_h = settings.canvas_width, settings.canvas_height
    else:
        canvas_w, canvas_h = _detect_screen_size()

    img  = Image.new("RGB", (canvas_w, canvas_h), theme.background)
    draw = ImageDraw.Draw(img)

    # Fonts -------------------------------------------------------------------
    area_h         = canvas_h - settings.padding_top - settings.padding_bottom
    label_font_size = max(9,  min(14, area_h // 60))
    stat_font_size  = max(10, min(16, area_h // 55))
    label_font      = _resolve_font(label_font_size)
    stat_font       = _resolve_font(stat_font_size)

    # Layout split: top 80% of screen for life calendar + week tracker,
    # bottom 20% for stats. Zones are calculated from full screen height
    # (no outer margins — they stick to screen edges as invisible guides).
    TOP_FRACTION = 0.80
    top_zone_y    = 0
    top_zone_h    = int(canvas_h * TOP_FRACTION)
    bottom_zone_y = top_zone_h
    bottom_zone_h = canvas_h - top_zone_h

    # Inner padding within each zone so content doesn't stick to edges
    inner_pad = 40

    # Week-column geometry (lives inside the top zone with inner padding) ------
    wcol_w = max(WEEK_COL_MIN_W, min(WEEK_COL_MAX_W,
                                     int(settings.padding_left * 0.30)))
    wcol_x = WEEK_COL_LEFT_MARGIN
    wcol_y = top_zone_y + inner_pad
    wcol_h = top_zone_h - 2 * inner_pad

    # Width of the day-name labels that sit to the right of the bar
    day_label_w = label_font_size * 3 + 8   # "Wed" ~ 3 chars

    # Grid area starts after: left-margin + bar + day-labels + gap
    grid_area_x = wcol_x + wcol_w + day_label_w + WEEK_COL_TO_GRID_GAP
    grid_area_y = top_zone_y + inner_pad
    grid_area_w = canvas_w - grid_area_x - inner_pad
    grid_area_h = top_zone_h - 2 * inner_pad

    # Space for tick labels
    x_tick_h  = label_font_size + 4 if settings.show_year_labels else 0
    y_label_w = label_font_size + 6 if settings.show_week_labels else 0

    grid_x = grid_area_x + y_label_w
    grid_y = grid_area_y
    grid_w = grid_area_w - y_label_w
    grid_h = grid_area_h - x_tick_h

    # Cell geometry -----------------------------------------------------------
    gap    = settings.cell_gap
    cell_w = max(1, math.floor((grid_w - (YEARS - 1)          * gap) / YEARS))
    cell_h = max(1, math.floor((grid_h - (WEEKS_PER_YEAR - 1) * gap) / WEEKS_PER_YEAR))

    actual_grid_w = YEARS          * cell_w + (YEARS - 1)          * gap
    actual_grid_h = WEEKS_PER_YEAR * cell_h + (WEEKS_PER_YEAR - 1) * gap

    # Centre grid within computed box
    grid_x += (grid_w - actual_grid_w) // 2
    grid_y += (grid_h - actual_grid_h) // 2

    # Elapsed weeks -----------------------------------------------------------
    elapsed     = 0
    total_weeks = YEARS * WEEKS_PER_YEAR
    if settings.birthday:
        try:
            elapsed = _weeks_elapsed(date.fromisoformat(settings.birthday), today)
        except ValueError:
            pass

    # Draw cells --------------------------------------------------------------
    week_counter = 0
    for col in range(YEARS):
        period = _period_index(col)

        if theme.gradient:
            period_start = period * PERIOD_YEARS
            period_end   = min(period_start + PERIOD_YEARS, YEARS) - 1
            t = (col - period_start) / max(1, period_end - period_start)
            elapsed_color = _blend(
                theme.elapsed_period_colors[period],
                theme.elapsed_period_end_colors[period],
                t,
            )
        else:
            elapsed_color = theme.elapsed_period_colors[period]

        future_color = theme.future_period_colors[period]
        x0 = grid_x + col * (cell_w + gap)

        for row in range(WEEKS_PER_YEAR):
            y0 = grid_y + row * (cell_h + gap)
            x1, y1 = x0 + cell_w - 1, y0 + cell_h - 1
            week_counter += 1

            if week_counter <= elapsed:
                if theme.elapsed_style == "hatched":
                    _draw_hatched_cell(draw, x0, y0, x1, y1,
                                       elapsed_color, theme.background)
                else:
                    draw.rectangle([x0, y0, x1, y1], fill=elapsed_color)
            else:
                if theme.future_style == "outline":
                    draw.rectangle([x0, y0, x1, y1], outline=future_color)
                else:
                    draw.rectangle([x0, y0, x1, y1], fill=future_color)

    # Period separator lines --------------------------------------------------
    sep_color = _blend(theme.background, theme.label_color, 0.35)
    for p in range(1, math.ceil(YEARS / PERIOD_YEARS)):
        sep_col = p * PERIOD_YEARS
        if sep_col >= YEARS:
            break
        sx = grid_x + sep_col * (cell_w + gap) - gap
        draw.line([(sx, grid_y - 4), (sx, grid_y + actual_grid_h + 4)],
                  fill=sep_color, width=max(1, gap))

    # Year tick labels (x-axis, bottom) ---------------------------------------
    if settings.show_year_labels and x_tick_h > 0:
        tick_y = grid_y + actual_grid_h + 6
        for col in list(range(0, YEARS, 10)) + [YEARS - 1]:
            lx  = grid_x + col * (cell_w + gap) + cell_w // 2
            lbl = str(col)
            tw, _ = _text_size(draw, lbl, label_font)
            draw.text((lx - tw // 2, tick_y), lbl,
                      fill=theme.label_color, font=label_font)

    # Week tick labels (y-axis, left of grid) ---------------------------------
    if settings.show_week_labels and y_label_w > 0:
        for row in range(0, WEEKS_PER_YEAR, 4):
            ly  = grid_y + row * (cell_h + gap) + cell_h // 2
            lbl = str(row + 1)
            _, th = _text_size(draw, lbl, label_font)
            draw.text((grid_area_x, ly - th // 2), lbl,
                      fill=theme.label_color, font=label_font)

    # Weekly progress column --------------------------------------------------
    _draw_week_column(draw, wcol_x, wcol_y, wcol_w, wcol_h,
                      now, theme, label_font)

    # Stats + live indicator (bottom-right of the bottom zone) ----------------
    _draw_stats_and_live(draw, canvas_w, bottom_zone_y, bottom_zone_h,
                         elapsed, total_weeks, now, theme,
                         stat_font, label_font_size)

    # Weather report (centered in the bottom zone) ----------------------------
    if settings.show_weather:
        _draw_weather(draw, canvas_w, bottom_zone_y, bottom_zone_h,
                      settings, theme, stat_font, label_font_size, today, now)

    return img


# ---------------------------------------------------------------------------
# Weekly progress column
# ---------------------------------------------------------------------------

def _draw_week_column(
    draw: ImageDraw.ImageDraw,
    x: int, y: int, w: int, h: int,
    now: datetime,
    theme: Theme,
    label_font,
) -> None:
    """
    Vertical bar subdivided into 7 day-sections (Mon top, Sun bottom).
    Past days fully filled, current day partially filled, future days empty.
    Day name labels sit to the right of the bar.
    """
    day_idx, _ = _week_progress(now)
    day_frac   = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0

    fill_color   = theme.elapsed_period_colors[0]
    empty_color  = theme.future_period_colors[0]
    border_color = _blend(theme.background, theme.label_color, 0.2)

    n_days    = 7
    sec_gap   = 2
    section_h = (h - (n_days - 1) * sec_gap) / n_days

    for i in range(n_days):
        sy0 = y + int(i * (section_h + sec_gap))
        sy1 = sy0 + max(1, int(section_h)) - 1

        draw.rectangle([x, sy0, x + w - 1, sy1], fill=empty_color)

        if i < day_idx:
            fill_px = sy1 - sy0 + 1
        elif i == day_idx:
            fill_px = max(1, int((sy1 - sy0 + 1) * day_frac))
        else:
            fill_px = 0

        if fill_px > 0:
            draw.rectangle([x, sy0, x + w - 1, sy0 + fill_px - 1],
                           fill=fill_color)

        draw.rectangle([x, sy0, x + w - 1, sy1], outline=border_color)

        # Day label to the right of the bar
        lbl    = DAY_NAMES[i]
        lw, lh = _text_size(draw, lbl, label_font)
        lx     = x + w + 4
        ly     = sy0 + (sy1 - sy0) // 2 - lh // 2
        lcolor = (_blend(fill_color, (255, 255, 255), 0.4)
                  if i == day_idx else theme.label_color)
        draw.text((lx, ly), lbl, fill=lcolor, font=label_font)


# ---------------------------------------------------------------------------
# Stats + live indicator (bottom-right pill)
# ---------------------------------------------------------------------------

def _draw_stats_and_live(
    draw: ImageDraw.ImageDraw,
    canvas_w: int, zone_y: int, zone_h: int,
    elapsed: int, total_weeks: int,
    now: datetime,
    theme: Theme,
    stat_font,
    base_font_size: int,
) -> None:
    live_font = _resolve_font(max(9, base_font_size - 1))
    line_gap  = 6

    live_text = f"● LIVE  ·  updated {now.strftime('%H:%M')}"
    stat_text = f"week {elapsed:,} / {total_weeks:,}"

    live_w, live_h = _text_size(draw, live_text, live_font)
    stat_w, stat_h = _text_size(draw, stat_text, stat_font)

    block_w = max(live_w, stat_w)
    block_h = stat_h + line_gap + live_h

    # Position the block at the bottom-right of the bottom zone (with inner padding)
    margin = 18
    bx = canvas_w - block_w - margin
    by = zone_y + zone_h - block_h - margin
    pad = 10

    pill_color = _blend(theme.background, theme.label_color, 0.10)
    draw.rounded_rectangle(
        [bx - pad, by - pad, bx + block_w + pad, by + block_h + pad],
        radius=5, fill=pill_color,
    )

    # Stat line — right-aligned
    sx = bx + (block_w - stat_w)
    draw.text((sx, by), stat_text,
              fill=_blend(theme.label_color, (255, 255, 255), 0.15),
              font=stat_font)

    # Live line — right-aligned
    lx        = bx + (block_w - live_w)
    ly        = by + stat_h + line_gap
    dot_char  = "● "
    dot_color = _blend(theme.elapsed_period_colors[0], (255, 255, 255), 0.3)
    dot_w, _  = _text_size(draw, dot_char, live_font)
    draw.text((lx,          ly), dot_char,                fill=dot_color,        font=live_font)
    draw.text((lx + dot_w,  ly), live_text[len(dot_char):], fill=theme.label_color, font=live_font)


# ---------------------------------------------------------------------------
# Weather report (bottom-left pill)
# ---------------------------------------------------------------------------

def _format_dates(today: date) -> Tuple[str, str, Optional[int]]:
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


def _weather_condition(code: Optional[int]) -> Tuple[str, str]:
    """
    Map a WMO weather code to an (icon_key, label) pair. The icon_key selects
    which vector icon _draw_weather_icon draws; the label is a short caption.

    WMO code groups (per Open-Meteo's documented interpretation):
      0        clear
      1–2      mainly clear / partly cloudy
      3        overcast
      45,48    fog
      51–57    drizzle
      61–67    rain
      71–77    snow
      80–82    rain showers
      85,86    snow showers
      95–99    thunderstorm
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


def _uv_label(uv: float) -> str:
    """WHO UV-index exposure band for a UV value."""
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very high"
    return "Extreme"


def _code_bucket(code: int) -> str:
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


def _summarize_week(codes) -> str:
    """
    Aggregate up-to-7 daily WMO codes into a one-line outlook, e.g.
    "mostly rainy", "mostly sunny and cloudy", or "an even mix of rain and
    shine". Returns "" when there are no codes to summarize.
    """
    if not codes:
        return ""

    from collections import Counter
    counts = Counter(_code_bucket(c) for c in codes)
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


def _next_solar_event(report, now: datetime) -> Optional[Tuple[str, str]]:
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


def _format_hour_rain(hour, as_pie: bool) -> str:
    """
    Text shown in the rain cell of a forecast row.

    In pie mode the probability is drawn as a pie, so this returns only the
    expected amount (e.g. "1.4mm"), or "" when there's no measurable rain.

    In percentage mode this returns the chance, plus the amount when
    measurable — e.g. "65%  1.4mm" or just "20%" — mirroring the earlier
    text-only presentation.
    """
    has_mm = hour.precip_amount >= 0.1
    mm = f"{hour.precip_amount:.1f}mm" if has_mm else ""
    if as_pie:
        return mm
    if has_mm:
        return f"{hour.precip_probability}%  {mm}"
    return f"{hour.precip_probability}%"


def _format_gmt_offset(utc_offset_seconds: Optional[int]) -> str:
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


# Brightness floor for the ramp's dark end: even a 0%/minimum value keeps
# roughly this fraction of the full brightness so it stays clearly readable
# rather than fading into the background.
_RAMP_MIN_BRIGHTNESS = 0.55


def _ramp_color(theme: Theme, t: float) -> Tuple[int, int, int]:
    """
    Colour along a dark→light ramp keyed by *t* in [0, 1], used to encode
    magnitude (rain chance, relative temperature) as brightness. The dark end
    is floored at _RAMP_MIN_BRIGHTNESS so t=0 is dim but still legible; t=1 is
    near-white.
    """
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    top = _blend(theme.label_color, (255, 255, 255), 0.4)
    # Map t into [floor, 1] then blend from background toward the bright top,
    # so the minimum never drops below the readable floor.
    brightness = _RAMP_MIN_BRIGHTNESS + (1.0 - _RAMP_MIN_BRIGHTNESS) * t
    return _blend(theme.background, top, brightness)


def _draw_crescent_moon(
    draw: ImageDraw.ImageDraw,
    x: int, y: int, radius: int,
    color: Tuple[int, int, int],
    bg: Tuple[int, int, int],
) -> None:
    """
    Draw a small crescent moon with its bounding box's top-left at (x, y).

    The system fallback fonts have no moon glyph (they render a tofu box), so
    the moon is drawn as vectors: a filled disc with an overlapping
    background-coloured disc bitten out of it to leave a crescent.
    """
    cx, cy = x + radius, y + radius
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    # Offset the "bite" toward the upper-right for a waxing-crescent look.
    bite_dx = radius * 0.6
    draw.ellipse(
        [cx - radius + bite_dx, cy - radius - radius * 0.15,
         cx + radius + bite_dx, cy + radius - radius * 0.15],
        fill=bg,
    )


def _draw_rain_pie(draw, cx, cy, radius, fraction, fill, track, outline) -> None:
    """
    Draw a mini pie chart at centre (cx, cy) showing *fraction* (0–1) filled.

    The full disc is drawn in *track* (an empty/background tone), then a wedge
    proportional to the fraction is filled in *fill*, sweeping clockwise from
    12 o'clock, and finally a thin *outline* ring frames the whole circle.
    """
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(box, fill=track)
    fraction = 0.0 if fraction < 0 else 1.0 if fraction > 1 else fraction
    if fraction > 0:
        # Pillow angles: 0° points to 3 o'clock and increase clockwise, so
        # starting at -90° begins the wedge at 12 o'clock.
        start = -90
        end = start + 360 * fraction
        draw.pieslice(box, start, end, fill=fill)
    draw.ellipse(box, outline=outline, width=max(1, radius // 6))


def _draw_sun(draw, x, y, size, color) -> None:
    """A sun: a filled disc with eight short rays, fit within a size box."""
    cx, cy = x + size / 2, y + size / 2
    r = size * 0.24
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    ray_in = r * 1.35
    ray_out = size * 0.5
    for i in range(8):
        a = i * (math.pi / 4)
        dx, dy = math.cos(a), math.sin(a)
        draw.line([(cx + dx * ray_in, cy + dy * ray_in),
                   (cx + dx * ray_out, cy + dy * ray_out)],
                  fill=color, width=max(1, size // 16))


def _draw_cloud(draw, x, y, w, h, color) -> None:
    """A simple cloud built from overlapping lobes on a flat base."""
    base_top = y + h * 0.55
    draw.rounded_rectangle([x, base_top, x + w, y + h], radius=h * 0.22, fill=color)
    draw.ellipse([x + w * 0.05, y + h * 0.30, x + w * 0.50, y + h * 0.80], fill=color)
    draw.ellipse([x + w * 0.35, y + h * 0.10, x + w * 0.80, y + h * 0.72], fill=color)
    draw.ellipse([x + w * 0.55, y + h * 0.32, x + w * 0.98, y + h * 0.82], fill=color)


def _draw_weather_icon(draw, key: str, x: int, y: int, size: int,
                       color, accent, bg) -> None:
    """
    Draw a small vector weather icon for *key* inside a size×size box at (x, y).
    The system fallback fonts lack weather glyphs, so conditions are drawn as
    shapes (same approach as the crescent moon).
    """
    if key == "clear":
        _draw_sun(draw, x, y, size, color)
        return

    if key == "partly":
        # Small sun peeking behind a cloud.
        _draw_sun(draw, x, int(y - size * 0.05), int(size * 0.7), color)
        _draw_cloud(draw, x + size * 0.15, y + size * 0.32, size * 0.85, size * 0.5, color)
        return

    # The remaining icons all sit under a cloud.
    cloud_w, cloud_h = size, size * 0.55
    cloud_y = y + size * 0.05
    _draw_cloud(draw, x, cloud_y, cloud_w, cloud_h, color)
    below_y = cloud_y + cloud_h + size * 0.06
    cx = x + size / 2

    if key == "rain":
        for i in (-1, 0, 1):
            dx = cx + i * size * 0.22
            draw.line([(dx, below_y), (dx - size * 0.08, below_y + size * 0.22)],
                      fill=accent, width=max(1, size // 14))
    elif key == "snow":
        r = max(1, size // 16)
        for i in (-1, 0, 1):
            dx = cx + i * size * 0.22
            dy = below_y + size * 0.10
            draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=accent)
    elif key == "thunder":
        s = size
        bolt = [
            (cx + s * 0.02, below_y),
            (cx - s * 0.14, below_y + s * 0.20),
            (cx - s * 0.02, below_y + s * 0.20),
            (cx - s * 0.10, below_y + s * 0.36),
            (cx + s * 0.16, below_y + s * 0.12),
            (cx + s * 0.02, below_y + s * 0.12),
        ]
        draw.polygon(bolt, fill=accent)
    elif key == "fog":
        for i in range(3):
            fy = below_y + i * size * 0.10
            draw.line([(x + size * 0.08, fy), (x + size * 0.92, fy)],
                      fill=accent, width=max(1, size // 16))
    # "cloudy" / "unknown": the cloud alone is enough.


def _draw_weather(
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

      • a full-width date line on top — Gregorian date plus a drawn crescent
        moon and the lunar "DD Mon" date,
      • a two-column body below it: the left column stacks the large current
        temperature over the low/high, location, and the next sunrise/sunset;
        the right column lists one row per upcoming hour (time, temperature,
        rain outlook).

    Splitting the body into columns widens the lower half so the block reads
    as balanced rather than top-heavy.

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

    detail_font = _resolve_font(max(9, base_font_size - 1))
    big_temp_font = _resolve_font(max(18, base_font_size * 2))

    # Vertical rhythm — roomier than before so lines don't feel packed.
    line_gap = base_font_size          # gap between stacked lines
    row_gap = max(6, base_font_size // 2)  # gap between hourly rows
    column_gap = base_font_size * 4    # gap between the temp and forecast columns

    unit = report.temperature_unit
    # Degrees without the unit letter, for the compact low/high pair.
    deg = unit[0] if unit else "°"

    # Date line: Gregorian text, then a drawn moon + lunar "DD Mon" -----------
    gregorian, lunar, lunar_day = _format_dates(today)
    moon_r = max(4, base_font_size // 2)   # crescent radius
    moon_gap = 5                           # space between moon and lunar text
    # Highlight observance days (2nd and 16th of the lunar month) with a box.
    lunar_boxed = lunar_day in (2, 16)

    # Left column — big current temperature, then low/high, then location.
    temp_text = f"{report.temperature:.0f}{unit}"
    lowhigh_text = ""
    low_text = high_text = lh_sep = ""
    if report.temp_low is not None and report.temp_high is not None:
        low_text = f"L {report.temp_low:.0f}{deg}"
        high_text = f"H {report.temp_high:.0f}{deg}"
        lh_sep = "    "
        lowhigh_text = f"{low_text}{lh_sep}{high_text}"
    place_text = report.location or ""
    gmt = _format_gmt_offset(report.utc_offset_seconds)
    if place_text and gmt:
        place_text = f"{place_text} ({gmt})"
    elif gmt:
        place_text = f"({gmt})"

    # Next solar event (sunrise before dawn, sunset by day, tomorrow's sunrise
    # after dusk).
    solar = _next_solar_event(report, now)
    solar_text = f"{solar[0]} {solar[1]}" if solar else ""

    # Current condition (icon + label) and UV. The condition label and UV
    # share one line to keep the left column from growing too tall.
    icon_key, condition_label = _weather_condition(report.weather_code)
    icon_size = max(20, base_font_size * 2)   # drawn above the temperature
    uv_value = report.uv_index_max if report.uv_index_max is not None else report.uv_index
    uv_text = f"UV {uv_value:.0f} {_uv_label(uv_value)}" if uv_value is not None else ""
    info_text = "  ·  ".join(t for t in (condition_label, uv_text) if t)

    # Running 7-day overview — one-line footer spanning the full block width.
    week_summary = _summarize_week(report.weekly_codes)
    week_text = f"7-day: {week_summary}" if week_summary else ""

    # Right column — one row per hour: time, temperature, rain. Rain chance is
    # shown either as a mini pie chart or as "NN%" text per the user setting.
    rain_as_pie = settings.weather_rain_as_pie
    rows = [
        (h.label, f"{h.temperature:.0f}{unit}", _format_hour_rain(h, rain_as_pie))
        for h in report.hours
    ]

    # ---- Measure everything -------------------------------------------------
    greg_w, date_h = _text_size(draw, gregorian, detail_font)
    lunar_w, lunar_h = _text_size(draw, lunar, detail_font) if lunar else (0, 0)
    date_sep = "    " if lunar else ""
    date_sep_w, _ = _text_size(draw, date_sep, detail_font)
    moon_w = (2 * moon_r + moon_gap) if lunar else 0
    date_line_w = greg_w + date_sep_w + moon_w + lunar_w
    date_line_h = max(date_h, lunar_h, 2 * moon_r if lunar else 0)

    temp_w, temp_h = _text_size(draw, temp_text, big_temp_font)
    lowhigh_w, lowhigh_h = _text_size(draw, lowhigh_text, detail_font) if lowhigh_text else (0, 0)
    place_w, place_h = _text_size(draw, place_text, detail_font) if place_text else (0, 0)
    solar_w, solar_h = _text_size(draw, solar_text, detail_font) if solar_text else (0, 0)
    info_w, info_h = _text_size(draw, info_text, detail_font) if info_text else (0, 0)
    has_icon = icon_key != "unknown"
    _, row_h = _text_size(draw, "0:00", detail_font)

    # Left column geometry — condition icon on top, then the temperature stack,
    # low/high, the condition+UV info line, location, and the next sun event.
    left_w = max(temp_w, lowhigh_w, place_w, solar_w, info_w, icon_size if has_icon else 0)
    left_h = temp_h
    if has_icon:
        left_h += icon_size + line_gap // 2
    if lowhigh_text:
        left_h += line_gap // 2 + lowhigh_h
    if info_text:
        left_h += line_gap // 2 + info_h
    if place_text:
        left_h += line_gap // 2 + place_h
    if solar_text:
        left_h += line_gap // 2 + solar_h

    # Right column (forecast table) geometry. A small condition icon leads
    # each row, followed by the time, temperature, and rain columns.
    col_gap = 10
    hour_icon_size = row_h + base_font_size // 2
    # Rain chance: either a mini pie chart (optionally followed by the mm
    # amount) or plain "NN%" text, depending on the setting.
    pie_d = row_h + base_font_size // 2  # a bit larger than the text height
    pie_gap = 6                         # gap between the pie and the mm text
    time_col_w = max((_text_size(draw, r[0], detail_font)[0] for r in rows), default=0)
    temp_col_w = max((_text_size(draw, r[1], detail_font)[0] for r in rows), default=0)
    rain_text_w = max((_text_size(draw, r[2], detail_font)[0] for r in rows), default=0)
    if rain_as_pie:
        rain_col_w = pie_d + (pie_gap + rain_text_w if rain_text_w else 0)
    else:
        rain_col_w = rain_text_w
    right_w = (hour_icon_size + col_gap + time_col_w + col_gap
               + temp_col_w + col_gap + rain_col_w)
    # Rows are as tall as their tallest element (icon, and the pie in pie mode)
    # so nothing is clipped.
    hour_row_h = max(row_h, hour_icon_size, pie_d if rain_as_pie else 0)
    right_h = len(rows) * hour_row_h + max(0, len(rows) - 1) * row_gap

    # The two columns sit side by side; the body is as tall as the taller one.
    body_w = left_w + column_gap + right_w
    body_h = max(left_h, right_h)

    # Weekly overview footer, spanning the full width under the body.
    week_w, week_h = _text_size(draw, week_text, detail_font) if week_text else (0, 0)

    block_w = max(date_line_w, body_w, week_w)
    block_h = date_line_h + line_gap + body_h
    if week_text:
        block_h += line_gap + week_h

    # Center the block horizontally in the bottom zone; keep it near the
    # bottom edge like the stats pill on the right.
    margin = 18
    pad = 14
    bx = (canvas_w - block_w) // 2
    by = zone_y + zone_h - block_h - margin

    pill_color = _blend(theme.background, theme.label_color, 0.10)
    draw.rounded_rectangle(
        [bx - pad, by - pad, bx + block_w + pad, by + block_h + pad],
        radius=6, fill=pill_color,
    )

    bright = _blend(theme.label_color, (255, 255, 255), 0.15)

    def _text_at(text, font, x, y, fill):
        draw.text((x, y), text, fill=fill, font=font)

    def _centered_in(text, font, col_x, col_w, y, fill):
        w, _ = _text_size(draw, text, font)
        _text_at(text, font, col_x + (col_w - w) // 2, y, fill)

    # ---- Date line (full width, centered) -----------------------------------
    dx = bx + (block_w - date_line_w) // 2
    _text_at(gregorian, detail_font, dx, by + (date_line_h - date_h) // 2,
             theme.label_color)
    if lunar:
        moon_x = dx + greg_w + date_sep_w
        _draw_crescent_moon(draw, moon_x, by + (date_line_h - 2 * moon_r) // 2,
                            moon_r, bright, pill_color)
        lunar_x = moon_x + 2 * moon_r + moon_gap
        lunar_y = by + (date_line_h - lunar_h) // 2
        # On observance days (lunar 2nd/16th), frame the lunar date in a box.
        if lunar_boxed:
            box_pad_x, box_pad_y = 5, 3
            draw.rounded_rectangle(
                [lunar_x - box_pad_x, lunar_y - box_pad_y,
                 lunar_x + lunar_w + box_pad_x, lunar_y + lunar_h + box_pad_y],
                radius=3, outline=bright, width=max(1, base_font_size // 8),
            )
        _text_at(lunar, detail_font, lunar_x, lunar_y, theme.label_color)

    # ---- Body: two columns, each vertically centered within the body --------
    body_y = by + date_line_h + line_gap
    left_x = bx + (block_w - body_w) // 2
    right_x = left_x + left_w + column_gap

    # Left column — condition icon, then temperature stack.
    ly = body_y + (body_h - left_h) // 2
    icon_accent = _blend(theme.elapsed_period_colors[1], (255, 255, 255), 0.3)
    if has_icon:
        _draw_weather_icon(draw, icon_key,
                           left_x + (left_w - icon_size) // 2, ly, icon_size,
                           bright, icon_accent, pill_color)
        ly += icon_size + line_gap // 2
    _centered_in(temp_text, big_temp_font, left_x, left_w, ly, bright)
    ly += temp_h
    if lowhigh_text:
        ly += line_gap // 2
        # Colour the low/high with the same ramp used for the hourly temps:
        # the low sits at the dark end, the high at the light end, so the two
        # anchor what "darkest" and "lightest" mean for the column.
        low_w, _ = _text_size(draw, low_text, detail_font)
        sep_w, _ = _text_size(draw, lh_sep, detail_font)
        group_w, _ = _text_size(draw, lowhigh_text, detail_font)
        gx = left_x + (left_w - group_w) // 2
        _text_at(low_text, detail_font, gx, ly, _ramp_color(theme, 0.0))
        _text_at(high_text, detail_font, gx + low_w + sep_w, ly, _ramp_color(theme, 1.0))
        ly += lowhigh_h
    if info_text:
        ly += line_gap // 2
        _centered_in(info_text, detail_font, left_x, left_w, ly, theme.label_color)
        ly += info_h
    if place_text:
        ly += line_gap // 2
        _centered_in(place_text, detail_font, left_x, left_w, ly, theme.label_color)
        ly += place_h
    if solar_text:
        ly += line_gap // 2
        _centered_in(solar_text, detail_font, left_x, left_w, ly, bright)

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
    pie_track = _blend(theme.background, theme.label_color, 0.18)
    pie_outline = _blend(theme.background, theme.label_color, 0.45)

    icon_x = right_x
    time_x = icon_x + hour_icon_size + col_gap
    temp_x = time_x + time_col_w + col_gap
    rain_x = temp_x + temp_col_w + col_gap
    ry = body_y + (body_h - right_h) // 2
    for (time_lbl, temp_lbl, rain_lbl), hour in zip(rows, report.hours):
        temp_color = _ramp_color(theme, (hour.temperature - t_min) / t_span)
        rain_color = _ramp_color(theme, hour.precip_probability / 100.0)
        # Per-hour condition icon at the row's left edge.
        hour_key, _ = _weather_condition(hour.weather_code)
        if hour_key != "unknown":
            _draw_weather_icon(draw, hour_key, icon_x, ry, hour_icon_size,
                               theme.label_color, icon_accent, pill_color)
        # Vertically center the text against the taller icon row.
        text_y = ry + (hour_row_h - row_h) // 2
        _text_at(time_lbl, detail_font, time_x, text_y, theme.label_color)
        _text_at(temp_lbl, detail_font, temp_x, text_y, temp_color)
        # Rain chance: pie chart (+ mm text) or plain percentage text.
        if rain_as_pie:
            pie_cx = rain_x + pie_d // 2
            pie_cy = ry + hour_row_h // 2
            _draw_rain_pie(draw, pie_cx, pie_cy, pie_d // 2,
                           hour.precip_probability / 100.0,
                           fill=rain_color, track=pie_track, outline=pie_outline)
            if rain_lbl:
                _text_at(rain_lbl, detail_font, rain_x + pie_d + pie_gap, text_y,
                         rain_color)
        else:
            _text_at(rain_lbl, detail_font, rain_x, text_y, rain_color)
        ry += hour_row_h + row_gap

    # ---- Weekly overview footer (full width, centered) ----------------------
    if week_text:
        week_y = body_y + body_h + line_gap
        _centered_in(week_text, detail_font, bx, block_w, week_y, bright)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _draw_hatched_cell(
    draw: ImageDraw.ImageDraw,
    x0: int, y0: int, x1: int, y1: int,
    color: Tuple[int, int, int],
    bg: Tuple[int, int, int],
) -> None:
    draw.rectangle([x0, y0, x1, y1], fill=bg)
    step = max(2, (x1 - x0) // 3)
    for offset in range(-(y1 - y0), (x1 - x0) + 1, step):
        draw.line([(x0 + offset, y0), (x0 + offset + (y1 - y0), y1)],
                  fill=color, width=1)


def _blend(
    c1: Tuple[int, int, int],
    c2: Tuple[int, int, int],
    t: float,
) -> Tuple[int, int, int]:
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
