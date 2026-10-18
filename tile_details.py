import os

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from constants import RESOLUTION
from geo_calc import tile_to_latlon
from handler.nasa_handler import get_img
from handler.satellite_handler import compass, get_passes
from sat_view_3d import SatView3D


class LoaderSignals(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal()


class ImageLoader(QRunnable):
    """Worker thread: downloads the image if it is not cached."""

    def __init__(self, lat, lon, path):
        super().__init__()
        self.lat, self.lon, self.path = lat, lon, path
        self.signals = LoaderSignals()
        self.setAutoDelete(False)

    def run(self):
        try:
            if not os.path.exists(self.path):
                get_img(self.lat, self.lon, self.path)
            if os.path.exists(self.path):
                self.signals.finished.emit(self.path)
            else:
                self.signals.failed.emit()
        except Exception as e:
            print("Download error:", e)
            self.signals.failed.emit()


class SatSignals(QObject):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class SatLoader(QRunnable):
    """Worker thread: computes satellite passes over the tile."""

    def __init__(self, lat, lon):
        super().__init__()
        self.lat, self.lon = lat, lon
        self.signals = SatSignals()
        self.setAutoDelete(False)

    def run(self):
        try:
            passes = get_passes(
                self.lat, self.lon,
                hours=48,
                group="stations",
                min_elev=0.0,
            )
            print(f"GUI: {len(passes)} passes for {self.lat:.2f}, {self.lon:.2f}")
            self.signals.finished.emit(passes)
        except Exception as e:
            print("Satellite error:", e)
            self.signals.failed.emit(str(e))


class TileDetails(QWidget):
    def __init__(self, x, y):
        super().__init__()
        layout = QVBoxLayout()

        lat, lon = tile_to_latlon(x, y)
        self.lat, self.lon = lat, lon
        self.selected_pass = None
        self.view3d = None

        self.label = QLabel(f"Tile ({x}, {y}) - Lat/Lon: {lat:.4f}, {lon:.4f}")

        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(base, "map_tiles"), exist_ok=True)
        path = os.path.join(base, "map_tiles", f"map_{x * RESOLUTION}_{y * RESOLUTION}.jpg")

        # Image placeholder
        self.image_label = QLabel("Lade Bild...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(400, 400)

        # Satellite list + details
        self.sat_title = QLabel("Satelliten-Überflüge (nächste 48 h):")
        self.sat_list = QListWidget()
        self.sat_list.addItem("Lade Satelliten...")
        self.sat_list.itemClicked.connect(self.show_details)

        self.details_label = QLabel("Klicke auf einen Überflug für Details.")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.btn_3d = QPushButton("3D-Ansicht")
        self.btn_3d.setEnabled(False)
        self.btn_3d.clicked.connect(self.open_3d)

        layout.addWidget(self.label)
        layout.addWidget(self.image_label)
        layout.addWidget(self.sat_title)
        layout.addWidget(self.sat_list)
        layout.addWidget(self.details_label)
        layout.addWidget(self.btn_3d)
        self.setLayout(layout)

        # Start both background jobs
        self.loader = ImageLoader(lat, lon, path)
        self.loader.signals.finished.connect(self.show_image)
        self.loader.signals.failed.connect(self.show_error)
        QThreadPool.globalInstance().start(self.loader)

        self.sat_loader = SatLoader(lat, lon)
        self.sat_loader.signals.finished.connect(self.show_satellites)
        self.sat_loader.signals.failed.connect(self.show_sat_error)
        QThreadPool.globalInstance().start(self.sat_loader)

    # ---------- image ----------
    def show_image(self, path):
        pixmap = QPixmap(path)
        self.image_label.setPixmap(
            pixmap.scaled(
                400, 400,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def show_error(self):
        self.image_label.setText("Bild konnte nicht geladen werden.")

    # ---------- satellites ----------
    def show_satellites(self, passes):
        self.sat_list.clear()
        if not passes:
            self.sat_list.addItem("Keine Überflüge gefunden.")
            return
        for p in passes:
            item = QListWidgetItem(
                f"{p['culm']:%d.%m. %H:%M}  |  {p['name']}  |  max. {p['max_alt']}°"
            )
            item.setData(Qt.ItemDataRole.UserRole, p)  # store the whole pass in the item
            self.sat_list.addItem(item)

    def show_sat_error(self, msg):
        self.sat_list.clear()
        self.sat_list.addItem(f"Fehler: {msg}")

    def show_details(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if not p:  # placeholder items like "Lade Satelliten..."
            return

        self.selected_pass = p
        self.btn_3d.setEnabled(True)

        lines = [f"<b>{p['name']}</b> (NORAD {p['norad']})"]
        if "rise" in p:
            lines.append(
                f"Aufgang: {p['rise']:%H:%M:%S} Richtung {compass(p['rise_az'])} ({p['rise_az']:.0f}°)"
            )
        lines.append(
            f"Höchststand: {p['culm']:%H:%M:%S}, {p['max_alt']}° Richtung {compass(p['culm_az'])}"
        )
        lines.append(
            f"Untergang: {p['set']:%H:%M:%S} Richtung {compass(p['set_az'])} ({p['set_az']:.0f}°)"
        )
        if "rise" in p:
            secs = int((p["set"] - p["rise"]).total_seconds())
            lines.append(f"Dauer: {secs // 60} min {secs % 60} s")
        lines.append(f"Höhe: {p['height_km']:.0f} km | Geschwindigkeit: {p['speed_kms']:.2f} km/s")
        lines.append(f"Entfernung beim Höchststand: {p['distance_km']:.0f} km")
        lines.append(f"TLE-Datenstand: {p['tle_epoch']:%d.%m.%Y %H:%M}")
        self.details_label.setText("<br>".join(lines))

    # ---------- 3D ----------
    def open_3d(self):
        if self.selected_pass:
            self.view3d = SatView3D(self.selected_pass, self.lat, self.lon)  # keep a reference!
            self.view3d.show()