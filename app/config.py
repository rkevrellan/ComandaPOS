"""Configuración general de ComandaPOS.

El nombre del sistema se cambia solo aquí (`NOMBRE`). Los datos (base, clave secreta, bitácoras,
respaldos y ancla de auditoría) viven fuera de la carpeta del programa:

- `COMANDAPOS_DATA` si está definida;
- en Windows, `%PROGRAMDATA%\\ComandaPOS`;
- en otros sistemas (desarrollo), la carpeta `instance/` del proyecto.
"""

from __future__ import annotations

import os

NOMBRE = "ComandaPOS"
VERSION = "1.1.0"
LEMA = "Del pedido a la factura, sin perder una comanda."

#: Niveles de seguridad del sistema de referencia, de menor a mayor.
ROLES = ("operador", "cajero", "supervisor", "administrador", "programador")
NOMBRE_ROL = {
    "operador": "Operador (mesero)",
    "cajero": "Cajero",
    "supervisor": "Supervisor",
    "administrador": "Administrador",
    "programador": "Programador",
}
#: Roles que entran con PIN numérico; el resto usa contraseña.
ROLES_CON_PIN = ("operador", "cajero")

#: Bloqueo por inactividad en segundos, según el rol (las terminales de mesero son compartidas).
INACTIVIDAD_SEG = {
    "operador": 90,
    "cajero": 300,
    "supervisor": 300,
    "administrador": 900,
    "programador": 900,
}
#: Duración máxima de una sesión aunque haya actividad.
SESION_MAXIMA_H = 12



def carpeta_datos(respaldo: str) -> str:
    """Carpeta de datos persistentes (se crea si no existe)."""
    ruta = os.environ.get("COMANDAPOS_DATA")
    if not ruta and os.name == "nt" and os.environ.get("PROGRAMDATA"):
        ruta = os.path.join(os.environ["PROGRAMDATA"], NOMBRE)
    ruta = ruta or respaldo
    os.makedirs(ruta, exist_ok=True)
    return ruta


ARCHIVO_MODO = "modo.txt"


def modo_demo(datos: str | None = None) -> bool:
    """¿Demostración o producción? (H-03)

    1. La variable COMANDAPOS_PRODUCCION manda si existe («1» producción, «0» demostración).
    2. Si no, el archivo «modo.txt» de la carpeta de datos (lo escribe el instalador o
       `ComandaPOS-servidor.exe --modo produccion`).
    3. Sin ninguno de los dos (desarrollo): demostración.
    """
    variable = os.environ.get("COMANDAPOS_PRODUCCION")
    if variable in ("0", "1"):
        return variable == "0"
    if datos:
        try:
            with open(os.path.join(datos, ARCHIVO_MODO), encoding="utf-8") as f:
                return f.read().strip().lower() != "produccion"
        except OSError:
            pass
    return True


def fijar_modo(datos: str, produccion: bool) -> None:
    with open(os.path.join(datos, ARCHIVO_MODO), "w", encoding="utf-8") as f:
        f.write("produccion\n" if produccion else "demostracion\n")
