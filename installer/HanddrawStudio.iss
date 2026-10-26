; Inno Setup 6 script for Handdraw Studio. Build with .\build_installer.ps1, which passes:
;   /DAppVersion=<desktop.APP_VERSION>  /DBuildDir=<PyInstaller output folder>  /DIconFile=<.ico>
; Installs the whole PyInstaller folder (HanddrawStudio.exe + _internal, including the segmentation
; model and FFmpeg). User data lives outside {app} and is never touched by the uninstaller:
;   settings  HKCU\Software\Handdraw\Handdraw Studio
;   logs      %LOCALAPPDATA%\Handdraw\Handdraw Studio\logs
;   videos    the Videos library (\Handdraw Studio), or the folder chosen in the app

#ifndef AppVersion
  #error AppVersion must be defined (/DAppVersion=1.2.3)
#endif
#ifndef BuildDir
  #error BuildDir must be defined (/DBuildDir=path\to\HanddrawStudio)
#endif
#ifndef IconFile
  #error IconFile must be defined (/DIconFile=path\to\icon.ico)
#endif

#define AppName "Handdraw Studio"
#define AppExe "HanddrawStudio.exe"
; Matches SetCurrentProcessExplicitAppUserModelID in desktop/__main__.py, so shortcuts and taskbar group together.
#define AppUserModelID "Handdraw.Studio"

[Setup]
AppId={{D4257152-4C8E-46AC-ABE8-F0E3AB2F2F6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Handdraw
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
; Per-user install by default (no admin, {autopf} = %LOCALAPPDATA%\Programs); the dialog offers all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputBaseFilename=HanddrawStudio-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Upgrades replace the bundle wholesale so no stale DLLs from an older build linger. Only program files live here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
