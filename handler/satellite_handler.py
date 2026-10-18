import os
import threading
from datetime import datetime, timedelta, timezone
from skyfield.framelib import itrs
import numpy as np
from skyfield.api import Loader, wgs84

_cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sat_cache")
_loader = Loader(_cache_dir)
_lock = threading.Lock()

_DIRS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]


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

def get_passes(lat, lon, hours=24, group="stations", min_elev=10.0):
    """Return a list of dicts (one per pass), sorted by culmination time."""
    fname = f"{group}.tle"
    url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"

    with _lock:
        reload = not os.path.exists(_loader.path_to(fname)) or _loader.days_old(fname) > 0.5
        sats = _loader.tle_file(url, reload=reload, filename=fname)
        ts = _loader.timescale()

    if not sats:
        try:
            os.remove(_loader.path_to(fname))
        except OSError:
            pass
        raise RuntimeError(f"Keine TLE-Daten für Gruppe '{group}' erhalten")

    observer = wgs84.latlon(lat, lon)
    start = datetime.now(timezone.utc)
    t0, t1 = ts.from_datetime(start), ts.from_datetime(start + timedelta(hours=hours))

    passes = []
    for sat in sats:
        times, events = sat.find_events(observer, t0, t1, altitude_degrees=min_elev)
        cur = {}
        for t, e in zip(times, events):
            alt, az, dist = (sat - observer).at(t).altaz()
            when = t.utc_datetime().astimezone()

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
            elif e == 2:  # set
                cur["set"] = when
                cur["set_az"] = az.degrees
                if "culm" in cur:
                    cur["sat"] = sat  # <- needed by get_track()
                    cur["name"] = sat.name
                    cur["norad"] = sat.model.satnum
                    cur["tle_epoch"] = sat.epoch.utc_datetime().astimezone()
                    passes.append(cur)
                cur = {}

    return sorted(passes, key=lambda p: p["culm"])


if __name__ == "__main__":
    for p in get_passes(48.39, 10.01, hours=48, group="stations", min_elev=0.0):
        print(f"{p['culm']:%d.%m. %H:%M} | {p['name']} | max. {p['max_alt']}°")

























