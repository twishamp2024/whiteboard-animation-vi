"""Background jobs: engine warm-up, rendering and the verified model download."""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import logging
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal, Slot

from handdraw.settings import Settings

from . import MODEL_PATH, ROOT

LOGGER = logging.getLogger(__name__)


class RenderCancelled(Exception):
    """Raised from the progress callback; ``render_video`` then aborts the encoder and removes the partial file."""


class EnvironmentProbe(QObject):
    """Imports the renderer (torch is slow to load) and reports what this machine can do."""

    finished = Signal(object)

    @Slot()
    def run(self):
        info = {'error': None}
        try:
            import torch
            import handdraw.render as render

            info['torch'] = torch.__version__
            info['cuda'] = torch.cuda.is_available()
            info['gpu'] = torch.cuda.get_device_name(0) if info['cuda'] else None
            info['nvenc'] = importlib.util.find_spec('PyNvVideoCodec') is not None
            try:
                info['ffmpeg'] = render.ffmpeg_binary()
            except (RuntimeError, ValueError):
                info['ffmpeg'] = None
        except Exception as exc:
            LOGGER.exception('Renderer import failed')
            info['error'] = f'{type(exc).__name__}: {exc}'
        info['model'] = model_present()
        LOGGER.info('Engine: torch %s, CUDA %s, FFmpeg %s, model %s', info.get('torch'), info.get('cuda'),
                    info.get('ffmpeg'), info['model'])
        self.finished.emit(info)


def model_present():
    return MODEL_PATH.is_file() and MODEL_PATH.stat().st_size == _downloader().EXPECTED_SIZE


@lru_cache(maxsize=1)
def _downloader():
    # scripts/ is not a package; load the stdlib-only downloader by path so it stays the single source.
    source = ROOT / 'scripts' / 'download_model.py'
    spec = importlib.util.spec_from_file_location('_handdraw_download_model', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderWorker(QObject):
    progress = Signal(float, str)
    finished = Signal(str, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, image, values, output_dir):
        super().__init__()
        self.image, self.values, self.output_dir = image, dict(values), Path(output_dir)
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _progress(self, fraction, description):
        if self._cancel.is_set():
            raise RenderCancelled()
        self.progress.emit(float(fraction), str(description))

    @Slot()
    def run(self):
        try:
            settings = Settings(**self.values).validate()
            from handdraw.render import render_video

            self.output_dir.mkdir(parents=True, exist_ok=True)
            output, report = render_video(self.image, settings, output_dir=self.output_dir,
                                          progress=self._progress)
            output = Path(output).resolve()
            if (not output.is_relative_to(self.output_dir.resolve()) or output.suffix.lower() != '.mp4'
                    or not output.is_file()):
                raise ValueError('Renderer returned an invalid output file.')
            LOGGER.info('Rendered %s', output)
            self.finished.emit(str(output), report)
        except RenderCancelled:
            LOGGER.info('Render cancelled')
            self.cancelled.emit()
        except Exception as exc:
            LOGGER.exception('Render failed')
            self.failed.emit(str(exc) or type(exc).__name__)


class ModelDownloadWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            path = _downloader().download_model(MODEL_PATH)
            self.finished.emit(str(path))
        except Exception as exc:
            LOGGER.exception('Model download failed')
            self.failed.emit(str(exc) or type(exc).__name__)


def download_progress():
    """Fraction of the model downloaded so far, read from the downloader's temporary ``.part`` file."""
    expected = _downloader().EXPECTED_SIZE
    sizes = [part.stat().st_size for part in MODEL_PATH.parent.glob(MODEL_PATH.name + '.*.part')]
    return min(1., max(sizes, default=0) / expected)
