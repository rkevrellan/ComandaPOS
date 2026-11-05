"""Secretos del equipo (credencial del PAC) guardados en la carpeta de datos, nunca en la base.

H-09: el Administrador de credenciales de Windows es POR USUARIO: si el administrador guardaba la
credencial con su cuenta y el servidor corría con la del cajero, no la encontraba. Ahora:

- Windows: archivo cifrado con DPAPI a nivel de EQUIPO (CRYPTPROTECT_LOCAL_MACHINE). Cualquier cuenta
  del equipo que pueda LEER el archivo lo descifra, y por eso vive en la carpeta de datos, que solo
  pueden leer Administradores, SYSTEM y el grupo «ComandaPOS» (H-05). Copiado a otra PC no sirve.
- Otros sistemas (desarrollo): archivo con permisos 0600.
- La variable de entorno COMANDAPOS_PAC_TOKEN tiene prioridad (despliegues administrados).
"""

from __future__ import annotations

import base64
import os

from flask import current_app

_PREFIJO_DPAPI = b"DPAPI1:"
_PREFIJO_PLANO = b"PLANO1:"


def _ruta(nombre: str) -> str:
    return os.path.join(current_app.config["DATOS"], f"{nombre}.credencial")


# --------------------------------------------------------------------------- DPAPI (Windows)
def _dpapi(datos: bytes, proteger: bool) -> bytes:  # pragma: no cover - solo Windows
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buffer = ctypes.create_string_buffer(datos, len(datos))
    entrada = Blob(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    salida = Blob()
    sin_ventanas, equipo = (
        0x1,
        0x4,
    )  # CRYPTPROTECT_UI_FORBIDDEN, CRYPTPROTECT_LOCAL_MACHINE
    crypt32 = ctypes.windll.crypt32
    if proteger:
        ok = crypt32.CryptProtectData(
            ctypes.byref(entrada),
            ctypes.c_wchar_p("ComandaPOS"),
            None,
            None,
            None,
            sin_ventanas | equipo,
            ctypes.byref(salida),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(entrada),
            None,
            None,
            None,
            None,
            sin_ventanas,
            ctypes.byref(salida),
        )
    if not ok:
        raise OSError("DPAPI no pudo procesar la credencial.")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def guardar(nombre: str, valor: str) -> None:
    datos = valor.encode("utf-8")
    if os.name == "nt":  # pragma: no cover - solo Windows
        contenido = _PREFIJO_DPAPI + base64.b64encode(_dpapi(datos, proteger=True))
    else:
        contenido = _PREFIJO_PLANO + base64.b64encode(datos)
    ruta = _ruta(nombre)
    temporal = ruta + ".tmp"
    fd = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(contenido)
    os.replace(temporal, ruta)


def leer(nombre: str) -> str:
    try:
        with open(_ruta(nombre), "rb") as f:
            contenido = f.read()
    except OSError:
        return ""
    try:
        if contenido.startswith(_PREFIJO_DPAPI):  # pragma: no cover - solo Windows
            return _dpapi(
                base64.b64decode(contenido[len(_PREFIJO_DPAPI) :]), proteger=False
            ).decode("utf-8")
        if contenido.startswith(_PREFIJO_PLANO):
            return base64.b64decode(contenido[len(_PREFIJO_PLANO) :]).decode("utf-8")
    except (OSError, ValueError):
        current_app.logger.warning("No se pudo leer la credencial %s", nombre)
    return ""
