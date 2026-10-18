import os

import numpy as np
import matplotlib.image as mpimg
import requests
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from handler.satellite_handler import get_track

R = 6371.0  # Earth radius in km
N_LAT, N_LON = 180, 360  # mesh grid (higher = nicer but slower to rotate)

# NASA Blue Marble (topo + bathymetry), equirectangular: lon -180..180 left->right, lat +90..-90 top->bottom
_TEX_URL = "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/world.topo.bathy.200412.3x5400x2700.jpg"
_TEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "earth_blue_marble.jpg")
_TEX_FALLBACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "earth_texture.jpg")


def sph(lat, lon, r=R):
    la, lo = np.radians(lat), np.radians(lon)
    return np.array([r * np.cos(la) * np.cos(lo), r * np.cos(la) * np.sin(lo), r * np.sin(la)])


def _cam_dir(lat, lon):
    """Unit vector from earth center towards the camera (same convention as sph)."""
    return sph(lat, lon) / R


def _is_behind(pts, cam):
    """True where a point is hidden behind the earth disc from the camera's view."""
    d = pts @ cam
    radial_sq = np.einsum("ij,ij->i", pts, pts) - d * d
    return (d < 0) & (radial_sq < R * R)


def _plot_split(ax, pts, cam, front, back):
    """Plot a polyline, dimming the segments hidden behind the earth."""
    occ = _is_behind(np.asarray(pts, float), cam)
    cuts = np.flatnonzero(np.diff(occ)) + 1
    for s, e in zip(np.r_[0, cuts], np.r_[cuts, len(occ)]):
        ax.plot(pts[s:e, 0], pts[s:e, 1], pts[s:e, 2], **(back if occ[s] else front))


def _plot_glow(ax, pts, cam, core, glows, back):
    """Plot a polyline with a glow effect: wide dim layers + bright core, dimmed behind the earth."""
    occ = _is_behind(np.asarray(pts, float), cam)
    cuts = np.flatnonzero(np.diff(occ)) + 1
    for s, e in zip(np.r_[0, cuts], np.r_[cuts, len(occ)]):
        seg = pts[s:e]
        if occ[s]:
            ax.plot(seg[:, 0], seg[:, 1], seg[:, 2], **back)
        else:
            for g in glows:
                ax.plot(seg[:, 0], seg[:, 1], seg[:, 2], **g)
            ax.plot(seg[:, 0], seg[:, 1], seg[:, 2], **core)


def _ground_track(pts):
    """Sub-satellite points: project the track onto the earth surface."""
    pts = np.asarray(pts, float)
    n = np.linalg.norm(pts, axis=-1, keepdims=True)
    return pts / n * (R * 1.002)


class _Sig(QObject):
    done = pyqtSignal(object)
    fail = pyqtSignal(str)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.sig = _Sig()
        self.setAutoDelete(False)

    def run(self):
        try:
            self.sig.done.emit(self.fn())
        except Exception as e:
            self.sig.fail.emit(str(e))


