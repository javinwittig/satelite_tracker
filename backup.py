import sys
import os
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget, QGridLayout, QPushButton
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt, QSize
from constants import RESOLUTION
from tile_details import *

TILES_X = 99
TILES_Y = 50
TILE_SIZE = 10


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.buttons = [[None for _ in range(TILES_X)] for _ in range(TILES_Y)]

        self.setWindowTitle("My PyQt6 App")

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
                    print("Nicht gefunden:", path)

                button = QPushButton()
                button.setIcon(QIcon(pixmap))
                button.setIconSize(QSize(TILE_SIZE, TILE_SIZE))
                button.setFixedSize(TILE_SIZE, TILE_SIZE)
                button.setFlat(True)
                button.setStyleSheet("border: none; padding: 0px;")

                button.clicked.connect(
                    lambda checked, r=row, c=col: self.on_tile_click(r, c)
                )

                self.buttons[row][col] = button
                layout.addWidget(button, row, col)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
    def on_tile_click(self, row, col):
        button = self.buttons[row][col]
        button.setIcon(QIcon())  # Bild entfernen
        button.setStyleSheet("border: none; padding: 0px; background-color: red;")

        self.tile_details = TileDetails(row, col)
        self.tile_details.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())