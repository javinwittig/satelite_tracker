import time
import requests
from datetime import datetime, timezone

_WEATHER_CACHE = {}
_CACHE_DURATION = 1800  # 30 minutes


def get_cloud_forecast(lat: float, lon: float):
    """Fetch hourly cloud cover forecast (0-100%) for the next 3 days from Open-Meteo.
    Returns a list of (datetime_utc, cloud_cover_int) tuples.
    """
    cache_key = (round(lat, 2), round(lon, 2))
    now = time.time()

    if cache_key in _WEATHER_CACHE:
        cached_time, cached_data = _WEATHER_CACHE[cache_key]
        if now - cached_time < _CACHE_DURATION:
            return cached_data

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.4f}&longitude={lon:.4f}&hourly=cloud_cover&forecast_days=3&timezone=UTC"
    )

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        times_raw = hourly.get("time", [])
        clouds_raw = hourly.get("cloud_cover", [])

        forecast = []
        for t_str, c_val in zip(times_raw, clouds_raw):
            dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
            forecast.append((dt, int(c_val) if c_val is not None else 0))

        _WEATHER_CACHE[cache_key] = (now, forecast)
        return forecast
    except Exception as e:
        print(f"Open-Meteo weather fetch error for ({lat:.2f}, {lon:.2f}): {e}")
        return []


def get_cloud_cover_for_time(forecast, target_dt: datetime):
    """Find the cloud cover percentage (%) closest to the given datetime."""
    if not forecast or target_dt is None:
        return None

    if target_dt.tzinfo is None:
        target_utc = target_dt.replace(tzinfo=timezone.utc)
    else:
        target_utc = target_dt.astimezone(timezone.utc)

    closest = min(forecast, key=lambda item: abs((item[0] - target_utc).total_seconds()))
    # Ensure it's within a reasonable window (e.g. 3 hours)
    if abs((closest[0] - target_utc).total_seconds()) <= 3 * 3600:
        return closest[1]
    return None


def get_cloud_meta(cloud_pct):
    """Return icon, descriptive text and suggested UI color for cloud cover percentage."""
    if cloud_pct is None:
        return "❓", "--%", "No data", "#888888"
    if cloud_pct < 25:
        return "☀️", f"{cloud_pct}%", "Clear (best visibility)", "#27ae60"
    elif cloud_pct < 70:
        return "⛅", f"{cloud_pct}%", "Partly cloudy", "#d35400"
    else:
        return "☁️", f"{cloud_pct}%", "Overcast (limited)", "#7f8c8d"

