import sys
import os
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QGridLayout, QPushButton
from PyQt6.QtGui import QColor, QPalette, QPixmap, QIcon
from PyQt6.QtCore import Qt, QSize
from constants import RESOLUTION
from geo_calc import tile_to_latlon
from tile_details import *

TILES_X = 99
TILES_Y = 50
TILE_SIZE = 10

TILE_STYLE = (
    "QPushButton { border: none; padding: 0px; background-color: transparent; }"
    "QPushButton:hover { background-color: rgba(52, 152, 219, 90); }"
)
TILE_SELECTED_STYLE = (
    "QPushButton { border: 1px solid #e74c3c; padding: 0px; background-color: rgba(231, 76, 60, 110); }"
)
DARK_STYLE = """
QToolTip {
    background-color: #2b2b2b;
    color: #ecf0f1;
    border: 1px solid #555;
    padding: 4px;
}
QTableView {
    background-color: #23272a;
    alternate-background-color: #262b2f;
    color: #ecf0f1;
    gridline-color: #3a3a3a;
    border: 1px solid #444;
    border-radius: 4px;
    selection-background-color: #34495e;
    selection-color: #ffffff;
    font-family: Consolas, monospace;
    font-size: 12px;
}
QHeaderView::section {
    background-color: #2b2b2b;
    color: #bdc3c7;
    border: none;
    border-right: 1px solid #3a3a3a;
    border-bottom: 1px solid #3a3a3a;
    padding: 5px;
    font-weight: bold;
}
QTableCornerButton::section {
    background-color: #2b2b2b;
    border: none;
}
QProgressBar {
    background-color: #2b2b2b;
    color: #ecf0f1;
    border: 1px solid #444;
    border-radius: 3px;
    text-align: center;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #2980b9;
}
QComboBox {
    background-color: #2b2b2b;
    color: #ecf0f1;
    border: 1px solid #444;
    border-radius: 3px;
    padding: 2px 6px;
}
QComboBox QAbstractItemView {
    background-color: #2b2b2b;
    color: #ecf0f1;
    selection-background-color: #34495e;
}
QScrollBar:vertical {
    background: #23272a;
    width: 12px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #4a4f54;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar:horizontal {
    background: #23272a;
    height: 12px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #4a4f54;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
}
"""


def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#ecf0f1"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#23272a"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#262b2f"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#ecf0f1"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2b2b2b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ecf0f1"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#34495e"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2b2b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ecf0f1"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
    app.setPalette(palette)
    app.setStyleSheet(DARK_STYLE)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.buttons = [[None for _ in range(TILES_X)] for _ in range(TILES_Y)]
        self.selected_button = None

        self.setWindowTitle("Satellite Tracker")

        layout = QGridLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        base = os.path.dirname(os.path.abspath(__file__))

        for row in range(TILES_Y):
            for col in range(TILES_X):
                path = os.path.join(
                    base, "map_tiles",
                    f"map_{row * RESOLUTION}_{col * RESOLUTION}.png"
                )
                pixmap = QPixmap(path).scaled(
                    TILE_SIZE, TILE_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if pixmap.isNull():
                    print("not found:", path)

                button = QPushButton()
                button.setIcon(QIcon(pixmap))
                button.setIconSize(QSize(TILE_SIZE, TILE_SIZE))
                button.setFixedSize(TILE_SIZE, TILE_SIZE)
                button.setFlat(True)
                button.setStyleSheet(TILE_STYLE)
                lat, lon = tile_to_latlon(row, col)
                button.setToolTip(
                    f"Tile ({row}, {col})\nLat {lat:.3f}°, Lon {lon:.3f}°\nClick for passes"
                )

                button.clicked.connect(
                    lambda checked, r=row, c=col: self.on_tile_click(r, c)
                ) 

                self.buttons[row][col] = button
                layout.addWidget  (button, row, col)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.resize(1000, 520)

    def on_tile_click(self, row, col):
        button = self.buttons[row][col]
        if self.selected_button is not None:
            self.selected_button.setStyleSheet(TILE_STYLE)
        button.setStyleSheet(TILE_SELECTED_STYLE)
        self.selected_button = button

        self.tile_details = TileDetails(row, col)
        self.tile_details.show()







if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())









