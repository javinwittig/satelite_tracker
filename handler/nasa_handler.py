import requests
from datetime import datetime, timedelta, timezone
import os
import requests
from datetime import datetime, timedelta, timezone
import math



def get_img(lat, lon, name, d=4.0):
    """
    Downloads an undistorted, gap-free satellite image around (lat, lon).
    - Uses VIIRS (no orbital swath gaps like MODIS).
    - Adjusts longitude span by 1 / cos(lat) to maintain real-world 1:1 aspect ratio.
    - Clamps boundaries to prevent black borders from out-of-bounds coordinates.
    """
    # Adjust lon span for latitude curvature so ground distance is roughly square
    rad = math.radians(lat)
    cos_lat = max(math.cos(rad), 0.15)  # avoid division by zero near poles
    d_lat = d
    d_lon = d / cos_lat
    # Clamp to valid geographical ranges
    lat_min = max(-89.9, lat - d_lat)
    lat_max = min(89.9, lat + d_lat)
    lon_min = max(-180.0, lon - d_lon)
    lon_max = min(180.0, lon + d_lon)
    day = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    params = {
        "REQUEST": "GetSnapshot",
        "LAYERS": "VIIRS_SNPP_CorrectedReflectance_TrueColor",
        "CRS": "EPSG:4326",
        "TIME": day,
        "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max}",
        "FORMAT": "image/jpeg",
        "WIDTH": 1024,
        "HEIGHT": 1024,
    }
    r = requests.get("https://wvs.earthdata.nasa.gov/api/v1/snapshot", params=params, timeout=60)
    print(r.status_code, r.headers.get("content-type"))
    if r.ok and r.headers.get("content-type", "").startswith("image"):
        with open(name, "wb") as f:
            f.write(r.content)
        print("Bild gespeichert:", name)
    else:
        print(r.text[:500])