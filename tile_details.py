import csv
import os
from datetime import datetime, timezone

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRunnable,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from constants import (
    CLOUDY_THRESHOLD,
    DATA_DIR,
    DEFAULT_MAX_CLOUDS,
    DEFAULT_MAX_MAGNITUDE,
    FAVORITES,
    MIN_ELEVATION,
    RESOLUTION,
    SUN_MAX_ALT,
    compass,
)
from geo_calc import format_tz_name, geocode_place, get_timezone_for_latlon, latlon_to_tile, tile_to_latlon
from handler.nasa_handler import get_img
from handler.satellite_handler import classify_twilight, get_passes
from sat_view_3d import SatView3D


class LoaderSignals(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)


class ImageLoader(QRunnable):
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
                self.signals.failed.emit(self.path)
        except Exception as e:
            print("Download error:", e)
            self.signals.failed.emit(self.path)


PASS_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class PassTableModel(QAbstractTableModel):
    HEADERS = ("", "Satellite", "Culmination", "Mag", "Max Alt", "Clouds", "Visibility", "Duration")

    def __init__(self, passes=None, parent=None):
        super().__init__(parent)
        self.passes = list(passes or [])

    def set_passes(self, passes):
        self.beginResetModel()
        self.passes = list(passes)
        self.endResetModel()

    def pass_at(self, row):
        if 0 <= row < len(self.passes):
            return self.passes[row]
        return None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.passes)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    @staticmethod
    def duration_seconds(p):
        if "rise_utc" in p and "set_utc" in p:
            return int((p["set_utc"] - p["rise_utc"]).total_seconds())
        if "rise" in p and "set" in p:
            return int((p["set"] - p["rise"]).total_seconds())
        return None

    @staticmethod
    def status_for(p):
        cloud = p.get("cloud_cover")
        mag = p.get("est_mag")
        reason = p.get("invisibility_reason", "")
        if not p.get("is_geom_visible"):
            if not p.get("sunlit"):
                text = "Earth shadow"
            elif p.get("sun_alt", 0) >= 0:
                text = "Daylight"
            else:
                text = "Low pass"
        elif cloud is not None and cloud >= CLOUDY_THRESHOLD:
            text = "Cloudy"
        elif mag is not None and mag > DEFAULT_MAX_MAGNITUDE:
            text = "Faint"
        else:
            text = "Visible"
        tooltip = f"{text}: {reason}" if reason else text
        if p.get("brightness_uncertain"):
            tooltip += " | Brightness uncertain (tumbling)"
        if p.get("tle_old"):
            tooltip += f" | TLE {p.get('tle_age_days', 0)} days old"
        return text, tooltip

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self.passes[index.row()]
        col = index.column()

        if role == PASS_ROLE:
            return p
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (2, 3, 4, 5, 7):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        status_text, status_tip = self.status_for(p)
        mag = p.get("est_mag")
        cloud = p.get("cloud_cover")
        duration = self.duration_seconds(p)

        if role == SORT_ROLE:
            values = {
                0: 1 if p.get("is_favorite") else 0,
                1: p.get("name", "").lower(),
                2: p["culm"].timestamp() if "culm" in p else 0,
                3: mag if mag is not None else 99.0,
                4: p.get("max_alt", 0.0),
                5: cloud if cloud is not None else 999,
                6: status_text.lower(),
                7: duration if duration is not None else -1,
            }
            return values.get(col)

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return "*" if p.get("is_favorite") else ""
            if col == 1:
                return p.get("name", "")
            if col == 2:
                culm = p.get("culm")
                if culm is None:
                    return "?"
                return f"{culm:%d.%m. %H:%M:%S} {p.get('tz_abbr', '')}".strip()
            if col == 3:
                return f"{mag:+.1f}" if mag is not None else "?"
            if col == 4:
                alt = p.get("max_alt")
                return f"{alt:.1f}°" if alt is not None else "?"
            if col == 5:
                return f"{cloud}%" if cloud is not None else "--"
            if col == 6:
                return status_text
            if col == 7:
                if duration is None:
                    return "--"
                return f"{duration // 60}m {duration % 60:02d}s"
            return None

        if role == Qt.ItemDataRole.FontRole and p.get("is_favorite"):
            font = QFont()
            font.setBold(True)
            return font

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 1:
                return f"{p.get('name', '')} (NORAD {p.get('norad', '?')})"
            if col == 6:
                return status_tip
            if col == 2 and "culm_utc" in p:
                return f"UTC: {p['culm_utc']:%d.%m.%Y %H:%M:%S}"
        return None


class PassFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.visible_only = True
        self.favorites_only = False
        self.max_clouds = DEFAULT_MAX_CLOUDS
        self.max_mag = DEFAULT_MAX_MAGNITUDE
        self.search = ""
        self.setSortRole(SORT_ROLE)

    def set_filters(self, visible_only, favorites_only, max_clouds, max_mag, search):
        self.visible_only = visible_only
        self.favorites_only = favorites_only
        self.max_clouds = max_clouds
        self.max_mag = max_mag
        self.search = search.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        p = model.pass_at(source_row) if model else None
        return p is not None and self.accepts(p)

    def accepts(self, p, ignore_clouds=False):
        if self.visible_only and not p.get("is_geom_visible"):
            return False
        if self.favorites_only and not p.get("is_favorite"):
            return False
        if p.get("est_mag") is not None and p.get("est_mag") > self.max_mag:
            return False
        if not ignore_clouds and p.get("cloud_cover") is not None and p.get("cloud_cover") > self.max_clouds:
            return False
        if self.search:
            name = p.get("name", "").lower()
            favorite = (p.get("favorite_name") or "").lower()
            norad = str(p.get("norad", ""))
            if self.search not in name and self.search not in favorite and self.search not in norad:
                return False
        return True


