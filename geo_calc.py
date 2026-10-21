from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from constants import TILES_X, TILES_Y

_tf = None


def get_timezone_finder():
    """Lazy loader for TimezoneFinder instance."""
    global _tf
    if _tf is None:
        try:
            from timezonefinder import TimezoneFinder
            _tf = TimezoneFinder()
        except ImportError:
            _tf = False
    return _tf


def tile_to_latlon(row, col):
    """Latitude and longitude of the tile center."""
    lon = -180 + (col + 0.5) / TILES_X * 360
    lat = 90 - (row + 0.5) / TILES_Y * 180
    return lat, lon


def get_timezone_for_latlon(lat: float, lon: float):
    """Derive local timezone (ZoneInfo or timezone object) and timezone name for lat/lon."""
    tf = get_timezone_finder()
    if tf:
        try:
            tz_name = tf.timezone_at(lng=lon, lat=lat)
            if not tz_name:
                tz_name = tf.closest_timezone_at(lng=lon, lat=lat)
            if tz_name:
                try:
                    return ZoneInfo(tz_name), tz_name
                except Exception:
                    pass
        except Exception as e:
            print(f"TimezoneFinder error for ({lat:.2f}, {lon:.2f}): {e}")



    
    offset_hours = int(round(lon / 15.0))
    offset_hours = max(-12, min(14, offset_hours))
    sign = "+" if offset_hours >= 0 else "-"
    name = f"UTC{sign}{abs(offset_hours)}" if offset_hours != 0 else "UTC"
    tz = timezone(timedelta(hours=offset_hours), name=name)
    return tz, name




def format_tz_name(dt: datetime) -> str:
    """Return a clean timezone abbreviation (e.g. 'CEST', 'EDT', 'UTC+2')."""
    if dt is None:
        return ""
    z = dt.strftime("%Z")
    if z and (z.isalpha() or z.startswith("UTC") or z.startswith("GMT")):
        return z
    offset = dt.utcoffset()
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if minutes == 0:
        return f"UTC{sign}{hours}"
    return f"UTC{sign}{hours:02d}:{minutes:02d}"




