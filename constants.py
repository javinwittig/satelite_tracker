import os
import sys
from dotenv import load_dotenv

# Read-only bundled files (map.png, icon, ...) and a writable folder for caches.
# In a PyInstaller build the bundle is read-only/temporary, so data goes to the user's home.
if getattr(sys, "frozen", False):
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    DATA_DIR = os.path.join(os.path.expanduser("~"), ".satellite_tracker")
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = RESOURCE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

load_dotenv(os.path.join(DATA_DIR, ".env"))

NASA_API_KEY = os.environ.get("NASA_API_KEY", "")
RESOLUTION = 50

TILES_X = 99
TILES_Y = 50

MIN_ELEVATION = 10.0
SUN_MAX_ALT = -6.0
TLE_MAX_AGE_HOURS = 6
FAVORITES = {25544: "ISS", 20580: "Hubble", 48274: "Tiangong"}
CACHE_DIR = os.path.join(DATA_DIR, "cache")

DIRECTIONS = {
    "en": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
    "de": ["N", "NO", "O", "SO", "S", "SW", "W", "NW"],
}
DEFAULT_LANG = "en"

def compass(deg: float, lang: str = DEFAULT_LANG) -> str:
    dirs = DIRECTIONS.get(lang, DIRECTIONS["en"])
    idx = int((deg + 22.5) % 360 // 45)
    return dirs[idx]

DEFAULT_MAX_MAGNITUDE = 3.5
DEFAULT_MAX_CLOUDS = 50
CLOUDY_THRESHOLD = 40
