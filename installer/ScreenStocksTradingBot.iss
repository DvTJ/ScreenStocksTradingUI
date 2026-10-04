; Inno Setup script for the ScreenStocks Trading Bot.
; Build the app first (pyinstaller --noconfirm ScreenStocksTradingBot.spec), then:
;   iscc /DMyAppVersion=1.0.0 installer\ScreenStocksTradingBot.iss
; Output: dist\installer\ScreenStocksTradingBot-Setup-<version>.exe

#define MyAppName "ScreenStocks Trading Bot"
#define MyAppExeName "ScreenStocksTradingBot.exe"
#define MyAppPublisher "ScreenStocksTradingBot"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{6C1C8B0E-3F7A-4B5D-9E62-5A3D2F0B8C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ScreenStocksTradingBot
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin rights needed); the user can choose all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=ScreenStocksTradingBot-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:LanguagesFrench.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ScreenStocksTradingBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName} – Setup"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Settings (%APPDATA%) and recorded history (%LOCALAPPDATA%) are intentionally kept on uninstall.
