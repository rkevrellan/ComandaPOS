"""Bitácora de auditoría encadenada (OWASP A08 integridad y A09 registro).

Cómo funciona:
1. `auditar()` agrega el registro a la MISMA transacción de la operación (si la operación se
   revierte, su registro también; nunca queda una anulación sin rastro ni un rastro sin anulación).
2. Después de confirmar, `sellar_pendientes()` toma los registros sin sello en orden y a cada uno le
   pone `sello` (1, 2, 3…), `hash_previo` (el hash del anterior) y `hash` = HMAC-SHA256 de sus
   campos + el hash previo, con una llave derivada de la clave secreta de la instalación.
3. Tras sellar se escribe el «ancla» (último sello y hash, firmados) en un archivo FUERA de la base.

`verificar()` recorre la cadena: si alguien edita un registro a mano, borra uno del medio o
trunca los últimos, la verificación lo detecta. Sin la clave secreta no se puede recalcular la cadena.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading

from flask import current_app, g, has_request_context, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..extensions import db
from ..models import Auditoria

GENESIS = "0" * 64
_LOCK = threading.Lock()
_CONTROL = re.compile("[\x00-\x1f\x7f  ]")


def limpiar_log(texto, maximo: int = 300) -> str:
    """Sin saltos de línea ni caracteres de control: nadie falsifica líneas de la bitácora (A09)."""
    return _CONTROL.sub(" ", str(texto or ""))[:maximo]


def _terminal() -> str:
    if not has_request_context():
        return "sistema"
    return limpiar_log(request.remote_addr or "", 60)


def auditar(
    accion: str, detalle: str = "", operador=None, autorizador=None
) -> Auditoria:
    """Agrega un registro a la transacción actual (el que llama confirma)."""
    from flask_login import current_user

    if operador is None and has_request_context() and current_user.is_authenticated:
        operador = current_user
    registro = Auditoria(
        operador_id=getattr(operador, "id", None),
        autorizador_id=getattr(autorizador, "id", None),
        accion=limpiar_log(accion, 40),
        detalle=limpiar_log(detalle),
        terminal=_terminal(),
    )
    db.session.add(registro)
    if has_request_context():
        g.auditoria_pendiente = True  # se sella al terminar la petición
    return registro


def auditar_ya(accion: str, detalle: str = "", operador=None, autorizador=None) -> None:
    """Registra y confirma de inmediato (eventos sin otra transacción: accesos, fallos…)."""
    try:
        auditar(accion, detalle, operador, autorizador)
        db.session.commit()
    except Exception:  # pragma: no cover - la auditoría nunca tumba la petición
        db.session.rollback()
        current_app.logger.exception("No se pudo registrar la auditoría %s", accion)


# --------------------------------------------------------------------------- cadena
def _llave() -> bytes:
    secreto = current_app.config["SECRET_KEY"]
    return hashlib.sha256(("comandapos-auditoria:" + secreto).encode()).digest()


def _huella(llave: bytes, r: Auditoria, previo: str) -> str:
    datos = "\x1f".join(
        [
            str(r.sello),
            str(r.id),
            r.fecha.isoformat(timespec="microseconds"),
            str(r.operador_id or ""),
            str(r.autorizador_id or ""),
            r.accion,
            r.detalle,
            r.terminal,
            previo,
        ]
    )
    return hmac.new(llave, datos.encode(), hashlib.sha256).hexdigest()


def _ruta_ancla() -> str:
    return os.path.join(current_app.config["DATOS"], "auditoria.ancla")


def _firmar_ancla(llave: bytes, sello: int, hash_: str) -> str:
    return hmac.new(
        llave, f"ancla|{sello}|{hash_}".encode(), hashlib.sha256
    ).hexdigest()


def _escribir_ancla(llave: bytes, sello: int, hash_: str) -> None:
    ruta = _ruta_ancla()
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(
            {
                "sello": sello,
                "hash": hash_,
                "firma": _firmar_ancla(llave, sello, hash_),
            },
            f,
        )
    os.replace(temporal, ruta)  # reemplazo atómico: nunca queda un ancla a medias


def _leer_ancla():
    try:
        with open(_ruta_ancla(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def sellar_pendientes() -> int:
    """Encadena los registros confirmados que aún no tienen sello. Devuelve cuántos selló."""
    llave = _llave()
    with _LOCK, Session(db.engine) as s:
        ultimo = s.scalars(
            select(Auditoria)
            .where(Auditoria.sello.is_not(None))
            .order_by(Auditoria.sello.desc())
            .limit(1)
        ).first()
        sello = ultimo.sello if ultimo else 0
        previo = ultimo.hash if ultimo else GENESIS
        pendientes = s.scalars(
            select(Auditoria).where(Auditoria.sello.is_(None)).order_by(Auditoria.id)
        ).all()
        if not pendientes:
            return 0
        for r in pendientes:
            sello += 1
            r.sello = sello
            r.hash_previo = previo
            r.hash = _huella(llave, r, previo)
            previo = r.hash
        s.commit()
        _escribir_ancla(llave, sello, previo)
        return len(pendientes)


def verificar() -> dict:
    """Recorre la cadena completa y la compara con el ancla externa."""
    llave = _llave()
    resultado = {
        "ok": True,
        "sellados": 0,
        "pendientes": 0,
        "error": None,
        "registro": None,
    }
    with Session(db.engine) as s:
        resultado["pendientes"] = len(
            s.scalars(select(Auditoria.id).where(Auditoria.sello.is_(None))).all()
        )
        previo, esperado = GENESIS, 1
        ultimo = None
        for r in s.scalars(
            select(Auditoria)
            .where(Auditoria.sello.is_not(None))
            .order_by(Auditoria.sello)
        ):
            if r.sello != esperado:
                return _falla(
                    resultado,
                    r.id,
                    f"Falta el registro con sello {esperado} (borrado).",
                )
            if r.hash_previo != previo or not hmac.compare_digest(
                r.hash, _huella(llave, r, previo)
            ):
                return _falla(
                    resultado, r.id, "El registro fue modificado fuera del sistema."
                )
            previo, esperado, ultimo = r.hash, esperado + 1, r
            resultado["sellados"] += 1
        ancla = _leer_ancla()
        if ancla is None:
            if ultimo is not None:
                return _falla(
                    resultado, None, "Falta el archivo ancla de la auditoría."
                )
            return resultado
        if not hmac.compare_digest(
            str(ancla.get("firma", "")),
            _firmar_ancla(
                llave, int(ancla.get("sello", 0)), str(ancla.get("hash", ""))
            ),
        ):
            return _falla(resultado, None, "El archivo ancla fue alterado.")
        sello_ancla = int(ancla["sello"])
        if ultimo is None or ultimo.sello < sello_ancla:
            return _falla(
                resultado,
                None,
                f"Se borraron los últimos registros (el ancla indica {sello_ancla}).",
            )
        en_ancla = s.scalars(
            select(Auditoria).where(Auditoria.sello == sello_ancla)
        ).first()
        if en_ancla is None or en_ancla.hash != ancla["hash"]:
            return _falla(resultado, None, "La cadena no coincide con el ancla.")
    return resultado


def _falla(resultado: dict, registro_id, motivo: str) -> dict:
    resultado.update(ok=False, error=motivo, registro=registro_id)
    return resultado
