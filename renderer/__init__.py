"""
renderer — Draw the life calendar wallpaper.

The package is split into focused modules:

  draw_utils     fonts, text measurement, colour blending, brightness ramp
  icons          vector weather + moon glyphs
  grid           the life calendar grid, weekly column, stats pill
  weather_panel  the weather block (conditions, forecast, UV, sun, moon)
  core           the top-level render() that composes everything

The public entry point is ``render``. The leading-underscore aliases below
preserve the pre-split module API (``renderer._blend`` etc.) so existing
callers and tests keep working after the move.
"""

from .core import render, render_weather_only

from .draw_utils import (
    RAMP_MIN_BRIGHTNESS as _RAMP_MIN_BRIGHTNESS,
    blend as _blend,
    ramp_color as _ramp_color,
    resolve_font as _resolve_font,
    text_size as _text_size,
)
from .icons import (
    draw_cloud as _draw_cloud,
    draw_moon_phase as _draw_moon_phase,
    draw_rain_pie as _draw_rain_pie,
    draw_sun as _draw_sun,
    draw_weather_icon as _draw_weather_icon,
    moon_illumination as _moon_illumination,
)
from .grid import (
    DAY_NAMES,
    detect_screen_size as _detect_screen_size,
    draw_hatched_cell as _draw_hatched_cell,
    draw_stats_and_live as _draw_stats_and_live,
    draw_week_column as _draw_week_column,
    period_index as _period_index,
    week_progress as _week_progress,
    weeks_elapsed as _weeks_elapsed,
)
from .weather_panel import (
    draw_uv_bar as _draw_uv_bar,
    draw_weather as _draw_weather,
)
from .weather_panel_text import (
    code_bucket as _code_bucket,
    format_dates as _format_dates,
    format_gmt_offset as _format_gmt_offset,
    format_hour_rain as _format_hour_rain,
    next_solar_event as _next_solar_event,
    summarize_week as _summarize_week,
    uv_band_index as _uv_band_index,
    uv_label as _uv_label,
    weather_condition as _weather_condition,
)

__all__ = ["render", "render_weather_only"]
