import io
import json
import os
import sys
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from skyfield import almanac

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skyfield.api import Loader, wgs84
from skyfield.framelib import itrs
from skyfield.iokit import parse_tle_file

from constants import (
    CLOUDY_THRESHOLD,
    DEFAULT_MAX_CLOUDS,
    DEFAULT_MAX_MAGNITUDE,
    FAVORITES,
    MIN_ELEVATION,
    SUN_MAX_ALT,
    TLE_MAX_AGE_HOURS,
    compass,
)
from geo_calc import format_tz_name, get_timezone_for_latlon
from handler.weather_handler import (
    get_cloud_cover_for_time,
    get_cloud_forecast,
    get_cloud_meta,
)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache_dir = os.path.join(_project_root, "sat_cache")
os.makedirs(_cache_dir, exist_ok=True)
_loader = Loader(_cache_dir)
_lock = threading.Lock()
_pass_cache_dir = os.path.join(_cache_dir, "passes")
os.makedirs(_pass_cache_dir, exist_ok=True)
UNCATEGORIZED_TOKENS = ("R/B", "ROCKET", "DEB", "STAGE", "AKM", "PKM", "APOGEE", "FREGAT", "CENTAUR")

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

    local_json = os.path.join(_project_root, "sat_magnitudes.json")
    if os.path.exists(local_json):
        try:
            with open(local_json, "r", encoding="utf-8") as f:
                for key, value in json.load(f).items():
                    mag_dict[int(key)] = float(value)
        except Exception as e:
            print(f"Error reading sat_magnitudes.json: {e}")

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

    _MAG_CACHE = mag_dict


def get_standard_magnitude(norad: int) -> float:
    """Return standard intrinsic magnitude (default 5.0 for typical satellite)."""
    global _MAG_CACHE
    if not _MAG_CACHE:
        _init_magnitudes()
    return _MAG_CACHE.get(norad, 5.0)


def is_uncertain_object(name: str) -> bool:
    upper = (name or "").upper()
    return any(token in upper for token in UNCATEGORIZED_TOKENS)


def _airmass(altitude_deg: float):
    if altitude_deg is None or altitude_deg <= 0:
        return None
    h = float(altitude_deg)
    return 1.0 / (np.sin(np.radians(h)) + 0.50572 * (h + 6.07995) ** -1.6364)


def calculate_brightness(sat, t_culm, eph, obs_pos, dist_km: float, altitude_deg: float):
    """Lambertian sphere estimate with range, phase angle and atmospheric extinction."""
    result = {
        "est_mag": 5.0,
        "std_mag": None,
        "phase_angle": None,
        "airmass": None,
        "extinction_mag": None,
        "brightness_uncertain": is_uncertain_object(getattr(sat, "name", "")),
    }
    try:
        earth = eph["earth"]
        sun = eph["sun"]

        sat_bary = (earth + sat).at(t_culm).position.km
        v_sun = sun.at(t_culm).position.km - sat_bary
        v_obs = obs_pos.at(t_culm).position.km - sat_bary

        norm_sun = np.linalg.norm(v_sun)
        norm_obs = np.linalg.norm(v_obs)
        if norm_sun == 0 or norm_obs == 0:
            return result

        cos_beta = np.clip(np.dot(v_sun, v_obs) / (norm_sun * norm_obs), -1.0, 1.0)
        beta = np.arccos(cos_beta)
        phi = max((np.sin(beta) + (np.pi - beta) * np.cos(beta)) / np.pi, 1e-4)

        m_std = get_standard_magnitude(sat.model.satnum)
        dist_factor = 5.0 * np.log10(max(dist_km, 1.0) / 1000.0)
        phase_factor = -2.5 * np.log10(phi)
        airmass = _airmass(altitude_deg)
        extinction = 0.0 if airmass is None else 0.2 * max(airmass - 1.0, 0.0)

        result.update(
            {
                "est_mag": round(float(m_std + dist_factor + phase_factor + extinction), 1),
                "std_mag": m_std,
                "phase_angle": round(float(np.degrees(beta)), 1),
                "airmass": None if airmass is None else round(float(airmass), 2),
                "extinction_mag": round(float(extinction), 2),
            }
        )
        return result
    except Exception:
        return result


def classify_twilight(sun_alt: float) -> str:
    if sun_alt >= 0:
        return "Daylight"
    if sun_alt >= -6:
        return "Civil twilight"
    if sun_alt >= -12:
        return "Nautical twilight"
    if sun_alt >= -18:
        return "Astronomical twilight"
    return "Night"


