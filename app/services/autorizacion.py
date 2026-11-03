"""Autorización de supervisor en el momento (sin cerrar la sesión del operador).

Si quien pide ya tiene el nivel, se autoriza él mismo. Si no, un supervisor escribe SU usuario y
SU clave en la misma pantalla. Intentos fallidos limitados por terminal (A07) y todo auditado.
"""

from __future__ import annotations

from werkzeug.security import check_password_hash

from ..models import Operador
from ..seguridad import AUTORIZACION, hash_relleno
from .calculos import ReglaNegocioError


def autorizar(
    rol_minimo: str, solicitante: Operador, usuario: str, clave: str, terminal: str
) -> Operador:
    if solicitante.puede(rol_minimo):
        return solicitante
    if AUTORIZACION.espera(terminal):
        raise ReglaNegocioError(
            "Demasiadas autorizaciones fallidas. Espera unos minutos."
        )
    usuario = (usuario or "").strip().lower()[:30]
    op = Operador.query.filter_by(usuario=usuario).first() if usuario else None
    if op is None:
        check_password_hash(hash_relleno(), clave or "x")  # mismo trabajo exista o no
        valido = False
    else:
        valido = op.verificar_clave(clave or "")
    if not (valido and op.activo and op.puede(rol_minimo)):
        AUTORIZACION.fallo(terminal)
        raise ReglaNegocioError(
            "La autorización no es válida: hace falta un usuario con nivel "
            f"{rol_minimo} o superior y su clave."
        )
    AUTORIZACION.limpiar(terminal)
    return op
