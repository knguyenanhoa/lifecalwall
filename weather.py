"""
weather.py — Fetch a short weather report for the life calendar wallpaper.

Provides the current temperature plus the rain forecast for the next few
hours of the current day, using only the standard library (no extra
dependencies) and free, key-less services:

  - Geolocation : ipapi.co  (fallback: ip-api.com) — derives lat/lon from
                  the machine's public IP. A manual lat/lon in settings
                  takes precedence and skips the network geolocation call.
  - Forecast    : Open-Meteo — free, no API key required.

The render loop ticks every minute, but the weather only needs to refresh
every half hour. To avoid hammering the network we cache the last successful
report on disk (~/.lifecal/weather_cache.json) with a TTL. Between refreshes,
and whenever the network is unavailable, the cached report is reused. If
there is no usable cache at all, get_weather() returns None so the renderer
can simply omit the weather block rather than crash.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional, Tuple

log = logging.getLogger("lifecal.weather")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.expanduser("~/.lifecal")
CACHE_FILE = os.path.join(CACHE_DIR, "weather_cache.json")
GEOCODE_CACHE_FILE = os.path.join(CACHE_DIR, "geocode_cache.json")

# Used when the user hasn't set a location.
DEFAULT_WEATHER_LOCATION = "Ho Chi Minh City"

# Bump whenever the cached report's schema changes (new fields, etc.) so a
# cache written by an older build is discarded and refetched rather than
# served with fields silently missing.
CACHE_VERSION = 2

# How long a fetched report stays fresh before we try to refresh it.
REFRESH_INTERVAL_SECONDS = 30 * 60  # half an hour

# How many hours ahead the rain forecast covers.
FORECAST_HOURS = 6

# Network timeout for each HTTP request (seconds).
HTTP_TIMEOUT = 8

# A browser-like User-Agent — some geolocation endpoints reject the default
# urllib agent with a 403.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) lifecal-wallpaper"
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class HourForecast:
    """Rain outlook for a single upcoming hour."""
    label: str            # e.g. "14:00"
    temperature: float    # degrees, in the report's unit
    precip_probability: int  # percent chance of precipitation, 0–100
    precip_amount: float  # precipitation in mm
    weather_code: Optional[int] = None  # condition for this hour, as a WMO code


@dataclass
class WeatherReport:
    """A complete, cacheable weather snapshot."""
    location: str                # resolved human-readable place name, may be ""
    temperature: float           # current temperature
    temperature_unit: str        # e.g. "°C"
    hours: List[HourForecast]    # next FORECAST_HOURS hours
    fetched_at: float            # epoch seconds when fetched
    temp_low: Optional[float] = None   # today's forecast low, in the report's unit
    temp_high: Optional[float] = None  # today's forecast high, in the report's unit
    utc_offset_seconds: Optional[int] = None  # location's UTC offset, in seconds
    weather_code: Optional[int] = None    # current condition as a WMO code
    uv_index: Optional[float] = None      # current UV index
    uv_index_max: Optional[float] = None  # today's peak UV index
    # Solar events as local-time ISO strings ("2026-09-19T05:42"), may be "".
    sunrise_today: str = ""      # today's sunrise
    sunset_today: str = ""       # today's sunset
    sunrise_tomorrow: str = ""   # tomorrow's sunrise
    requested_location: str = "" # the location string this report was built for

    @property
    def max_precip_probability(self) -> int:
        return max((h.precip_probability for h in self.hours), default=0)

    @property
    def total_precip_amount(self) -> float:
        return sum(h.precip_amount for h in self.hours)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get_json(url: str) -> dict:
    """GET *url* and parse the JSON body. Raises on any failure."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Geolocation
# ---------------------------------------------------------------------------

def _geolocate() -> Tuple[float, float, str]:
    """
    Resolve the machine's approximate (latitude, longitude, city) from its
    public IP. Tries ipapi.co first, then ip-api.com. Raises if both fail.
    """
    try:
        data = _http_get_json("https://ipapi.co/json/")
        lat, lon = data.get("latitude"), data.get("longitude")
        if lat is not None and lon is not None:
            return float(lat), float(lon), data.get("city", "") or ""
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
        log.info("ipapi.co geolocation failed: %s", exc)

    # Fallback provider
    data = _http_get_json("http://ip-api.com/json/?fields=status,lat,lon,city")
    if data.get("status") == "success":
        return float(data["lat"]), float(data["lon"]), data.get("city", "") or ""
    raise RuntimeError("all geolocation providers failed")


