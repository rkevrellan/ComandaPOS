# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: genera dist/ComandaPOS/ con dos programas que comparten las mismas librerías:
#   ComandaPOS.exe           → ventana de escritorio (este equipo)       [escritorio.py]
#   ComandaPOS-servidor.exe  → servidor con consola (red local, claves)  [run.py]
# Uso:  pyinstaller --noconfirm --clean comandapos.spec      (build.bat lo hace todo)
#
# Modo "onedir" a propósito: arranca más rápido que "onefile", no se descomprime en %TEMP% en cada
# apertura y los antivirus lo marcan mucho menos. Los datos NO van aquí: viven en %PROGRAMDATA%.

import os

from PyInstaller.utils.hooks import collect_submodules

RAIZ = os.path.abspath(SPECPATH)
ICONO = os.path.join(RAIZ, "instalador", "comandapos.ico")

DATOS = [
    (os.path.join(RAIZ, "app", "templates"), os.path.join("app", "templates")),
    (os.path.join(RAIZ, "app", "static"), os.path.join("app", "static")),
]
OCULTOS = (
    collect_submodules("app")
    + collect_submodules("waitress")
    + collect_submodules("reportlab.graphics.barcode")
    + collect_submodules("cheroot")
    + ["seed", "run", "sqlalchemy.dialects.sqlite"]
    + (["win32print", "win32api", "pywintypes"] if os.name == "nt" else [])
)
FUERA = ["tkinter", "pytest", "_pytest", "IPython", "matplotlib", "numpy", "PIL.ImageQt"]


def analisis(script):
    return Analysis(
        [os.path.join(RAIZ, script)],
        pathex=[RAIZ],
        datas=DATOS,
        hiddenimports=OCULTOS,
        excludes=FUERA,
        noarchive=False,
        optimize=0,  # 0: los assert de las reglas de negocio se mantienen
    )


a_ventana = analisis("escritorio.py")
a_servidor = analisis("run.py")

exe_ventana = EXE(
    PYZ(a_ventana.pure),
    a_ventana.scripts,
    [],
    exclude_binaries=True,
    name="ComandaPOS",
    icon=ICONO,
    console=False,
    upx=False,
    version=os.path.join(RAIZ, "instalador", "version.txt"),
)
exe_servidor = EXE(
    PYZ(a_servidor.pure),
    a_servidor.scripts,
    [],
    exclude_binaries=True,
    name="ComandaPOS-servidor",
    icon=ICONO,
    console=True,
    upx=False,
    version=os.path.join(RAIZ, "instalador", "version.txt"),
)

COLLECT(
    exe_ventana,
    a_ventana.binaries,
    a_ventana.datas,
    exe_servidor,
    a_servidor.binaries,
    a_servidor.datas,
    strip=False,
    upx=False,
    name="ComandaPOS",
)
