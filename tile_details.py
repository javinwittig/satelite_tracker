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
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from constants import (
    CLOUDY_THRESHOLD,
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
                text, color = "Earth shadow", "#888888"
            elif p.get("sun_alt", 0) >= 0:
                text, color = "Daylight", "#888888"
            else:
                text, color = "Low pass", "#888888"
        elif cloud is not None and cloud >= CLOUDY_THRESHOLD:
            text, color = "Cloudy", "#e67e22"
        elif mag is not None and mag > DEFAULT_MAX_MAGNITUDE:
            text, color = "Faint", "#74b9ff"
        else:
            text, color = "Visible", "#2ecc71"
        tooltip = f"{text}: {reason}" if reason else text
        if p.get("brightness_uncertain"):
            tooltip += " | Brightness uncertain (tumbling)"
        if p.get("tle_old"):
            tooltip += f" | TLE {p.get('tle_age_days', 0)} days old"
        return text, color, tooltip

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

        status_text, status_color, status_tip = self.status_for(p)
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
                return "★" if p.get("is_favorite") else ""
            if col == 1:
                return p.get("name", "")
            if col == 2:
                culm = p.get("culm")
                if culm is None:
                    return "?"
                return f"{culm:%d.%m.%Y %H:%M:%S} {p.get('tz_abbr', '')}".strip()
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

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0 and p.get("is_favorite"):
                return QColor("#f1c40f")
            if col == 6:
                return QColor(status_color)
            if not p.get("is_geom_visible"):
                return QColor("#888888")
            if p.get("is_favorite"):
                return QColor("#f1c40f")
            return QColor("#ecf0f1")

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
        if p is None:
            return False
        if self.visible_only and not p.get("is_geom_visible"):
            return False
        if self.favorites_only and not p.get("is_favorite"):
            return False
        if p.get("est_mag") is not None and p.get("est_mag") > self.max_mag:
            return False
        if p.get("cloud_cover") is not None and p.get("cloud_cover") > self.max_clouds:
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
    """Worker thread: computes satellite passes and weather over the tile."""

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


class TileDetails(QWidget):
    def __init__(self, x, y):
        super().__init__()
        self.x, self.y = x, y
        lat, lon = tile_to_latlon(x, y)
        self.lat, self.lon = lat, lon
        self.elevation_m = 0.0
        self.free_location = False
        self.load_token = 0
        self.geocode_loader = None

        # Derive tile's local timezone
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
        self.resize(1060, 720)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # =======================================================
        # LEFT PANEL: NASA Image & Tile Info
        # =======================================================
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.label = QLabel(
            f"<b>Tile ({x}, {y})</b> — Lat: {lat:.4f}°, Lon: {lon:.4f}°<br>"
            f"<span style='color: #3498db; font-size: 11px;'>Timezone: {self.tz_name} ({tz_abbr})</span>"
        )
        self.label.setStyleSheet("font-size: 13px;")

        observer_box = QFrame()
        observer_box.setStyleSheet("background-color: #2b2b2b; border-radius: 4px; padding: 6px;")
        observer_layout = QVBoxLayout(observer_box)
        observer_layout.setContentsMargins(8, 8, 8, 8)
        observer_layout.setSpacing(4)

        coords = QGridLayout()
        coords.setHorizontalSpacing(6)
        coords.setVerticalSpacing(4)
        lat_lbl = QLabel("Lat")
        lon_lbl = QLabel("Lon")
        elev_lbl = QLabel("Elev m")
        for lbl in (lat_lbl, lon_lbl, elev_lbl):
            lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        self.txt_lat = QLineEdit(f"{lat:.4f}")
        self.txt_lon = QLineEdit(f"{lon:.4f}")
        self.txt_elev = QLineEdit("0")
        self.txt_lat.setToolTip("Observer latitude in degrees")
        self.txt_lon.setToolTip("Observer longitude in degrees")
        self.txt_elev.setToolTip("Observer elevation above sea level in metres")
        for field in (self.txt_lat, self.txt_lon, self.txt_elev):
            field.setStyleSheet("padding: 2px; border-radius: 3px;")
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
        self.txt_place.setStyleSheet("padding: 2px; border-radius: 3px;")
        self.txt_place.returnPressed.connect(self.search_place)
        self.btn_geocode = QPushButton("Search")
        self.btn_geocode.setStyleSheet(
            "QPushButton { background-color: #444; color: #eee; border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #555; }"
        )
        self.btn_geocode.clicked.connect(self.search_place)
        place_row.addWidget(self.txt_place, stretch=1)
        place_row.addWidget(self.btn_geocode)

        use_row = QHBoxLayout()
        self.geocode_label = QLabel("Tile centre in use")
        self.geocode_label.setStyleSheet("color: #888; font-size: 11px;")
        self.btn_use_location = QPushButton("Use location")
        self.btn_use_location.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        self.btn_use_location.clicked.connect(self.use_location)
        use_row.addWidget(self.geocode_label, stretch=1)
        use_row.addWidget(self.btn_use_location)

        observer_layout.addLayout(coords)
        observer_layout.addLayout(place_row)
        observer_layout.addLayout(use_row)

        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(base, "map_tiles"), exist_ok=True)
        path = os.path.join(base, "map_tiles", f"map_{x * RESOLUTION}_{y * RESOLUTION}.jpg")
        self.image_path = path

        self.image_label = QLabel("Loading NASA satellite image...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(400, 400)
        self.image_label.setStyleSheet("background-color: #1e1e1e; border: 1px solid #444; border-radius: 4px;")

        # Weather card overview
        self.weather_card = QLabel("Loading weather & cloud forecast...")
        self.weather_card.setWordWrap(True)
        self.weather_card.setStyleSheet(
            "background-color: #2b2b2b; color: #ddd; padding: 10px; border-radius: 4px; font-size: 12px;"
        )

        left_layout.addWidget(self.label)
        left_layout.addWidget(observer_box)
        self.update_location_label()
        left_layout.addWidget(self.image_label)
        left_layout.addWidget(self.weather_card)
        left_layout.addStretch()
        left_panel.setLayout(left_layout)
        left_panel.setMinimumWidth(420)
        left_panel.setMaximumWidth(460)

        # =======================================================
        # RIGHT PANEL: Satellite Passes, Filters, Details, 3D
        # =======================================================
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Header with title & stats
        header_layout = QHBoxLayout()
        self.sat_title = QLabel("<b>Satellite passes (next 48 h):</b>")
        self.sat_title.setStyleSheet("font-size: 15px;")
        self.sat_count_label = QLabel("Calculating passes...")
        self.sat_count_label.setStyleSheet("color: #888; font-size: 12px;")
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

        # Loading progress
        load_row = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #95a5a6; font-size: 11px;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(220)
        self.progress_bar.setVisible(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #444; color: #eee; border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #555; }"
        )
        self.btn_cancel.clicked.connect(self.cancel_loading)
        load_row.addWidget(self.progress_label)
        load_row.addStretch()
        load_row.addWidget(self.progress_bar)
        load_row.addWidget(self.btn_cancel)
        right_layout.addLayout(load_row)

        # Filter box
        filter_box = QFrame()
        filter_box.setStyleSheet("background-color: #2b2b2b; border-radius: 4px; padding: 6px;")
        filter_layout = QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(8, 8, 8, 8)
        filter_layout.setSpacing(6)

        # Row 1: Checkboxes & Reset
        filter_row1 = QHBoxLayout()
        self.chk_visible = QCheckBox("Only visible")
        self.chk_visible.setToolTip("Elevation ≥ 10°, dark sky, satellite illuminated")
        self.chk_visible.setChecked(True)
        self.chk_visible.setStyleSheet("font-weight: bold; color: #4cd137;")
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
        self.btn_reset_filters.setStyleSheet(
            "QPushButton { background-color: #444; color: #eee; border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #555; }"
        )
        self.btn_reset_filters.clicked.connect(self.reset_filters)

        filter_row1.addWidget(self.chk_visible)
        filter_row1.addSpacing(10)
        filter_row1.addWidget(self.chk_favorites_only)
        filter_row1.addSpacing(10)
        filter_row1.addWidget(self.chk_moon_warning)
        filter_row1.addStretch()
        filter_row1.addWidget(self.btn_reset_filters)

        # Row 2: Sliders for Cloud cover and Magnitude
        filter_row2 = QHBoxLayout()
        filter_row2.setSpacing(8)

        # Max Cloud Cover slider
        self.lbl_cloud = QLabel(f"Max Clouds: ≤ {DEFAULT_MAX_CLOUDS}%")
        self.lbl_cloud.setStyleSheet("color: #ddd; font-size: 11px; min-width: 105px;")
        self.slider_clouds = QSlider(Qt.Orientation.Horizontal)
        self.slider_clouds.setRange(0, 100)
        self.slider_clouds.setSingleStep(5)
        self.slider_clouds.setPageStep(10)
        self.slider_clouds.setMinimumWidth(90)
        self.slider_clouds.setValue(DEFAULT_MAX_CLOUDS)
        self.slider_clouds.setToolTip("Filter passes by maximum cloud cover percentage (default 50%)")
        self.slider_clouds.valueChanged.connect(self.on_cloud_slider_changed)

        # Max Magnitude slider (-2.0 to 6.0 in 0.1 steps, mapped to -20 .. 60)
        self.lbl_mag = QLabel(f"Max Mag: ≤ {DEFAULT_MAX_MAGNITUDE:+.1f}")
        self.lbl_mag.setStyleSheet("color: #ddd; font-size: 11px; min-width: 95px;")
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

        # Row 3: Search text box
        filter_row3 = QHBoxLayout()
        search_lbl = QLabel("Search:")
        search_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search satellite name or NORAD ID...")
        self.txt_search.textChanged.connect(self.apply_filter)
        self.txt_search.setStyleSheet("padding: 3px; border-radius: 3px;")

        filter_row3.addWidget(search_lbl)
        filter_row3.addWidget(self.txt_search)

        filter_layout.addLayout(filter_row1)
        filter_layout.addLayout(filter_row2)
        filter_layout.addLayout(filter_row3)
        right_layout.addWidget(filter_box)

        # Satellite table
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
        right_layout.addWidget(self.sat_table, stretch=2)

        # Pass Details card
        self.details_label = QLabel("Click a pass for detailed visibility and orbit data.")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_label.setStyleSheet(
            "background-color: #2b2b2b; color: #ecf0f1; padding: 10px; border-radius: 4px; font-size: 12px; min-height: 120px;"
        )
        right_layout.addWidget(self.details_label, stretch=1)

        # 3D View button
        self.btn_3d = QPushButton("Open 3D globe")
        self.btn_3d.setEnabled(False)
        self.btn_3d.setMinimumHeight(34)
        self.btn_3d.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; font-weight: bold; border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background-color: #3498db; }"
            "QPushButton:disabled { background-color: #555; color: #888; }"
        )
        self.btn_3d.clicked.connect(self.open_3d)
        right_layout.addWidget(self.btn_3d)

        right_panel.setLayout(right_layout)

        # Add panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 740])
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
        self.setMinimumSize(980, 700)

        # Start background jobs
        self.loader = ImageLoader(lat, lon, path)
        self.loader.signals.finished.connect(self.show_image)
        self.loader.signals.failed.connect(self.show_error)
        QThreadPool.globalInstance().start(self.loader)
        self.start_loading()

    # ---------- image ----------
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

    # ---------- location ----------
    def update_location_label(self):
        title = "Observer" if getattr(self, "free_location", False) else f"Tile ({self.x}, {self.y})"
        self.label.setText(
            f"<b>{title}</b> — Lat: {self.lat:.4f}°, Lon: {self.lon:.4f}°, Elev: {self.elevation_m:.0f} m<br>"
            f"<span style='color: #3498db; font-size: 11px;'>Timezone: {self.tz_name} ({format_tz_name(datetime.now(self.tz))})</span>"
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
            os.path.dirname(os.path.abspath(__file__)),
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
        self.pass_model.set_passes([])
        self.btn_3d.setEnabled(False)
        self.details_label.setText("Loading passes...")

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

    # ---------- slider listeners ----------
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

    # ---------- loading ----------
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

    # ---------- time zone ----------
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

    # ---------- satellites ----------
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
        self.details_label.setText(f"Error calculating passes: {msg}")
        self.btn_3d.setEnabled(False)
        self.selected_pass = None

    def apply_filter(self):
        visible_only = self.chk_visible.isChecked()
        favorites_only = self.chk_favorites_only.isChecked()
        search_query = self.txt_search.text().strip()
        max_clouds = self.slider_clouds.value()
        max_mag = self.slider_mag.value() / 10.0

        self.pass_proxy.set_filters(visible_only, favorites_only, max_clouds, max_mag, search_query)
        if not self.all_passes:
            return

        total_geom = sum(1 for p in self.all_passes if p.get("is_geom_visible"))
        total_vis = sum(1 for p in self.all_passes if p.get("is_visible"))
        total_fav = sum(1 for p in self.all_passes if p.get("is_favorite"))
        self.sat_count_label.setText(
            f"{self.pass_proxy.rowCount()} displayed ({total_vis} visible / {total_geom} geom / {total_fav} fav)"
        )

        if self.pass_proxy.rowCount() == 0:
            self.details_label.setText(
                "No passes match the current filter settings. Try adjusting the sliders or unchecking 'Only visible'."
            )
            self.btn_3d.setEnabled(False)
            self.selected_pass = None
            return

        self.sat_table.selectRow(0)
        self.show_details(self.pass_proxy.index(0, 0))

    def on_current_row_changed(self, current, previous):
        if current.isValid():
            self.show_details(self.pass_proxy.index(current.row(), 0))

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
        self.btn_3d.setEnabled(True)

        is_fav = p.get("is_favorite", False)
        fav_name = p.get("favorite_name")
        is_geom = p.get("is_geom_visible", False)
        cloud_pct = p.get("cloud_cover")
        mag = p.get("est_mag")
        tz_abbr = p.get("tz_abbr") or self.tz_abbr

        lines = []
        if is_fav:
            lines.append(
                f"<div style='font-size: 15px; color: #f1c40f;'><b>★ {fav_name}</b> — "
                f"<b>{p['name']}</b> (NORAD {p['norad']})</div>"
            )
        else:
            lines.append(
                f"<div style='font-size: 15px;'><b>{p['name']}</b> (NORAD {p['norad']})</div>"
            )

        if is_geom and (cloud_pct is None or cloud_pct < 40) and (mag is None or mag <= 3.5):
            vis_banner = "<div style='color: #2ecc71; font-size: 13px; font-weight: bold;'>Visible to the naked eye (clear sky and bright)</div>"
        elif is_geom and cloud_pct is not None and cloud_pct >= 40:
            vis_banner = f"<div style='color: #e67e22; font-size: 13px; font-weight: bold;'>Geometrically visible, but obscured by clouds ({cloud_pct}%)</div>"
        elif is_geom and mag is not None and mag > 3.5:
            vis_banner = f"<div style='color: #74b9ff; font-size: 13px; font-weight: bold;'>Geometrically visible, but faint (Mag {mag:+.1f} > 3.5)</div>"
        else:
            vis_banner = f"<div style='color: #e74c3c; font-size: 13px; font-weight: bold;'>Not visible ({p.get('invisibility_reason')})</div>"
        lines.append(vis_banner)

        if is_geom:
            geom_html = "<span style='color: #2ecc71; font-weight: bold;'>Geometrically visible</span> (Elevation ≥ 10°, dark sky, sunlit)"
        else:
            geom_html = f"<span style='color: #e74c3c; font-weight: bold;'>Geometrically not visible</span> ({p.get('invisibility_reason')})"
        lines.append(f"<b>Geometric visibility:</b> {geom_html}")

        if is_geom:
            if cloud_pct is not None and cloud_pct < 40:
                cloud_vis_html = f"<span style='color: #2ecc71; font-weight: bold;'>Visible despite clouds (&lt; 40%)</span> ({cloud_pct}% cloud cover)"
            elif cloud_pct is not None:
                cloud_vis_html = f"<span style='color: #e67e22; font-weight: bold;'>Obscured by clouds (&ge; 40%)</span> ({cloud_pct}% — observation unlikely despite geometry)"
            else:
                cloud_vis_html = "<span style='color: #888;'>Cloud forecast unavailable</span>"
        else:
            cloud_vis_html = "<span style='color: #888;'>— (Pass is not geometrically visible)</span>"
        lines.append(f"<b>Observation conditions:</b> {cloud_vis_html}")

        if mag is None:
            lines.append("<b>Estimated brightness:</b> unknown")
        else:
            mag_desc = (
                "Extremely bright" if mag < -1 else ("Very bright" if mag < 1 else ("Clearly visible" if mag <= 3.5 else "Faint"))
            )
            naked_eye_note = (
                "<span style='color: #2ecc71;'>(Naked-eye visible)</span>"
                if mag <= 3.5
                else "<span style='color: #f39c12;'>(Faint — binoculars recommended)</span>"
            )
            uncertain_note = (
                " <span style='color: #f39c12;'>uncertain (tumbling)</span>"
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
            lines.append(f"<span style='color: #95a5a6; font-size: 11px;'>{' | '.join(parts)}</span>")

        sun_alt = p.get("sun_alt", 0.0)
        sun_desc = "below horizon" if sun_alt < 0 else "above horizon (day)"
        sunlit_html = (
            "<span style='color: #2ecc71;'>Yes (in sunlight)</span>"
            if p.get("sunlit")
            else "<span style='color: #e74c3c;'>No (in Earth's shadow)</span>"
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
                    f"<span style='color: #f39c12;'><b>Moon glare warning:</b> bright Moon "
                    f"{p.get('moon_separation', 0):.0f}° from the satellite</span>"
                )

        c_icon = p.get("cloud_icon", "☁️")
        c_pct = p.get("cloud_pct_str", "--%")
        c_desc = p.get("cloud_desc", "No data")
        c_col = p.get("cloud_color", "#aaa")
        lines.append(
            f"<b>Cloud forecast (Open-Meteo):</b> {c_icon} <span style='color: {c_col}; font-weight: bold;'>{c_pct}</span> ({c_desc})"
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
                " <span style='color: #e67e22;'>older than 3 days — predictions may drift</span>"
                if p.get("tle_old")
                else ""
            )
            lines.append(
                f"<b>TLE epoch:</b> {p['tle_epoch']:%d.%m.%Y %H:%M} {tz_abbr} ({age:.1f} days old){age_warn}"
            )

        self.details_label.setText("<br>".join(lines))

    def open_3d(self):
        if self.selected_pass:
            self.view3d = SatView3D(self.selected_pass, self.lat, self.lon)
            self.view3d.show()











