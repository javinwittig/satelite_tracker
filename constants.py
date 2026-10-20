import os
import os
from dotenv import load_dotenv

load_dotenv()

NASA_API_KEY = os.environ["NASA_API_KEY"]
RESOLUTION = 50

TILES_X = 99
TILES_Y = 50




MIN_ELEVATION = 10.0        # degrees
SUN_MAX_ALT = -6.0          # degrees, civil twilight
TLE_MAX_AGE_HOURS = 6
FAVORITES = {25544: "ISS", 20580: "Hubble", 48274: "Tiangong"}
CACHE_DIR = "cache"







