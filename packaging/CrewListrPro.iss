#define AppName "CrewListr Pro"
#define AppVersion "0.1.0"
#define AppPublisher "Tsevis"
#define AppExeName "CrewListrPro.exe"

[Setup]
AppId={{B861FB98-566A-4973-9684-A8E16AAEC2E5}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\CrewListr Pro
DefaultGroupName=CrewListr Pro
OutputDir=..\dist\installer
OutputBaseFilename=CrewListrPro-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\dist\CrewListrPro\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\CrewListr Pro"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\CrewListr Pro"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch CrewListr Pro"; Flags: nowait postinstall skipifsilent
