import io
import os
import sys
import threading
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skyfield.api import Loader, wgs84
from skyfield.framelib import itrs

from constants import (
    CLOUDY_THRESHOLD,
    DEFAULT_MAX_CLOUDS,
    DEFAULT_MAX_MAGNITUDE,
    FAVORITES,
    MIN_ELEVATION,
    SUN_MAX_ALT,
    compass,
)
from geo_calc import format_tz_name, get_timezone_for_latlon
from handler.weather_handler import (
    get_cloud_cover_for_time,
    get_cloud_forecast,
    get_cloud_meta,
)

_cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sat_cache")
os.makedirs(_cache_dir, exist_ok=True)
_loader = Loader(_cache_dir)
_lock = threading.Lock()

# Space station docked modules that share orbits with main stations
DOCKED_MODULES = {
    36086,  # Poisk (docked to ISS)
    49044,  # Nauka (docked to ISS)
    53239,  # Wentian (docked to Tiangong)
    54216,  # Mengtian (docked to Tiangong)
}

# (Compass directions are defined in constants.py with multi-language support)

# Standard intrinsic magnitude (at 1000 km, 50% illumination)
KNOWN_STANDARD_MAGS = {
    25544: -2.5,  # ISS
    20580: 1.5,   # Hubble Space Telescope (HST)
    48274: 0.0,   # Tiangong Core Module (CSS Tianhe)
    53239: 1.0,   # Wentian
    54216: 1.0,   # Mengtian
}

_MAG_CACHE = {}


def _init_magnitudes():
    """Load standard magnitudes from quicksat.mag or download if needed."""
    global _MAG_CACHE
    mag_file = os.path.join(_cache_dir, "quicksat.mag")

    if not os.path.exists(mag_file):
        try:
            url = "https://www.mmccants.org/programs/qsmag.zip"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                zf = zipfile.ZipFile(io.BytesIO(resp.read()))
                for name in zf.namelist():
                    if name.lower().endswith(".mag") or "quicksat" in name.lower():
                        with open(mag_file, "wb") as f_out:
                            f_out.write(zf.read(name))
                        break
        except Exception as e:
            print(f"Standard magnitude file download failed: {e}")

    mag_dict = dict(KNOWN_STANDARD_MAGS)
    if os.path.exists(mag_file):
        try:
            with open(mag_file, "r", encoding="latin-1", errors="ignore") as f:
                for line in f:
                    if len(line) >= 38:
                        try:
                            satnum = int(line[0:5].strip())
                            mag_str = line[33:37].strip()
                            if mag_str and satnum not in mag_dict:
                                mag_dict[satnum] = float(mag_str)
                        except ValueError:
                            pass
        except Exception as e:
            print(f"Error reading quicksat.mag: {e}")

    # Ensure known favorites are always exact
    mag_dict.update(KNOWN_STANDARD_MAGS)
    _MAG_CACHE = mag_dict


def get_standard_magnitude(norad: int) -> float:
    """Return standard intrinsic magnitude (default 5.0 for typical satellite)."""
    global _MAG_CACHE
    if not _MAG_CACHE:
        _init_magnitudes()
    return _MAG_CACHE.get(norad, 5.0)


def calculate_magnitude(sat, t_culm, eph, obs_pos, dist_km: float, norad: int) -> float:
    """Calculate estimated visual magnitude at culmination using the Lambertian sphere model:
    m = m_std + 5 * log10(R / 1000) - 2.5 * log10(Phi(beta))
    """
    try:
        earth = eph["earth"]
        sun = eph["sun"]

        sat_bary = (earth + sat).at(t_culm).position.km
        v_sun = sun.at(t_culm).position.km - sat_bary
        v_obs = obs_pos.at(t_culm).position.km - sat_bary

        norm_sun = np.linalg.norm(v_sun)
        norm_obs = np.linalg.norm(v_obs)
        if norm_sun == 0 or norm_obs == 0:
            return 5.0

        cos_beta = np.clip(np.dot(v_sun, v_obs) / (norm_sun * norm_obs), -1.0, 1.0)
        beta = np.arccos(cos_beta)
        phi = max((np.sin(beta) + (np.pi - beta) * np.cos(beta)) / np.pi, 1e-4)

        m_std = get_standard_magnitude(norad)
        dist_factor = 5.0 * np.log10(max(dist_km, 1.0) / 1000.0)
        phase_factor = -2.5 * np.log10(phi)
        return round(float(m_std + dist_factor + phase_factor), 1)
    except Exception as e:
        return 5.0


