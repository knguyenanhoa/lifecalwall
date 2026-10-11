"""
draw_utils.py — Low-level drawing primitives shared across the renderer.

Font resolution, text measurement, colour blending, and the brightness ramp
used to encode magnitude (rain chance, relative temperature) live here because
both the grid and the weather panel depend on them.
"""

from typing import Tuple

from PIL import ImageDraw, ImageFont

from config import Theme


def resolve_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Return a TrueType font at *size*, trying a list of common system fonts
    (macOS first, then Linux) and falling back to Pillow's bundled default.
    """
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


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    """Width/height of *text* in *font*, across Pillow versions."""
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        return draw.textsize(text, font=font)


def blend(
    c1: Tuple[int, int, int],
    c2: Tuple[int, int, int],
    t: float,
) -> Tuple[int, int, int]:
    """Linear interpolation between two RGB colours at fraction *t* in [0, 1]."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


# Brightness floor for the ramp's dark end: even a 0%/minimum value keeps
# roughly this fraction of the full brightness so it stays clearly readable
# rather than fading into the background.
RAMP_MIN_BRIGHTNESS = 0.55


def ramp_color(theme: Theme, t: float) -> Tuple[int, int, int]:
    """
    Colour along a dark→light ramp keyed by *t* in [0, 1], used to encode
    magnitude (rain chance, relative temperature) as brightness. The dark end
    is floored at RAMP_MIN_BRIGHTNESS so t=0 is dim but still legible; t=1 is
    near-white.
    """
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    top = blend(theme.label_color, (255, 255, 255), 0.4)
    # Map t into [floor, 1] then blend from background toward the bright top,
    # so the minimum never drops below the readable floor.
    brightness = RAMP_MIN_BRIGHTNESS + (1.0 - RAMP_MIN_BRIGHTNESS) * t
    return blend(theme.background, top, brightness)
