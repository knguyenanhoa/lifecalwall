"""
core.py — The top-level render(): compose the life calendar grid, weekly
progress column, stats pill, and weather panel into one wallpaper image.

Layout: the top 80% of the screen holds the life calendar grid plus the weekly
tracker; the bottom 20% holds the stats pill (right) and the weather panel
(centered).
"""

import math
from datetime import date, datetime
from typing import Optional

from PIL import Image, ImageDraw

from config import PERIOD_YEARS, WEEKS_PER_YEAR, YEARS, Settings, get_theme

from .draw_utils import blend, resolve_font, text_size
from .grid import (
    WEEK_COL_LEFT_MARGIN,
    WEEK_COL_MAX_W,
    WEEK_COL_MIN_W,
    WEEK_COL_TO_GRID_GAP,
    detect_screen_size,
    draw_hatched_cell,
    draw_stats_and_live,
    draw_week_column,
    period_index,
    weeks_elapsed,
)
from .weather_panel import draw_weather, render_weather_panel


def render_weather_only(
    settings: Settings,
    width: int,
    height: int,
    today: Optional[date] = None,
    now: Optional[datetime] = None,
) -> Image.Image:
    """
    Render *only* the weather widget onto a width×height image, sized so the
    panel fills the frame.

    This backs the "Open Weather" quick view: a fast way to see the weather
    for different locations without the surrounding life calendar. The panel's
    base font is scaled up relative to the frame so the widget reads large,
    then it is centered on a background matching the resolved theme.

    Returns a plain background image when there is no weather data to show
    (offline with no cache), mirroring the main render's behaviour of simply
    omitting the panel.
    """
    if today is None:
        today = date.today()
    if now is None:
        now = datetime.now()

    theme = get_theme(settings, today)
    img = Image.new("RGB", (width, height), theme.background)

    # Scale the panel's base font to the frame so the single widget reads large
    # rather than hugging one corner. Clamp so very small/large frames stay sane.
    base_font_size = max(11, min(22, height // 16))

    render_weather_panel(img, settings, theme, base_font_size, today, now)
    return img


def render(settings: Settings, today: Optional[date] = None,
           now: Optional[datetime] = None) -> Image.Image:
    """Render the complete wallpaper for *settings* and return a Pillow image."""
    if today is None:
        today = date.today()
    if now is None:
        now = datetime.now()

    theme = get_theme(settings, today)

    # Canvas ------------------------------------------------------------------
    if settings.canvas_width > 0 and settings.canvas_height > 0:
        canvas_w, canvas_h = settings.canvas_width, settings.canvas_height
    else:
        canvas_w, canvas_h = detect_screen_size()

    img  = Image.new("RGB", (canvas_w, canvas_h), theme.background)
    draw = ImageDraw.Draw(img)

    # Fonts -------------------------------------------------------------------
    area_h         = canvas_h - settings.padding_top - settings.padding_bottom
    label_font_size = max(9,  min(14, area_h // 60))
    stat_font_size  = max(10, min(16, area_h // 55))
    label_font      = resolve_font(label_font_size)
    stat_font       = resolve_font(stat_font_size)

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
            elapsed = weeks_elapsed(date.fromisoformat(settings.birthday), today)
        except ValueError:
            pass

    # Draw cells --------------------------------------------------------------
    week_counter = 0
    for col in range(YEARS):
        period = period_index(col)

        if theme.gradient:
            period_start = period * PERIOD_YEARS
            period_end   = min(period_start + PERIOD_YEARS, YEARS) - 1
            t = (col - period_start) / max(1, period_end - period_start)
            elapsed_color = blend(
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
                    draw_hatched_cell(draw, x0, y0, x1, y1,
                                      elapsed_color, theme.background)
                else:
                    draw.rectangle([x0, y0, x1, y1], fill=elapsed_color)
            else:
                if theme.future_style == "outline":
                    draw.rectangle([x0, y0, x1, y1], outline=future_color)
                else:
                    draw.rectangle([x0, y0, x1, y1], fill=future_color)

    # Period separator lines --------------------------------------------------
    sep_color = blend(theme.background, theme.label_color, 0.35)
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
            tw, _ = text_size(draw, lbl, label_font)
            draw.text((lx - tw // 2, tick_y), lbl,
                      fill=theme.label_color, font=label_font)

    # Week tick labels (y-axis, left of grid) ---------------------------------
    if settings.show_week_labels and y_label_w > 0:
        for row in range(0, WEEKS_PER_YEAR, 4):
            ly  = grid_y + row * (cell_h + gap) + cell_h // 2
            lbl = str(row + 1)
            _, th = text_size(draw, lbl, label_font)
            draw.text((grid_area_x, ly - th // 2), lbl,
                      fill=theme.label_color, font=label_font)

    # Weekly progress column --------------------------------------------------
    draw_week_column(draw, wcol_x, wcol_y, wcol_w, wcol_h,
                     now, theme, label_font)

    # Stats + live indicator (bottom-right of the bottom zone) ----------------
    draw_stats_and_live(draw, canvas_w, bottom_zone_y, bottom_zone_h,
                        elapsed, total_weeks, now, theme,
                        stat_font, label_font_size)

    # Weather report (centered in the bottom zone) ----------------------------
    if settings.show_weather:
        draw_weather(draw, canvas_w, bottom_zone_y, bottom_zone_h,
                     settings, theme, stat_font, label_font_size, today, now)

    return img
