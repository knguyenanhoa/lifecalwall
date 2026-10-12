"""
icons.py — Vector weather and moon glyphs.

The system fallback fonts have no weather or moon glyphs, so conditions and the
moon phase are drawn as shapes. These primitives are pure drawing: given a
box and colours, they paint into a Pillow ImageDraw.
"""

import math
from typing import Optional, Tuple

from PIL import ImageDraw

from .draw_utils import blend


_LUNAR_CYCLE_DAYS = 29.53  # mean synodic month


def moon_illumination(lunar_day: Optional[int]) -> Tuple[float, bool]:
    """
    Estimate (illuminated_fraction, waxing) from a lunar-calendar day number.

    The Chinese/Vietnamese lunar calendar is a true lunar calendar, so the day
    of the lunar month closely tracks the moon's phase: day 1 ≈ new moon,
    ~day 15 ≈ full moon. We map the day onto the synodic cycle to get the
    illuminated fraction and whether the moon is waxing (growing toward full)
    or waning (shrinking toward new).

    Returns (0.5, True) as a neutral default when the day is unknown.
    """
    if not lunar_day:
        return 0.5, True
    # Age in days since the new moon (day 1 is ~new, i.e. age 0).
    age = (lunar_day - 1) % _LUNAR_CYCLE_DAYS
    phase = 2 * math.pi * age / _LUNAR_CYCLE_DAYS  # 0=new, π=full, 2π=new
    illum = (1 - math.cos(phase)) / 2              # 0 at new, 1 at full
    waxing = age < _LUNAR_CYCLE_DAYS / 2
    return illum, waxing


