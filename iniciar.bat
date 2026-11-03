@echo off
rem ComandaPOS - inicio en Windows (doble clic). La primera vez crea el entorno e instala todo.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo Creando el entorno de Python...
    %PY% -m venv .venv || goto error
)
echo Revisando dependencias...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto error
".venv\Scripts\python.exe" run.py %*
goto fin

:error
echo.
echo No se pudo iniciar ComandaPOS. Instala Python 3.11 o superior desde python.org
echo (marca "Add python.exe to PATH") y vuelve a intentarlo.
pause
:fin
endlocal