def compass(deg):
    return _DIRS[int((deg + 22.5) % 360 // 45)]


def get_track(p, n=400):
    """Earth-fixed (ITRS) xyz positions in km: one full orbit around the culmination, plus the pass itself."""
    ts = _loader.timescale()
    sat = p["sat"]

    period_min = 2 * np.pi / sat.model.no_kozai  # no_kozai is in rad/min
    day = period_min / 1440
    t_c = ts.from_datetime(p["culm"])
    t_orbit = ts.tt_jd(t_c.tt + np.linspace(-0.5, 0.5, n) * day)

    start = p.get("rise", p["culm"] - timedelta(minutes=5))
    t_a, t_b = ts.from_datetime(start), ts.from_datetime(p["set"])
    t_pass = ts.tt_jd(np.linspace(t_a.tt, t_b.tt, 60))

    def xyz(t):
        return sat.at(t).frame_xyz(itrs).km.T

    return {"orbit": xyz(t_orbit), "pass": xyz(t_pass), "culm": xyz(t_c)}


def get_passes(
    lat,
    lon,
    hours=48,
    groups=("visual", "stations"),
    min_elev=0.0,
    fetch_weather=True,
    tz=None,
):
    """Return a list of dicts (one per pass) for the given coordinates, sorted with favorites pinned to top.

    Each pass dictionary contains:
      - sat: skyfield EarthSatellite
      - name: satellite name
      - norad: NORAD catalog ID
      - rise, culm, set: datetime objects (converted to local timezone)
      - tz, tz_name, tz_abbr: local timezone and abbreviation (e.g. CEST, EDT)
      - rise_az, culm_az, set_az: azimuth in degrees
      - max_alt: maximum elevation in degrees
      - distance_km, height_km, speed_kms: orbital geometry
      - sun_alt: Sun elevation from observer at culmination
      - sunlit: True if satellite is illuminated by Sun (not in Earth's shadow)
      - est_mag: estimated apparent visual magnitude
      - is_geom_visible: True if max_alt >= 10.0, sun_alt < 0.0, and sunlit is True
      - is_weather_visible: True if is_geom_visible and cloud_cover < 40%
      - is_naked_eye_mag: True if est_mag <= 3.5
      - is_visible: True if geometrically visible, naked-eye magnitude, and cloud cover < 50%
      - invisibility_reason: description why pass is not visible
      - is_favorite: True if ISS, Hubble, or Tiangong
      - favorite_name: friendly name (e.g. "ISS", "Hubble", "Tiangong")
      - cloud_cover: cloud cover % (0-100) from Open-Meteo
      - cloud_icon, cloud_pct_str, cloud_desc, cloud_color: cloud metadata
    """
    if isinstance(groups, str):
        groups = [groups]

    if tz is None:
        tz, tz_name = get_timezone_for_latlon(lat, lon)
    else:
        tz_name = getattr(tz, "key", str(tz))

    with _lock:
        sats_map = {}
        for group in groups:
            fname = f"{group}.tle"
            url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
            reload = not os.path.exists(_loader.path_to(fname)) or _loader.days_old(fname) > 0.5
            try:
                loaded = _loader.tle_file(url, reload=reload, filename=fname)
                for s in loaded:
                    if s.model.satnum not in DOCKED_MODULES:
                        sats_map[s.model.satnum] = s
            except Exception as e:
                print(f"Error loading TLE group '{group}': {e}")

        sats = list(sats_map.values())
        if not sats:
            raise RuntimeError(f"No TLE data received for groups {groups}")

        ts = _loader.timescale()
        eph = _loader("de421.bsp")

    # Cloud forecast
    cloud_forecast = get_cloud_forecast(lat, lon) if fetch_weather else []

    observer = wgs84.latlon(lat, lon)
    earth = eph["earth"]
    sun = eph["sun"]
    obs_pos = earth + observer

    start = datetime.now(timezone.utc)
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(start + timedelta(hours=hours))

    passes = []
    for sat in sats:
        times, events = sat.find_events(observer, t0, t1, altitude_degrees=min_elev)
        cur = {}
        for t, e in zip(times, events):
            alt, az, dist = (sat - observer).at(t).altaz()
            when = t.utc_datetime().astimezone(tz)

            if e == 0:  # rise
                cur = {"rise": when, "rise_az": az.degrees}
            elif e == 1:  # culmination
                geo = sat.at(t)
                cur["culm"] = when
                cur["culm_az"] = az.degrees
                cur["max_alt"] = round(alt.degrees, 1)
                cur["distance_km"] = dist.km
                cur["height_km"] = wgs84.height_of(geo).km
                cur["speed_kms"] = float(np.linalg.norm(geo.velocity.km_per_s))
                cur["t_culm"] = t
            elif e == 2:  # set
                cur["set"] = when
                cur["set_az"] = az.degrees
                if "culm" in cur and "t_culm" in cur:
                    tc = cur["t_culm"]
                    norad = sat.model.satnum
                    cur["sat"] = sat
                    cur["name"] = sat.name
                    cur["norad"] = norad
                    cur["tle_epoch"] = sat.epoch.utc_datetime().astimezone(tz)
                    cur["tz"] = tz
                    cur["tz_name"] = tz_name
                    cur["tz_abbr"] = format_tz_name(cur["culm"])

                    # Sun position & illumination
                    sun_alt_deg = obs_pos.at(tc).observe(sun).apparent().altaz()[0].degrees
                    sunlit = bool(sat.at(tc).is_sunlit(eph))
                    cur["sun_alt"] = round(sun_alt_deg, 1)
                    cur["sunlit"] = sunlit

                    # Brightness estimation
                    cur["est_mag"] = calculate_magnitude(
                        sat, tc, eph, obs_pos, cur["distance_km"], norad
                    )

                    # Favorites: ISS (25544), Hubble (20580), Tiangong (48274)
                    is_fav = norad in FAVORITES
                    fav_name = FAVORITES.get(norad)

                    cur["is_favorite"] = is_fav
                    cur["favorite_name"] = fav_name

                    # Cloud forecast from Open-Meteo
                    cloud_pct = get_cloud_cover_for_time(cloud_forecast, cur["culm"])
                    cur["cloud_cover"] = cloud_pct
                    c_icon, c_str, c_desc, c_col = get_cloud_meta(cloud_pct)
                    cur["cloud_icon"] = c_icon
                    cur["cloud_pct_str"] = c_str
                    cur["cloud_desc"] = c_desc
                    cur["cloud_color"] = c_col

                    # Two classifications:
                    # 1. Geometrically visible:
                    #    - Minimum elevation >= 10.0°
                    #    - Sun below horizon (sun_alt < 0.0°)
                    #    - Satellite illuminated by sun (sunlit == True)
                    is_geom_vis = (cur["max_alt"] >= MIN_ELEVATION) and (cur["sun_alt"] < 0.0) and cur["sunlit"]
                    cur["is_geom_visible"] = is_geom_vis

                    # 2. Weather visible:
                    #    - Geometrically visible AND clouds < 40%
                    is_weather_vis = is_geom_vis and (cloud_pct is None or cloud_pct < CLOUDY_THRESHOLD)
                    cur["is_weather_visible"] = is_weather_vis

                    # Naked-eye magnitude limit (<= 3.5 mag)
                    is_naked_eye = (cur["est_mag"] is not None and cur["est_mag"] <= DEFAULT_MAX_MAGNITUDE)
                    cur["is_naked_eye_mag"] = is_naked_eye

                    # Combined visibility (geometrically visible, clouds < 50%, and mag <= 3.5)
                    is_vis = is_geom_vis and is_naked_eye and (cloud_pct is None or cloud_pct < DEFAULT_MAX_CLOUDS)
                    cur["is_visible"] = is_vis

                    # Explanatory reasons when not visible
                    reasons = []
                    if cur["max_alt"] < MIN_ELEVATION:
                        reasons.append(f"Too low ({cur['max_alt']}° < {MIN_ELEVATION:.0f}°)")
                    if cur["sun_alt"] >= 0.0:
                        reasons.append(f"Daytime pass (Sun {cur['sun_alt']:+.1f}°)")
                    if not cur["sunlit"]:
                        reasons.append("In Earth's shadow (dimmed)")
                    if is_geom_vis:
                        if not is_naked_eye:
                            reasons.append(f"Faint magnitude (Mag {cur['est_mag']:+.1f} > {DEFAULT_MAX_MAGNITUDE})")
                        if cloud_pct is not None and cloud_pct >= DEFAULT_MAX_CLOUDS:
                            reasons.append(f"Cloudy ({cloud_pct}% ≥ {DEFAULT_MAX_CLOUDS}%)")
                    cur["invisibility_reason"] = ", ".join(reasons) if reasons else "Fully visible"

                    del cur["t_culm"]
                    passes.append(cur)
                cur = {}

    # Sort with favorites ALWAYS pinned to top, followed by chronological culmination
    return sorted(passes, key=lambda p: (0 if p.get("is_favorite") else 1, p["culm"]))


if __name__ == "__main__":
    passes = get_passes(48.39, 10.01, hours=48)
    visible_passes = [p for p in passes if p["is_visible"]]
    print(f"Total passes: {len(passes)}, Visible: {len(visible_passes)}")
    for p in visible_passes[:10]:
        fav = f"[{p['favorite_name']}] " if p['is_favorite'] else ""
        print(
            f"{p['culm']:%d.%m. %H:%M} | {fav}{p['name']} | Mag {p['est_mag']:+.1f} | "
            f"max {p['max_alt']}° | Sun {p['sun_alt']}° | Clouds {p['cloud_pct_str']}"
        )









 








