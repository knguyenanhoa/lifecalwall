"""
grid.py — The life calendar grid, weekly progress column, and bottom-right
stats pill.

The grid is one cell per week of a lifespan, columns = years, rows = weeks,
coloured in 30-year bands. The weekly column is a vertical bar that fills from
Monday 00:00 to Sunday 23:59. These are the "life calendar" half of the
wallpaper; the weather panel is drawn separately.
"""

import math
from datetime import date, datetime
from typing import Tuple

from PIL import ImageDraw

from config import PERIOD_YEARS, WEEKS_PER_YEAR, YEARS, Theme

from .draw_utils import blend, resolve_font, text_size

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
# Grid math
# ---------------------------------------------------------------------------

def weeks_elapsed(birthday: date, today: date) -> int:
    """Whole weeks between *birthday* and *today*; 0 if today is not after."""
    if today <= birthday:
        return 0
    return (today - birthday).days // 7


def period_index(year_index: int) -> int:
    """Which 30-year colour band a year falls in, capped at the last band."""
    return min(year_index // PERIOD_YEARS, 2)


def week_progress(now: datetime) -> Tuple[int, float]:
    """Return (day_index 0=Mon…6=Sun, fraction_of_week_elapsed)."""
    day_idx       = now.weekday()
    seconds_today = now.hour * 3600 + now.minute * 60 + now.second
    elapsed       = day_idx * 86400 + seconds_today
    return day_idx, elapsed / (7 * 86400)


# ---------------------------------------------------------------------------
# Auto-detect screen resolution
# ---------------------------------------------------------------------------

def detect_screen_size() -> Tuple[int, int]:
    """Best-effort display resolution; falls back to 2560×1440."""
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
# Cell styles
# ---------------------------------------------------------------------------

def draw_hatched_cell(
    draw: ImageDraw.ImageDraw,
    x0: int, y0: int, x1: int, y1: int,
    color: Tuple[int, int, int],
    bg: Tuple[int, int, int],
) -> None:
    """An elapsed cell drawn as diagonal hatching over the background."""
    draw.rectangle([x0, y0, x1, y1], fill=bg)
    step = max(2, (x1 - x0) // 3)
    for offset in range(-(y1 - y0), (x1 - x0) + 1, step):
        draw.line([(x0 + offset, y0), (x0 + offset + (y1 - y0), y1)],
                  fill=color, width=1)


# ---------------------------------------------------------------------------
# Weekly progress column
# ---------------------------------------------------------------------------

def draw_week_column(
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
    day_idx, _ = week_progress(now)
    day_frac   = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0

    fill_color   = theme.elapsed_period_colors[0]
    empty_color  = theme.future_period_colors[0]
    border_color = blend(theme.background, theme.label_color, 0.2)

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
        lw, lh = text_size(draw, lbl, label_font)
        lx     = x + w + 4
        ly     = sy0 + (sy1 - sy0) // 2 - lh // 2
        lcolor = (blend(fill_color, (255, 255, 255), 0.4)
                  if i == day_idx else theme.label_color)
        draw.text((lx, ly), lbl, fill=lcolor, font=label_font)


# ---------------------------------------------------------------------------
# Stats + live indicator (bottom-right pill)
# ---------------------------------------------------------------------------

def draw_stats_and_live(
    draw: ImageDraw.ImageDraw,
    canvas_w: int, zone_y: int, zone_h: int,
    elapsed: int, total_weeks: int,
    now: datetime,
    theme: Theme,
    stat_font,
    base_font_size: int,
) -> None:
    """A bottom-right pill with the elapsed-week count and a live timestamp."""
    live_font = resolve_font(max(9, base_font_size - 1))
    line_gap  = 6

    live_text = f"● LIVE  ·  updated {now.strftime('%H:%M')}"
    stat_text = f"week {elapsed:,} / {total_weeks:,}"

    live_w, live_h = text_size(draw, live_text, live_font)
    stat_w, stat_h = text_size(draw, stat_text, stat_font)

    block_w = max(live_w, stat_w)
    block_h = stat_h + line_gap + live_h

    # Position the block at the bottom-right of the bottom zone (with inner padding)
    margin = 18
    bx = canvas_w - block_w - margin
    by = zone_y + zone_h - block_h - margin
    pad = 10

    pill_color = blend(theme.background, theme.label_color, 0.10)
    draw.rounded_rectangle(
        [bx - pad, by - pad, bx + block_w + pad, by + block_h + pad],
        radius=5, fill=pill_color,
    )

    # Stat line — right-aligned
    sx = bx + (block_w - stat_w)
    draw.text((sx, by), stat_text,
              fill=blend(theme.label_color, (255, 255, 255), 0.15),
              font=stat_font)

    # Live line — right-aligned
    lx        = bx + (block_w - live_w)
    ly        = by + stat_h + line_gap
    dot_char  = "● "
    dot_color = blend(theme.elapsed_period_colors[0], (255, 255, 255), 0.3)
    dot_w, _  = text_size(draw, dot_char, live_font)
    draw.text((lx,          ly), dot_char,                fill=dot_color,        font=live_font)
    draw.text((lx + dot_w,  ly), live_text[len(dot_char):], fill=theme.label_color, font=live_font)
