; Inno Setup 6 — instalador de ComandaPOS para Windows 10/11 (64 bits).
; Lo compila build.bat después de PyInstaller:  ISCC.exe instalador\comandapos.iss
;
; - Programa en  C:\Program Files\ComandaPOS   (solo lectura para los usuarios)
; - Datos en     C:\ProgramData\ComandaPOS     (base, clave secreta, ancla de auditoría, PDF, respaldos)
;   Solo pueden leerla y escribirla Administradores, SYSTEM y el grupo local «ComandaPOS» (H-05):
;   el resto de usuarios de Windows del equipo no ve la base ni la clave secreta.
;   Al desinstalar los DATOS NO SE BORRAN: los comprobantes fiscales deben conservarse.
; - El instalador pregunta «Producción» o «Demostración» y lo guarda en modo.txt (H-03).
; - Regla de firewall opcional SOLO para redes privadas (servidor de red local).

#define Nombre "ComandaPOS"
#define Version "1.1.0"
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
; Los permisos los fija icacls en [Run]: Administradores, SYSTEM y el grupo «ComandaPOS».
Name: "{commonappdata}\{#Nombre}"; Flags: uninsneveruninstall

[Files]
Source: "..\dist\ComandaPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Manuales en .txt: Windows abre .txt con el Bloc de notas; .md no tiene programa asociado (H-23).
Source: "..\README.md"; DestDir: "{app}\docs"; DestName: "LEEME.txt"; Flags: ignoreversion
Source: "..\docs\MANUAL.md"; DestDir: "{app}\docs"; DestName: "MANUAL.txt"; Flags: ignoreversion
Source: "..\docs\FISCAL.md"; DestDir: "{app}\docs"; DestName: "FISCAL.txt"; Flags: ignoreversion
Source: "..\docs\SEGURIDAD.md"; DestDir: "{app}\docs"; DestName: "SEGURIDAD.txt"; Flags: ignoreversion
Source: "..\docs\SUPOSICIONES.md"; DestDir: "{app}\docs"; DestName: "SUPOSICIONES.txt"; Flags: ignoreversion
Source: "..\docs\PRIMEROS_PASOS.txt"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\ComandaPOS.exe"
Name: "{group}\{#Nombre} (servidor de red local)"; Filename: "{app}\ComandaPOS-servidor.exe"; Parameters: "--red"
Name: "{group}\Cambiar credenciales de prueba"; Filename: "{app}\ComandaPOS-servidor.exe"; Parameters: "--nuevas-claves"
Name: "{group}\Empezar con una base nueva"; Filename: "{app}\ComandaPOS-servidor.exe"; Parameters: "--nueva-base"
Name: "{group}\Confiar en el certificado (este equipo)"; Filename: "{app}\ComandaPOS-servidor.exe"; Parameters: "--confiar"
Name: "{group}\Certificado para las terminales"; Filename: "{commonappdata}\{#Nombre}\tls"
Name: "{group}\Carpeta de datos y respaldos"; Filename: "{commonappdata}\{#Nombre}"
Name: "{group}\Manual"; Filename: "{app}\docs\MANUAL.txt"
Name: "{group}\Desinstalar {#Nombre}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\ComandaPOS.exe"; Tasks: escritorio

[Run]
; H-05: grupo local «ComandaPOS» (quien instala queda dentro) y permisos solo para él, Administradores y SYSTEM.
Filename: "{sys}\net.exe"; Parameters: "localgroup ComandaPOS /add /comment:""Usuarios de Windows que usan ComandaPOS"""; Flags: runhidden; StatusMsg: "Creando el grupo de usuarios ComandaPOS..."
Filename: "{sys}\net.exe"; Parameters: "localgroup ComandaPOS ""{username}"" /add"; Flags: runhidden
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\{#Nombre}"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F ComandaPOS:(OI)(CI)M"; Flags: runhidden; StatusMsg: "Protegiendo la carpeta de datos..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#Nombre}"" dir=in action=allow program=""{app}\ComandaPOS-servidor.exe"" profile=private protocol=TCP enable=yes"; Flags: runhidden; Tasks: firewall; StatusMsg: "Configurando el firewall (solo redes privadas)..."
Filename: "{app}\ComandaPOS.exe"; Description: "Abrir {#Nombre} ahora"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#Nombre}"""; Flags: runhidden; RunOnceId: "QuitarFirewall"

[Code]
var
  PaginaModo: TInputOptionWizardPage;

procedure InitializeWizard;
begin
  { H-03: el modo se elige al instalar; nunca queda en demostración por descuido. }
  PaginaModo := CreateInputOptionPage(wpSelectTasks,
    'Modo de uso', '¿Cómo vas a usar ComandaPOS en este equipo?',
    'Producción: base vacía; al abrirlo crearás el primer administrador y configurarás el PAC.' + #13#10 +
    'Demostración: datos de prueba y facturas SIN validez fiscal, para aprender y practicar.',
    True, False);
  PaginaModo.Add('Producción (restaurante en operación)');
  PaginaModo.Add('Demostración (prueba y capacitación)');
  PaginaModo.SelectedValueIndex := 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Archivo: String;
begin
  if CurStep = ssPostInstall then
  begin
    Archivo := ExpandConstant('{commonappdata}\{#Nombre}\modo.txt');
    { En una actualización se respeta el modo que ya tenía el equipo. }
    if not FileExists(Archivo) then
    begin
      if PaginaModo.SelectedValueIndex = 0 then
        SaveStringToFile(Archivo, 'produccion', False)
      else
        SaveStringToFile(Archivo, 'demostracion', False);
    end;
  end;
end;

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