def draw_moon_phase(
    draw: ImageDraw.ImageDraw,
    x: int, y: int, radius: int,
    color: Tuple[int, int, int],
    bg: Tuple[int, int, int],
    lunar_day: Optional[int] = None,
) -> None:
    """
    Draw the moon at (x, y) showing the phase implied by *lunar_day*.

    The lit disc is built from a lit half-disc plus a terminator ellipse: for a
    crescent the ellipse is painted in the dark/background tone (carving the lit
    half down to a sliver), and for a gibbous it's painted in the lit tone
    (filling the dark half out toward full). The lit side is the right for a
    waxing moon and the left for a waning moon (Northern view).
    """
    cx, cy = x + radius, y + radius
    box = [cx - radius, cy - radius, cx + radius, cy + radius]

    illum, waxing = moon_illumination(lunar_day)

    # Dark base disc with a faint ring so a new moon still reads as a circle.
    ring = blend(bg, color, 0.5)
    draw.ellipse(box, fill=bg, outline=ring, width=max(1, radius // 6))

    # The lit half: right side when waxing, left side when waning. Pillow
    # angles go clockwise from 3 o'clock, so -90..90 is the right semicircle.
    if waxing:
        draw.pieslice(box, -90, 90, fill=color)
    else:
        draw.pieslice(box, 90, 270, fill=color)

    # Terminator ellipse: its half-width shrinks as the phase nears the
    # quarters (straight terminator) and grows toward new/full.
    term_w = radius * abs(1 - 2 * illum)
    if term_w >= 1:
        term_box = [cx - term_w, cy - radius, cx + term_w, cy + radius]
        # Crescent (<half lit): carve the lit half with the dark tone.
        # Gibbous (>half lit): extend light into the dark half.
        draw.ellipse(term_box, fill=(bg if illum < 0.5 else color))

    # Re-stroke the outline so the disc edge stays crisp over the fills.
    draw.ellipse(box, outline=ring, width=max(1, radius // 6))


def draw_rain_pie(draw, cx, cy, radius, fraction, fill, track, outline) -> None:
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


def draw_sun(draw, x, y, size, color) -> None:
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


def draw_cloud(draw, x, y, w, h, color) -> None:
    """A simple cloud built from overlapping lobes on a flat base."""
    base_top = y + h * 0.55
    draw.rounded_rectangle([x, base_top, x + w, y + h], radius=h * 0.22, fill=color)
    draw.ellipse([x + w * 0.05, y + h * 0.30, x + w * 0.50, y + h * 0.80], fill=color)
    draw.ellipse([x + w * 0.35, y + h * 0.10, x + w * 0.80, y + h * 0.72], fill=color)
    draw.ellipse([x + w * 0.55, y + h * 0.32, x + w * 0.98, y + h * 0.82], fill=color)


def draw_weather_icon(draw, key: str, x: int, y: int, size: int,
                      color, accent, bg) -> None:
    """
    Draw a small vector weather icon for *key* inside a size×size box at (x, y).
    Conditions are drawn as shapes (same approach as the crescent moon).
    """
    if key == "clear":
        draw_sun(draw, x, y, size, color)
        return

    if key == "partly":
        # Small sun peeking behind a cloud.
        draw_sun(draw, x, int(y - size * 0.05), int(size * 0.7), color)
        draw_cloud(draw, x + size * 0.15, y + size * 0.32, size * 0.85, size * 0.5, color)
        return

    # The remaining icons all sit under a cloud.
    cloud_w, cloud_h = size, size * 0.55
    cloud_y = y + size * 0.05
    draw_cloud(draw, x, cloud_y, cloud_w, cloud_h, color)
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


# ---------------------------------------------------------------------------
# Planetary symbols (vector) — the system fallback fonts lack these glyphs,
# so the conventional astronomical symbols are drawn as simple shapes, the
# same approach as the moon and weather icons. Each is drawn to fit a size×size
# box at (x, y); *weight* scales the stroke width.
# ---------------------------------------------------------------------------

PLANET_SYMBOLS = ("Mercury", "Venus", "Mars", "Jupiter", "Saturn")


def _planet_stroke(size: int) -> int:
    return max(1, size // 10)


def _circle(draw, cx, cy, r, color, w):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)


def _cross(draw, cx, top_y, length, color, w):
    """A plus-cross centred horizontally at cx, spanning vertically from top_y."""
    half = length / 2
    midy = top_y + half
    draw.line([(cx, top_y), (cx, top_y + length)], fill=color, width=w)
    draw.line([(cx - half, midy), (cx + half, midy)], fill=color, width=w)


def draw_planet_symbol(draw, planet: str, x: int, y: int, size: int, color) -> None:
    """
    Draw the astronomical symbol for *planet* inside a size×size box at (x, y).

    Schematic but recognizable renditions of the classical glyphs:
      Mercury ☿  circle with horns above and a cross below
      Venus   ♀  circle above a cross
      Mars    ♂  circle with an arrow to the upper-right
      Jupiter ♃  a stylised numeral-four / zeta with a crossbar
      Saturn  ♄  a cross above a stylised scythe hook
    """
    w = _planet_stroke(size)
    cx = x + size / 2

    if planet == "Venus":
        r = size * 0.22
        cy = y + size * 0.32
        _circle(draw, cx, cy, r, color, w)
        _cross(draw, cx, cy + r, size * 0.30, color, w)
        return

    if planet == "Mercury":
        r = size * 0.20
        cy = y + size * 0.42
        _circle(draw, cx, cy, r, color, w)
        _cross(draw, cx, cy + r, size * 0.26, color, w)
        # Horns: a shallow upward arc above the circle.
        horn_box = [cx - r, y + size * 0.04, cx + r, y + size * 0.30]
        draw.arc(horn_box, start=200, end=340, fill=color, width=w)
        return

    if planet == "Mars":
        r = size * 0.22
        cy = y + size * 0.60
        _circle(draw, cx, cy, r, color, w)
        # Arrow from the circle's upper-right edge to the top-right corner.
        ax0 = cx + r * 0.7
        ay0 = cy - r * 0.7
        ax1 = x + size * 0.88
        ay1 = y + size * 0.14
        draw.line([(ax0, ay0), (ax1, ay1)], fill=color, width=w)
        head = size * 0.22
        draw.line([(ax1, ay1), (ax1 - head, ay1)], fill=color, width=w)
        draw.line([(ax1, ay1), (ax1, ay1 + head)], fill=color, width=w)
        return

    if planet == "Jupiter":
        # A horizontal baseline crossed by a hooked vertical — a stylised "4".
        baseline_y = y + size * 0.72
        draw.line([(cx - size * 0.02, y + size * 0.18),
                   (cx - size * 0.02, baseline_y)], fill=color, width=w)
        # Hook at the top-left, like the glyph's rounded head.
        hook_box = [x + size * 0.14, y + size * 0.12,
                    cx + size * 0.04, y + size * 0.46]
        draw.arc(hook_box, start=90, end=270, fill=color, width=w)
        draw.line([(x + size * 0.20, baseline_y),
                   (x + size * 0.80, baseline_y)], fill=color, width=w)
        return

    if planet == "Saturn":
        # A cross up top above a scythe-like hook.
        stem_x = cx - size * 0.10
        draw.line([(stem_x, y + size * 0.16),
                   (stem_x, y + size * 0.58)], fill=color, width=w)
        draw.line([(stem_x - size * 0.14, y + size * 0.24),
                   (stem_x + size * 0.14, y + size * 0.24)], fill=color, width=w)
        # The hook curving down and to the right off the stem's foot.
        hook_box = [stem_x - size * 0.02, y + size * 0.46,
                    cx + size * 0.30, y + size * 0.88]
        draw.arc(hook_box, start=160, end=20, fill=color, width=w)
        return

    # Unknown planet: a bare circle so something still shows.
    _circle(draw, cx, y + size / 2, size * 0.22, color, w)