def moon_phase_name(phase_deg: float) -> str:
    if phase_deg < 22.5 or phase_deg >= 337.5:
        return "New moon"
    if phase_deg < 67.5:
        return "Waxing crescent"
    if phase_deg < 112.5:
        return "First quarter"
    if phase_deg < 157.5:
        return "Waxing gibbous"
    if phase_deg < 202.5:
        return "Full moon"
    if phase_deg < 247.5:
        return "Waning gibbous"
    if phase_deg < 292.5:
        return "Last quarter"
    return "Waning crescent"


def compass(deg):
    from constants import compass as _compass
    return _compass(deg)


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


def _cache_key(lat, lon, elevation_m, hours, groups, sats):
    latest = max((s.epoch.utc_datetime() for s in sats), default=datetime.now(timezone.utc))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hour = datetime.now(timezone.utc).strftime("%H")
    group_key = "-".join(sorted(groups))
    return os.path.join(
        _pass_cache_dir,
        f"passes_{lat:+.3f}_{lon:+.3f}_{elevation_m:.0f}m_{day}_{hour}_{latest:%Y%m%d%H%M%S}_{group_key}_{hours}h.json",
    )


def _load_tle_group(group, ts):
    fname = f"{group}.tle"
    url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
    path = _loader.path_to(fname)
    meta_path = path + ".http.json"
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}

    cache_exists = os.path.exists(path)
    cache_fresh = cache_exists and time.time() - os.path.getmtime(path) < TLE_MAX_AGE_HOURS * 3600
    if cache_fresh:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    headers = {"User-Agent": "satellite_tracker"}
    if meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code == 304 and cache_exists:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            resp.raise_for_status()
            text = resp.text
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        meta = {
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "fetched_at": time.time(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        return text
    except Exception as e:
        if cache_exists:
            print(f"TLE refresh failed for '{group}', using cache: {e}")
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        raise


def _serialize_pass(p):
    data = {}
    for key, value in p.items():
        if key in ("sat", "t_culm"):
            continue
        if isinstance(value, datetime):
            data[key] = value.astimezone(timezone.utc).isoformat()
        elif value is None or isinstance(value, (str, bool, int, float)):
            data[key] = value
    return data


def _deserialize_pass(data, sats_by_norad, tz, tz_name):
    p = dict(data)
    for key in ("rise", "culm", "set", "tle_epoch"):
        if key in p:
            value = datetime.fromisoformat(p[key])
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            p[key] = value.astimezone(tz)
    for key in ("rise_utc", "culm_utc", "set_utc", "tle_epoch_utc"):
        if key in p:
            value = datetime.fromisoformat(p[key])
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            p[key] = value.astimezone(timezone.utc)
    p["sat"] = sats_by_norad.get(p.get("norad"))
    p["tz"] = tz
    p["tz_name"] = tz_name
    if "culm" in p:
        p["tz_abbr"] = format_tz_name(p["culm"])
    return p


def get_passes(
    lat,
    lon,
    hours=48,
    groups=("visual", "stations"),
    min_elev=0.0,
    fetch_weather=True,
    tz=None,
    elevation_m=0.0,
    progress=None,
    cancel=None,
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
      - tle_age_days, tle_old: age of the satellite's TLE (old if > 3 days)
      - twilight: twilight class at culmination based on Sun altitude
      - phase_angle, airmass, extinction_mag, brightness_uncertain: brightness model data
      - moon_phase_name, moon_illumination, moon_alt, moon_az, moon_separation, moon_glare: Moon conditions
    """
    if isinstance(groups, str):
        groups = [groups]

    if tz is None:
        tz, tz_name = get_timezone_for_latlon(lat, lon)
    else:
        tz_name = getattr(tz, "key", str(tz))

    def check_cancel():
        if cancel and cancel():
            raise RuntimeError("cancelled")

    def report(pct, text):
        if progress:
            progress(pct, text)

    with _lock:
        sats_map = {}
        ts = _loader.timescale()
        for index, group in enumerate(groups):
            check_cancel()
            report(2 + index * 4, f"Loading TLE group {group}...")
            try:
                text = _load_tle_group(group, ts)
                loaded = parse_tle_file(io.BytesIO(text.encode("utf-8")), ts=ts)
                for s in loaded:
                    if s.model.satnum not in DOCKED_MODULES:
                        sats_map[s.model.satnum] = s
            except Exception as e:
                print(f"Error loading TLE group '{group}': {e}")

        sats = list(sats_map.values())
        if not sats:
            raise RuntimeError(f"No TLE data received for groups {groups}")

        eph = _loader("de421.bsp")

    sats_by_norad = {s.model.satnum: s for s in sats}
    cache_path = _cache_key(lat, lon, elevation_m, hours, groups, sats)
    cached = None
    if min_elev == 0.0 and fetch_weather and os.path.exists(cache_path):
        try:
            report(12, "Loading cached passes...")
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except Exception as e:
            print(f"Pass cache read error: {e}")

    if cached is not None:
        passes = []
        for item in cached:
            p = _deserialize_pass(item, sats_by_norad, tz, tz_name)
            if p.get("sat") is not None:
                passes.append(p)
        report(100, f"{len(passes)} passes loaded from cache")
        return sorted(passes, key=lambda p: (0 if p.get("is_favorite") else 1, p["culm"]))

    check_cancel()
    report(16, "Loading cloud forecast...")
    cloud_forecast = get_cloud_forecast(lat, lon) if fetch_weather else []

    observer = wgs84.latlon(lat, lon, elevation_m=elevation_m)
    earth = eph["earth"]
    sun = eph["sun"]
    moon = eph["moon"]
    obs_pos = earth + observer

    start = datetime.now(timezone.utc)
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(start + timedelta(hours=hours))

    passes = []
    for index, sat in enumerate(sats):
        check_cancel()
        if index % 10 == 0:
            report(20 + int(75 * index / max(len(sats), 1)), f"Computing passes {index}/{len(sats)}...")
        times, events = sat.find_events(observer, t0, t1, altitude_degrees=min_elev)
        cur = {}
        for t, e in zip(times, events):
            alt, az, dist = (sat - observer).at(t).altaz()
            when = t.utc_datetime().astimezone(tz)

            if e == 0:  # rise
                cur = {"rise": when, "rise_az": az.degrees, "rise_utc": t.utc_datetime()}
            elif e == 1:  # culmination
                geo = sat.at(t)
                cur["culm"] = when
                cur["culm_utc"] = t.utc_datetime()
                cur["culm_az"] = az.degrees
                cur["max_alt"] = round(alt.degrees, 1)
                cur["distance_km"] = dist.km
                cur["height_km"] = wgs84.height_of(geo).km
                cur["speed_kms"] = float(np.linalg.norm(geo.velocity.km_per_s))
                cur["t_culm"] = t
            elif e == 2:  # set
                cur["set"] = when
                cur["set_utc"] = t.utc_datetime()
                cur["set_az"] = az.degrees
                if "culm" in cur and "t_culm" in cur:
                    tc = cur["t_culm"]
                    norad = sat.model.satnum
                    cur["sat"] = sat
                    cur["name"] = sat.name
                    cur["norad"] = norad
                    epoch_utc = sat.epoch.utc_datetime()
                    tle_age_days = (datetime.now(timezone.utc) - epoch_utc).total_seconds() / 86400.0
                    cur["tle_epoch"] = epoch_utc.astimezone(tz)
                    cur["tle_epoch_utc"] = epoch_utc
                    cur["tle_age_days"] = round(tle_age_days, 1)
                    cur["tle_old"] = tle_age_days > 3.0
                    cur["tz"] = tz
                    cur["tz_name"] = tz_name
                    cur["tz_abbr"] = format_tz_name(cur["culm"])

                    # Sun position & illumination
                    sun_alt_deg = obs_pos.at(tc).observe(sun).apparent().altaz()[0].degrees
                    sunlit = bool(sat.at(tc).is_sunlit(eph))
                    cur["sun_alt"] = round(sun_alt_deg, 1)
                    cur["sunlit"] = sunlit
                    cur["twilight"] = classify_twilight(cur["sun_alt"])

                    moon_alt, moon_az, _ = obs_pos.at(tc).observe(moon).apparent().altaz()
                    phase_deg = almanac.moon_phase(eph, tc).degrees
                    illumination = (1.0 - np.cos(np.radians(phase_deg))) / 2.0
                    cur["moon_phase_name"] = moon_phase_name(phase_deg)
                    cur["moon_illumination"] = round(illumination * 100)
                    cur["moon_alt"] = round(moon_alt.degrees, 1)
                    cur["moon_az"] = round(moon_az.degrees, 1)
                    sep = np.degrees(
                        np.arccos(
                            np.clip(
                                np.sin(np.radians(cur["max_alt"])) * np.sin(np.radians(moon_alt.degrees))
                                + np.cos(np.radians(cur["max_alt"]))
                                * np.cos(np.radians(moon_alt.degrees))
                                * np.cos(np.radians(cur["culm_az"] - moon_az.degrees)),
                                -1.0,
                                1.0,
                            )
                        )
                    )
                    cur["moon_separation"] = round(float(sep), 1)
                    cur["moon_glare"] = bool(
                        illumination >= 0.5 and moon_alt.degrees > 10 and sep < 60
                    )

                    # Brightness estimation
                    cur.update(
                        calculate_brightness(
                            sat, tc, eph, obs_pos, cur["distance_km"], cur["max_alt"]
                        )
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

    if min_elev == 0.0 and fetch_weather:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump([_serialize_pass(p) for p in passes], f)
        except Exception as e:
            print(f"Pass cache write error: {e}")

    report(100, f"{len(passes)} passes computed")
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









 








