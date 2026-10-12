"""
Tests for the pure helpers in settings_ui.py.

The tkinter window itself needs a display and isn't exercised here; we only
cover the standalone colour helper used to build the planet-symbol legend.
"""

from settings_ui import _hex_to_rgb


def test_hex_to_rgb_basic():
    assert _hex_to_rgb("#1e1e2e") == (30, 30, 46)
    assert _hex_to_rgb("#ffffff") == (255, 255, 255)
    assert _hex_to_rgb("#000000") == (0, 0, 0)


def test_hex_to_rgb_without_hash():
    assert _hex_to_rgb("cdd6f4") == (205, 214, 244)
