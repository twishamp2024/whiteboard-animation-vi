"""Media widgets: the source-image drop area and the looping result player."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPalette, QPen, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider, QStyle,
                               QToolButton, QVBoxLayout, QWidget)

IMAGE_SUFFIXES = {'.' + bytes(fmt).decode().lower() for fmt in QImageReader.supportedImageFormats()}


def _time(ms):
    seconds = max(0, ms) // 1000
    return f'{seconds // 60}:{seconds % 60:02d}'


class ImageDropArea(QFrame):
    """Shows the source image; click to browse, or drop an image file onto it."""

    fileDropped = Signal(str)
    browseRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(QSize(280, 220))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pixmap = None
        self.hover = False

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.setToolTip('' if pixmap is None else f'{pixmap.width()} × {pixmap.height()} px — click to replace')
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.browseRequested.emit()

    @staticmethod
    def _image_path(event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in IMAGE_SUFFIXES:
                return path
        return None

    def dragEnterEvent(self, event):
        if self._image_path(event):
            self.hover = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.hover = False
        self.update()

    def dropEvent(self, event):
        self.hover = False
        self.update()
        path = self._image_path(event)
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(str(path))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        palette = self.palette()
        area = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        accent = palette.color(QPalette.ColorRole.Highlight)
        pen = QPen(accent if self.hover else palette.color(QPalette.ColorRole.Mid), 2 if self.hover else 1.2)
        if self.pixmap is None or self.hover:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(area, 10, 10)
        if self.pixmap is not None:
            inner = area.adjusted(10, 10, -10, -10)
            scaled = self.pixmap.size().scaled(inner.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(inner.center())
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        if self.pixmap is None or self.hover:
            text = QColor(palette.color(QPalette.ColorRole.Text))
            text.setAlphaF(.7)
            painter.setPen(text)
            font = painter.font()
            font.setPointSizeF(font.pointSizeF() * 1.15)
            painter.setFont(font)
            message = ('Drop to load this image' if self.hover else
                       'Drop an image here\nor click to browse  ·  Ctrl+V to paste')
            if self.pixmap is not None:
                painter.fillRect(area, QColor(0, 0, 0, 90))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, message)


class VideoPanel(QWidget):
    """Plays the rendered MP4 with play/pause, seek and loop controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.video = QVideoWidget()
        self.video.setMinimumSize(QSize(280, 200))
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.player.setVideoOutput(self.video)
        self.placeholder = QLabel('Your animation will appear here after rendering.')
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)

        self.play = QToolButton()
        self.play.setAutoRaise(True)
        self.play.clicked.connect(self.toggle)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.clock = QLabel('0:00 / 0:00')
        self.loop = QCheckBox('Loop')
        self.loop.setChecked(True)
        self.loop.toggled.connect(self._apply_loop)

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 0, 4, 0)
        controls.addWidget(self.play)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.clock)
        controls.addWidget(self.loop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.placeholder, 1)
        layout.addWidget(self.video, 1)
        layout.addLayout(controls)
        self.video.hide()

        self.player.durationChanged.connect(self._duration)
        self.player.positionChanged.connect(self._position)
        self.player.playbackStateChanged.connect(self._state)
        self._apply_loop(True)
        self._state()
        self.set_enabled(False)

    def set_enabled(self, enabled):
        for widget in (self.play, self.seek, self.loop):
            widget.setEnabled(enabled)

    def load(self, path):
        self.placeholder.hide()
        self.video.show()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.set_enabled(True)
        self.player.play()

    def clear(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.video.hide()
        self.placeholder.show()
        self.set_enabled(False)

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _apply_loop(self, on):
        self.player.setLoops(QMediaPlayer.Loops.Infinite if on else QMediaPlayer.Loops.Once)

    def _duration(self, duration):
        self.seek.setRange(0, duration)
        self._position(self.player.position())

    def _position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.clock.setText(f'{_time(position)} / {_time(self.player.duration())}')

    def _state(self, *_):
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        icon = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.play.setIcon(self.style().standardIcon(icon))
        self.play.setToolTip('Pause' if playing else 'Play')
