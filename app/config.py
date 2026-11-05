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
VERSION = "1.0.0"
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


def modo_demo() -> bool:
    """La demostración está encendida salvo que se pida producción explícitamente."""
    return os.environ.get("COMANDAPOS_PRODUCCION", "") != "1"
