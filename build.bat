@echo off
rem ============================================================================================
rem  ComandaPOS - construye el instalador de Windows (doble clic o desde la consola).
rem  Requisitos en el equipo de construccion:
rem    - Python 3.12 o superior (python.org, marcar "Add python.exe to PATH")
rem    - Inno Setup 6 (jrsoftware.org) para el instalador; sin el, queda la carpeta dist\ComandaPOS
rem  Pasos: entorno limpio -> dependencias -> pruebas -> pip-audit -> bandit -> PyInstaller
rem         -> Inno Setup -> SHA256SUMS.txt.  Si un paso falla, se detiene.
rem ============================================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

echo.
echo [1/7] Entorno de construccion (.venv-build)
if exist ".venv-build" rmdir /s /q ".venv-build"
%PY% -m venv .venv-build || goto error
set VPY=.venv-build\Scripts\python.exe
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip || goto error

echo [2/7] Dependencias
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements-build.txt || goto error

echo [3/7] Pruebas automaticas
"%VPY%" -m pytest -q -p no:cacheprovider || goto error

echo [4/7] Dependencias sin vulnerabilidades conocidas (pip-audit)
"%VPY%" -m pip_audit -r requirements.txt || goto error

echo [5/7] Analisis estatico de seguridad (bandit, severidad media o alta)
"%VPY%" -m bandit -q -r app run.py escritorio.py seed.py -ll -c bandit.yaml || goto error

echo [6/7] Empaquetado (PyInstaller)
rem La llave de suscripcion debe ser la del proveedor (proveedor\emitir_codigo.py crear-llave).
"%VPY%" run.py --verificar-llave || goto error
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
"%VPY%" -m PyInstaller --noconfirm --clean comandapos.spec || goto error
"dist\ComandaPOS\ComandaPOS-servidor.exe" --verificar || goto error

echo [7/7] Instalador (Inno Setup)
set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    %ISCC% /Q instalador\comandapos.iss || goto error
) else (
    echo    Inno Setup 6 no esta instalado: se omite el instalador.
    echo    La version portable quedo en dist\ComandaPOS\ComandaPOS.exe
)

echo.
echo Huellas SHA-256 (para verificar que nadie altero los archivos):
"%VPY%" -c "import hashlib,pathlib;fs=[p for p in pathlib.Path('dist').glob('*.exe')]+[pathlib.Path('dist/ComandaPOS/ComandaPOS.exe'),pathlib.Path('dist/ComandaPOS/ComandaPOS-servidor.exe')];t=''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.as_posix()}'+chr(10) for p in fs if p.exists());pathlib.Path('dist/SHA256SUMS.txt').write_text(t);print(t)"

echo Listo. Revisa la carpeta dist\
echo Recomendado antes de distribuir: firmar los .exe con un certificado de firma de codigo (signtool).
goto fin

:error
echo.
echo *** La construccion se detuvo en el paso anterior. Revisa el mensaje de arriba. ***
exit /b 1

:fin
endlocal
