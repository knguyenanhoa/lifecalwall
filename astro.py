"""
astro.py — Lightweight, dependency-free astronomy helpers for the wallpaper.

Everything here is pure computation from a date (and, for sun geometry, from
times the weather report already provides). No network and no third-party
ephemeris: the planet positions use low-precision Keplerian mean elements,
which are plenty accurate for "which planets are up and are any of them close
together" on a desktop wallpaper (good to roughly a degree, far better than the
eye can judge against the sky).

Three independent pieces live here:

  • solar_cycle_phase  — where we are in the ~11-year sunspot cycle
  • day_length_text    — length of daylight from sunrise/sunset
  • visible_planets / planet_conjunctions — naked-eye planet visibility
"""

import math
from datetime import date, datetime
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Solar cycle phase
# ---------------------------------------------------------------------------
#
# Solar activity waxes and wanes over an ~11-year cycle. Solar Cycle 25 began
# at the December 2019 minimum and reached its maximum around 2024–2025. We
# model the cycle as a cosine between a known minimum and the mean cycle length
# so we can name the current phase without any live data. These anchors are
# approximate by nature; the label is a gentle "where are we" indicator, not a
# forecast.

_CYCLE_START = date(2019, 12, 1)   # Solar Cycle 25 minimum
_CYCLE_LENGTH_DAYS = 11 * 365.25   # mean solar-cycle length
_CYCLE_START_NUMBER = 25


def solar_cycle_phase(today: Optional[date] = None) -> Tuple[int, str, float]:
    """
    Return (cycle_number, phase_label, fraction) for *today*.

    fraction is 0–1 through the current cycle (0 = minimum, 0.5 = maximum).
    phase_label is one of: "rising", "near maximum", "declining",
    "near minimum". cycle_number increments each time a cycle completes.
    """
    if today is None:
        today = date.today()

    days = (today - _CYCLE_START).days
    cycles_elapsed = days / _CYCLE_LENGTH_DAYS
    cycle_number = _CYCLE_START_NUMBER + int(cycles_elapsed)
    frac = cycles_elapsed - math.floor(cycles_elapsed)  # 0..1 within the cycle

    # 0 = minimum, 0.5 = maximum, 1 = next minimum.
    if frac < 0.15 or frac >= 0.85:
        label = "near minimum"
    elif frac < 0.5:
        label = "rising"
    elif frac < 0.65:
        label = "near maximum"
    else:
        label = "declining"
    return cycle_number, label, frac


def solar_cycle_text(today: Optional[date] = None) -> str:
    """A one-line solar-cycle summary, e.g. "Solar cycle 25 · declining"."""
    number, label, _frac = solar_cycle_phase(today)
    return f"Solar cycle {number} · {label}"


# ---------------------------------------------------------------------------
# Day length
# ---------------------------------------------------------------------------

def day_length_text(sunrise_iso: str, sunset_iso: str) -> str:
    """
    Return daylight length as "Hh Mm" (e.g. "10h 18m") from ISO sunrise/sunset
    strings, or "" when either is missing or unparseable. Handles a sunset past
    midnight (polar-ish edge) by wrapping to a positive duration.
    """
    def _parse(iso: str) -> Optional[datetime]:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            return None

    sr, ss = _parse(sunrise_iso), _parse(sunset_iso)
    if sr is None or ss is None:
        return ""

    minutes = round((ss - sr).total_seconds() / 60)
    if minutes < 0:
        minutes += 24 * 60
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


# ---------------------------------------------------------------------------
# Planet positions (low-precision Keplerian elements)
# ---------------------------------------------------------------------------
#
# Mean orbital elements at J2000 with linear rates, from the standard
# low-precision formulae (Standish/JPL "Keplerian Elements for Approximate
# Positions"). Units: a in AU, angles in degrees; rates are per Julian century.
# Columns: a, e, I (inclination), L (mean longitude), long. of perihelion,
# long. of ascending node — each as (value, rate_per_century).

