from dataclasses import fields
import json
import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication  # noqa: E402

from handdraw.settings import INK_DEFAULTS, RIG_SETTINGS, Settings  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp):
    from desktop.controls import SettingsPanel

    widget = SettingsPanel()
    yield widget
    widget.deleteLater()


def test_every_setting_has_a_control_with_native_defaults_and_bounds(panel):
    from desktop.controls import NumberControl, PROTECTED_RIG_KEYS

    assert set(panel.controls) == {item.name for item in fields(Settings)}
    values = panel.values()
    for item in fields(Settings):
        control = panel.controls[item.name]
        if item.name not in ('rig_json', 'ink_json'):
            assert values[item.name] == item.default, item.name
            assert type(values[item.name]) is type(item.default), item.name
        if item.metadata['low'] is not None:
            assert isinstance(control, NumberControl)
            assert control.spin.minimum() == item.metadata['low']
            assert control.spin.maximum() == item.metadata['high']
    assert json.loads(values['rig_json']) == {key: value for key, value in RIG_SETTINGS.items()
                                              if key not in PROTECTED_RIG_KEYS}
    assert json.loads(values['ink_json']) == INK_DEFAULTS
    Settings(**values).validate()


def test_values_round_trip_and_snap_to_the_native_step(panel):
    panel.set_values({'mode': 'e', 'duration': 7.3, 'fps': 50, 'device': 'cpu', 'encoder': 'cpu',
                      'show_hand': False, 'paper_color': '#FAF0E6', 'fit': 'contain'})
    values = panel.values()
    assert (values['mode'], values['duration'], values['fps'], values['show_hand']) == ('e', 7.3, 50, False)
    assert (values['device'], values['encoder'], values['paper_color'], values['fit']) == ('cpu', 'cpu', '#faf0e6', 'contain')
    panel.set_values({'adaptive_block': 16, 'path_samples': 300})
    assert panel.values()['adaptive_block'] in (15, 17)  # odd window, as the renderer requires
    assert panel.values()['path_samples'] == 257
    Settings(**panel.values()).validate()
    panel.reset()
    assert panel.values()['mode'] == 'd'


def test_unknown_settings_are_rejected_before_any_change(panel):
    with pytest.raises(ValueError, match='Unknown settings'):
        panel.set_values({'duration': 3.0, 'bogus': 1})
    assert panel.values()['duration'] == Settings().duration


def _defaults():
    from desktop.controls import default_values

    return {**default_values(), 'device': 'cpu', 'encoder': 'cpu'}


def test_render_worker_forwards_progress_and_result(qapp, monkeypatch, tmp_path):
    from desktop.workers import RenderWorker

    output = tmp_path / 'video.mp4'
    output.write_bytes(b'test')
    image = np.zeros((8, 8, 4), np.uint8)

    def render(image_numpy, settings, output_dir=None, progress=None):
        assert image_numpy is image and settings.device == 'cpu'
        progress(.5, 'Exporting video')
        return output, {'frames': 1}

    monkeypatch.setitem(sys.modules, 'handdraw.render', SimpleNamespace(render_video=render))
    worker = RenderWorker(image, _defaults(), tmp_path)
    events = []
    worker.progress.connect(lambda fraction, text: events.append(('progress', fraction, text)))
    worker.finished.connect(lambda path, report: events.append(('done', path, report)))
    worker.run()
    assert events == [('progress', .5, 'Exporting video'), ('done', str(output.resolve()), {'frames': 1})]


def test_cancel_raises_inside_the_renderer_and_reports_cancelled(qapp, monkeypatch, tmp_path):
    from desktop.workers import RenderCancelled, RenderWorker

    seen = []

    def render(image_numpy, settings, output_dir=None, progress=None):
        try:
            progress(.2, 'Exporting video')
        except BaseException as exc:  # render_video aborts its encoder here and re-raises
            seen.append(type(exc))
            raise

    monkeypatch.setitem(sys.modules, 'handdraw.render', SimpleNamespace(render_video=render))
    worker = RenderWorker(np.zeros((8, 8, 4), np.uint8), _defaults(), tmp_path)
    events = []
    worker.cancelled.connect(lambda: events.append('cancelled'))
    worker.failed.connect(events.append)
    worker.cancel()
    worker.run()
    assert seen == [RenderCancelled] and events == ['cancelled']


def test_invalid_settings_and_foreign_outputs_fail(qapp, monkeypatch, tmp_path):
    from desktop.workers import RenderWorker

    outside = tmp_path / 'outside.mp4'
    outside.write_bytes(b'test')
    monkeypatch.setitem(sys.modules, 'handdraw.render', SimpleNamespace(
        render_video=lambda *args, **kwargs: (outside, {})))
    errors = []
    worker = RenderWorker(np.zeros((8, 8, 4), np.uint8), {**_defaults(), 'duration': -1}, tmp_path / 'out')
    worker.failed.connect(errors.append)
    worker.run()
    worker = RenderWorker(np.zeros((8, 8, 4), np.uint8), _defaults(), tmp_path / 'out')
    worker.failed.connect(errors.append)
    worker.run()
    assert 'duration' in errors[0] and 'invalid output file' in errors[1]


def test_main_window_builds_and_icon_renders(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from desktop.icon import icon_image
    from desktop.window import MainWindow

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    monkeypatch.setattr('desktop.window._spawn', lambda worker, name: None)
    window = MainWindow()
    try:
        assert not window.render_button.isEnabled()  # engine still loading, no image
        window._environment_ready({'error': None, 'torch': 'x', 'cuda': False, 'gpu': None,
                                   'nvenc': False, 'ffmpeg': 'ffmpeg', 'model': True})
        assert window.panel.values()['device'] == 'cpu' and window.panel.values()['encoder'] == 'cpu'
        window._set_image(np.zeros((20, 30, 4), np.uint8), 'test.png')
        assert window.render_button.isEnabled()
    finally:
        window.close()
    assert not icon_image(64).isNull()


def test_bundled_ffmpeg_is_preferred_unless_user_set_one(monkeypatch, tmp_path):
    import desktop.__main__ as entry

    bundled = tmp_path / 'ffmpeg.exe'
    monkeypatch.setattr(entry, 'BUNDLED_FFMPEG', bundled)
    # setenv first so monkeypatch records the original value (or absence) and restores it afterwards;
    # _use_bundled_ffmpeg() writes os.environ directly.
    monkeypatch.setenv('FFMPEG_BINARY', 'placeholder')
    monkeypatch.delenv('FFMPEG_BINARY')
    entry._use_bundled_ffmpeg()
    assert 'FFMPEG_BINARY' not in os.environ  # nothing bundled: PATH lookup stays in charge
    bundled.write_bytes(b'')
    entry._use_bundled_ffmpeg()
    assert os.environ['FFMPEG_BINARY'] == str(bundled)
    monkeypatch.setenv('FFMPEG_BINARY', 'C:/custom/ffmpeg.exe')
    entry._use_bundled_ffmpeg()
    assert os.environ['FFMPEG_BINARY'] == 'C:/custom/ffmpeg.exe'