class SatView3D(QWidget):
    def __init__(self, p, lat, lon):
        super().__init__()
        self.p, self.lat, self.lon = p, lat, lon
        self.setWindowTitle(f"3D: {p['name']}")
        self.resize(800, 800)

        self.track = get_track(p)

        self.fig = Figure(figsize=(8, 8), facecolor="black")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.status = QLabel("Lade Erdtextur...")

        layout = QVBoxLayout(self)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        layout.addWidget(self.status)

        self.draw_scene(None)

        # load the texture in the background, redraw when ready
        self.job = _Job(self._load_texture)
        self.job.sig.done.connect(self.on_texture)
        self.job.sig.fail.connect(lambda m: self.status.setText(f"Keine Textur: {m}"))
        QThreadPool.globalInstance().start(self.job)

    def _load_texture(self):
        if not os.path.exists(_TEX_PATH):
            try:
                r = requests.get(_TEX_URL, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                with open(_TEX_PATH, "wb") as f:
                    f.write(r.content)
            except Exception:
                if not os.path.exists(_TEX_FALLBACK):
                    raise
                path = _TEX_FALLBACK
            else:
                path = _TEX_PATH
        else:
            path = _TEX_PATH

        img = mpimg.imread(path)
        if img.ndim == 2:
            img = np.stack([img] * 3, axis=-1)
        img = img[..., :3]
        scale = 255.0 if img.dtype == np.uint8 else 1.0
        img = img.astype(np.float32) / scale
        # average-pool the texture onto the mesh grid for smooth, non-pixelated surfaces
        if img.shape[0] % N_LAT == 0 and img.shape[1] % N_LON == 0:
            ry, rx = img.shape[0] // N_LAT, img.shape[1] // N_LON
            img = img.reshape(N_LAT, ry, N_LON, rx, 3).mean(axis=(1, 3))
        return img

    def on_texture(self, img):
        self.status.setText("Maus ziehen = drehen, Mausrad/Rechtsklick = zoomen")
        self.draw_scene(img)

    def draw_scene(self, texture):
        ax = self.ax
        ax.clear()
        ax.set_axis_off()
        ax.set_facecolor("black")
        # matplotlib sorts 3D collections by depth but draws plain Line3D objects
        # below the surface, so we control the painter's order manually
        ax.computed_zorder = False

        # Earth
        lats = np.radians(np.linspace(90, -90, N_LAT))
        lons = np.radians(np.linspace(-180, 180, N_LON))
        lon_g, lat_g = np.meshgrid(lons, lats)
        x = R * np.cos(lat_g) * np.cos(lon_g)
        y = R * np.cos(lat_g) * np.sin(lon_g)
        z = R * np.sin(lat_g)

        if texture is not None:
            if texture.shape[:2] == (N_LAT, N_LON):
                tex = texture
            else:  # nearest-neighbour resample for non-poolable sizes
                h, w = texture.shape[:2]
                rows = np.linspace(0, h - 1, N_LAT).astype(int)
                cols = np.linspace(0, w - 1, N_LON).astype(int)
                tex = texture[np.ix_(rows, cols)]
            ax.plot_surface(x, y, z, facecolors=tex, zorder=1,
                            rstride=1, cstride=1, shade=False, linewidth=0, antialiased=False)
        else:
            ax.plot_surface(x, y, z, color="#1f4e79", zorder=1, rstride=2, cstride=2, shade=True, linewidth=0)

        # orbit, pass, ground tracks, satellite, observer
        cam = _cam_dir(self.lat, self.lon)
        o, pa, c = self.track["orbit"], self.track["pass"], self.track["culm"]

        _plot_split(ax, o, cam,
                    dict(color="#ff5555", lw=1.6, zorder=3, label="Bahn"),
                    dict(color="#ff5555", lw=1.0, alpha=0.22, zorder=2))
        _plot_split(ax, _ground_track(o), cam,
                    dict(color="#ff8866", lw=0.9, alpha=0.55, zorder=3),
                    dict(color="#ff8866", lw=0.9, alpha=0.12, zorder=2))
        # pass: glow layers + bright core, only in-front segments
        _plot_glow(ax, pa, cam,
                   dict(color="yellow", lw=4.5, zorder=3, label="Überflug"),
                   [dict(color="#ffab00", lw=10, alpha=0.22, zorder=3),
                    dict(color="#ffd54f", lw=7, alpha=0.4, zorder=3)],
                   dict(color="yellow", lw=2.0, alpha=0.25, zorder=2))

        # dots along the pass (only where visible)
        vis = ~_is_behind(pa, cam)
        ax.scatter(pa[vis, 0], pa[vis, 1], pa[vis, 2], color="#ff8f00", s=28, zorder=4,
                   edgecolors="black", linewidths=0.5, depthshade=False, label="Zeitverlauf")

        # ground tracks
        _plot_split(ax, _ground_track(pa), cam,
                    dict(color="#00e5ff", lw=2.2, zorder=3, label="Subsatellitenpunkt"),
                    dict(color="#00e5ff", lw=1.2, alpha=0.2, zorder=2))

        # connector: ground point -> satellite at culmination
        _plot_split(ax, np.vstack([_ground_track(c), c]), cam,
                    dict(color="white", lw=1.2, ls=":", alpha=0.9, zorder=3),
                    dict(color="white", lw=1.0, ls=":", alpha=0.25, zorder=2))
        ax.scatter(*c, color="white", s=140, zorder=4, edgecolors="black", linewidths=0.8,
                   depthshade=False, label="Höchststand")
        ax.scatter(*sph(self.lat, self.lon, R * 1.005), color="lime", s=80, zorder=4,
                   depthshade=False, label="Tile")

        lim = np.abs(o).max()
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_zlim(-lim, lim)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=self.lat, azim=self.lon)  # camera looks at the tile
        ax.legend(loc="upper left", facecolor="black", labelcolor="white")
        self.canvas.draw_idle()