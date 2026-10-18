import os
import os
from dotenv import load_dotenv

load_dotenv()

NASA_API_KEY = os.environ["NASA_API_KEY"]
RESOLUTION = 50

TILES_X = 99
TILES_Y = 50