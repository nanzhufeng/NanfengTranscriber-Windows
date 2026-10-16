"""Shared, recolorable line icons with high-DPI raster backing."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


@lru_cache(maxsize=256)
def icon(name, color="#5269ac", size=20):
    path = Path(__file__).with_name("assets") / "ui-icons" / f"{name}.svg"
    if not path.is_file():
        return QIcon()
    renderer = QSvgRenderer(path.read_bytes().replace(b"currentColor", color.encode("ascii")))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)
