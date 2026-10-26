# Packages a built Handdraw Studio folder into release\HanddrawStudio-<version>-Setup.exe with Inno Setup 6.
#   .\build_desktop.ps1 -DistPath dist-release
#   .\build_installer.ps1 -BuildDir dist-release\HanddrawStudio
param(
    [string]$BuildDir = 'dist-release\HanddrawStudio',
    [string]$OutputDir = 'release'
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Push-Location $PSScriptRoot
try {
    $iscc = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $iscc) { throw 'Inno Setup 6 not found. Install it: winget install --id JRSoftware.InnoSetup -e --scope user' }

    $build = (Resolve-Path -LiteralPath $BuildDir).Path
    # Refuse to package an incomplete bundle (the failures these guard against have shipped before).
    foreach ($required in 'HanddrawStudio.exe', '_internal\torchvision\_C_stable.pyd',
                         '_internal\assets\v181d\model.safetensors', '_internal\ffmpeg\ffmpeg.exe',
                         '_internal\ffmpeg\LICENSE') {
        if (-not (Test-Path -LiteralPath (Join-Path $build $required))) { throw "$BuildDir is missing $required" }
    }
    $version = & $python -c "from desktop import APP_VERSION; print(APP_VERSION)"
    if ($LASTEXITCODE -or -not $version) { throw 'Could not read APP_VERSION from desktop/__init__.py.' }
    $icon = Join-Path $PSScriptRoot 'build\icon.ico'
    if (-not (Test-Path -LiteralPath $icon)) { throw 'build\icon.ico is missing; run build_desktop.ps1 first.' }

    New-Item -ItemType Directory -Force $OutputDir | Out-Null
    & $iscc "/DAppVersion=$version" "/DBuildDir=$build" "/DIconFile=$icon" "/O$((Resolve-Path $OutputDir).Path)" `
        'installer\HanddrawStudio.iss'
    if ($LASTEXITCODE) { throw 'Inno Setup compilation failed.' }

    $setup = Get-Item (Join-Path $OutputDir "HanddrawStudio-$version-Setup.exe")
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup.FullName).Hash
    "$hash  $($setup.Name)" | Set-Content -Encoding ascii "$($setup.FullName).sha256"
    Write-Output ("Built {0} ({1:N0} MB), SHA256 {2}" -f $setup.FullName, ($setup.Length / 1MB), $hash)
} finally {
    Pop-Location
}