_ELEMENTS = {
    # planet:      a,            e,              I,            L,                 ϖ (peri),         Ω (node)
    "Mercury": ((0.38709927, 0.00000037), (0.20563593, 0.00001906), (7.00497902, -0.00594749),
                (252.25032350, 149472.67411175), (77.45779628, 0.16047689), (48.33076593, -0.12534081)),
    "Venus":   ((0.72333566, 0.00000390), (0.00677672, -0.00004107), (3.39467605, -0.00078890),
                (181.97909950, 58517.81538729), (131.60246718, 0.00268329), (76.67984255, -0.27769418)),
    "Earth":   ((1.00000261, 0.00000562), (0.01671123, -0.00004392), (-0.00001531, -0.01294668),
                (100.46457166, 35999.37244981), (102.93768193, 0.32327364), (0.0, 0.0)),
    "Mars":    ((1.52371034, 0.00001847), (0.09339410, 0.00007882), (1.84969142, -0.00813131),
                (-4.55343205, 19140.30268499), (-23.94362959, 0.44441088), (49.55953891, -0.29257343)),
    "Jupiter": ((5.20288700, -0.00011607), (0.04838624, -0.00013253), (1.30439695, -0.00183714),
                (34.39644051, 3034.74612775), (14.72847983, 0.21252668), (100.47390909, 0.20469106)),
    "Saturn":  ((9.53667594, -0.00125060), (0.05386179, -0.00050991), (2.48599187, 0.00193609),
                (49.95424423, 1222.49362201), (92.59887831, -0.41897216), (113.66242448, -0.28867794)),
}

# The naked-eye planets we report, in order from the Sun.
NAKED_EYE_PLANETS = ["Mercury", "Venus", "Mars", "Jupiter", "Saturn"]


def _julian_centuries(when: datetime) -> float:
    """Julian centuries (TT≈UT here) since J2000.0 for *when* (treated as UTC)."""
    # Days since J2000.0 (2000-01-01 12:00 UT).
    j2000 = datetime(2000, 1, 1, 12, 0, 0)
    days = (when - j2000).total_seconds() / 86400.0
    return days / 36525.0


def _norm_deg(x: float) -> float:
    return x % 360.0


def _heliocentric_ecliptic(planet: str, t: float) -> Tuple[float, float]:
    """
    Return (x, y) heliocentric ecliptic coordinates (AU) of *planet* at epoch
    *t* (Julian centuries past J2000), projected onto the ecliptic plane.
    Inclination is small for these planets, so a planar projection is fine for
    longitude/elongation purposes.
    """
    a0, e0, I0, L0, peri0, node0 = _ELEMENTS[planet]
    a = a0[0] + a0[1] * t
    e = e0[0] + e0[1] * t
    L = _norm_deg(L0[0] + L0[1] * t)
    peri = peri0[0] + peri0[1] * t
    node = node0[0] + node0[1] * t

    # Mean anomaly, then solve Kepler for eccentric anomaly.
    M = math.radians(_norm_deg(L - peri + 180.0) - 180.0)
    E = M
    for _ in range(8):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))

    # Position in the orbital plane.
    xv = a * (math.cos(E) - e)
    yv = a * (math.sqrt(1 - e * e) * math.sin(E))

    # True anomaly + heliocentric distance → ecliptic longitude.
    v = math.atan2(yv, xv)
    r = math.hypot(xv, yv)
    arg_peri = math.radians(peri - node)
    node_r = math.radians(node)
    lon = v + arg_peri + node_r
    return r * math.cos(lon), r * math.sin(lon)


def _geocentric_ecliptic_longitude(planet: str, t: float) -> float:
    """Geocentric ecliptic longitude (degrees, 0–360) of *planet* at epoch t."""
    ex, ey = _heliocentric_ecliptic("Earth", t)
    px, py = _heliocentric_ecliptic(planet, t)
    return _norm_deg(math.degrees(math.atan2(py - ey, px - ex)))


def _sun_ecliptic_longitude(t: float) -> float:
    """Geocentric ecliptic longitude of the Sun = Earth's heliocentric lon + 180."""
    ex, ey = _heliocentric_ecliptic("Earth", t)
    return _norm_deg(math.degrees(math.atan2(ey, ex)) + 180.0)


