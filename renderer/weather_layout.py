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
    PLANET_COLORS,
    PLANET_PROMINENCE,
    PLANET_SHORT,
    flare_band_index,
    flare_label,
    format_dates,
    format_gmt_offset,
    format_hour_rain,
    next_solar_event,
    parse_flare_class,
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


def _wrap_to_width(draw, text: str, font, max_width: int):
    """
    Greedily wrap *text* into a list of lines that each fit *max_width* pixels
    in *font*. A single word longer than the width is left on its own line
    rather than split. Returns [text] when it already fits or max_width is
    non-positive.
    """
    if max_width <= 0 or text_size(draw, text, font)[0] <= max_width:
        return [text]
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if cur and text_size(draw, trial, font)[0] > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


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
class FlareBar:
    """
    The segmented solar-flare-class widget's placement (A/B/C/M/X), UV-bar
    style. *flare_class* is the raw class string (e.g. "C3.6") the bar decodes.
    """
    x: int
    y: int
    width: int
    flare_class: str


@dataclass
class PlanetGlyph:
    """A planet's vector symbol positioned at an absolute (x, y) in a box."""
    planet: str
    x: int
    y: int
    size: int


@dataclass
class PlanetDot:
    """A planet as a coloured filled circle on the sky strip, with an optional
    short label (e.g. "Me") positioned beneath it."""
    planet: str
    cx: int
    cy: int
    radius: int
    color: Tuple[int, int, int]
    label: Optional["TextPiece"] = None


@dataclass
class SkyStrip:
    """
    A night-sky strip spanning the space column: a horizontal gradient track
    (dusk on the left → midnight centre → dawn on the right) with the visible
    planets placed along it as coloured circles — evening planets toward the
    left, all-night planets centred, morning planets toward the right. Circle
    size encodes rough prominence (Venus largest, Mercury smallest). A close
    conjunction naturally shows as two dots nearly touching.
    """
    track: Tuple[int, int, int, int]      # the gradient track rect
    dots: List["PlanetDot"] = field(default_factory=list)


