import os
from dotenv import load_dotenv

load_dotenv()

NASA_API_KEY = os.environ.get("NASA_API_KEY", "")
RESOLUTION = 50

TILES_X = 99
TILES_Y = 50

MIN_ELEVATION = 10.0        # degrees
SUN_MAX_ALT = -6.0          # degrees, civil twilight
TLE_MAX_AGE_HOURS = 6
FAVORITES = {25544: "ISS", 20580: "Hubble", 48274: "Tiangong"}
CACHE_DIR = "cache"

# Compass directions with language support
DIRECTIONS = {
    "en": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
    "de": ["N", "NO", "O", "SO", "S", "SW", "W", "NW"],
}
DEFAULT_LANG = "en"

def compass(deg: float, lang: str = DEFAULT_LANG) -> str:
    """Convert azimuth degrees (0-360) to compass direction string in the selected language."""
    dirs = DIRECTIONS.get(lang, DIRECTIONS["en"])
    idx = int((deg + 22.5) % 360 // 45)
    return dirs[idx]

# Visibility criteria constants
DEFAULT_MAX_MAGNITUDE = 3.5    # naked-eye threshold
DEFAULT_MAX_CLOUDS = 50        # default cloud cover threshold for 'Only visible' filter (%)
CLOUDY_THRESHOLD = 40          # threshold for 'Visible despite clouds (< 40%)'



