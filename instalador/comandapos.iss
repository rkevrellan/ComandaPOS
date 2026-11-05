; Inno Setup 6 — instalador de ComandaPOS para Windows 10/11 (64 bits).
; Lo compila build.bat después de PyInstaller:  ISCC.exe instalador\comandapos.iss
;
; - Programa en  C:\Program Files\ComandaPOS   (solo lectura para los usuarios)
; - Datos en     C:\ProgramData\ComandaPOS     (base, clave secreta, ancla de auditoría, PDF, respaldos)
;   Al desinstalar los DATOS NO SE BORRAN: los comprobantes fiscales deben conservarse.
; - Regla de firewall opcional SOLO para redes privadas (servidor de red local).

#define Nombre "ComandaPOS"
#define Version "1.0.0"
#define Autor "Kevin Rellán"

[Setup]
AppId={{6F1C2B7E-3D4A-4C59-9E2B-7A1D5C3F8B21}
AppName={#Nombre}
AppVersion={#Version}
AppVerName={#Nombre} {#Version}
AppPublisher={#Autor}
DefaultDirName={autopf}\{#Nombre}
DefaultGroupName={#Nombre}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#Nombre}-{#Version}-instalador
SetupIconFile=comandapos.ico
UninstallDisplayIcon={app}\ComandaPOS.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENCIA.txt
InfoAfterFile=..\docs\PRIMEROS_PASOS.txt

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "firewall"; Description: "Permitir terminales de la red local (solo redes privadas)"; GroupDescription: "Red local:"; Flags: unchecked

[Dirs]
; Los usuarios del equipo (cajero, mesero) escriben aquí la base de datos y los PDF.
Name: "{commonappdata}\{#Nombre}"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\dist\ComandaPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\*.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\PRIMEROS_PASOS.txt"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\ComandaPOS.exe"
Name: "{group}\{#Nombre} (servidor de red local)"; Filename: "{app}\ComandaPOS-servidor.exe"; Parameters: "--red"
Name: "{group}\Cambiar credenciales de prueba"; Filename: "{app}\ComandaPOS-servidor.exe"; Parameters: "--nuevas-claves"
Name: "{group}\Carpeta de datos y respaldos"; Filename: "{commonappdata}\{#Nombre}"
Name: "{group}\Manual"; Filename: "{app}\docs\MANUAL.md"
Name: "{group}\Desinstalar {#Nombre}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\ComandaPOS.exe"; Tasks: escritorio

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#Nombre}"" dir=in action=allow program=""{app}\ComandaPOS-servidor.exe"" profile=private protocol=TCP enable=yes"; Flags: runhidden; Tasks: firewall; StatusMsg: "Configurando el firewall (solo redes privadas)..."
Filename: "{app}\ComandaPOS.exe"; Description: "Abrir {#Nombre} ahora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#Nombre}"""; Flags: runhidden; RunOnceId: "QuitarFirewall"

[Code]
function InitializeSetup(): Boolean;
var
  Version: String;
begin
  Result := True;
  { WebView2 viene con Windows 11 y con Edge actualizado en Windows 10; sin él se usa el navegador. }
  if not RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    if not RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
      MsgBox('Este equipo no tiene Microsoft Edge WebView2. ComandaPOS funcionará en el navegador.' + #13#10 +
             'Para tener su propia ventana instala "WebView2 Runtime" desde microsoft.com.', mbInformation, MB_OK);
end;