def _signed_sep(a: float, b: float) -> float:
    """Smallest signed angular separation a−b in degrees, within (−180, 180]."""
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


def planet_visibility(planet: str, when: datetime) -> Tuple[float, str]:
    """
    Return (elongation_deg, visibility_label) for *planet* at *when*.

    Elongation is the angular distance from the Sun (0 = behind/in front of the
    Sun, 180 = opposite). The label is a coarse naked-eye prospect:

      • < 15°  → "not visible" (lost in the Sun's glare)
      • planet east of the Sun → "evening sky" (sets after the Sun)
      • planet west of the Sun → "morning sky" (rises before the Sun)
      • near 180° (outer planets) → "visible all night"
    """
    t = _julian_centuries(when)
    sun_lon = _sun_ecliptic_longitude(t)
    p_lon = _geocentric_ecliptic_longitude(planet, t)
    signed = _signed_sep(p_lon, sun_lon)   # +east of Sun, −west
    elong = abs(signed)

    if elong < 15:
        return elong, "not visible"
    if elong > 150:
        return elong, "visible all night"
    # East of the Sun → trails it → evening sky; west → leads it → morning sky.
    return elong, ("evening sky" if signed > 0 else "morning sky")


def visible_planets(when: Optional[datetime] = None) -> List[Tuple[str, str]]:
    """
    Return [(planet, visibility_label), …] for the naked-eye planets that are
    currently clear of the Sun's glare (elongation ≥ 15°), brightest/innermost
    first by our fixed order. Planets lost in the glare are omitted.
    """
    if when is None:
        when = datetime.now()
    out: List[Tuple[str, str]] = []
    for planet in NAKED_EYE_PLANETS:
        elong, label = planet_visibility(planet, when)
        if label != "not visible":
            out.append((planet, label))
    return out


def planet_conjunctions(when: Optional[datetime] = None,
                        threshold_deg: float = 10.0) -> List[Tuple[str, str, float]]:
    """
    Return [(planet_a, planet_b, separation_deg), …] for pairs of naked-eye
    planets closer than *threshold_deg* in ecliptic longitude at *when*, both
    being clear of the Sun's glare. Sorted closest-first. Approximate (longitude
    only), which is enough to flag an eye-catching pairing in the sky.

    The default 10° matches the span commonly cited for a naked-eye "close
    pairing" — tight enough to be noteworthy, loose enough that the line
    actually appears through the year rather than only on rare exact meetings.
    """
    if when is None:
        when = datetime.now()
    t = _julian_centuries(when)

    lons = {}
    for planet in NAKED_EYE_PLANETS:
        elong, label = planet_visibility(planet, when)
        if label != "not visible":
            lons[planet] = _geocentric_ecliptic_longitude(planet, t)

    pairs: List[Tuple[str, str, float]] = []
    names = list(lons)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sep = abs(_signed_sep(lons[names[i]], lons[names[j]]))
            if sep <= threshold_deg:
                pairs.append((names[i], names[j], sep))
    pairs.sort(key=lambda p: p[2])
    return pairs


def planets_text(when: Optional[datetime] = None, max_planets: int = 3) -> str:
    """
    A compact one-liner of currently visible planets, e.g.
    "Planets: Venus (evening), Jupiter (all night)". Returns "" when none are
    clear of the Sun. At most *max_planets* are listed to keep it short.
    """
    vis = visible_planets(when)
    if not vis:
        return ""
    short = {
        "evening sky": "evening",
        "morning sky": "morning",
        "visible all night": "all night",
    }
    parts = [f"{name} ({short.get(label, label)})" for name, label in vis[:max_planets]]
    return "Planets: " + ", ".join(parts)


def conjunction_text(when: Optional[datetime] = None) -> str:
    """
    A one-liner for the closest current planetary conjunction, e.g.
    "Venus–Jupiter 3° apart", or "" when no pair is within threshold.
    """
    pairs = planet_conjunctions(when)
    if not pairs:
        return ""
    a, b, sep = pairs[0]
    return f"{a}–{b} {sep:.0f}° apart"