# ---------------------------------------------------------------------------
# Geocoding (place name → coordinates)
# ---------------------------------------------------------------------------

def _load_geocode_cache() -> dict:
    try:
        with open(GEOCODE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_geocode_cache(cache: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError as exc:
        log.info("Could not write geocode cache: %s", exc)


def geocode(place: str) -> Tuple[float, float, str]:
    """
    Resolve a place name to (latitude, longitude, canonical_name) via the
    Open-Meteo geocoding API. Results are cached on disk keyed by the query,
    since a place's coordinates never change and geocoding is comparatively
    slow. Raises if the place cannot be found.
    """
    key = place.strip().lower()
    if not key:
        raise ValueError("empty place name")

    cache = _load_geocode_cache()
    if key in cache:
        lat, lon, name = cache[key]
        return float(lat), float(lon), name

    query = urllib.parse.quote(place.strip())
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={query}&count=1&language=en&format=json"
    )
    data = _http_get_json(url)
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"no geocoding match for {place!r}")

    top = results[0]
    lat, lon = float(top["latitude"]), float(top["longitude"])
    name = top.get("name", place.strip())

    cache[key] = [lat, lon, name]
    _save_geocode_cache(cache)
    return lat, lon, name


# ---------------------------------------------------------------------------
# Forecast fetch
# ---------------------------------------------------------------------------

def _resolve_location(
    latitude: Optional[float],
    longitude: Optional[float],
    location: str,
) -> Tuple[float, float, str]:
    """
    Determine which coordinates to fetch weather for, in priority order:

      1. An explicit latitude/longitude pair (manual override).
      2. The given location name, geocoded (falls back to the default
         location name if blank).
      3. IP-based geolocation, as a last resort when geocoding fails.
    """
    if latitude is not None and longitude is not None:
        return latitude, longitude, location or ""

    place = location.strip() or DEFAULT_WEATHER_LOCATION
    try:
        return geocode(place)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError,
            RuntimeError, OSError) as exc:
        log.info("Geocoding %r failed (%s); falling back to IP location.",
                 place, exc)
        return _geolocate()


def _fetch_report(
    latitude: Optional[float],
    longitude: Optional[float],
    location: str,
    fahrenheit: bool,
) -> WeatherReport:
    """
    Build a WeatherReport from Open-Meteo for the resolved location.
    """
    latitude, longitude, location_name = _resolve_location(
        latitude, longitude, location)

    unit_param = "fahrenheit" if fahrenheit else "celsius"
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude:.4f}&longitude={longitude:.4f}"
        "&current=temperature_2m,weather_code,uv_index"
        "&hourly=temperature_2m,precipitation_probability,precipitation,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset,uv_index_max"
        # Two days so a late-evening "next 6 hours" window can roll past
        # midnight into tomorrow instead of running out of hours.
        "&forecast_days=2"
        f"&temperature_unit={unit_param}"
        "&timezone=auto"
    )
    data = _http_get_json(url)

    hourly = data.get("hourly", {})
    times: List[str] = hourly.get("time", [])
    temps: List[float] = hourly.get("temperature_2m", [])
    probs: List[float] = hourly.get("precipitation_probability", [])
    amounts: List[float] = hourly.get("precipitation", [])
    codes: List[float] = hourly.get("weather_code", [])

    # Select the next FORECAST_HOURS hourly slots, starting at the current
    # hour and rolling forward — across midnight if necessary.
    current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
    hours: List[HourForecast] = []
    for i, iso in enumerate(times):
        try:
            slot = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if slot < current_hour:
            continue
        code_i = _at(codes, i, None)
        hours.append(HourForecast(
            label=slot.strftime("%H:%M"),
            temperature=_at(temps, i, 0.0),
            precip_probability=int(round(_at(probs, i, 0.0))),
            precip_amount=float(_at(amounts, i, 0.0)),
            weather_code=int(code_i) if code_i is not None else None,
        ))
        if len(hours) >= FORECAST_HOURS:
            break

    current = data.get("current", {})
    current_units = data.get("current_units", {})
    temperature_unit = current_units.get("temperature_2m", "°F" if fahrenheit else "°C")

    # Today's low/high come from the first entry of the daily arrays.
    daily = data.get("daily", {})
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    temp_high = float(highs[0]) if highs else None
    temp_low = float(lows[0]) if lows else None

    offset = data.get("utc_offset_seconds")
    utc_offset_seconds = int(offset) if offset is not None else None

    sunrises = daily.get("sunrise", [])
    sunsets = daily.get("sunset", [])

    code = current.get("weather_code")
    uv_now = current.get("uv_index")
    uv_max_list = daily.get("uv_index_max", [])
    uv_max = uv_max_list[0] if uv_max_list else None

    return WeatherReport(
        location=location_name,
        temperature=float(current.get("temperature_2m", hours[0].temperature if hours else 0.0)),
        temperature_unit=temperature_unit,
        hours=hours,
        fetched_at=time.time(),
        temp_low=temp_low,
        temp_high=temp_high,
        utc_offset_seconds=utc_offset_seconds,
        sunrise_today=str(_at(sunrises, 0, "")),
        sunset_today=str(_at(sunsets, 0, "")),
        sunrise_tomorrow=str(_at(sunrises, 1, "")),
        weather_code=int(code) if code is not None else None,
        uv_index=float(uv_now) if uv_now is not None else None,
        uv_index_max=float(uv_max) if uv_max is not None else None,
    )


