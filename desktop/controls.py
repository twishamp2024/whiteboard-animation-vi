"""Qt controls generated from the native ``Settings`` metadata (mirrors ``app.setting_control``)."""
from __future__ import annotations

from dataclasses import fields
import json
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QToolBox,
                               QVBoxLayout, QWidget)

from handdraw.settings import INK_DEFAULTS, RIG_SETTINGS, Settings

PROTECTED_RIG_KEYS = {'reference_height', 'native_scale', 'wrist_degrees', 'wrist_frequency'}
QUICK_FIELDS = ('mode', 'duration', 'fps', 'show_hand', 'subject_first')
GROUP_ORDER = ('Video', 'Lines & colors', 'Coloring path', 'Hand & pen', 'Video export', 'Advanced')
GROUP_LABELS = {'Video': 'Frame & timing', 'Advanced': 'Advanced (JSON)'}
GROUP_HINTS = {'Video export': 'No NVIDIA GPU? Select CPU and CPU H.264.',
               'Advanced': 'Native rig and line-filter overrides. Validated before rendering.'}


def default_value(item):
    if item.name == 'rig_json':
        return json.dumps({key: value for key, value in RIG_SETTINGS.items()
                           if key not in PROTECTED_RIG_KEYS}, indent=2)
    if item.name == 'ink_json':
        return json.dumps(INK_DEFAULTS, indent=2)
    return item.default


def default_values():
    return {item.name: default_value(item) for item in fields(Settings)}


def _choices(spec):
    return [entry if isinstance(entry, tuple) else (entry, entry) for entry in spec['choices']]


def _decimals(step):
    text = f'{step:g}'
    return len(text.split('.')[1]) if '.' in text else 0


class Control(QWidget):
    changed = Signal()

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item, self.spec = item, item.metadata
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.layout_ = layout

    def value(self):
        raise NotImplementedError

    def set_value(self, value):
        raise NotImplementedError


class SegmentedChoice(Control):
    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        self.group = QButtonGroup(self)
        self.values = []
        for index, (label, value) in enumerate(_choices(self.spec)):
            button = QRadioButton(label)
            self.group.addButton(button, index)
            self.layout_.addWidget(button)
            self.values.append(value)
        self.layout_.addStretch(1)
        self.group.idToggled.connect(lambda _id, on: on and self.changed.emit())

    def value(self):
        return self.values[max(0, self.group.checkedId())]

    def set_value(self, value):
        self.group.button(self.values.index(value)).setChecked(True)


class ComboChoice(Control):
    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        self.combo = QComboBox()
        for label, value in _choices(self.spec):
            self.combo.addItem(label, value)
        self.layout_.addWidget(self.combo, 1)
        self.combo.currentIndexChanged.connect(self.changed)

    def value(self):
        return self.combo.currentData()

    def set_value(self, value):
        self.combo.setCurrentIndex(self.combo.findData(value))


class BoolControl(Control):
    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        self.box = QCheckBox(self.spec['label'])
        self.layout_.addWidget(self.box)
        self.box.toggled.connect(self.changed)

    def value(self):
        return self.box.isChecked()

    def set_value(self, value):
        self.box.setChecked(bool(value))


class NumberControl(Control):
    """Slider + spin box that snaps to the native low/step grid, like a Gradio slider."""

    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        low, high, step = self.spec['low'], self.spec['high'], self.spec['step']
        self.integer = isinstance(item.default, int)
        self.steps = round((high - low) / step)
        if self.integer:
            self.spin = QSpinBox()
            self.spin.setRange(int(low), int(high))
            self.spin.setSingleStep(int(step))
        else:
            self.spin = QDoubleSpinBox()
            self.spin.setDecimals(_decimals(step))
            self.spin.setRange(low, high)
            self.spin.setSingleStep(step)
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(84)
        self.slider = None
        if self.steps <= 20000 and item.name != 'seed':
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(0, self.steps)
            self.layout_.addWidget(self.slider, 1)
            self.slider.valueChanged.connect(self._from_slider)
        self.layout_.addWidget(self.spin, 0 if self.slider else 1)
        self.spin.valueChanged.connect(self._from_spin)
        self.setToolTip(f'{low:g} – {high:g}, step {step:g}')

    def _snap(self, value):
        low, step = self.spec['low'], self.spec['step']
        snapped = low + round((value - low) / step) * step
        snapped = min(self.spec['high'], max(low, snapped))
        return int(round(snapped)) if self.integer else round(snapped, _decimals(step))

    def _from_slider(self, position):
        value = self._snap(self.spec['low'] + position * self.spec['step'])
        if self.spin.value() != value:
            self.spin.setValue(value)

    def _from_spin(self, value):
        snapped = self._snap(value)
        if snapped != value:
            self.spin.setValue(snapped)
            return
        if self.slider is not None:
            self.slider.blockSignals(True)
            self.slider.setValue(round((snapped - self.spec['low']) / self.spec['step']))
            self.slider.blockSignals(False)
        self.changed.emit()

    def value(self):
        value = self._snap(self.spin.value())
        return int(value) if self.integer else float(value)

    def set_value(self, value):
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{self.item.name}: number required')
        self.spin.setValue(self._snap(value))
        self._from_spin(self.spin.value())


