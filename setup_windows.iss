; Inno Setup script for iPad Mirror
; Build with:  iscc setup_windows.iss
; Or let build_windows.bat run it automatically.

#define AppName      "iPad Mirror"
#define AppVersion   "1.0"
#define AppPublisher "iPad Mirror"
#define AppExeName   "iPad Mirror.exe"
#define AppId        "{{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=iPad_Mirror_Setup
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; Require Windows 10 or later
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\{#AppExeName}";    DestDir: "{app}"; Flags: ignoreversion
Source: "dist\tunnel_helper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\icon.ico";        DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (optional, user-selected)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
; Offer to launch the app after installation
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up any leftover files on uninstall
Type: filesandordirs; Name: "{app}"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nThe app mirrors your iPad screen to your PC over USB.%n%nClick Next to continue.

[Code]
// Check if iTunes / Apple Mobile Device Support is installed
// (required for USB iPad detection)
function ItunesInstalled: Boolean;
var
  path: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\Apple Inc.\Apple Mobile Device Support',
                                'InstallDir', path);
  if not Result then
    Result := RegQueryStringValue(HKLM64, 'SOFTWARE\Apple Inc.\Apple Mobile Device Support',
                                  'InstallDir', path);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    if not ItunesInstalled then begin
      MsgBox(
        'iTunes (or Apple Mobile Device Support) was not detected.' + #13#10 + #13#10 +
        'iPad Mirror needs iTunes drivers to detect your iPad over USB.' + #13#10 +
        'Please install iTunes from the Microsoft Store or apple.com/itunes' + #13#10 +
        'before using the app.',
        mbInformation, MB_OK
      );
    end;
  end;
end;
