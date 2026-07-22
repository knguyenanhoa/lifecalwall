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

    # Week-column geometry ----------------------------------------------------
    wcol_w = max(WEEK_COL_MIN_W, min(WEEK_COL_MAX_W,
                                     int(settings.padding_left * 0.30)))
    wcol_x = WEEK_COL_LEFT_MARGIN
    wcol_y = settings.padding_top
    wcol_h = canvas_h - settings.padding_top - settings.padding_bottom

    # Width of the day-name labels that sit to the right of the bar
    day_label_w = label_font_size * 3 + 8   # "Wed" ~ 3 chars

    # Grid area starts after: left-margin + bar + day-labels + gap
    grid_area_x = wcol_x + wcol_w + day_label_w + WEEK_COL_TO_GRID_GAP
    grid_area_y = settings.padding_top
    grid_area_w = canvas_w - grid_area_x - settings.padding_right
    grid_area_h = canvas_h - settings.padding_top - settings.padding_bottom

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

    # Stats + live indicator --------------------------------------------------
    _draw_stats_and_live(draw, canvas_w, canvas_h,
                         elapsed, total_weeks, now, theme,
                         stat_font, label_font_size)

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
    canvas_w: int, canvas_h: int,
    elapsed: int, total_weeks: int,
    now: datetime,
    theme: Theme,
    stat_font,
    base_font_size: int,
) -> None:
    live_font = _resolve_font(max(9, base_font_size - 1))
    margin    = 18
    line_gap  = 6

    live_text = f"● LIVE  ·  updated {now.strftime('%H:%M')}"
    stat_text = f"week {elapsed:,} / {total_weeks:,}"

    live_w, live_h = _text_size(draw, live_text, live_font)
    stat_w, stat_h = _text_size(draw, stat_text, stat_font)

    block_w = max(live_w, stat_w)
    block_h = stat_h + line_gap + live_h
    bx      = canvas_w - block_w - margin
    by      = canvas_h - block_h - margin
    pad     = 8

    pill_color = _blend(theme.background, theme.label_color, 0.10)
    draw.rounded_rectangle(
        [bx - pad, by - pad, bx + block_w + pad, by + block_h + pad],
        radius=5, fill=pill_color,
    )

    # Stat line — right-aligned
    draw.text((bx + block_w - stat_w, by), stat_text,
              fill=_blend(theme.label_color, (255, 255, 255), 0.15),
              font=stat_font)

    # Live line — dot in accent colour, rest in label colour
    lx        = bx + block_w - live_w
    ly        = by + stat_h + line_gap
    dot_char  = "● "
    dot_color = _blend(theme.elapsed_period_colors[0], (255, 255, 255), 0.3)
    dot_w, _  = _text_size(draw, dot_char, live_font)
    draw.text((lx,          ly), dot_char,                fill=dot_color,        font=live_font)
    draw.text((lx + dot_w,  ly), live_text[len(dot_char):], fill=theme.label_color, font=live_font)


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
