import os
from datetime import datetime

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSplitter,
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
from geo_calc import format_tz_name, get_timezone_for_latlon, tile_to_latlon
from handler.nasa_handler import get_img
from handler.satellite_handler import get_passes
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
    """Worker thread: computes satellite passes and weather over the tile."""

    def __init__(self, lat, lon, tz=None):
        super().__init__()
        self.lat, self.lon = lat, lon
        self.tz = tz
        self.signals = SatSignals()
        self.setAutoDelete(False)

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
            )
            print(f"GUI: {len(passes)} passes loaded for {self.lat:.2f}, {self.lon:.2f}")
            self.signals.finished.emit(passes)
        except Exception as e:
            print("Satellite error:", e)
            self.signals.failed.emit(str(e))


class TileDetails(QWidget):
    def __init__(self, x, y):
        super().__init__()
        self.x, self.y = x, y
        lat, lon = tile_to_latlon(x, y)
        self.lat, self.lon = lat, lon

        # Derive tile's local timezone
        self.tz, self.tz_name = get_timezone_for_latlon(lat, lon)
        tz_abbr = format_tz_name(datetime.now(self.tz))
        self.tz_abbr = tz_abbr

        self.all_passes = []
        self.selected_pass = None
        self.view3d = None

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

        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(base, "map_tiles"), exist_ok=True)
        path = os.path.join(base, "map_tiles", f"map_{x * RESOLUTION}_{y * RESOLUTION}.jpg")

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
        left_layout.addWidget(self.image_label)
        left_layout.addWidget(self.weather_card)
        left_layout.addStretch()
        left_panel.setLayout(left_layout)
        left_panel.setFixedWidth(410)

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
        header_layout.addWidget(self.sat_count_label)
        right_layout.addLayout(header_layout)

        # Filter box
        filter_box = QFrame()
        filter_box.setStyleSheet("background-color: #2b2b2b; border-radius: 4px; padding: 6px;")
        filter_layout = QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(8, 8, 8, 8)
        filter_layout.setSpacing(6)

        # Row 1: Checkboxes & Reset
        filter_row1 = QHBoxLayout()
        self.chk_visible = QCheckBox("Only visible (≥10° elev, dark sky, illuminated)")
        self.chk_visible.setChecked(True)
        self.chk_visible.setStyleSheet("font-weight: bold; color: #4cd137;")
        self.chk_visible.toggled.connect(self.apply_filter)

        self.chk_favorites_only = QCheckBox("Only favorites (ISS, Hubble, Tiangong)")
        self.chk_favorites_only.setChecked(False)
        self.chk_favorites_only.toggled.connect(self.apply_filter)

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
        self.slider_mag.setValue(int(DEFAULT_MAX_MAGNITUDE * 10))
        self.slider_mag.setToolTip("Filter passes by maximum apparent magnitude / brightness (default ≤ +3.5)")
        self.slider_mag.valueChanged.connect(self.on_mag_slider_changed)

        filter_row2.addWidget(self.lbl_cloud)
        filter_row2.addWidget(self.slider_clouds)
        filter_row2.addSpacing(14)
        filter_row2.addWidget(self.lbl_mag)
        filter_row2.addWidget(self.slider_mag)

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

        # Column header above satellite list for clear tabular layout
        self.col_header = QLabel(
            "   Satellite       | Culm (Local Time)   | Mag     | Max Alt  | Clouds | Visibility Status"
        )
        self.col_header.setStyleSheet(
            "color: #95a5a6; font-family: Consolas, monospace; font-size: 11px; padding: 2px 6px; font-weight: bold;"
        )
        right_layout.addWidget(self.col_header)

        # Satellite list widget
        self.sat_list = QListWidget()
        self.sat_list.addItem("Loading satellites & cloud forecast...")
        self.sat_list.itemClicked.connect(self.show_details)
        self.sat_list.setStyleSheet(
            "QListWidget { background-color: #23272a; color: #ecf0f1; border: 1px solid #444; border-radius: 4px; padding: 4px; font-family: Consolas, monospace; font-size: 12px; }"
            "QListWidget::item { padding: 4px; border-bottom: 1px solid #2f3136; }"
            "QListWidget::item:selected { background-color: #34495e; color: #ffffff; }"
        )
        right_layout.addWidget(self.sat_list, stretch=2)

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
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, stretch=1)
        self.setLayout(main_layout)

        # Start background jobs
        self.loader = ImageLoader(lat, lon, path)
        self.loader.signals.finished.connect(self.show_image)
        self.loader.signals.failed.connect(self.show_error)
        QThreadPool.globalInstance().start(self.loader)

        self.sat_loader = SatLoader(lat, lon, tz=self.tz)
        self.sat_loader.signals.finished.connect(self.show_satellites)
        self.sat_loader.signals.failed.connect(self.show_sat_error)
        QThreadPool.globalInstance().start(self.sat_loader)

    # ---------- image ----------
    def show_image(self, path):
        pixmap = QPixmap(path)
        self.image_label.setPixmap(
            pixmap.scaled(
                400,
                400,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def show_error(self):
        self.image_label.setText("Could not load NASA image.")

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
        self.slider_clouds.setValue(DEFAULT_MAX_CLOUDS)
        self.slider_mag.setValue(int(DEFAULT_MAX_MAGNITUDE * 10))
        self.txt_search.clear()
        self.apply_filter()

    # ---------- satellites ----------
    def show_satellites(self, passes):
        self.all_passes = passes
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

        self.apply_filter()

    def show_sat_error(self, msg):
        self.sat_list.clear()
        self.sat_list.addItem(f"Error calculating: {msg}")
        self.sat_count_label.setText("Error")

    def apply_filter(self):
        """Filter passes according to visibility, cloud limit, magnitude limit, favorites, and search."""
        if not self.all_passes:
            return

        visible_only = self.chk_visible.isChecked()
        favorites_only = self.chk_favorites_only.isChecked()
        search_query = self.txt_search.text().strip().lower()
        max_clouds = self.slider_clouds.value()
        max_mag = self.slider_mag.value() / 10.0

        filtered = []
        for p in self.all_passes:
            if visible_only and not p.get("is_geom_visible"):
                continue
            if favorites_only and not p.get("is_favorite"):
                continue
            if p.get("est_mag") is not None and p.get("est_mag") > max_mag:
                continue
            if p.get("cloud_cover") is not None and p.get("cloud_cover") > max_clouds:
                continue
            if search_query:
                s_name = p.get("name", "").lower()
                s_fav = (p.get("favorite_name") or "").lower()
                s_norad = str(p.get("norad", ""))
                if (search_query not in s_name) and (search_query not in s_fav) and (search_query not in s_norad):
                    continue
            filtered.append(p)

        # Always pin favorites to top, then chronological by culmination
        filtered.sort(key=lambda p: (0 if p.get("is_favorite") else 1, p["culm"]))

        self.sat_list.clear()
        total_geom = sum(1 for p in self.all_passes if p.get("is_geom_visible"))
        total_vis = sum(1 for p in self.all_passes if p.get("is_visible"))
        total_fav = sum(1 for p in self.all_passes if p.get("is_favorite"))
        self.sat_count_label.setText(
            f"{len(filtered)} displayed ({total_vis} visible / {total_geom} geom / {total_fav} fav)"
        )

        if not filtered:
            msg = "No passes found matching filter settings."
            self.sat_list.addItem(msg)
            self.details_label.setText("No passes match the current filter settings. Try adjusting the sliders or unchecking 'Only visible'.")
            self.btn_3d.setEnabled(False)
            self.selected_pass = None
            return

        for p in filtered:
            is_fav = p.get("is_favorite", False)
            fav_label = p.get("favorite_name")
            is_geom = p.get("is_geom_visible", False)
            c_pct = p.get("cloud_cover")
            m_val = p.get("est_mag")

            # Icon & Prefix
            if is_fav:
                prefix = f"⭐ {fav_label:<10}"
            else:
                prefix = "   " + f"{p['name'][:12]:<10}"

            # Time string with local timezone abbreviation
            tz_abbr = p.get("tz_abbr") or self.tz_abbr
            time_str = f"{p['culm']:%d.%m %H:%M} {tz_abbr:<4}"
            alt_str = f"max {p['max_alt']:>4.1f}°"

            # Magnitude formatting
            mag_str = f"Mag {m_val:>+4.1f}" if m_val is not None else "Mag  ?.?"

            # Weather cloud cover
            cloud_str = f"{p.get('cloud_icon', '☁️')} {p.get('cloud_pct_str', '--%'):>4}"

            # Visibility status badge
            if is_geom:
                if c_pct is not None and c_pct >= 40:
                    status_badge = f"Geom. (☁️{c_pct}%)"
                elif m_val is not None and m_val > 3.5:
                    status_badge = f"Faint (+{m_val:.1f})"
                else:
                    status_badge = "✨ Visible (<40% ☁️)"
            elif not p.get("sunlit"):
                status_badge = "🌑 Earth shadow"
            elif p.get("sun_alt", 0) >= 0:
                status_badge = "☀️ Day"
            else:
                status_badge = "📉 <10°"

            line_text = f"{prefix} | {time_str} | {mag_str} | {alt_str} | {cloud_str} | {status_badge}"
            item = QListWidgetItem(line_text)
            item.setData(Qt.ItemDataRole.UserRole, p)

            # Highlight styling for favorites and visible passes
            if is_fav and is_geom and (c_pct is None or c_pct < 40) and (m_val is None or m_val <= 3.5):
                item.setForeground(QColor("#f1c40f"))  # Bright Gold
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif is_fav:
                item.setForeground(QColor("#e67e22"))  # Orange / Bronze for non-visible favorite
            elif is_geom and (c_pct is None or c_pct < 40) and (m_val is None or m_val <= 3.5):
                item.setForeground(QColor("#2ecc71"))  # Emerald Green for truly visible pass
            elif is_geom and (c_pct is not None and c_pct >= 40):
                item.setForeground(QColor("#e67e22"))  # Amber / Dark Orange for cloudy pass
            elif is_geom and (m_val is not None and m_val > 3.5):
                item.setForeground(QColor("#74b9ff"))  # Muted blue for faint pass
            else:
                item.setForeground(QColor("#888888"))  # Dimmed grey for non-visible passes

            self.sat_list.addItem(item)

        # Retain selection or select first
        self.sat_list.setCurrentRow(0)
        self.show_details(self.sat_list.item(0))

    def show_details(self, item):
        if not item:
            return
        p = item.data(Qt.ItemDataRole.UserRole)
        if not p:
            return

        self.selected_pass = p
        self.btn_3d.setEnabled(True)

        is_fav = p.get("is_favorite", False)
        fav_name = p.get("favorite_name")
        is_geom = p.get("is_geom_visible", False)
        cloud_pct = p.get("cloud_cover")
        mag = p.get("est_mag", 5.0)
        tz_abbr = p.get("tz_abbr") or self.tz_abbr

        lines = []
        if is_fav:
            lines.append(
                f"<div style='font-size: 15px; color: #f1c40f;'><b>⭐ {fav_name}</b> — "
                f"<b>{p['name']}</b> (NORAD {p['norad']})</div>"
            )
        else:
            lines.append(
                f"<div style='font-size: 15px;'><b>{p['name']}</b> (NORAD {p['norad']})</div>"
            )

        # Overall Status Banner
        if is_geom and (cloud_pct is None or cloud_pct < 40) and (mag is None or mag <= 3.5):
            vis_banner = "<div style='color: #2ecc71; font-size: 13px; font-weight: bold;'>🌟 Visible to the naked eye (clear sky & bright)</div>"
        elif is_geom and cloud_pct is not None and cloud_pct >= 40:
            vis_banner = f"<div style='color: #e67e22; font-size: 13px; font-weight: bold;'>☁️ Geometrically visible, but obscured by clouds ({cloud_pct}%)</div>"
        elif is_geom and mag is not None and mag > 3.5:
            vis_banner = f"<div style='color: #74b9ff; font-size: 13px; font-weight: bold;'>🔭 Geometrically visible, but faint (Mag {mag:+.1f} > 3.5)</div>"
        else:
            vis_banner = f"<div style='color: #e74c3c; font-size: 13px; font-weight: bold;'>❌ Not visible ({p.get('invisibility_reason')})</div>"
        lines.append(vis_banner)

        # 1. Geometric visibility
        if is_geom:
            geom_html = "<span style='color: #2ecc71; font-weight: bold;'>✔ Geometrically visible</span> (Elevation ≥ 10°, dark sky, sunlit)"
        else:
            geom_html = f"<span style='color: #e74c3c; font-weight: bold;'>❌ Geometrically not visible</span> ({p.get('invisibility_reason')})"
        lines.append(f"<b>Geometric visibility:</b> {geom_html}")

        # 2. Cloud visibility (< 40%)
        if is_geom:
            if cloud_pct is not None and cloud_pct < 40:
                cloud_vis_html = f"<span style='color: #2ecc71; font-weight: bold;'>✔ Visible despite clouds (&lt; 40%)</span> ({cloud_pct}% cloud cover)"
            elif cloud_pct is not None:
                cloud_vis_html = f"<span style='color: #e67e22; font-weight: bold;'>⚠️ Obscured by clouds (&ge; 40%)</span> ({cloud_pct}% — observation unlikely despite geometry)"
            else:
                cloud_vis_html = "<span style='color: #888;'>❓ Cloud forecast unavailable</span>"
        else:
            cloud_vis_html = "<span style='color: #888;'>— (Pass is not geometrically visible)</span>"
        lines.append(f"<b>Observation conditions:</b> {cloud_vis_html}")

        # Estimated magnitude with naked-eye assessment
        mag_desc = (
            "Extremely bright" if mag < -1 else ("Very bright" if mag < 1 else ("Clearly visible" if mag <= 3.5 else "Faint"))
        )
        naked_eye_note = (
            "<span style='color: #2ecc71;'>(Naked-eye visible)</span>"
            if mag <= 3.5
            else "<span style='color: #f39c12;'>(Faint — binoculars recommended)</span>"
        )
        lines.append(f"<b>Estimated brightness:</b> <b>Mag {mag:+.1f}</b> ({mag_desc}) {naked_eye_note}")

        # Sun & Illumination
        sun_alt = p.get("sun_alt", 0.0)
        sun_desc = "below horizon" if sun_alt < 0 else "above horizon (day)"
        sunlit_html = (
            "<span style='color: #2ecc71;'>Yes (in sunlight)</span>"
            if p.get("sunlit")
            else "<span style='color: #e74c3c;'>No (in Earth's shadow)</span>"
        )
        lines.append(f"<b>Sun elevation:</b> {sun_alt:+.1f}° ({sun_desc}) | <b>Illuminated:</b> {sunlit_html}")

        # Cloud Forecast (Open-Meteo)
        c_icon = p.get("cloud_icon", "☁️")
        c_pct = p.get("cloud_pct_str", "--%")
        c_desc = p.get("cloud_desc", "No data")
        c_col = p.get("cloud_color", "#aaa")
        lines.append(
            f"<b>Cloud forecast (Open-Meteo):</b> {c_icon} <span style='color: {c_col}; font-weight: bold;'>{c_pct}</span> ({c_desc})"
        )

        # Timing & Azimuth with local timezone
        if "rise" in p:
            lines.append(
                f"<b>Rise:</b> {p['rise']:%H:%M:%S} {tz_abbr} direction <b>{compass(p['rise_az'])}</b> ({p['rise_az']:.0f}°)"
            )
        lines.append(
            f"<b>Culmination:</b> {p['culm']:%H:%M:%S} {tz_abbr}, <b>{p['max_alt']}°</b> direction <b>{compass(p['culm_az'])}</b> ({p['culm_az']:.0f}°)"
        )
        lines.append(
            f"<b>Set:</b> {p['set']:%H:%M:%S} {tz_abbr} direction <b>{compass(p['set_az'])}</b> ({p['set_az']:.0f}°)"
        )

        if "rise" in p:
            secs = int((p["set"] - p["rise"]).total_seconds())
            lines.append(f"<b>Duration:</b> {secs // 60} min {secs % 60} s")

        lines.append(
            f"<b>Distance at culmination:</b> {p['distance_km']:.0f} km | <b>Height:</b> {p['height_km']:.0f} km | <b>Speed:</b> {p['speed_kms']:.2f} km/s"
        )
        lines.append(f"<b>TLE epoch:</b> {p['tle_epoch']:%d.%m.%Y %H:%M} {tz_abbr}")

        self.details_label.setText("<br>".join(lines))

  
    def open_3d(self):
        if self.selected_pass:
            self.view3d = SatView3D(self.selected_pass, self.lat, self.lon)
            self.view3d.show()











