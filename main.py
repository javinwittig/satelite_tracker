import sys
import os
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QToolTip, QInputDialog, QMessageBox
from PyQt6.QtGui import QAction, QColor, QIcon, QPixmap, QPainter, QKeySequence
from PyQt6.QtCore import Qt, QRect, QObject, QRunnable, QThreadPool, pyqtSignal
from constants import RESOLUTION, RESOURCE_DIR, TILES_X, TILES_Y
from geo_calc import geocode_place, get_current_location, latlon_to_tile, tile_to_latlon
from tile_details import TileDetails

TILE_SIZE = 10

HOVER_COLOR = QColor(52, 152, 219, 90)
SELECTED_FILL = QColor(231, 76, 60, 110)
SELECTED_BORDER = QColor("#e74c3c")

def load_map_pixmap(base):
    width, height = TILES_X * TILE_SIZE, TILES_Y * TILE_SIZE
    source = QPixmap(os.path.join(base, "map.png"))
    if not source.isNull():
        source = source.copy(0, 0, TILES_X * RESOLUTION, TILES_Y * RESOLUTION)
        return source.scaled(
            width, height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.lightGray)
    painter = QPainter(pixmap)
    for row in range(TILES_Y):
        for col in range(TILES_X):
            path = os.path.join(base, "map_tiles", f"map_{row * RESOLUTION}_{col * RESOLUTION}.png")
            tile = QPixmap(path)
            if tile.isNull():
                print("not found:", path)
                continue
            painter.drawPixmap(QRect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE), tile)
    painter.end()
    return pixmap


class MapWidget(QWidget):
    tile_clicked = pyqtSignal(int, int)

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.hover_tile = None
        self.selected_tile = None
        self.setFixedSize(TILES_X * TILE_SIZE, TILES_Y * TILE_SIZE)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def tile_at(self, pos):
        col = int(pos.x()) // TILE_SIZE
        row = int(pos.y()) // TILE_SIZE
        if 0 <= row < TILES_Y and 0 <= col < TILES_X:
            return row, col
        return None

    @staticmethod
    def tile_rect(tile):
        row, col = tile
        return QRect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)
        if self.hover_tile is not None and self.hover_tile != self.selected_tile:
            painter.fillRect(self.tile_rect(self.hover_tile), HOVER_COLOR)
        if self.selected_tile is not None:
            rect = self.tile_rect(self.selected_tile)
            painter.fillRect(rect, SELECTED_FILL)
            painter.setPen(SELECTED_BORDER)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def mouseMoveEvent(self, event):
        tile = self.tile_at(event.position())
        if tile == self.hover_tile:
            return
        old = self.hover_tile
        self.hover_tile = tile
        for t in (old, tile):
            if t is not None:
                self.update(self.tile_rect(t))
        if tile is None:
            QToolTip.hideText()
            return
        row, col = tile
        lat, lon = tile_to_latlon(row, col)
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"Tile ({row}, {col})\nLat {lat:.3f}°, Lon {lon:.3f}°\nClick for passes",
            self,
            self.tile_rect(tile),
        )

    def leaveEvent(self, event):
        if self.hover_tile is not None:
            self.update(self.tile_rect(self.hover_tile))
            self.hover_tile = None
        QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        tile = self.tile_at(event.position())
        if tile is None:
            return
        self.select_tile(tile)
        self.tile_clicked.emit(*tile)

    def select_tile(self, tile):
        old = self.selected_tile
        self.selected_tile = tile
        for t in (old, tile):
            if t is not None:
                self.update(self.tile_rect(t))


class JobSignals(QObject):
    finished = pyqtSignal(object)


class Job(QRunnable):
    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = JobSignals()
        self.setAutoDelete(False)

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as e:
            print("Lookup error:", e)
            result = None
        self.signals.finished.emit(result)


