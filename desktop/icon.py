"""App icon drawn with QPainter, so no binary asset has to ship with the source."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

SIZES = (16, 24, 32, 48, 64, 128, 256)


def icon_image(size=256):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 256, size / 256)

    gradient = QLinearGradient(0, 0, 256, 256)
    gradient.setColorAt(0, QColor('#fb923c'))
    gradient.setColorAt(1, QColor('#ea580c'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(QRectF(12, 12, 232, 232), 52, 52)

    # A hand-drawn squiggle on the "paper".
    stroke = QPainterPath(QPointF(48, 186))
    stroke.cubicTo(78, 150, 98, 214, 128, 182)
    stroke.cubicTo(150, 158, 160, 196, 186, 178)
    painter.setPen(QPen(QColor('#1f2937'), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(stroke)

    # Pencil, tip resting at the end of the stroke.
    painter.translate(186, 172)
    painter.rotate(-45)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#fff7ed'))
    painter.drawRoundedRect(QRectF(26, -17, 120, 34), 6, 6)
    painter.setBrush(QColor('#fde68a'))
    painter.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(28, -17), QPointF(28, 17)]))
    painter.setBrush(QColor('#1f2937'))
    painter.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(10, -6), QPointF(10, 6)]))
    painter.setBrush(QColor('#fdba74'))
    painter.drawRect(QRectF(126, -17, 12, 34))
    painter.end()
    return image


def app_icon():
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(QPixmap.fromImage(icon_image(size)))
    return icon


def save_icon(path):
    """Write a multi-resolution .ico (via Qt's ICO plugin) or a single PNG, depending on the suffix."""
    if str(path).lower().endswith('.png'):
        return icon_image(256).save(str(path))
    from PIL import Image

    image = icon_image(256)
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(rgba.constBits())[:256 * 256 * 4]
    Image.frombytes('RGBA', (256, 256), data).save(str(path), sizes=[(s, s) for s in SIZES])
    return True
