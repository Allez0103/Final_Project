#define MyAppName "PA² Pilot Assembly Assistant"
#define MyAppVersion "0.1.0"
#define MyAppExeName "PA2.exe"

[Setup]
AppId={{D36B3C0A-9208-4A9F-A4E9-2AEF2DB14853}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\PA2
DefaultGroupName=PA²
OutputDir=output
OutputBaseFilename=PA2-Setup-{#MyAppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\PA2.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "PA² 실행"; Flags: nowait postinstall skipifsilent

