#ifndef AppVersion
  #error AppVersion must be provided by build_native.py
#endif
[Setup]
AppId={{27288238-CE78-4C41-A51A-5337E42E6E58}
AppName=AI Run Relay
AppVersion={#AppVersion}
AppPublisher=AI Run Relay
DefaultDirName={localappdata}\Programs\AI Run Relay
DefaultGroupName=AI Run Relay
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release-native
OutputBaseFilename=AI-Run-Relay-{#AppVersion}-windows-x64-setup
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayIcon={app}\AI-Run-Relay.exe

[Files]
Source: "..\build\native\launcher.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{group}\AI Run Relay"; Filename: "{app}\AI-Run-Relay.exe"
Name: "{autodesktop}\AI Run Relay"; Filename: "{app}\AI-Run-Relay.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AI-Run-Relay.exe"; Description: "Launch AI Run Relay"; Flags: nowait postinstall skipifsilent

; No UninstallDelete of user data. Upgrades and uninstall retain jobs/workspaces.
