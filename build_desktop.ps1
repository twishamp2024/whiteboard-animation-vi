# Builds the standalone Handdraw Studio folder with PyInstaller, then runs its self-test.
#   .\build_desktop.ps1                          -> dist\HanddrawStudio
#   .\build_desktop.ps1 -DistPath dist-release   -> dist-release\HanddrawStudio (leaves dist\ untouched)
# FFmpeg is bundled from -FFmpegDir (a gyan.dev-style folder with bin\ffmpeg.exe, LICENSE, README.txt),
# or from the ffmpeg found on PATH; pass -NoFFmpeg to rely on the user's FFmpeg instead.
param(
    [switch]$Clean,
    [string]$DistPath = 'dist',
    [string]$FFmpegDir,
    [switch]$NoFFmpeg
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Missing .venv. Follow the desktop installation steps in README.md.'
}
Push-Location $PSScriptRoot
try {
    & $python -m pip install --quiet -r requirements-build.txt
    if ($LASTEXITCODE) { throw 'Installing the pinned build tools failed.' }

    # The release ships the segmentation model; refuse to build without the verified checkpoint.
    & $python -c "import sys; sys.path.insert(0, 'scripts'); from download_model import DEFAULT_PATH, verify_model; sys.exit(0 if verify_model(DEFAULT_PATH) else 1)"
    if ($LASTEXITCODE) { throw 'The segmentation model is missing or fails its SHA256 check. Run scripts\download_model.py first.' }

    $env:HANDDRAW_FFMPEG_DIR = ''
    if (-not $NoFFmpeg) {
        if (-not $FFmpegDir) {
            $command = Get-Command ffmpeg -ErrorAction SilentlyContinue
            if (-not $command) { throw 'FFmpeg not found on PATH. Pass -FFmpegDir, or -NoFFmpeg to build without it.' }
            $exe = Get-Item -LiteralPath $command.Source
            if ($exe.LinkType) { $exe = Get-Item -LiteralPath $exe.Target }  # winget's Links shim
            $FFmpegDir = $exe.Directory.Parent.FullName
        }
        foreach ($required in 'bin\ffmpeg.exe', 'LICENSE', 'README.txt') {
            if (-not (Test-Path -LiteralPath (Join-Path $FFmpegDir $required))) {
                throw "FFmpeg folder $FFmpegDir has no $required (expected a gyan.dev-style build)."
            }
        }
        $env:HANDDRAW_FFMPEG_DIR = (Resolve-Path -LiteralPath $FFmpegDir).Path
        Write-Output "Bundling FFmpeg from $env:HANDDRAW_FFMPEG_DIR"
    }

    New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot 'build') | Out-Null
    & $python -c "from desktop.icon import save_icon; save_icon(r'build\icon.ico')"
    if ($LASTEXITCODE) { throw 'Creating the icon failed.' }
    $arguments = @('-m', 'PyInstaller', '--noconfirm', '--distpath', $DistPath, 'handdraw_studio.spec')
    if ($Clean) { $arguments += '--clean' }
    & $python @arguments
    if ($LASTEXITCODE) { throw 'PyInstaller failed.' }

    $exe = Join-Path (Resolve-Path -LiteralPath $DistPath).Path 'HanddrawStudio\HanddrawStudio.exe'
    $test = Start-Process -FilePath $exe -ArgumentList '--self-test' -Wait -PassThru
    if ($test.ExitCode) { throw "The built app failed its self-test (exit code $($test.ExitCode))." }
    Write-Output "Built $exe"
} finally {
    Remove-Item Env:HANDDRAW_FFMPEG_DIR -ErrorAction SilentlyContinue
    Pop-Location
}
