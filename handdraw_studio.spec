# PyInstaller spec for the Handdraw Studio desktop app. Build with .\build_desktop.ps1
# The renderer resolves assets from Path(handdraw.__file__).parents[1], which is the bundle's
# _internal folder when frozen, so assets/ and vendor_runtime/ are placed at its root.
import os
from pathlib import Path

import torchvision

root = Path(SPECPATH)
# torchvision >= 0.29 ships its custom ops as _C_stable.pyd, loaded with torch.ops.load_library rather than
# imported, and the stock hook still names the old 'torchvision._C'. Without it, `import torchvision` fails with
# "operator torchvision::nms does not exist". Bundle every native torchvision library next to its package.
binaries = [(str(path), 'torchvision') for path in Path(torchvision.__file__).parent.glob('*.pyd')]

datas = [
    (str(root / 'assets' / 'v181d' / 'draw-hand-long.png'), 'assets/v181d'),
    (str(root / 'assets' / 'v181d' / 'color-hand-long.png'), 'assets/v181d'),
    (str(root / 'assets' / 'v181d' / 'PROVENANCE.md'), 'assets/v181d'),
    (str(root / 'vendor_runtime'), 'vendor_runtime'),
    (str(root / 'scripts' / 'download_model.py'), 'scripts'),
    (str(root / 'LICENSE'), '.'),
    (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
]
model = root / 'assets' / 'v181d' / 'model.safetensors'
if model.is_file():  # ship the verified checkpoint when it has been downloaded
    datas.append((str(model), 'assets/v181d'))
# Optional FFmpeg (set by build_desktop.ps1): the app points FFMPEG_BINARY at _internal/ffmpeg/ffmpeg.exe.
# It ships as a separate GPL program with its license, build README (source link) and a notice.
ffmpeg = os.environ.get('HANDDRAW_FFMPEG_DIR')
if ffmpeg:
    ffmpeg = Path(ffmpeg)
    datas += [(str(ffmpeg / 'bin' / 'ffmpeg.exe'), 'ffmpeg'), (str(ffmpeg / 'LICENSE'), 'ffmpeg'),
              (str(ffmpeg / 'README.txt'), 'ffmpeg'), (str(root / 'installer' / 'FFMPEG-NOTICE.txt'), 'ffmpeg')]

a = Analysis(
    [str(root / 'HanddrawStudio.pyw')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    # Imported lazily inside functions (or, for torchvision, by vendor_runtime's isnet.py loaded from a
    # file path), so static analysis can miss them.
    hiddenimports=['handdraw.subject', 'handdraw.nvenc', 'handdraw.v181e_background_fill', 'torchvision',
                   'safetensors.torch', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets'],
    excludes=['gradio', 'tkinter', 'matplotlib', 'IPython', 'pytest', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.Qt3DCore',
              'PySide6.QtQuick3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HanddrawStudio',
    console=False,
    icon=str(root / 'build' / 'icon.ico'),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name='HanddrawStudio')
