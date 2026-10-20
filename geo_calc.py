from constants import *

def tile_to_latlon(row, col):
    """Latitude and longitude of the tile center."""
    lon = -180 + (col + 0.5) / TILES_X * 360
    lat = 90 - (row + 0.5) / TILES_Y * 180
    return lat, lon





