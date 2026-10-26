"""Native Qt desktop front end for the Handdraw renderer."""
from __future__ import annotations

from pathlib import Path

import handdraw

APP_NAME = 'Handdraw Studio'
APP_VERSION = '1.0.0'
# Same root the renderer uses for its hand assets and model, also when frozen by PyInstaller.
ROOT = Path(handdraw.__file__).resolve().parents[1]
MODEL_PATH = ROOT / 'assets' / 'v181d' / 'model.safetensors'
