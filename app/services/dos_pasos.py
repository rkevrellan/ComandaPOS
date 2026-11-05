"""Verificación en dos pasos (TOTP, RFC 6238) sin dependencias externas.

- Compatible con Google Authenticator, Microsoft Authenticator, Authy, etc.
- Ventana de ±30 s y protección contra repetición: un código ya usado no vuelve a servir.
- 8 códigos de recuperación de un solo uso, guardados con hash (scrypt); se muestran UNA vez.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from reportlab.graphics import renderSVG
from werkzeug.security import check_password_hash, generate_password_hash

from ..config import NOMBRE

PASO = 30
DIGITOS = 6


def nuevo_secreto() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(secreto: str, paso: int) -> str:
    llave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    h = hmac.new(llave, struct.pack(">Q", paso), hashlib.sha1).digest()
    desfase = h[-1] & 0x0F
    numero = (
        struct.unpack(">I", h[desfase : desfase + 4])[0] & 0x7FFFFFFF
    ) % 10**DIGITOS
    return f"{numero:0{DIGITOS}d}"


def codigo_actual(secreto: str, momento: float | None = None) -> str:
    return _codigo(secreto, int((momento or time.time()) // PASO))


def verificar(
    operador, codigo: str, secreto: str | None = None, momento: float | None = None
) -> bool:
    """Valida el código y marca el paso como usado (no se acepta dos veces el mismo)."""
    secreto = secreto or operador.totp_secreto
    codigo = "".join(ch for ch in (codigo or "") if ch.isdigit())
    if not secreto or len(codigo) != DIGITOS:
        return False
    actual = int((momento or time.time()) // PASO)
    for paso in (actual - 1, actual, actual + 1):
        if operador.totp_ultimo_paso is not None and paso <= operador.totp_ultimo_paso:
            continue
        if hmac.compare_digest(_codigo(secreto, paso), codigo):
            operador.totp_ultimo_paso = paso
            return True
    return False


def uri(operador, secreto: str) -> str:
    etiqueta = quote(f"{NOMBRE}:{operador.usuario}")
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(NOMBRE)}&digits={DIGITOS}&period={PASO}"


def qr_svg(texto: str) -> str:
    """Código QR como imagen `data:` SVG (sin servicios externos y compatible con la CSP estricta:
    un SVG usado como imagen no ejecuta nada ni aplica estilos a la página)."""
    from .pdf import _qr

    svg = renderSVG.drawToString(_qr(texto, 180))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def nuevos_codigos_recuperacion() -> tuple[list, str]:
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codigos = [
        "".join(secrets.choice(alfabeto) for _ in range(5))
        + "-"
        + "".join(secrets.choice(alfabeto) for _ in range(5))
        for _ in range(8)
    ]
    hashes = [generate_password_hash(c, method="scrypt") for c in codigos]
    return codigos, json.dumps(hashes)


def usar_codigo_recuperacion(operador, codigo: str) -> bool:
    codigo = (codigo or "").strip().upper()
    if len(codigo) != 11:
        return False
    try:
        hashes = json.loads(operador.codigos_recuperacion or "[]")
    except ValueError:
        return False
    for h in hashes:
        if check_password_hash(h, codigo):
            hashes.remove(h)
            operador.codigos_recuperacion = json.dumps(hashes)
            return True
    return False


def restantes(operador) -> int:
    try:
        return len(json.loads(operador.codigos_recuperacion or "[]"))
    except ValueError:
        return 0