class GeocodeSignals(QObject):
    finished = pyqtSignal(object)


class GeocodeLoader(QRunnable):
    def __init__(self, query):
        super().__init__()
        self.query = query
        self.signals = GeocodeSignals()
        self.setAutoDelete(False)

    def run(self):
        self.signals.finished.emit(geocode_place(self.query))


class SatSignals(QObject):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, str)


class SatLoader(QRunnable):
    def __init__(self, lat, lon, tz=None, elevation_m=0.0):
        super().__init__()
        self.lat, self.lon = lat, lon
        self.tz = tz
        self.elevation_m = elevation_m
        self.cancelled = False
        self.signals = SatSignals()
        self.setAutoDelete(False)

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            passes = get_passes(
                self.lat,
                self.lon,
                hours=48,
                groups=("visual", "stations"),
                min_elev=0.0,
                fetch_weather=True,
                tz=self.tz,
                elevation_m=self.elevation_m,
                progress=self.signals.progress.emit,
                cancel=lambda: self.cancelled,
            )
            if self.cancelled:
                return
            print(f"GUI: {len(passes)} passes loaded for {self.lat:.2f}, {self.lon:.2f}")
            self.signals.finished.emit(passes)
        except Exception as e:
            if self.cancelled:
                return
            print("Satellite error:", e)
            self.signals.failed.emit(str(e))


def _fmt_time(value):
    return f"{value:%Y-%m-%d %H:%M:%S}" if value is not None else ""


def _fmt_num(value, digits):
    return f"{value:.{digits}f}" if value is not None else ""


