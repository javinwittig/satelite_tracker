import os, time, requests
from constants import CACHE_DIR, TLE_MAX_AGE_HOURS

URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle"

def load_tles():
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "visual.tle")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < TLE_MAX_AGE_HOURS * 3600:
        return open(path, encoding="utf-8").read()
    text = requests.get(URL, timeout=15).text
    open(path, "w", encoding="utf-8").write(text)
    return text