HELP_TEXT = """
<h3>Satellite Tracker</h3>
<p><b>Pick a location</b></p>
<ul>
<li>Click any tile on the map to see satellite passes over the centre of that tile.</li>
<li><b>Location &rarr; Use my current location</b> finds your approximate position
(city level, from your internet connection) and opens the passes for it.</li>
<li><b>Location &rarr; Search place...</b> looks up a town or address by name.</li>
<li>In the pass window you can also type exact coordinates and press <i>Use location</i>.</li>
</ul>
<p><b>Pass window</b></p>
<ul>
<li>Passes for the next 48 hours, including cloud cover and estimated brightness.</li>
<li><i>Only visible</i>: satellite at least 10&deg; high, sky dark and the satellite lit by the Sun.</li>
<li>Magnitude: lower is brighter. Up to about +3.5 is visible to the naked eye.</li>
<li>Click a pass for details, or <i>Open 3D globe</i> to see its orbit.</li>
<li><i>Export CSV</i> saves the passes currently shown in the table (after filters).</li>
</ul>
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.tile_details = None
        self.location_job = None

        self.setWindowTitle("Satellite Tracker")

        self.map_widget = MapWidget(load_map_pixmap(RESOURCE_DIR))
        self.map_widget.tile_clicked.connect(self.on_tile_click)
        self.setCentralWidget(self.map_widget)
        self.create_menus()

        self.setFixedSize(
            self.map_widget.width(),
            self.map_widget.height() + self.menuBar().sizeHint().height(),
        )
        self.setWindowFlag(Qt.WindowType.MSWindowsFixedSizeDialogHint, True)

    def create_menus(self):
        location_menu = self.menuBar().addMenu("&Location")
        self.act_my_location = QAction("Use my current location", self)
        self.act_my_location.setShortcut(QKeySequence("Ctrl+L"))
        self.act_my_location.triggered.connect(self.use_my_location)
        location_menu.addAction(self.act_my_location)
        self.act_search = QAction("Search place...", self)
        self.act_search.setShortcut(QKeySequence("Ctrl+F"))
        self.act_search.triggered.connect(self.search_place)
        location_menu.addAction(self.act_search)
        location_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        location_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("&Help")
        act_help = QAction("How to use", self)
        act_help.setShortcut(QKeySequence("F1"))
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)
        act_about = QAction("About", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

    def use_my_location(self):
        self.run_lookup("Finding your location...", get_current_location)

    def search_place(self):
        query, ok = QInputDialog.getText(self, "Search place", "Town, city or address:")
        query = query.strip()
        if ok and query:
            self.run_lookup(f"Searching for {query}...", geocode_place, query)

    def run_lookup(self, message, fn, *args):
        if self.location_job is not None:
            return
        self.act_my_location.setEnabled(False)
        self.act_search.setEnabled(False)
        self.setWindowTitle(f"Satellite Tracker - {message}")
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.location_job = Job(fn, *args)
        self.location_job.signals.finished.connect(self.on_location_found)
        QThreadPool.globalInstance().start(self.location_job)

    def on_location_found(self, location):
        self.location_job = None
        QApplication.restoreOverrideCursor()
        self.act_my_location.setEnabled(True)
        self.act_search.setEnabled(True)
        self.setWindowTitle("Satellite Tracker")
        if not location:
            QMessageBox.warning(
                self, "Location not found",
                "The location could not be determined. Check your internet connection or try another name.",
            )
            return
        row, col = latlon_to_tile(location["latitude"], location["longitude"])
        self.map_widget.select_tile((row, col))
        self.open_details(row, col, location)

    def on_tile_click(self, row, col):
        self.open_details(row, col)

    def open_details(self, row, col, location=None):
        if self.tile_details is not None:
            self.tile_details.close()

        self.tile_details = TileDetails(row, col, location)
        self.tile_details.show()

    def show_help(self):
        QMessageBox.information(self, "How to use", HELP_TEXT)

    def show_about(self):
        QMessageBox.about(
            self, "About Satellite Tracker",
            "<b>Satellite Tracker</b><br>Predicts visible satellite passes for any place on Earth.<br><br>"
            "Orbit data: CelesTrak &middot; Weather: Open-Meteo &middot; Images: NASA<br>"
            "Calculations: Skyfield",
        )

    def closeEvent(self, event):
        if self.tile_details is not None:
            self.tile_details.close()
        super().closeEvent(event)


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("satellite_tracker")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(RESOURCE_DIR, "icon.ico")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
