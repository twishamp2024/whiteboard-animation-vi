"""Main window: source image, result player, every native setting and the render queue of one."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import QByteArray, QSettings, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from handdraw.settings import Settings

from . import APP_NAME, APP_VERSION, MODEL_PATH
from .controls import SettingsPanel
from .icon import app_icon
from .widgets import IMAGE_SUFFIXES, ImageDropArea, VideoPanel
from .workers import EnvironmentProbe, ModelDownloadWorker, RenderWorker, download_progress

LOGGER = logging.getLogger(__name__)
MAX_PIXELS = 32_000_000  # fit_image() limit
MODEL_MB = 195


def _spawn(worker, name):
    # Daemon threads: closing the window never waits on an uninterruptible plan or download.
    # Worker signals are emitted off the GUI thread, so Qt queues them to MainWindow's slots.
    thread = threading.Thread(target=worker.run, name=name, daemon=True)
    thread.start()
    return thread


def _clock(seconds):
    seconds = max(0, int(round(seconds)))
    return f'{seconds // 60}:{seconds % 60:02d}'


class NoticeBar(QWidget):
    """Stack of dismissable notices with optional action buttons, keyed so each can be replaced."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = {}
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        self.hide()

    def set(self, key, text, actions=(), warning=False):
        self.remove(key)
        frame = QFrame()
        color = '220, 38, 38' if warning else '249, 115, 22'
        frame.setStyleSheet(f'QFrame#notice {{ background: rgba({color}, .13); '
                            f'border: 1px solid rgba({color}, .55); border-radius: 6px; }}')
        frame.setObjectName('notice')
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 6, 6, 6)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(label, 1)
        for caption, callback in actions:
            button = QPushButton(caption)
            button.clicked.connect(callback)
            row.addWidget(button)
        close = QPushButton('✕')
        close.setFlat(True)
        close.setFixedWidth(28)
        close.setToolTip('Dismiss')
        close.clicked.connect(lambda: self.remove(key))
        row.addWidget(close)
        self.rows[key] = frame
        self.layout_.addWidget(frame)
        self.show()

    def remove(self, key):
        frame = self.rows.pop(key, None)
        if frame is not None:
            frame.deleteLater()
        self.setVisible(bool(self.rows))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.store = QSettings()
        self.env = None
        self.image = None
        self.image_name = None
        self.output = None
        self.render_worker = None
        self.download_worker = None
        self.probe = None
        self.render_thread = None
        self.started = 0.
        self._stage_text = 'Starting…'
        self._build()
        self._restore()
        self._probe_environment()

    # ----------------------------------------------------------------- layout
    def _build(self):
        self.drop = ImageDropArea()
        self.drop.browseRequested.connect(self.open_image)
        self.drop.fileDropped.connect(self.load_image)
        self.image_info = QLabel('No image loaded')
        source = QWidget()
        column = QVBoxLayout(source)
        column.setContentsMargins(0, 0, 0, 0)
        title = QLabel('<b>Original image</b>')
        column.addWidget(title)
        column.addWidget(self.drop, 1)
        column.addWidget(self.image_info)

        self.player = VideoPanel()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlaceholderText('The JSON render report appears here after a render.')
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.addWidget(self.summary)
        details_layout.addWidget(self.report_view, 1)
        self.result_tabs = QTabWidget()
        self.result_tabs.addTab(self.player, 'Rendered video')
        self.result_tabs.addTab(details, 'Render details')

        media = QSplitter(Qt.Orientation.Horizontal)
        media.addWidget(source)
        media.addWidget(self.result_tabs)
        media.setChildrenCollapsible(False)
        media.setSizes([1, 1])

        self.panel = SettingsPanel()
        self.panel.setMinimumWidth(340)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(media)
        self.splitter.addWidget(self.panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([900, 380])

        self.render_button = QPushButton('Render && export MP4')
        self.render_button.setMinimumHeight(42)
        self.render_button.setMinimumWidth(220)
        self.render_button.setStyleSheet(
            'QPushButton { background: #ea580c; color: white; font-weight: 600; border-radius: 6px; '
            'padding: 6px 18px; border: none; } QPushButton:hover { background: #f97316; } '
            'QPushButton:disabled { background: rgba(234, 88, 12, .4); color: rgba(255,255,255,.75); }')
        self.render_button.clicked.connect(self.start_render)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setMinimumHeight(42)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_render)
        self.save_button = QPushButton('Save video as…')
        self.save_button.setMinimumHeight(42)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_video)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.stage = QLabel('Load an image to begin.')

        progress_column = QVBoxLayout()
        progress_column.addWidget(self.stage)
        progress_column.addWidget(self.progress)
        actions = QHBoxLayout()
        actions.addWidget(self.render_button)
        actions.addWidget(self.cancel_button)
        actions.addLayout(progress_column, 1)
        actions.addWidget(self.save_button)

        self.notices = NoticeBar()
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.notices)
        layout.addWidget(self.splitter, 1)
        layout.addLayout(actions)
        self.setCentralWidget(central)

        self.engine_label = QLabel('Loading rendering engine…')
        self.statusBar().addPermanentWidget(self.engine_label)
        self.tick = QTimer(self)
        self.tick.setInterval(500)
        self.tick.timeout.connect(self._tick)
        self._menus()
        self._update_buttons()

    def _menus(self):
        def action(menu, text, slot, shortcut=None):
            item = QAction(text, self)
            item.triggered.connect(slot)
            if shortcut:
                item.setShortcuts(shortcut if isinstance(shortcut, list) else [QKeySequence(shortcut)])
            menu.addAction(item)
            return item

        file = self.menuBar().addMenu('&File')
        action(file, '&Open image…', self.open_image, QKeySequence.StandardKey.Open)
        action(file, '&Paste image', self.paste_image, QKeySequence.StandardKey.Paste)
        file.addSeparator()
        self.save_action = action(file, '&Save video as…', self.save_video, QKeySequence.StandardKey.Save)
        self.reveal_action = action(file, 'Show video in &folder', self.reveal_video)
        action(file, 'Open &output folder', self.open_output_folder)
        action(file, 'Change output folder…', self.choose_output_folder)
        file.addSeparator()
        action(file, 'E&xit', self.close, QKeySequence.StandardKey.Quit)

        render = self.menuBar().addMenu('&Render')
        self.render_action = action(render, '&Render && export MP4', self.start_render,
                                    [QKeySequence('Ctrl+Return'), QKeySequence('F5')])
        self.cancel_action = action(render, '&Cancel render', self.cancel_render, 'Esc')

        settings = self.menuBar().addMenu('&Settings')
        action(settings, '&Load preset…', self.load_preset)
        action(settings, '&Save preset…', self.save_preset)
        settings.addSeparator()
        action(settings, '&Reset to defaults', self.panel.reset)

        help_menu = self.menuBar().addMenu('&Help')
        self.download_action = action(help_menu, 'Download &segmentation model…', self.download_model)
        action(help_menu, 'Open &log folder', lambda: self._open_path(Path(_log_dir())))
        help_menu.addSeparator()
        action(help_menu, '&About', self.about)

    # ------------------------------------------------------------- persistence
    def _restore(self):
        geometry = self.store.value('geometry')
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        else:
            self.resize(1360, 820)
        splitter = self.store.value('splitter')
        if isinstance(splitter, QByteArray):
            self.splitter.restoreState(splitter)
        saved = self.store.value('settings')
        if saved:
            try:
                values = json.loads(saved)
                self.panel.set_values(values)
                Settings(**self.panel.values()).validate()
            except Exception:
                LOGGER.warning('Ignoring invalid saved settings', exc_info=True)
                self.panel.reset()

    def _persist(self):
        self.store.setValue('geometry', self.saveGeometry())
        self.store.setValue('splitter', self.splitter.saveState())
        self.store.setValue('settings', json.dumps(self.panel.values()))

    @property
    def output_dir(self):
        default = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
                       or Path.home()) / APP_NAME
        return Path(self.store.value('output_dir', str(default)))

    # ------------------------------------------------------------ environment
    def _probe_environment(self):
        self.probe = EnvironmentProbe()
        self.probe.finished.connect(self._environment_ready)
        _spawn(self.probe, 'engine-probe')

    def _environment_ready(self, info):
        self.env, self.probe = info, None
        if info['error']:
            self.engine_label.setText('Rendering engine unavailable')
            self.notices.set('engine', f'<b>The rendering engine failed to load.</b> {info["error"]}', warning=True)
            self._update_buttons()
            return
        device = f'CUDA · {info["gpu"]}' if info['cuda'] else 'CPU'
        self.engine_label.setText(f'{device}  ·  PyTorch {info["torch"]}')
        values = self.panel.values()
        if not info['cuda'] and (values['device'] == 'cuda' or values['encoder'] == 'nvenc'):
            self.panel.set_values({'device': 'cpu', 'encoder': 'cpu'})
            self.notices.set('cuda', 'No CUDA GPU was found, so <b>Rendering device</b> is set to CPU and '
                                     '<b>Encoder</b> to CPU H.264 (Video export settings).')
        elif info['cuda'] and values['encoder'] == 'nvenc' and not info['nvenc']:
            self.panel.set_values({'encoder': 'cpu'})
            self.notices.set('nvenc', 'PyNvVideoCodec is not installed, so <b>Encoder</b> is set to CPU H.264.')
        if not info['ffmpeg']:
            self.notices.set('ffmpeg', 'FFmpeg was not found. CPU H.264 export needs <code>ffmpeg</code> on PATH '
                                       '(or the FFMPEG_BINARY environment variable).', warning=True)
        self._model_notice()
        self._update_buttons()

    def _model_notice(self):
        if MODEL_PATH.is_file() or self.download_worker is not None:
            self.notices.remove('model')
            return
        self.notices.set('model', f'The character segmentation model (~{MODEL_MB} MB) is not downloaded. '
                                  '<b>Color characters first</b> needs it.',
                         [('Download model', self.download_model),
                          ('Turn off characters-first', lambda: self.panel.set_values({'subject_first': False}))])

    # ------------------------------------------------------------------ image
    def open_image(self):
        if self.render_worker is not None:
            return
        patterns = ' '.join(f'*{suffix}' for suffix in sorted(IMAGE_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(self, 'Open image', self.store.value('image_dir', ''),
                                              f'Images ({patterns});;All files (*)')
        if path:
            self.load_image(path)

    def load_image(self, path):
        if self.render_worker is not None:
            return
        path = Path(path)
        try:
            with Image.open(path) as source:
                rgba = np.asarray(ImageOps.exif_transpose(source).convert('RGBA')).copy()
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not open {path.name}:\n{exc}')
            return
        self.store.setValue('image_dir', str(path.parent))
        self._set_image(rgba, path.name)

    def paste_image(self):
        if self.render_worker is not None:
            return
        image = QApplication.clipboard().image()
        if image.isNull():
            urls = QApplication.clipboard().mimeData().urls()
            local = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
            if local and local[0].suffix.lower() in IMAGE_SUFFIXES:
                return self.load_image(local[0])
            self.statusBar().showMessage('The clipboard does not contain an image.', 4000)
            return
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width, height = image.width(), image.height()
        buffer = np.frombuffer(image.constBits(), np.uint8, count=image.bytesPerLine() * height)
        rgba = buffer.reshape(height, image.bytesPerLine())[:, :width * 4].reshape(height, width, 4).copy()
        self._set_image(rgba, 'Pasted image')

    def _set_image(self, rgba, name):
        height, width = rgba.shape[:2]
        if width * height > MAX_PIXELS:
            QMessageBox.warning(self, APP_NAME, f'{name} is {width}×{height}; images up to 32 megapixels are supported.')
            return
        self.image, self.image_name = rgba, name
        preview = QImage(rgba.data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
        self.drop.set_pixmap(QPixmap.fromImage(preview))
        self.image_info.setText(f'{name}  ·  {width} × {height} px')
        self.stage.setText('Ready to render.')
        self.progress.setValue(0)
        self._update_buttons()

    # ----------------------------------------------------------------- render
    def _update_buttons(self):
        busy = self.render_worker is not None
        ready = self.env is not None and not self.env.get('error')
        can_render = not busy and ready and self.image is not None
        self.render_button.setEnabled(can_render)
        self.render_action.setEnabled(can_render)
        self.render_button.setText('Loading engine…' if self.env is None else 'Render && export MP4')
        self.cancel_button.setEnabled(busy)
        self.cancel_action.setEnabled(busy)
        has_video = self.output is not None and Path(self.output).is_file()
        self.save_button.setEnabled(has_video and not busy)
        self.save_action.setEnabled(has_video and not busy)
        self.reveal_action.setEnabled(has_video)
        self.panel.setEnabled(not busy)
        self.drop.setEnabled(not busy)
        self.download_action.setEnabled(self.download_worker is None and not MODEL_PATH.is_file())

    def _preflight(self, values):
        """Resolve problems a render would hit, offering the fix instead of failing midway."""
        env = self.env
        if values['device'] == 'cuda' and not env['cuda']:
            if not self._ask('CUDA is not available on this computer. Switch to CPU rendering and CPU H.264 export?'):
                return None
            self.panel.set_values({'device': 'cpu', 'encoder': 'cpu'})
        elif values['encoder'] == 'nvenc' and not env['nvenc']:
            if not self._ask('The NVENC encoder needs the PyNvVideoCodec package. Use CPU H.264 export instead?'):
                return None
            self.panel.set_values({'encoder': 'cpu'})
        values = self.panel.values()
        if values['encoder'] == 'cpu' and not env['ffmpeg']:
            QMessageBox.warning(self, APP_NAME, 'CPU H.264 export needs FFmpeg. Install it and add it to PATH, '
                                                'or set the FFMPEG_BINARY environment variable, then restart.')
            return None
        if values['subject_first'] and not MODEL_PATH.is_file():
            box = QMessageBox(QMessageBox.Icon.Question, APP_NAME,
                              'Coloring characters first needs the segmentation model, which is not downloaded yet.',
                              parent=self)
            download = box.addButton(f'Download model (~{MODEL_MB} MB)', QMessageBox.ButtonRole.AcceptRole)
            without = box.addButton('Render without it', QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is download:
                self.download_model(confirm=False)
                return None
            if box.clickedButton() is not without:
                return None
            values['subject_first'] = False
        return values

    def _ask(self, question):
        return QMessageBox.question(self, APP_NAME, question) == QMessageBox.StandardButton.Yes

    def start_render(self):
        if self.render_worker is not None or self.image is None or self.env is None or self.env.get('error'):
            return
        try:
            Settings(**self.panel.values()).validate()
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f'Please fix the settings before rendering:\n\n{exc}')
            return
        values = self._preflight(self.panel.values())
        if values is None:
            return
        self._persist()
        worker = RenderWorker(self.image, values, self.output_dir)
        worker.progress.connect(self._render_progress)
        worker.finished.connect(self._render_done)
        worker.failed.connect(self._render_failed)
        worker.cancelled.connect(self._render_cancelled)
        self.render_worker = worker
        self.started = time.perf_counter()
        self.progress.setValue(0)
        self.stage.setText('Starting…')
        self.tick.start()
        self._update_buttons()
        self.render_thread = _spawn(worker, 'render')

    def cancel_render(self):
        if self.render_worker is not None:
            self.render_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.stage.setText('Cancelling after the current step…')

    def _render_progress(self, fraction, description):
        if self.render_worker is None or not self.cancel_button.isEnabled():
            return
        self.progress.setValue(round(fraction * 1000))
        self._stage_text = description
        self._tick()

    def _tick(self):
        if self.render_worker is None or not self.cancel_button.isEnabled():
            return
        elapsed = time.perf_counter() - self.started
        fraction = self.progress.value() / 1000
        text = f'{self._stage_text} — {fraction:.0%} · {_clock(elapsed)} elapsed'
        if fraction > .2:
            # Export dominates; extrapolate from export progress only (planning time is front-loaded).
            remaining = elapsed * (1 - fraction) / fraction
            text += f' · ~{_clock(remaining)} left'
        self.stage.setText(text)

    def _render_finished(self):
        self.render_worker = None
        self._stage_text = 'Starting…'
        self.tick.stop()
        self._update_buttons()

    def _render_done(self, path, report):
        self.output = path
        self._render_finished()
        self.progress.setValue(1000)
        elapsed = report.get('wall_seconds', time.perf_counter() - self.started)
        self.stage.setText(f'Done in {_clock(elapsed)} — saved to {Path(path).name}')
        self.player.load(path)
        self.result_tabs.setCurrentWidget(self.player)
        size = report.get('bytes', 0) / 1e6
        phases = report.get('phase_seconds', {})
        self.summary.setText(
            f'<b>{Path(path).name}</b><br>{report.get("width")} × {report.get("height")} px · {report.get("fps")} FPS · '
            f'{report.get("frames")} frames · {report.get("duration", 0):.1f} s · {size:.1f} MB<br>'
            f'Draw {phases.get("draw", 0):.1f} s · Color {phases.get("color", 0):.1f} s · Hold {phases.get("hold", 0):.1f} s'
            f' · rendered in {elapsed:.1f} s on {report.get("device", "?").upper()}'
            f'{" (plan reused)" if report.get("plan_cache_hit") else ""}')
        self.report_view.setPlainText(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        self.statusBar().showMessage(f'Saved {path}', 8000)
        QApplication.alert(self)

    def _render_failed(self, message):
        self._render_finished()
        self.progress.setValue(0)
        self.stage.setText('Render failed.')
        QMessageBox.critical(self, APP_NAME, f'Rendering failed:\n\n{message}')

    def _render_cancelled(self):
        self._render_finished()
        self.progress.setValue(0)
        self.stage.setText('Render cancelled.')

    # ------------------------------------------------------------------ model
    def download_model(self, confirm=True):
        if self.download_worker is not None or MODEL_PATH.is_file():
            return
        if confirm and not self._ask(f'Download the SkyTNT anime-segmentation checkpoint (~{MODEL_MB} MB) from '
                                     'Hugging Face? It is verified by size and SHA256 before use.'):
            return
        for stale in MODEL_PATH.parent.glob(MODEL_PATH.name + '.*.part'):
            stale.unlink(missing_ok=True)  # left behind if the app was closed mid-download
        worker = ModelDownloadWorker()
        worker.finished.connect(self._download_done)
        worker.failed.connect(self._download_failed)
        self.download_worker = worker
        self.notices.set('model', 'Downloading the segmentation model… 0%')
        self.download_timer = QTimer(self)
        self.download_timer.timeout.connect(self._download_tick)
        self.download_timer.start(400)
        self._update_buttons()
        _spawn(worker, 'model-download')

    def _download_tick(self):
        fraction = download_progress()
        label = 'Verifying the segmentation model…' if fraction >= 1 else \
            f'Downloading the segmentation model… {fraction:.0%}'
        frame = self.notices.rows.get('model')
        if frame is not None:
            frame.findChild(QLabel).setText(label)

    def _download_stopped(self):
        self.download_worker = None
        self.download_timer.stop()
        self._update_buttons()

    def _download_done(self, path):
        self._download_stopped()
        self.notices.remove('model')
        self.statusBar().showMessage('Segmentation model downloaded and verified.', 8000)

    def _download_failed(self, message):
        self._download_stopped()
        self._model_notice()
        QMessageBox.warning(self, APP_NAME, f'Model download failed:\n\n{message}')

    # ------------------------------------------------------------ files/menus
    def save_video(self):
        if not self.output or self.render_worker is not None:
            return
        source = Path(self.output)
        target, _ = QFileDialog.getSaveFileName(self, 'Save video as',
                                                str(Path(self.store.value('save_dir', str(Path.home()))) / source.name),
                                                'MP4 video (*.mp4)')
        if not target:
            return
        target = Path(target).with_suffix('.mp4')
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not save the video:\n{exc}')
            return
        self.store.setValue('save_dir', str(target.parent))
        self.statusBar().showMessage(f'Saved {target}', 8000)

    def reveal_video(self):
        if not self.output:
            return
        if os.name == 'nt':
            subprocess.Popen(['explorer', '/select,', str(Path(self.output))])
        else:
            self._open_path(Path(self.output).parent)

    def open_output_folder(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(self.output_dir)

    def _open_path(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Output folder', str(self.output_dir))
        if folder:
            self.store.setValue('output_dir', folder)
            self.statusBar().showMessage(f'Videos will be saved to {folder}', 6000)

    def save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save preset', str(Path(self.store.value('preset_dir', str(Path.home()))) / 'handdraw-preset.json'),
                                              'Handdraw preset (*.json)')
        if path:
            Path(path).write_text(json.dumps(self.panel.values(), indent=2), encoding='utf-8')
            self.store.setValue('preset_dir', str(Path(path).parent))

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load preset', self.store.value('preset_dir', ''),
                                              'Handdraw preset (*.json)')
        if not path:
            return
        previous = self.panel.values()
        try:
            values = json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(values, dict):
                raise ValueError('A preset must be a JSON object of setting names to values.')
            self.panel.set_values(values)
            Settings(**self.panel.values()).validate()
        except Exception as exc:
            self.panel.set_values(previous)
            QMessageBox.warning(self, APP_NAME, f'Could not load the preset:\n{exc}')
            return
        self.store.setValue('preset_dir', str(Path(path).parent))
        self.statusBar().showMessage(f'Loaded preset {Path(path).name}', 5000)

    def about(self):
        QMessageBox.about(self, f'About {APP_NAME}',
                          f'<h3>{APP_NAME} {APP_VERSION}</h3>'
                          '<p>Turn an illustration into a whiteboard animation: draw the lines, color the '
                          'characters first, then finish the background with moving photographic hands.</p>'
                          '<p>Native desktop front end for the <i>whiteboard-animation-vi</i> Handdraw renderer. '
                          'Original code is CC0 1.0; third-party components keep their own licenses '
                          '(see THIRD_PARTY_NOTICES.md). Hand images and model weights are not covered by CC0.</p>')

    def closeEvent(self, event):
        if self.render_worker is not None:
            if not self._ask('A render is in progress. Stop it and quit?'):
                event.ignore()
                return
            self.render_worker.cancel()
            # Give the renderer a moment to reach its next progress check, stop FFmpeg and delete the partial file.
            self.render_thread.join(timeout=5)
        self._persist()
        self.player.clear()
        event.accept()


def _log_dir():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'logs'
