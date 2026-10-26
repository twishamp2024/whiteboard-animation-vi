"""Entry point: ``python -m desktop [image]``."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, APP_VERSION, MODEL_PATH, ROOT

BUNDLED_FFMPEG = ROOT / 'ffmpeg' / 'ffmpeg.exe'


def _use_bundled_ffmpeg():
    """Point the renderer at the FFmpeg shipped with release builds, unless FFMPEG_BINARY was set explicitly."""
    if BUNDLED_FFMPEG.is_file() and not os.environ.get('FFMPEG_BINARY'):
        os.environ['FFMPEG_BINARY'] = str(BUNDLED_FFMPEG)


def _configure_logging():
    from .window import _log_dir

    directory = _log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / 'desktop.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handlers = [handler]
    if sys.stderr is not None:  # None under pythonw / a windowed PyInstaller build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format='%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s')


def _excepthook(kind, value, trace):
    logging.getLogger(APP_NAME).critical('Unhandled exception', exc_info=(kind, value, trace))
    if QApplication.instance() is not None:
        QMessageBox.critical(None, APP_NAME, ''.join(traceback.format_exception_only(kind, value)).strip())


def self_test():
    """Render a tiny synthetic image on the CPU; verifies a frozen build end to end (exit code 0 = OK).

    With the model bundled, character segmentation runs too, which imports torchvision and its native ops.
    """
    import tempfile

    import numpy as np

    from handdraw.render import ffmpeg_binary, render_video
    from handdraw.settings import Settings

    rgb = np.full((64, 96, 3), 245, np.uint8)
    rgb[8:55, 15:80] = (50, 130, 180)
    rgb[30:33, 8:88] = 0
    subject_first = MODEL_PATH.is_file()
    settings = Settings(device='cpu', encoder='cpu', subject_first=subject_first, duration=1, fps=10,
                        width=96, height=64)
    with tempfile.TemporaryDirectory() as directory:
        output, report = render_video(rgb, settings, output_dir=directory)
        logging.getLogger(APP_NAME).info('Self-test rendered %s frames, %s bytes; subject_first=%s; ffmpeg=%s',
                                         report['frames'], report['bytes'], subject_first, ffmpeg_binary())
        return 0 if output.is_file() and report['frames'] == 10 else 1


def main(argv=None):
    argv = sys.argv if argv is None else argv
    _use_bundled_ffmpeg()
    if '--self-test' in argv:
        logging.basicConfig(level=logging.INFO)
        return self_test()
    if sys.platform == 'win32':
        import ctypes

        # Own taskbar group and icon instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Handdraw.Studio')
    app = QApplication(argv)
    app.setOrganizationName('Handdraw')
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    _configure_logging()
    sys.excepthook = _excepthook
    logging.getLogger(APP_NAME).info('Starting %s %s; data in %s', APP_NAME, APP_VERSION,
                                     QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))

    from .window import MainWindow

    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.load_image(argv[1])
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
