import os

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
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from constants import FAVORITES, MIN_ELEVATION, RESOLUTION, SUN_MAX_ALT
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
    """Worker thread: computes satellite passes and weather over the tile."""

    def __init__(self, lat, lon):
        super().__init__()
        self.lat, self.lon = lat, lon
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

        self.all_passes = []
        self.selected_pass = None
        self.view3d = None

        self.setWindowTitle(f"Satelliten & Detailansicht: Tile ({x}, {y})")
        self.resize(1020, 680)

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

        self.label = QLabel(f"<b>Tile ({x}, {y})</b> — Lat: {lat:.4f}°, Lon: {lon:.4f}°")
        self.label.setStyleSheet("font-size: 14px;")

        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(base, "map_tiles"), exist_ok=True)
        path = os.path.join(base, "map_tiles", f"map_{x * RESOLUTION}_{y * RESOLUTION}.jpg")

        self.image_label = QLabel("Lade NASA-Satellitenbild...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(400, 400)
        self.image_label.setStyleSheet("background-color: #1e1e1e; border: 1px solid #444; border-radius: 4px;")

        # Weather card overview
        self.weather_card = QLabel("Lade Wetter- & Wolkenprognose...")
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
        right_layout.setSpacing(8)

        # Header with title & stats
        header_layout = QHBoxLayout()
        self.sat_title = QLabel("<b>Satelliten-Überflüge (nächste 48 h):</b>")
        self.sat_title.setStyleSheet("font-size: 15px;")
        self.sat_count_label = QLabel("Berechne Überflüge...")
        self.sat_count_label.setStyleSheet("color: #888; font-size: 12px;")
        header_layout.addWidget(self.sat_title)
        header_layout.addStretch()
        header_layout.addWidget(self.sat_count_label)
        right_layout.addLayout(header_layout)

        # Filter bar
        filter_box = QFrame()
        filter_box.setStyleSheet("background-color: #2b2b2b; border-radius: 4px; padding: 6px;")
        filter_layout = QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(6, 6, 6, 6)
        filter_layout.setSpacing(6)

        filter_row1 = QHBoxLayout()
        self.chk_visible = QCheckBox("Nur sichtbare Überflüge (≥10° Höhe, Sonne unter Horizont, beleuchtet)")
        self.chk_visible.setChecked(True)
        self.chk_visible.setStyleSheet("font-weight: bold; color: #4cd137;")
        self.chk_visible.toggled.connect(self.apply_filter)

        self.chk_favorites_only = QCheckBox("Nur Favoriten (ISS, Hubble, Tiangong)")
        self.chk_favorites_only.setChecked(False)
        self.chk_favorites_only.toggled.connect(self.apply_filter)

        filter_row1.addWidget(self.chk_visible)
        filter_row1.addSpacing(12)
        filter_row1.addWidget(self.chk_favorites_only)
        filter_row1.addStretch()

        filter_row2 = QHBoxLayout()
        search_lbl = QLabel("Suche:")
        search_lbl.setStyleSheet("color: #aaa;")
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Nach Satellit oder NORAD suchen...")
        self.txt_search.textChanged.connect(self.apply_filter)
        self.txt_search.setStyleSheet("padding: 4px; border-radius: 3px;")

        filter_row2.addWidget(search_lbl)
        filter_row2.addWidget(self.txt_search)

        filter_layout.addLayout(filter_row1)
        filter_layout.addLayout(filter_row2)
        right_layout.addWidget(filter_box)

        # Satellite list
        self.sat_list = QListWidget()
        self.sat_list.addItem("Lade Satelliten & Wolkenprognose...")
        self.sat_list.itemClicked.connect(self.show_details)
        self.sat_list.setStyleSheet(
            "QListWidget { background-color: #23272a; color: #ecf0f1; border: 1px solid #444; border-radius: 4px; padding: 4px; font-family: Consolas, monospace; }"
            "QListWidget::item { padding: 5px; border-bottom: 1px solid #2f3136; }"
            "QListWidget::item:selected { background-color: #34495e; color: #ffffff; }"
        )
        right_layout.addWidget(self.sat_list, stretch=2)

        # Pass Details card
        self.details_label = QLabel("Klicke auf einen Überflug für detaillierte Sichtbarkeits- und Bahndaten.")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_label.setStyleSheet(
            "background-color: #2b2b2b; color: #ecf0f1; padding: 10px; border-radius: 4px; font-size: 12px; min-height: 110px;"
        )
        right_layout.addWidget(self.details_label, stretch=1)

        # 3D View button
        self.btn_3d = QPushButton("In 3D-Globus öffnen")
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

        # Add both panels to main layout
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, stretch=1)
        self.setLayout(main_layout)

        # Start background jobs
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
                400,
                400,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def show_error(self):
        self.image_label.setText("NASA-Bild konnte nicht geladen werden.")

    # ---------- satellites ----------
    def show_satellites(self, passes):
        self.all_passes = passes
        total_count = len(passes)
        vis_count = sum(1 for p in passes if p.get("is_visible"))
        fav_count = sum(1 for p in passes if p.get("is_favorite"))

        self.weather_card.setText(
            f"<b>Open-Meteo Wolkenprognose:</b> Aktiv<br>"
            f"Gefundene Überflüge: <b>{total_count}</b> (davon <b>{vis_count}</b> mit freiem Auge sichtbar, "
            f"<b>{fav_count}</b> Favoriten-Überflüge)."
        )

        self.apply_filter()

    def show_sat_error(self, msg):
        self.sat_list.clear()
        self.sat_list.addItem(f"Fehler beim Berechnen: {msg}")
        self.sat_count_label.setText("Fehler")

    def apply_filter(self):
        """Filter passes according to visibility, favorites, and search query."""
        if not self.all_passes:
            return

        visible_only = self.chk_visible.isChecked()
        favorites_only = self.chk_favorites_only.isChecked()
        search_query = self.txt_search.text().strip().lower()

        filtered = []
        for p in self.all_passes:
            if visible_only and not p.get("is_visible"):
                continue
            if favorites_only and not p.get("is_favorite"):
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
        total_vis = sum(1 for p in self.all_passes if p.get("is_visible"))
        total_fav = sum(1 for p in self.all_passes if p.get("is_favorite"))
        self.sat_count_label.setText(
            f"{len(filtered)} angezeigt ({total_vis} sichtbar / {total_fav} Favoriten)"
        )

        if not filtered:
            msg = "Keine Überflüge gefunden."
            if visible_only:
                msg = "Keine sichtbaren Überflüge in den nächsten 48h für diese Kachel."
            self.sat_list.addItem(msg)
            self.details_label.setText("Keine Überflüge für die aktuellen Filtereinstellungen.")
            self.btn_3d.setEnabled(False)
            self.selected_pass = None
            return

        for p in filtered:
            is_fav = p.get("is_favorite", False)
            fav_label = p.get("favorite_name")
            is_vis = p.get("is_visible", False)

            # Icon & Prefix
            if is_fav:
                prefix = f"⭐ {fav_label:<8}"
            else:
                prefix = "   " + f"{p['name'][:10]:<8}"

            time_str = f"{p['culm']:%d.%m %H:%M}"
            alt_str = f"max {p['max_alt']:>4.1f}°"

            # Magnitude formatting
            mag_val = p.get("est_mag")
            mag_str = f"Mag {mag_val:>+4.1f}" if mag_val is not None else "Mag  ?.?"

            # Weather cloud cover
            cloud_str = f"{p.get('cloud_icon', '☁️')} {p.get('cloud_pct_str', '--%'):>4}"

            # Visibility status badge
            if is_vis:
                status_badge = "👁️ Sichtbar"
            elif not p.get("sunlit"):
                status_badge = "🌑 Erdschatten"
            elif p.get("sun_alt", 0) >= 0:
                status_badge = "☀️ Tag"
            else:
                status_badge = "📉 <10°"

            line_text = f"{prefix} | {time_str} | {mag_str} | {alt_str} | {cloud_str} | {status_badge}"
            item = QListWidgetItem(line_text)
            item.setData(Qt.ItemDataRole.UserRole, p)

            # Highlight styling for favorites and visible passes
            if is_fav and is_vis:
                item.setForeground(QColor("#f1c40f"))  # Bright Gold
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif is_fav:
                item.setForeground(QColor("#e67e22"))  # Orange / Bronze for non-visible favorite
            elif is_vis:
                item.setForeground(QColor("#2ecc71"))  # Emerald Green for visible pass
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

        # Visibility status
        if p.get("is_visible"):
            vis_html = "<span style='color: #2ecc71; font-weight: bold;'>👁️ Sichtbar mit freiem Auge</span>"
        else:
            vis_html = f"<span style='color: #e74c3c; font-weight: bold;'>❌ Nicht sichtbar</span> ({p.get('invisibility_reason')})"
        lines.append(f"<b>Sichtbarkeit:</b> {vis_html}")

        # Estimated magnitude
        mag = p.get("est_mag", 5.0)
        mag_desc = (
            "Extrem hell" if mag < -1 else ("Sehr hell" if mag < 1 else ("Gut sichtbar" if mag < 3.5 else "Schwach"))
        )
        lines.append(f"<b>Geschätzte Helligkeit:</b> <b>Mag {mag:+.1f}</b> ({mag_desc})")

        # Sun & Illumination
        sun_alt = p.get("sun_alt", 0.0)
        sun_desc = "unter Horizont" if sun_alt < 0 else "über Horizont (Tag)"
        sunlit_html = (
            "<span style='color: #2ecc71;'>Ja (im Sonnenlicht)</span>"
            if p.get("sunlit")
            else "<span style='color: #e74c3c;'>Nein (im Erdschatten)</span>"
        )
        lines.append(f"<b>Sonnenhöhe:</b> {sun_alt:+.1f}° ({sun_desc}) | <b>Angestrahlt:</b> {sunlit_html}")

        # Cloud Forecast (Open-Meteo)
        cloud_pct = p.get("cloud_cover")
        c_icon = p.get("cloud_icon", "☁️")
        c_pct = p.get("cloud_pct_str", "--%")
        c_desc = p.get("cloud_desc", "Keine Daten")
        c_col = p.get("cloud_color", "#aaa")
        lines.append(
            f"<b>Wolkenprognose (Open-Meteo):</b> {c_icon} <span style='color: {c_col}; font-weight: bold;'>{c_pct}</span> ({c_desc})"
        )

        # Timing & Azimuth
        if "rise" in p:
            lines.append(
                f"<b>Aufgang:</b> {p['rise']:%H:%M:%S} Richtung <b>{compass(p['rise_az'])}</b> ({p['rise_az']:.0f}°)"
            )
        lines.append(
            f"<b>Höchststand:</b> {p['culm']:%H:%M:%S}, <b>{p['max_alt']}°</b> Richtung <b>{compass(p['culm_az'])}</b> ({p['culm_az']:.0f}°)"
        )
        lines.append(
            f"<b>Untergang:</b> {p['set']:%H:%M:%S} Richtung <b>{compass(p['set_az'])}</b> ({p['set_az']:.0f}°)"
        )

        if "rise" in p:
            secs = int((p["set"] - p["rise"]).total_seconds())
            lines.append(f"<b>Dauer:</b> {secs // 60} min {secs % 60} s")

        lines.append(
            f"<b>Distanz beim Höchststand:</b> {p['distance_km']:.0f} km | <b>Höhe:</b> {p['height_km']:.0f} km | <b>Tempo:</b> {p['speed_kms']:.2f} km/s"
        )
        lines.append(f"<b>TLE-Datenstand:</b> {p['tle_epoch']:%d.%m.%Y %H:%M}")

        self.details_label.setText("<br>".join(lines))

    # ---------- 3D ----------
    def open_3d(self):
        if self.selected_pass:
            self.view3d = SatView3D(self.selected_pass, self.lat, self.lon)
            self.view3d.show()
