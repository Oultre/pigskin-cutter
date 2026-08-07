; Inno Setup script for Pigskin Cutter — a real Windows installer with a
; destination-folder page (pick your drive/folder), Start Menu + optional desktop
; shortcuts, and an uninstaller. Unsigned by design (PLAN §3.6).
;
; Built in CI (see .github/workflows/release.yml): the Windows job installs Inno
; Setup and runs, from the packaging/ folder:
;   ISCC.exe /DMyAppVersion=0.2.0 installer.iss
; which reads dist\PigskinCutter.exe and writes dist\PigskinCutter-Setup.exe.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Pigskin Cutter"
#define MyAppExe "PigskinCutter.exe"
#define MyAppPublisher "Pigskin Cutter"
#define MyAppUrl "https://github.com/Oultre/pigskin-cutter"

[Setup]
; A stable AppId so upgrades replace the previous install instead of stacking.
AppId={{B7A9E2F4-3C6D-4E51-9A2B-8F1C7D0E6A34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin prompt), but the user may switch to an
; all-users/Program Files install from the wizard.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Show the "choose destination folder" page so a coach can pick the drive/folder.
DisableDirPage=no
OutputDir=dist
OutputBaseFilename=PigskinCutter-Setup
SetupIconFile=..\src\cutup\data\branding\app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
