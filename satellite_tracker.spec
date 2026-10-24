# PyInstaller build spec: `pyinstaller satellite_tracker.spec`
# Windows/Linux -> single executable in dist/, macOS -> dist/SatelliteTracker.app
import sys
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("map.png", "."),
    ("icon.ico", "."),
    ("icon.png", "."),
    ("earth_texture.jpg", "."),
    ("sat_magnitudes.json", "."),
]
for pkg in ("skyfield", "timezonefinder", "timezonefinder_data", "tzdata"):
    datas += collect_data_files(pkg)

a = Analysis(
    ["main.py"],
    datas=datas,
    hiddenimports=["timezonefinder_data"],
    excludes=["tkinter", "pandas", "PyQt5", "PySide6"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SatelliteTracker",
              console=False, icon="icon.png")
    coll = COLLECT(exe, a.binaries, a.datas, name="SatelliteTracker")
    app = BUNDLE(coll, name="SatelliteTracker.app", icon="icon.png",
                 bundle_identifier="com.javinwittig.satellitetracker",
                 info_plist={"NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="SatelliteTracker",
              console=False, icon="icon.ico")