class TileDetails(QWidget):
    def __init__(self, x, y, location=None):
        super().__init__()
        self.x, self.y = x, y
        lat, lon = tile_to_latlon(x, y)
        self.elevation_m = 0.0
        self.free_location = False
        if location is not None:
            lat, lon = location["latitude"], location["longitude"]
            self.elevation_m = location.get("elevation") or 0.0
            self.free_location = True
        self.lat, self.lon = lat, lon
        self.load_token = 0
        self.geocode_loader = None

        self.tile_tz, self.tile_tz_name = get_timezone_for_latlon(lat, lon)
        self.local_tz = datetime.now().astimezone().tzinfo
        self.tz = self.tile_tz
        self.tz_name = self.tile_tz_name
        self.tz_mode = "tile"
        tz_abbr = format_tz_name(datetime.now(self.tz))
        self.tz_abbr = tz_abbr

        self.all_passes = []
        self.selected_pass = None
        self.view3d = None
        self.sat_loader = None

        self.setWindowTitle(f"Satellite Tracker - Tile ({x}, {y})")

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.label = QLabel(
            f"<b>Tile ({x}, {y})</b> — Lat: {lat:.4f}°, Lon: {lon:.4f}°<br>"
            f"Timezone: {self.tz_name} ({tz_abbr})"
        )

        observer_box = QFrame()
        observer_layout = QVBoxLayout(observer_box)
        observer_layout.setContentsMargins(8, 8, 8, 8)
        observer_layout.setSpacing(4)

        coords = QGridLayout()
        coords.setHorizontalSpacing(6)
        coords.setVerticalSpacing(4)
        lat_lbl = QLabel("Lat")
        lon_lbl = QLabel("Lon")
        elev_lbl = QLabel("Elev m")
        self.txt_lat = QLineEdit(f"{lat:.4f}")
        self.txt_lon = QLineEdit(f"{lon:.4f}")
        self.txt_elev = QLineEdit(f"{self.elevation_m:.0f}")
        self.txt_lat.setToolTip("Observer latitude in degrees")
        self.txt_lon.setToolTip("Observer longitude in degrees")
        self.txt_elev.setToolTip("Observer elevation above sea level in metres")
        coords.addWidget(lat_lbl, 0, 0)
        coords.addWidget(self.txt_lat, 0, 1)
        coords.addWidget(lon_lbl, 0, 2)
        coords.addWidget(self.txt_lon, 0, 3)
        coords.addWidget(elev_lbl, 0, 4)
        coords.addWidget(self.txt_elev, 0, 5)
        coords.setColumnStretch(1, 1)
        coords.setColumnStretch(3, 1)

        place_row = QHBoxLayout()
        self.txt_place = QLineEdit()
        self.txt_place.setPlaceholderText("Search place name...")
        self.txt_place.returnPressed.connect(self.search_place)
        self.btn_geocode = QPushButton("Search")
        self.btn_geocode.clicked.connect(self.search_place)
        place_row.addWidget(self.txt_place, stretch=1)
        place_row.addWidget(self.btn_geocode)

        use_row = QHBoxLayout()
        if location is not None:
            place = location.get("name") or "Custom observer location"
            if location.get("country"):
                place = f"{place}, {location['country']}"
            self.geocode_label = QLabel(place)
        else:
            self.geocode_label = QLabel("Tile centre in use")
        self.btn_use_location = QPushButton("Use location")
        self.btn_use_location.clicked.connect(self.use_location)
        use_row.addWidget(self.geocode_label, stretch=1)
        use_row.addWidget(self.btn_use_location)

        observer_layout.addLayout(coords)
        observer_layout.addLayout(place_row)
        observer_layout.addLayout(use_row)

        os.makedirs(os.path.join(DATA_DIR, "map_tiles"), exist_ok=True)
        path = os.path.join(DATA_DIR, "map_tiles", f"map_{x * RESOLUTION}_{y * RESOLUTION}.jpg")
        self.image_path = path

        self.image_label = QLabel("Loading NASA satellite image...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(400, 400)

        self.weather_card = QLabel("Loading weather & cloud forecast...")
        self.weather_card.setWordWrap(True)

        left_layout.addWidget(self.label)
        left_layout.addWidget(observer_box)
        self.update_location_label()
        left_layout.addWidget(self.image_label)
        left_layout.addWidget(self.weather_card)
        left_layout.addStretch()
        left_panel.setLayout(left_layout)
        left_panel.setMinimumWidth(420)
        left_panel.setMaximumWidth(460)

        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        header_layout = QHBoxLayout()
        self.sat_title = QLabel("<b>Satellite passes (next 48 h):</b>")
        self.sat_count_label = QLabel("Calculating passes...")
        header_layout.addWidget(self.sat_title)
        header_layout.addStretch()

        header_layout.addWidget(QLabel("Time zone:"))
        self.cmb_timezone = QComboBox()
        self.cmb_timezone.addItem(f"Tile ({format_tz_name(datetime.now(self.tile_tz))})", "tile")
        self.cmb_timezone.addItem(f"Local ({format_tz_name(datetime.now(self.local_tz))})", "local")
        self.cmb_timezone.addItem("UTC", "utc")
        self.cmb_timezone.setToolTip("Time zone used for pass times")
        self.cmb_timezone.currentIndexChanged.connect(self.on_timezone_changed)
        header_layout.addWidget(self.cmb_timezone)
        header_layout.addWidget(self.sat_count_label)
        right_layout.addLayout(header_layout)

        load_row = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(220)
        self.progress_bar.setVisible(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_loading)
        load_row.addWidget(self.progress_label)
        load_row.addStretch()
        load_row.addWidget(self.progress_bar)
        load_row.addWidget(self.btn_cancel)
        right_layout.addLayout(load_row)

        filter_box = QFrame()
        filter_layout = QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(8, 8, 8, 8)
        filter_layout.setSpacing(6)

        filter_row1 = QHBoxLayout()
        self.chk_visible = QCheckBox("Only visible")
        self.chk_visible.setToolTip("Elevation ≥ 10°, dark sky, satellite illuminated")
        self.chk_visible.setChecked(True)
        self.chk_visible.toggled.connect(self.apply_filter)

        self.chk_favorites_only = QCheckBox("Only favorites")
        self.chk_favorites_only.setToolTip("ISS, Hubble, Tiangong")
        self.chk_favorites_only.setChecked(False)
        self.chk_favorites_only.toggled.connect(self.apply_filter)

        self.chk_moon_warning = QCheckBox("Moon glare")
        self.chk_moon_warning.setToolTip("Warn when a bright Moon is close to the satellite")
        self.chk_moon_warning.setChecked(True)
        self.chk_moon_warning.toggled.connect(self.refresh_details)

        self.btn_reset_filters = QPushButton("Reset")
        self.btn_reset_filters.setToolTip("Reset filters to default (Visible ≤3.5 Mag, ≤50% clouds)")
        self.btn_reset_filters.clicked.connect(self.reset_filters)

        filter_row1.addWidget(self.chk_visible)
        filter_row1.addSpacing(10)
        filter_row1.addWidget(self.chk_favorites_only)
        filter_row1.addSpacing(10)
        filter_row1.addWidget(self.chk_moon_warning)
        filter_row1.addStretch()
        filter_row1.addWidget(self.btn_reset_filters)

        filter_row2 = QHBoxLayout()
        filter_row2.setSpacing(8)

        self.lbl_cloud = QLabel(f"Max Clouds: ≤ {DEFAULT_MAX_CLOUDS}%")
        self.slider_clouds = QSlider(Qt.Orientation.Horizontal)
        self.slider_clouds.setRange(0, 100)
        self.slider_clouds.setSingleStep(5)
        self.slider_clouds.setPageStep(10)
        self.slider_clouds.setMinimumWidth(90)
        self.slider_clouds.setValue(DEFAULT_MAX_CLOUDS)
        self.slider_clouds.setToolTip("Filter passes by maximum cloud cover percentage (default 50%)")
        self.slider_clouds.valueChanged.connect(self.on_cloud_slider_changed)

        self.lbl_mag = QLabel(f"Max Mag: ≤ {DEFAULT_MAX_MAGNITUDE:+.1f}")
        self.slider_mag = QSlider(Qt.Orientation.Horizontal)
        self.slider_mag.setRange(-20, 60)
        self.slider_mag.setSingleStep(1)
        self.slider_mag.setPageStep(5)
        self.slider_mag.setMinimumWidth(90)
        self.slider_mag.setValue(int(DEFAULT_MAX_MAGNITUDE * 10))
        self.slider_mag.setToolTip("Filter passes by maximum apparent magnitude / brightness (default ≤ +3.5)")
        self.slider_mag.valueChanged.connect(self.on_mag_slider_changed)

        filter_row2.addWidget(self.lbl_cloud)
        filter_row2.addWidget(self.slider_clouds, stretch=1)
        filter_row2.addSpacing(14)
        filter_row2.addWidget(self.lbl_mag)
        filter_row2.addWidget(self.slider_mag, stretch=1)

        filter_row3 = QHBoxLayout()
        search_lbl = QLabel("Search:")
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search satellite name or NORAD ID...")
        self.txt_search.textChanged.connect(self.apply_filter)

        filter_row3.addWidget(search_lbl)
        filter_row3.addWidget(self.txt_search)

        filter_layout.addLayout(filter_row1)
        filter_layout.addLayout(filter_row2)
        filter_layout.addLayout(filter_row3)
        right_layout.addWidget(filter_box)

        self.pass_model = PassTableModel()
        self.pass_proxy = PassFilterProxyModel(self)
        self.pass_proxy.setSourceModel(self.pass_model)
        self.pass_proxy.setSortRole(SORT_ROLE)
        self.pass_proxy.setDynamicSortFilter(True)

        self.sat_table = QTableView()
        self.sat_table.setModel(self.pass_proxy)
        self.sat_table.setSortingEnabled(True)
        self.sat_table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.sat_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.sat_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.sat_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.sat_table.setAlternatingRowColors(True)
        selection = self.sat_table.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            selection.setColor(group, QPalette.ColorRole.Highlight, QColor("#cce8ff"))
            selection.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.sat_table.setPalette(selection)
        self.sat_table.setWordWrap(False)
        self.sat_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.sat_table.verticalHeader().setVisible(False)
        self.sat_table.verticalHeader().setDefaultSectionSize(26)
        self.sat_table.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        table_header = self.sat_table.horizontalHeader()
        table_header.setMinimumSectionSize(50)
        table_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setStretchLastSection(True)
        self.sat_table.selectionModel().currentRowChanged.connect(self.on_current_row_changed)
        self.cloud_notice = QLabel()
        self.cloud_notice.setWordWrap(True)
        self.cloud_notice.setVisible(False)
        right_layout.addWidget(self.cloud_notice)

        right_layout.addWidget(self.sat_table, stretch=2)

        self.details_box = QTextBrowser()
        self.details_box.setReadOnly(True)
        self.details_box.setMinimumHeight(120)
        self.details_box.setPlaceholderText("Select a pass in the table to see its details.")
        right_layout.addWidget(self.details_box, stretch=1)

        self.btn_3d = QPushButton("Open 3D globe")
        self.btn_3d.setMinimumHeight(34)
        self.btn_3d.clicked.connect(self.open_3d)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.setEnabled(False)
        self.btn_export.setMinimumHeight(34)
        self.btn_export.setToolTip("Save the passes currently shown in the table to a CSV file")
        self.btn_export.clicked.connect(self.export_csv)

        button_row = QHBoxLayout()
        button_row.addWidget(self.btn_3d, stretch=1)
        button_row.addWidget(self.btn_export)
        right_layout.addLayout(button_row)

        right_panel.setLayout(right_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 740])
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
        self.setMinimumSize(980, 700)

        screen = QGuiApplication.primaryScreen().availableGeometry()
        width = max(980, int(screen.width() * 0.65))
        height = max(700, int(screen.height() * 0.65))
        self.resize(width, height)
        self.move(
            screen.x() + max(0, (screen.width() - width) // 2),
            screen.y() + max(0, (screen.height() - height) // 2),
        )

        self.loader = ImageLoader(lat, lon, path)
        self.loader.signals.finished.connect(self.show_image)
        self.loader.signals.failed.connect(self.show_error)
        QThreadPool.globalInstance().start(self.loader)
        self.start_loading()

    def show_image(self, path):
        if path != self.image_path:
            return
        pixmap = QPixmap(path)
        self.image_label.setPixmap(
            pixmap.scaled(
                400,
                400,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def show_error(self, path):
        if path == self.image_path:
            self.image_label.setText("Could not load NASA image.")

    def update_location_label(self):
        title = "Observer" if getattr(self, "free_location", False) else f"Tile ({self.x}, {self.y})"
        self.label.setText(
            f"<b>{title}</b> — Lat: {self.lat:.4f}°, Lon: {self.lon:.4f}°, Elev: {self.elevation_m:.0f} m<br>"
            f"Timezone: {self.tz_name} ({format_tz_name(datetime.now(self.tz))})"
        )

    def search_place(self):
        query = self.txt_place.text().strip()
        if not query:
            return
        self.btn_geocode.setEnabled(False)
        self.geocode_label.setText("Searching...")
        self.geocode_loader = GeocodeLoader(query)
        self.geocode_loader.signals.finished.connect(self.on_geocode_result)
        QThreadPool.globalInstance().start(self.geocode_loader)

    def on_geocode_result(self, result):
        self.btn_geocode.setEnabled(True)
        if not result:
            self.geocode_label.setText("No place found")
            return
        self.txt_lat.setText(f"{result['latitude']:.4f}")
        self.txt_lon.setText(f"{result['longitude']:.4f}")
        self.txt_elev.setText(f"{result['elevation']:.0f}")
        place = result["name"]
        if result.get("country"):
            place = f"{place}, {result['country']}"
        self.geocode_label.setText(f"{place} — click Use location")

    def use_location(self):
        try:
            lat = float(self.txt_lat.text().replace(",", "."))
            lon = float(self.txt_lon.text().replace(",", "."))
            elevation = float(self.txt_elev.text().replace(",", ".") or 0)
        except ValueError:
            self.geocode_label.setText("Enter valid coordinates")
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and -500 <= elevation <= 9000):
            self.geocode_label.setText("Coordinates out of range")
            return

        self.lat, self.lon = lat, lon
        self.elevation_m = elevation
        self.free_location = True
        self.geocode_label.setText("Custom observer location")
        self.tile_tz, self.tile_tz_name = get_timezone_for_latlon(lat, lon)
        self.cmb_timezone.setItemText(0, f"Tile ({format_tz_name(datetime.now(self.tile_tz))})")
        if self.tz_mode == "tile":
            self.tz = self.tile_tz
            self.tz_name = self.tile_tz_name
        self.update_location_label()

        row, col = latlon_to_tile(lat, lon)
        new_path = os.path.join(
            DATA_DIR,
            "map_tiles",
            f"map_{row * RESOLUTION}_{col * RESOLUTION}.jpg",
        )
        if new_path != self.image_path:
            self.image_path = new_path
            self.image_label.setText("Loading NASA satellite image...")
            self.loader = ImageLoader(lat, lon, new_path)
            self.loader.signals.finished.connect(self.show_image)
            self.loader.signals.failed.connect(self.show_error)
            QThreadPool.globalInstance().start(self.loader)
        self.start_loading()

    def start_loading(self):
        self.load_token += 1
        token = self.load_token
        if self.sat_loader:
            self.sat_loader.cancel()
        self.all_passes = []
        self.selected_pass = None
        self.update_3d_button()
        self.pass_model.set_passes([])
        self.btn_export.setEnabled(False)
        self.cloud_notice.setVisible(False)
        self.details_box.setText("Loading passes...")

        self.sat_loader = SatLoader(
            self.lat, self.lon, tz=self.tz, elevation_m=self.elevation_m
        )
        self.sat_loader.signals.finished.connect(
            lambda passes, t=token: self.show_satellites(passes) if t == self.load_token else None
        )
        self.sat_loader.signals.failed.connect(
            lambda msg, t=token: self.show_sat_error(msg) if t == self.load_token else None
        )
        self.sat_loader.signals.progress.connect(
            lambda pct, text, t=token: self.on_load_progress(pct, text) if t == self.load_token else None
        )
        self.progress_label.setVisible(True)
        self.progress_bar.setVisible(True)
        self.btn_cancel.setVisible(True)
        self.on_load_progress(0, "Starting...")
        QThreadPool.globalInstance().start(self.sat_loader)

    def on_cloud_slider_changed(self, val):
        self.lbl_cloud.setText(f"Max Clouds: ≤ {val}%")
        self.apply_filter()

    def on_mag_slider_changed(self, val):
        mag = val / 10.0
        self.lbl_mag.setText(f"Max Mag: ≤ {mag:+.1f}")
        self.apply_filter()

    def reset_filters(self):
        self.chk_visible.setChecked(True)
        self.chk_favorites_only.setChecked(False)
        self.chk_moon_warning.setChecked(True)
        self.slider_clouds.setValue(DEFAULT_MAX_CLOUDS)
        self.slider_mag.setValue(int(DEFAULT_MAX_MAGNITUDE * 10))
        self.txt_search.clear()
        self.apply_filter()

    def on_load_progress(self, pct, text):
        self.progress_bar.setValue(pct)
        self.progress_label.setText(text)
        self.sat_count_label.setText(text)

    def cancel_loading(self):
        self.load_token += 1
        if self.sat_loader:
            self.sat_loader.cancel()
        self.progress_label.setVisible(False)
        self.progress_bar.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.sat_count_label.setText("Cancelled")
        self.details_box.setText("Loading cancelled.")

    def closeEvent(self, event):
        self.load_token += 1
        if self.sat_loader:
            self.sat_loader.cancel()
        if self.view3d is not None:
            self.view3d.close()
        super().closeEvent(event)

    def on_timezone_changed(self, index):
        mode = self.cmb_timezone.currentData()
        if mode == "local":
            self.tz = self.local_tz
            self.tz_name = getattr(self.local_tz, "key", str(self.local_tz))
        elif mode == "utc":
            self.tz = timezone.utc
            self.tz_name = "UTC"
        else:
            self.tz = self.tile_tz
            self.tz_name = self.tile_tz_name
        self.tz_mode = mode
        self.update_location_label()
        self.apply_timezone()

    def apply_timezone(self):
        for p in self.all_passes:
            for key, utc_key in (
                ("rise", "rise_utc"),
                ("culm", "culm_utc"),
                ("set", "set_utc"),
                ("tle_epoch", "tle_epoch_utc"),
            ):
                if utc_key in p:
                    p[key] = p[utc_key].astimezone(self.tz)
                elif key in p:
                    p[key] = p[key].astimezone(self.tz)
            p["tz"] = self.tz
            p["tz_name"] = self.tz_name
            if "culm" in p:
                p["tz_abbr"] = format_tz_name(p["culm"])
                self.tz_abbr = p["tz_abbr"]
        if self.all_passes:
            top = self.pass_model.index(0, 0)
            bottom = self.pass_model.index(self.pass_model.rowCount() - 1, self.pass_model.columnCount() - 1)
            self.pass_model.dataChanged.emit(top, bottom)
            self.pass_proxy.invalidate()
        self.apply_filter()

    def show_satellites(self, passes):
        self.all_passes = passes
        self.pass_model.set_passes(self.all_passes)
        self.progress_bar.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.progress_label.setVisible(False)

        total_count = len(passes)
        geom_count = sum(1 for p in passes if p.get("is_geom_visible"))
        weather_count = sum(1 for p in passes if p.get("is_weather_visible"))
        vis_count = sum(1 for p in passes if p.get("is_visible"))
        fav_count = sum(1 for p in passes if p.get("is_favorite"))

        self.weather_card.setText(
            f"<b>Open-Meteo cloud forecast:</b> Active<br>"
            f"Passes found (48h): <b>{total_count}</b><br>"
            f"• Geometrically visible: <b>{geom_count}</b><br>"
            f"• Clear sky (&lt;40% clouds): <b>{weather_count}</b><br>"
            f"• Naked-eye visible (&le;3.5 Mag, &lt;50% clouds): <b>{vis_count}</b><br>"
            f"• Favorites: <b>{fav_count}</b>"
        )

        self.apply_timezone()

    def show_sat_error(self, msg):
        self.all_passes = []
        self.pass_model.set_passes([])
        self.progress_bar.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.progress_label.setVisible(False)
        self.sat_count_label.setText("Error")
        self.details_box.setText(f"Error calculating passes: {msg}")
        self.btn_export.setEnabled(False)
        self.selected_pass = None
        self.update_3d_button()

    def apply_filter(self):
        visible_only = self.chk_visible.isChecked()
        favorites_only = self.chk_favorites_only.isChecked()
        search_query = self.txt_search.text().strip()
        max_clouds = self.slider_clouds.value()
        max_mag = self.slider_mag.value() / 10.0

        self.pass_proxy.set_filters(visible_only, favorites_only, max_clouds, max_mag, search_query)
        self.btn_export.setEnabled(self.pass_proxy.rowCount() > 0)
        cloud_message = self.update_cloud_notice(max_clouds)
        if not self.all_passes:
            if not self.progress_bar.isVisible() and self.sat_count_label.text() != "Cancelled":
                self.sat_count_label.setText("0 passes found")
                self.details_box.setText("No satellite passes found for this location in the next 48 h.")
            return

        total_geom = sum(1 for p in self.all_passes if p.get("is_geom_visible"))
        total_vis = sum(1 for p in self.all_passes if p.get("is_visible"))
        total_fav = sum(1 for p in self.all_passes if p.get("is_favorite"))
        self.sat_count_label.setText(
            f"{self.pass_proxy.rowCount()} displayed ({total_vis} visible / {total_geom} geom / {total_fav} fav)"
        )

        if self.pass_proxy.rowCount() == 0:
            self.details_box.setText(
                ""
                if cloud_message
                else "No passes match the current filter settings. Try adjusting the sliders or unchecking 'Only visible'."
            )
            self.selected_pass = None
            self.update_3d_button()
            return

        if self.sat_table.currentIndex().isValid():
            self.refresh_details()
        else:
            self.clear_details()

    def update_3d_button(self):
        if self.selected_pass:
            self.btn_3d.setStyleSheet(
                "QPushButton { background-color: #0067c0; color: white; border: none; border-radius: 4px; }"
                "QPushButton:hover { background-color: #1975c5; }"
            )
        else:
            self.btn_3d.setStyleSheet("")

    def clear_details(self):
        self.selected_pass = None
        self.update_3d_button()
        self.details_box.clear()

    def update_cloud_notice(self, max_clouds):
        cloudy = [
            p for p in self.all_passes
            if self.pass_proxy.accepts(p, ignore_clouds=True) and not self.pass_proxy.accepts(p)
        ]
        if not cloudy:
            self.cloud_notice.setVisible(False)
            return ""

        covers = [p["cloud_cover"] for p in cloudy]
        cover_text = f"{min(covers)}%" if min(covers) == max(covers) else f"{min(covers)}–{max(covers)}%"
        count = len(cloudy)
        plural = "pass is" if count == 1 else "passes are"
        if self.pass_proxy.rowCount() == 0:
            message = (
                f"<b>Too cloudy:</b> no satellites can be seen because of clouds. "
                f"{count} {plural} hidden because the forecast shows {cover_text} cloud cover "
                f"(your limit is {max_clouds}%). Raise <i>Max Clouds</i> to show them anyway."
            )
        else:
            message = (
                f"{count} more {plural} hidden because it is too cloudy "
                f"({cover_text} cloud cover, limit {max_clouds}%)."
            )
        self.cloud_notice.setText(message)
        self.cloud_notice.setVisible(True)
        return message

    def on_current_row_changed(self, current, previous):
        if current.isValid():
            self.show_details(self.pass_proxy.index(current.row(), 0))
        else:
            self.clear_details()

    def refresh_details(self):
        current = self.sat_table.currentIndex()
        if current.isValid():
            self.show_details(self.pass_proxy.index(current.row(), 0))

    def show_details(self, index):
        if not index or not index.isValid():
            return
        p = index.data(PASS_ROLE)
        if not p:
            return

        self.selected_pass = p
        self.update_3d_button()

        is_fav = p.get("is_favorite", False)
        fav_name = p.get("favorite_name")
        is_geom = p.get("is_geom_visible", False)
        cloud_pct = p.get("cloud_cover")
        mag = p.get("est_mag")
        tz_abbr = p.get("tz_abbr") or self.tz_abbr

        lines = []
        if is_fav:
            lines.append(
                f"<div><b>{fav_name}</b> — "
                f"<b>{p['name']}</b> (NORAD {p['norad']})</div>"
            )
        else:
            lines.append(
                f"<div><b>{p['name']}</b> (NORAD {p['norad']})</div>"
            )

        if is_geom and (cloud_pct is None or cloud_pct < 40) and (mag is None or mag <= 3.5):
            vis_banner = "<div><b>Visible to the naked eye (clear sky and bright)</b></div>"
        elif is_geom and cloud_pct is not None and cloud_pct >= 40:
            vis_banner = f"<div><b>Geometrically visible, but obscured by clouds ({cloud_pct}%)</b></div>"
        elif is_geom and mag is not None and mag > 3.5:
            vis_banner = f"<div><b>Geometrically visible, but faint (Mag {mag:+.1f} > 3.5)</b></div>"
        else:
            vis_banner = f"<div><b>Not visible ({p.get('invisibility_reason')})</b></div>"
        lines.append(vis_banner)

        if is_geom:
            geom_html = "<b>Geometrically visible</b> (Elevation ≥ 10°, dark sky, sunlit)"
        else:
            geom_html = f"<b>Geometrically not visible</b> ({p.get('invisibility_reason')})"
        lines.append(f"<b>Geometric visibility:</b> {geom_html}")

        if is_geom:
            if cloud_pct is not None and cloud_pct < 40:
                cloud_vis_html = f"<b>Visible despite clouds (&lt; 40%)</b> ({cloud_pct}% cloud cover)"
            elif cloud_pct is not None:
                cloud_vis_html = f"<b>Obscured by clouds (&ge; 40%)</b> ({cloud_pct}% — observation unlikely despite geometry)"
            else:
                cloud_vis_html = "Cloud forecast unavailable"
        else:
            cloud_vis_html = "— (Pass is not geometrically visible)"
        lines.append(f"<b>Observation conditions:</b> {cloud_vis_html}")

        if mag is None:
            lines.append("<b>Estimated brightness:</b> unknown")
        else:
            mag_desc = (
                "Extremely bright" if mag < -1 else ("Very bright" if mag < 1 else ("Clearly visible" if mag <= 3.5 else "Faint"))
            )
            naked_eye_note = (
                "(Naked-eye visible)"
                if mag <= 3.5
                else "(Faint — binoculars recommended)"
            )
            uncertain_note = (
                " uncertain (tumbling)"
                if p.get("brightness_uncertain")
                else ""
            )
            lines.append(
                f"<b>Estimated brightness:</b> <b>Mag {mag:+.1f}</b> ({mag_desc}) {naked_eye_note}{uncertain_note}"
            )
            parts = [f"range {p['distance_km']:.0f} km"]
            if p.get("phase_angle") is not None:
                parts.append(f"phase {p['phase_angle']:.0f}°")
            if p.get("airmass") is not None:
                parts.append(f"airmass {p['airmass']:.2f}")
            if p.get("extinction_mag") is not None:
                parts.append(f"extinction +{p['extinction_mag']:.2f} mag")
            lines.append(f"{' | '.join(parts)}")

        sun_alt = p.get("sun_alt", 0.0)
        sun_desc = "below horizon" if sun_alt < 0 else "above horizon (day)"
        sunlit_html = (
            "Yes (in sunlight)"
            if p.get("sunlit")
            else "No (in Earth's shadow)"
        )
        twilight = p.get("twilight", classify_twilight(sun_alt))
        lines.append(
            f"<b>Sun elevation:</b> {sun_alt:+.1f}° ({sun_desc}) | <b>Twilight:</b> {twilight} | <b>Illuminated:</b> {sunlit_html}"
        )

        if p.get("moon_phase_name"):
            lines.append(
                f"<b>Moon:</b> {p['moon_phase_name']} ({p.get('moon_illumination', 0)}%), "
                f"altitude {p.get('moon_alt', 0):+.1f}°, azimuth {p.get('moon_az', 0):.0f}° "
                f"({compass(p.get('moon_az', 0))})"
            )
            if p.get("moon_glare") and self.chk_moon_warning.isChecked():
                lines.append(
                    f"<b>Moon glare warning:</b> bright Moon "
                    f"{p.get('moon_separation', 0):.0f}° from the satellite"
                )

        c_pct = p.get("cloud_pct_str", "--%")
        c_desc = p.get("cloud_desc", "No data")
        lines.append(
            f"<b>Cloud forecast (Open-Meteo):</b> <b>{c_pct}</b> ({c_desc})"
        )

        if "rise" in p:
            lines.append(
                f"<b>Rise:</b> {p['rise']:%d.%m.%Y %H:%M:%S} {tz_abbr} direction <b>{compass(p['rise_az'])}</b> ({p['rise_az']:.0f}°)"
            )
        lines.append(
            f"<b>Culmination:</b> {p['culm']:%d.%m.%Y %H:%M:%S} {tz_abbr}, <b>{p['max_alt']}°</b> direction <b>{compass(p['culm_az'])}</b> ({p['culm_az']:.0f}°)"
        )
        lines.append(
            f"<b>Set:</b> {p['set']:%d.%m.%Y %H:%M:%S} {tz_abbr} direction <b>{compass(p['set_az'])}</b> ({p['set_az']:.0f}°)"
        )

        if "rise_utc" in p and "set_utc" in p:
            secs = int((p["set_utc"] - p["rise_utc"]).total_seconds())
            lines.append(f"<b>Duration:</b> {secs // 60} min {secs % 60} s")
        elif "rise" in p:
            secs = int((p["set"] - p["rise"]).total_seconds())
            lines.append(f"<b>Duration:</b> {secs // 60} min {secs % 60} s")

        lines.append(
            f"<b>Distance at culmination:</b> {p['distance_km']:.0f} km | <b>Height:</b> {p['height_km']:.0f} km | <b>Speed:</b> {p['speed_kms']:.2f} km/s"
        )
        age = p.get("tle_age_days")
        if age is None:
            lines.append(f"<b>TLE epoch:</b> {p['tle_epoch']:%d.%m.%Y %H:%M} {tz_abbr}")
        else:
            age_warn = (
                " older than 3 days — predictions may drift"
                if p.get("tle_old")
                else ""
            )
            lines.append(
                f"<b>TLE epoch:</b> {p['tle_epoch']:%d.%m.%Y %H:%M} {tz_abbr} ({age:.1f} days old){age_warn}"
            )

        self.details_box.setText("<br>".join(lines))

    CSV_COLUMNS = (
        ("Satellite", lambda p, tz: p.get("name", "")),
        ("NORAD", lambda p, tz: p.get("norad", "")),
        ("Favorite", lambda p, tz: p.get("favorite_name") or ""),
        ("Status", lambda p, tz: PassTableModel.status_for(p)[0]),
        ("Rise", lambda p, tz: _fmt_time(p.get("rise"))),
        ("Rise azimuth", lambda p, tz: _fmt_num(p.get("rise_az"), 0)),
        ("Rise direction", lambda p, tz: compass(p["rise_az"]) if "rise_az" in p else ""),
        ("Culmination", lambda p, tz: _fmt_time(p.get("culm"))),
        ("Culmination UTC", lambda p, tz: _fmt_time(p.get("culm_utc"))),
        ("Max altitude", lambda p, tz: _fmt_num(p.get("max_alt"), 1)),
        ("Culmination azimuth", lambda p, tz: _fmt_num(p.get("culm_az"), 0)),
        ("Culmination direction", lambda p, tz: compass(p["culm_az"]) if "culm_az" in p else ""),
        ("Set", lambda p, tz: _fmt_time(p.get("set"))),
        ("Set azimuth", lambda p, tz: _fmt_num(p.get("set_az"), 0)),
        ("Set direction", lambda p, tz: compass(p["set_az"]) if "set_az" in p else ""),
        ("Duration s", lambda p, tz: PassTableModel.duration_seconds(p) or ""),
        ("Time zone", lambda p, tz: tz),
        ("Magnitude", lambda p, tz: _fmt_num(p.get("est_mag"), 1)),
        ("Distance km", lambda p, tz: _fmt_num(p.get("distance_km"), 0)),
        ("Height km", lambda p, tz: _fmt_num(p.get("height_km"), 0)),
        ("Speed km/s", lambda p, tz: _fmt_num(p.get("speed_kms"), 2)),
        ("Sun altitude", lambda p, tz: _fmt_num(p.get("sun_alt"), 1)),
        ("Sunlit", lambda p, tz: "yes" if p.get("sunlit") else "no"),
        ("Twilight", lambda p, tz: p.get("twilight", "")),
        ("Cloud cover %", lambda p, tz: "" if p.get("cloud_cover") is None else p["cloud_cover"]),
        ("Moon glare", lambda p, tz: "yes" if p.get("moon_glare") else "no"),
        ("Reason", lambda p, tz: p.get("invisibility_reason", "")),
        ("TLE age days", lambda p, tz: _fmt_num(p.get("tle_age_days"), 1)),
    )

    def export_csv(self):
        passes = [self.pass_proxy.index(r, 0).data(PASS_ROLE) for r in range(self.pass_proxy.rowCount())]
        if not passes:
            return
        default_name = f"passes_{self.lat:.3f}_{self.lon:.3f}_{datetime.now():%Y-%m-%d_%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export passes to CSV", os.path.join(os.path.expanduser("~"), default_name), "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([name for name, _ in self.CSV_COLUMNS])
                for p in passes:
                    writer.writerow([get(p, self.tz_name) for _, get in self.CSV_COLUMNS])
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not save the CSV file:\n{e}")
            return
        self.sat_count_label.setText(f"Exported {len(passes)} passes to {os.path.basename(path)}")

    def open_3d(self):
        if not self.selected_pass:
            QMessageBox.warning(
                self, "No satellite selected",
                "Please select a satellite pass in the table first, then open the 3D globe.",
            )
            return
        self.view3d = SatView3D(self.selected_pass, self.lat, self.lon)
        self.view3d.show()