@dataclass
class SpaceColumn:
    """
    The optional space-weather column (leftmost): a night-sky strip hero (the
    visible planets as coloured dots), then the Kp and flare bars and the
    solar-cycle line. All positions absolute; present only when enabled, and
    each piece is optional so the column collapses cleanly when data is absent.
    """
    heading: TextPiece
    kp_bar: KpBar
    flare_bar: Optional[FlareBar] = None
    solar_cycle: Optional[TextPiece] = None
    sky: Optional["SkyStrip"] = None


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
    week: List[TextPiece] = field(default_factory=list)  # 7-day summary, wrapped
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
    column_gap = int(base_font_size * 5.5)

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

    # Next sun event, with today's length-of-day in parentheses, e.g.
    # "Sunrise: 05:42 (Ld: 11h 55m)" — Ld = length of day.
    import astro
    solar = next_solar_event(report, now)
    daylen = astro.day_length_text(report.sunrise_today, report.sunset_today)
    if solar:
        solar_text = f"{solar[0]}: {solar[1]}"
        if daylen:
            solar_text += f" (Ld: {daylen})"
    else:
        solar_text = ""

    icon_key, _ = weather_condition(report.weather_code)
    has_icon = icon_key != "unknown"

    uv_value = report.uv_index if report.uv_index is not None else report.uv_index_max
    show_uv = uv_value is not None

    # Space weather: show the column only when the setting is on AND we have a
    # Kp value (the fetch may have failed or the cache may predate the field).
    kp_value = report.kp_index if report.kp_index is not None else report.kp_forecast_max
    show_space = bool(getattr(settings, "show_space_weather", False)) and kp_value is not None
    # No top heading: the column leads with the Kp bar so it aligns with the
    # UV bar in the middle column. The solar-cycle line sits below the flare bar.
    space_heading_text = ""
    solar_cycle_text = astro.solar_cycle_text(today) if show_space else ""
    # Solar activity as a flare-class bar (A/B/C/M/X), like the UV/Kp bars.
    # Shown only when we actually have a parseable class.
    flare_class = report.flare_class if show_space else None
    show_flare = show_space and parse_flare_class(flare_class) is not None
    # Visible planets as structured (planet, visibility) pairs, drawn with
    # vector symbols, grouped into three visibility windows (evening → all
    # night → morning). visible_planets() already returns them near→far from
    # the Sun, so each window's list keeps that order.
    _VIS_WINDOW = {"evening sky": "evening", "visible all night": "night",
                   "morning sky": "morning"}
    _WINDOW_ORDER = ("evening", "night", "morning")
    visible = astro.visible_planets(now) if show_space else []
    planets_by_window = {w: [] for w in _WINDOW_ORDER}
    for planet, label in visible:
        win = _VIS_WINDOW.get(label)
        if win:
            planets_by_window[win].append(planet)
    any_planets = bool(visible)
    # Conjunctions are no longer a separate row — the sky strip conveys them by
    # placing the two planets' dots nearly touching.

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
    # A segmented bar's height: the segment row + a 4px gap + its caption line.
    # The Kp and flare bars share this shape.
    kp_bar_h = (space_seg_h + 4 + detail_line_h) if show_space else 0
    flare_bar_h = (space_seg_h + 4 + detail_line_h) if show_flare else 0
    space_head_w, space_head_h = tsize(space_heading_text, detail_font) if show_space else (0, 0)
    # Plain text lines below the bars. The solar-cycle line sits under the
    # flare bar (placed explicitly in the positioning pass below).
    space_lines = []
    if show_space and solar_cycle_text:
        lw, lh = tsize(solar_cycle_text, detail_font)
        space_lines.append(("solar_cycle", solar_cycle_text, lw, lh))

    # Sky strip: a horizontal gradient track with the visible planets as
    # coloured dots. The largest dot (Venus, prominence 1.0) is sized to the
    # detail line height; others scale down by prominence. The strip fills the
    # space hero slot — it does not grow the column (hero height is shared with
    # the middle column, set below).
    dot_max_r = max(3, (detail_line_h + 2) // 2) if (show_space and any_planets) else 0
    space_hero_h = hero_h if show_space else 0

    # Width is driven by the widest line; give the Kp bar a sensible minimum so
    # its six segments stay legible, matching the UV bar's floor.
    # Space column uses the same fixed width as the others (set below as col_w).
    # Measured content widths are retained only for internal left-alignment.
    space_w = 0  # finalized to col_w once col_w is known (see fixed geometry)
    if show_space:
        space_h = space_hero_h + line_gap + kp_bar_h
        if show_flare:
            space_h += line_gap + flare_bar_h
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
    # ---- Fixed geometry -----------------------------------------------------
    # The widget does not breathe with content: all columns share one fixed
    # width derived from the base font (so it scales with the font but never
    # resizes to fit text), and the overall block width is fixed. Dynamic
    # content (the 7-day summary) gets a fixed vertical slot and wraps/truncates
    # into it rather than growing the block.
    col_w = max(base_font_size * 13, forecast_w)  # one width for every column
    space_w = col_w
    space_prefix_w = (col_w + column_gap) if show_space else 0

    left_w = col_w
    right_w = col_w

    # 7-day summary: wrap into the fixed column width, cap at WEEK_MAX_LINES,
    # truncating the last shown line with "…" if the text still overflows.
    WEEK_MAX_LINES = 2
    week_lines = []
    if week_text:
        wrapped = _wrap_to_width(draw, week_text, detail_font, col_w)
        if len(wrapped) > WEEK_MAX_LINES:
            wrapped = wrapped[:WEEK_MAX_LINES]
            wrapped[-1] = _truncate_to_width(draw, wrapped[-1] + " …", detail_font, col_w)
        week_lines = wrapped
    # Fixed slot height for the summary: always WEEK_MAX_LINES tall so the block
    # height stays constant whether the text wraps to one line or two.
    week_slot_h = WEEK_MAX_LINES * detail_line_h + (WEEK_MAX_LINES - 1) * (line_gap // 2)

    left_h = hero_h
    if show_uv:
        left_h += line_gap + uv_h
    if solar_text:
        left_h += line_gap + solar_h
    left_h += line_gap + week_slot_h   # summary slot is always reserved

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
    left_row_heights.append(week_slot_h)  # fixed summary slot, always present
    left_gap = justified_gap(sum(left_row_heights), len(left_row_heights) - 1, line_gap)
    right_gap = justified_gap(len(rows_text) * hour_row_h,
                              max(0, len(rows_text) - 1), row_gap)

    # Footer gets a fixed-height slot (one detail line) whether or not there's
    # text, so the block height doesn't change when location/tz are absent.
    footer_h = detail_line_h
    footer_w = tsize(footer_text, detail_font)[0] if footer_text else 0

    # Fixed block dimensions: the columns plus their gaps, never content-fit.
    # Date line and footer are centered within this fixed width (and truncated
    # to it if ever longer), so they can't widen the block.
    block_w = body_w
    block_h = date_line_h + line_gap + body_h + line_gap + footer_h

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
        heading = TextPiece(space_heading_text, space_x, body_y)
        space_column = SpaceColumn(heading=heading, kp_bar=None)
        line_by_key = {k: (t, lh) for k, t, _lw, lh in space_lines}

        # Hero slot (top): planets row, then the conjunction row, together
        # occupying space_hero_h so the Kp/flare bars below line up with the
        # middle column's UV bar (which sits below an equally tall hero).
        # Sky strip hero: a gradient track across the column with the visible
        # planets as coloured dots. Evening planets sit toward the left (dusk),
        # all-night planets toward the centre, morning planets toward the right
        # (dawn). Dot radius scales with prominence; a close conjunction shows
        # as two dots nearly touching.
        if any_planets:
            show_labels = bool(getattr(settings, "show_planet_labels", False))
            track_h = max(4, detail_line_h // 2)
            label_h = detail_line_h if show_labels else 0
            label_gap = 2 if show_labels else 0
            # Centre the track in the hero slot, but when labels are shown lift
            # it so the dot + label pair stays centred within the slot (labels
            # sit below the dots, inside the existing hero height — no growth).
            group_h = 2 * dot_max_r + label_gap + label_h
            group_top = body_y + (space_hero_h - group_h) // 2
            track_cy = group_top + dot_max_r
            track = (space_x, track_cy - track_h // 2,
                     space_x + space_w, track_cy + track_h // 2)
            # Each visibility window owns a horizontal third of the strip; the
            # planet's longitude within its window maps to a position in that
            # third (near→far from the Sun spreads them out). A small inset keeps
            # dots clear of the strip ends.
            inset = dot_max_r + 2
            usable = space_w - 2 * inset
            third = usable / 3.0
            _WINDOW_SLOT = {"evening": 0, "night": 1, "morning": 2}
            dots = []
            for win in _WINDOW_ORDER:
                members = planets_by_window[win]
                if not members:
                    continue
                slot_x0 = space_x + inset + _WINDOW_SLOT[win] * third
                n = len(members)
                for i, planet in enumerate(members):
                    # Spread members evenly across their third.
                    frac = (i + 1) / (n + 1)
                    cx = int(slot_x0 + frac * third)
                    prom = PLANET_PROMINENCE.get(planet, 0.6)
                    r = max(2, int(dot_max_r * prom))
                    label_piece = None
                    if show_labels:
                        short = PLANET_SHORT.get(planet, planet[:2])
                        lw, lh = tsize(short, detail_font)
                        label_piece = TextPiece(
                            short, cx - lw // 2,
                            track_cy + dot_max_r + label_gap)
                    dots.append(PlanetDot(
                        planet=planet, cx=cx, cy=track_cy, radius=r,
                        color=PLANET_COLORS.get(planet, theme.label_color),
                        label=label_piece,
                    ))
            space_column.sky = SkyStrip(track=track, dots=dots)

        # Kp bar, anchored just below the hero slot using the SAME gap the
        # middle column puts below its hero (left_gap, the justified gap) → the
        # Kp bar lines up with the UV bar. When the space hero is exactly
        # hero_h (the common case) the two bars share a y to the pixel.
        sy = body_y + space_hero_h + left_gap
        space_column.kp_bar = KpBar(x=space_x, y=sy, width=space_w, value=kp_value)
        sy += kp_bar_h

        # Solar-activity flare bar (A/B/C/M/X), styled like the Kp bar.
        if show_flare:
            sy += line_gap
            space_column.flare_bar = FlareBar(x=space_x, y=sy, width=space_w,
                                              flare_class=flare_class)
            sy += flare_bar_h

        # Solar-cycle line, last.
        if "solar_cycle" in line_by_key:
            txt, lh = line_by_key["solar_cycle"]
            sy += line_gap
            space_column.solar_cycle = TextPiece(txt, space_x, sy)
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
        uv_bar = UVBar(x=left_x, y=ly, width=col_w, value=uv_value)
        ly += uv_h

    solar_piece = None
    if solar_text:
        ly += left_gap
        # Keep the sun line within the fixed column.
        solar_piece = TextPiece(_truncate_to_width(draw, solar_text, detail_font, col_w),
                                left_x, ly)
        ly += solar_h

    # 7-day summary in its fixed slot, wrapped across up to WEEK_MAX_LINES.
    ly += left_gap
    week_pieces = []
    wy = ly
    for line in week_lines:
        week_pieces.append(TextPiece(line, left_x, wy))
        wy += detail_line_h + (line_gap // 2)
    ly += week_slot_h

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
        footer_text = _truncate_to_width(draw, footer_text, detail_font, block_w)
        footer_w = tsize(footer_text, detail_font)[0]
        footer_y = by + block_h - footer_h
        footer_piece = TextPiece(footer_text, bx + (block_w - footer_w) // 2, footer_y)

    return WeatherLayout(
        pill_box=pill_box,
        date_line=date_line,
        hero=hero,
        forecast_rows=forecast_rows,
        uv_bar=uv_bar,
        solar=solar_piece,
        week=week_pieces,
        footer=footer_piece,
        space=space_column,
        rain_as_pie=rain_as_pie,
    )
