"""
weather_panel_text.py — Pure data/formatting helpers for the weather panel.

Everything here maps a weather report (or a date) to strings, buckets, bands,
or chosen events. No drawing and no layout — just interpretation of the data,
kept separate so it is trivially testable and reusable by both the layout pass
and the paint pass.
"""

from datetime import date, datetime
from typing import Optional, Tuple


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
UV_BANDS = [
    (3,            "Low",       (90, 190, 90)),
    (6,            "Moderate",  (230, 200, 60)),
    (8,            "High",      (235, 150, 50)),
    (11,           "Very high", (220, 70, 60)),
    (float("inf"), "Extreme",   (160, 90, 200)),
]


def uv_band_index(uv: float) -> int:
    """Index into UV_BANDS for a UV value."""
    for i, (upper, _label, _color) in enumerate(UV_BANDS):
        if uv < upper:
            return i
    return len(UV_BANDS) - 1


def uv_label(uv: float) -> str:
    """WHO UV-index exposure band label for a UV value."""
    return UV_BANDS[uv_band_index(uv)][1]


# Planetary K-index (geomagnetic activity) bands, keyed to NOAA's G-scale.
# (upper_bound_exclusive, label, color). Kp runs 0–9. Below Kp5 is "quiet"
# through "unsettled" (no storm, G0); Kp5+ maps to geomagnetic storm levels
# G1–G5. The colours deepen with intensity like the UV ramp, so the segmented
# bar reads at a glance and agrees with the text label.
KP_BANDS = [
    (5,            "Quiet",       (90, 150, 200)),   # Kp 0–4  (G0)
    (6,            "G1 Minor",    (90, 190, 90)),    # Kp 5
    (7,            "G2 Moderate", (230, 200, 60)),   # Kp 6
    (8,            "G3 Strong",   (235, 150, 50)),   # Kp 7
    (9,            "G4 Severe",   (220, 70, 60)),    # Kp 8
    (float("inf"), "G5 Extreme",  (160, 90, 200)),   # Kp 9
]


def kp_band_index(kp: float) -> int:
    """Index into KP_BANDS for a Kp value."""
    for i, (upper, _label, _color) in enumerate(KP_BANDS):
        if kp < upper:
            return i
    return len(KP_BANDS) - 1


def kp_label(kp: float) -> str:
    """Geomagnetic-activity band label for a Kp value."""
    return KP_BANDS[kp_band_index(kp)][1]


def aurora_outlook(kp: float) -> str:
    """
    A short, plain-language aurora prospect for a Kp value. Higher Kp pushes
    the auroral oval toward lower (more equatorward) latitudes, so the phrasing
    escalates from "unlikely" to visibility well away from the poles.
    """
    if kp < 3:
        return "Aurora unlikely"
    if kp < 5:
        return "Aurora at high latitudes"
    if kp < 7:
        return "Aurora possible mid-latitudes"
    return "Aurora far from poles"


# NOAA R-scale (radio blackouts, driven by solar flares) → plain-language
# solar-activity label. R0 means no blackout, i.e. a calm Sun; R1–R5 escalate.
_R_SCALE_LABELS = {
    0: "Quiet",
    1: "Minor flares",
    2: "Moderate flares",
    3: "Strong flares",
    4: "Severe flares",
    5: "Extreme flares",
}


def solar_activity_outlook(r_scale: Optional[int]) -> str:
    """
    A short solar-activity line from the NOAA R-scale, in the same spirit as
    the aurora outlook, e.g. "Sun: quiet" or "Sun: strong flares". Returns ""
    when the scale is unknown so the caller can omit the line.
    """
    if r_scale is None:
        return ""
    label = _R_SCALE_LABELS.get(int(r_scale), "active")
    return f"Sun: {label.lower()}"


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