def _at(seq: List, index: int, default):
    """Safe indexed access returning *default* when out of range."""
    return seq[index] if 0 <= index < len(seq) else default


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _load_cache() -> Optional[WeatherReport]:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Discard caches written by an older schema so newly-added fields
        # (e.g. hourly weather codes) aren't served as missing.
        if data.get("cache_version") != CACHE_VERSION:
            log.info("Discarding weather cache from an older schema version.")
            return None
        hours = [HourForecast(**h) for h in data.get("hours", [])]
        return WeatherReport(
            location=data.get("location", ""),
            temperature=data["temperature"],
            temperature_unit=data.get("temperature_unit", "°C"),
            hours=hours,
            fetched_at=data.get("fetched_at", 0.0),
            temp_low=data.get("temp_low"),
            temp_high=data.get("temp_high"),
            utc_offset_seconds=data.get("utc_offset_seconds"),
            sunrise_today=data.get("sunrise_today", ""),
            sunset_today=data.get("sunset_today", ""),
            sunrise_tomorrow=data.get("sunrise_tomorrow", ""),
            weather_code=data.get("weather_code"),
            uv_index=data.get("uv_index"),
            uv_index_max=data.get("uv_index_max"),
            requested_location=data.get("requested_location", ""),
        )
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
        log.info("Ignoring unreadable weather cache: %s", exc)
        return None


def _save_cache(report: WeatherReport) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        payload = asdict(report)
        payload["cache_version"] = CACHE_VERSION
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError as exc:
        log.info("Could not write weather cache: %s", exc)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _cache_matches(cached: WeatherReport, location: str, fahrenheit: bool) -> bool:
    """
    True when a cached report was produced for the same location and unit the
    caller is now asking for. A mismatch (the user changed their settings)
    must force an immediate refresh rather than serving stale settings.
    """
    unit_ok = ("F" in cached.temperature_unit) == fahrenheit
    wanted = (location.strip() or DEFAULT_WEATHER_LOCATION).strip().lower()
    have = (cached.requested_location or "").strip().lower()
    return unit_ok and wanted == have


def get_weather(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    location: str = "",
    fahrenheit: bool = False,
) -> Optional[WeatherReport]:
    """
    Return a current WeatherReport, or None if no report can be obtained.

    *location* is a place name (e.g. "Ho Chi Minh City"); when blank the
    module's default location is used. An explicit latitude/longitude pair
    overrides the name. The result carries the resolved, human-readable place
    name for display.

    A cached report is reused while it is still fresh (younger than
    REFRESH_INTERVAL_SECONDS) *and* it was produced for the same location and
    temperature unit. Changing either forces an immediate refresh. Once stale,
    a network refresh is attempted; if that fails, the stale cache is returned
    as a best-effort fallback so the wallpaper still shows the last known
    weather instead of nothing.

    This function never raises — network and parsing errors are logged and
    turned into a None (or cached) result so a weather hiccup can never take
    down the wallpaper render.
    """
    cached = _load_cache()
    fresh = (
        cached is not None
        and (time.time() - cached.fetched_at) < REFRESH_INTERVAL_SECONDS
        and (latitude is not None and longitude is not None
             or _cache_matches(cached, location, fahrenheit))
    )
    if fresh:
        return cached

    try:
        report = _fetch_report(latitude, longitude, location, fahrenheit)
        report.requested_location = location.strip() or DEFAULT_WEATHER_LOCATION
        _save_cache(report)
        return report
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError,
            RuntimeError, OSError) as exc:
        log.info("Weather refresh failed (%s); using cache if available.", exc)
        return cached