class ColorControl(Control):
    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        self.button = QPushButton()
        self.button.setMinimumWidth(110)
        self.button.clicked.connect(self._pick)
        self.layout_.addWidget(self.button)
        self.layout_.addStretch(1)
        self._value = item.default

    def _pick(self):
        color = QColorDialog.getColor(QColor(self._value), self, self.spec['label'])
        if color.isValid():
            self.set_value(color.name())
            self.changed.emit()

    def value(self):
        return self._value

    def set_value(self, value):
        color = QColor(value)
        if not color.isValid():
            raise ValueError(f'{self.item.name}: invalid color')
        self._value = color.name()
        text = '#000000' if color.lightnessF() > .55 else '#ffffff'
        self.button.setText(self._value)
        self.button.setStyleSheet(f'background:{self._value}; color:{text}; border:1px solid #8888; '
                                  'border-radius:4px; padding:4px 10px;')


class JsonControl(Control):
    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        column = QVBoxLayout()
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setMinimumHeight(220)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.status = QLabel()
        self.status.setWordWrap(True)
        reset = QPushButton('Restore native defaults')
        reset.clicked.connect(lambda: self.set_value(default_value(item)))
        column.addWidget(self.editor)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(reset)
        column.addLayout(row)
        self.layout_.addLayout(column)
        self.editor.textChanged.connect(self._check)
        self.editor.textChanged.connect(self.changed)

    def _check(self):
        try:
            json.loads(self.editor.toPlainText())
            self.status.setText('')
        except json.JSONDecodeError as exc:
            self.status.setText(f'<span style="color:#d9480f">JSON error: {exc.msg} (line {exc.lineno})</span>')

    def value(self):
        return self.editor.toPlainText()

    def set_value(self, value):
        self.editor.setPlainText(str(value))


class TextControl(Control):
    def __init__(self, item, parent=None):
        super().__init__(item, parent)
        self.edit = QLineEdit()
        self.layout_.addWidget(self.edit, 1)
        self.edit.editingFinished.connect(self.changed)

    def value(self):
        return self.edit.text()

    def set_value(self, value):
        self.edit.setText(str(value))


def setting_control(item):
    spec = item.metadata
    if spec['choices']:
        return SegmentedChoice(item) if item.name == 'mode' else ComboChoice(item)
    if isinstance(item.default, bool):
        return BoolControl(item)
    if spec['low'] is not None:
        return NumberControl(item)
    if item.name == 'paper_color':
        return ColorControl(item)
    if item.name in ('rig_json', 'ink_json'):
        return JsonControl(item)
    return TextControl(item)


class SettingsPanel(QWidget):
    """Every ``Settings`` field as a control: quick settings on top, the rest grouped below."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = {}
        items = {item.name: item for item in fields(Settings)}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        quick = QGroupBox('Quick settings')
        form = QFormLayout(quick)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for name in QUICK_FIELDS:
            self._add(form, items[name])
        hint = QLabel('Both modes prioritize characters. <b>Quick</b> colors background '
                      'clusters from left to right.')
        hint.setWordWrap(True)
        font = hint.font()
        font.setPointSizeF(font.pointSizeF() * .92)
        hint.setFont(font)
        form.addRow(hint)
        layout.addWidget(quick)

        self.toolbox = QToolBox()
        for group in GROUP_ORDER:
            page = QWidget()
            form = QFormLayout(page)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            if group in GROUP_HINTS:
                note = QLabel(GROUP_HINTS[group])
                note.setWordWrap(True)
                form.addRow(note)
            for item in fields(Settings):
                if item.metadata['group'] == group and item.name not in self.controls:
                    self._add(form, item, stacked=group == 'Advanced')
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.toolbox.addItem(scroll, GROUP_LABELS.get(group, group).replace('&', '&&'))  # '&' is a mnemonic
        layout.addWidget(self.toolbox, 1)

        reset = QPushButton('Reset all settings to defaults')
        reset.clicked.connect(self.reset)
        layout.addWidget(reset)
        self.reset()

    def _add(self, form, item, stacked=False):
        control = setting_control(item)
        control.changed.connect(self.changed)
        self.controls[item.name] = control
        if isinstance(control, BoolControl):
            form.addRow(control)
        elif stacked:
            title = QLabel(item.metadata['label'])
            bold = QFont(title.font())
            bold.setBold(True)
            title.setFont(bold)
            form.addRow(title)
            form.addRow(control)
        else:
            label = QLabel(item.metadata['label'])
            label.setWordWrap(True)
            form.addRow(label, control)

    def values(self):
        return {name: control.value() for name, control in self.controls.items()}

    def set_values(self, values):
        """Apply a (possibly partial) mapping; unknown keys are rejected before anything changes."""
        unknown = set(values) - set(self.controls)
        if unknown:
            raise ValueError(f'Unknown settings: {", ".join(sorted(unknown))}')
        for name, value in values.items():
            self.controls[name].set_value(value)
        self.changed.emit()

    def reset(self):
        self.set_values(default_values())
