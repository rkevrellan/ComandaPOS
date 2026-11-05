"""Facturación electrónica de Panamá (DGI · SFEP) a través de un PAC.

- El sistema NUNCA inventa el CUFE ni el QR: los recibe del proveedor al autorizarse el documento.
- La venta no se detiene si el PAC o internet fallan: el documento queda en «contingencia» y se reenvía.
- La llamada al PAC ocurre FUERA de la transacción de la venta (la base no queda bloqueada esperando).
- `PACSimulado` solo existe en la demostración: sus documentos dicen «SIN VALIDEZ FISCAL».
- `PACHttp` es genérico: se conecta SOLO a la URL configurada por el administrador (A10) y la
  credencial va en el almacén seguro del sistema (DPAPI en Windows) o en una variable de entorno,
  nunca en la base de datos. Ver docs/FISCAL.md para mapearlo a la API del PAC contratado.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from flask import current_app

from ..extensions import db
from ..models import Documento, NotaCredito, ahora
from . import configuracion
from .auditoria import auditar

ESTADOS_PENDIENTES = ("pendiente", "contingencia")
TIEMPO_MAXIMO = 8  # segundos


class ErrorConexionPAC(Exception):
    """El PAC no respondió o respondió algo ilegible: el documento queda en contingencia."""


@dataclass
class ResultadoFiscal:
    ok: bool
    cufe: str = ""
    protocolo: str = ""
    qr: str = ""
    mensaje: str = ""


class ProveedorFiscal:
    nombre = "base"
    simulado = False

    def emitir(self, carga: dict) -> ResultadoFiscal:  # pragma: no cover - interfaz
        raise NotImplementedError


class PACSimulado(ProveedorFiscal):
    """Solo para demostración y pruebas. Imita la autorización de un PAC."""

    nombre = "simulado"
    simulado = True

    def emitir(self, carga: dict) -> ResultadoFiscal:
        if configuracion.obtener("fiscal.simular_caida") == "1":
            raise ErrorConexionPAC(
                "El PAC simulado está «caído» (prueba de contingencia)."
            )
        huella = (
            hashlib.sha256(json.dumps(carga, sort_keys=True).encode())
            .hexdigest()
            .upper()
        )
        ruc = "".join(ch for ch in carga["emisor"]["ruc"] if ch.isdigit())[:12].rjust(
            12, "0"
        )
        cufe = f"SIM{carga['tipo']}{ruc}{carga['punto']}{carga['numero']:010d}{huella[:24]}"
        protocolo = str(int(huella[:12], 16))[:14]
        return ResultadoFiscal(
            True, cufe=cufe, protocolo=protocolo, qr=carga.get("url_consulta", "")
        )


class PACHttp(ProveedorFiscal):
    """Cliente HTTP genérico. Espera JSON {estado, cufe, protocolo, qr, mensaje}."""

    nombre = "http"

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token

    def emitir(self, carga: dict) -> ResultadoFiscal:
        cuerpo = json.dumps(
            {k: v for k, v in carga.items() if k != "url_consulta"}
        ).encode()
        peticion = urllib.request.Request(
            self.url,
            data=cuerpo,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            # La URL ya pasó url_pac_valida(): solo https:// (nunca file:// ni otros esquemas).
            with urllib.request.urlopen(  # nosec B310
                peticion, timeout=TIEMPO_MAXIMO
            ) as resp:
                datos = json.loads(resp.read(200_000).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise ErrorConexionPAC(
                f"Sin respuesta del PAC: {type(e).__name__}"
            ) from None
        if not isinstance(datos, dict):
            raise ErrorConexionPAC("Respuesta del PAC ilegible.")
        if datos.get("estado") == "autorizado" and datos.get("cufe"):
            return ResultadoFiscal(
                True,
                cufe=str(datos["cufe"])[:80],
                protocolo=str(datos.get("protocolo", ""))[:60],
                qr=str(datos.get("qr", ""))[:2000],
            )
        return ResultadoFiscal(
            False, mensaje=str(datos.get("mensaje") or "Rechazado por el PAC")[:200]
        )


def url_pac_valida(url: str) -> bool:
    """Solo HTTPS (o http a la propia máquina, para pruebas del integrador)."""
    p = urlparse(url or "")
    if p.scheme == "https" and p.hostname:
        return True
    return p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")


def _token_pac() -> str:
    if os.environ.get("COMANDAPOS_PAC_TOKEN"):
        return os.environ["COMANDAPOS_PAC_TOKEN"]
    try:  # almacén seguro del sistema (DPAPI en Windows)
        import keyring

        return keyring.get_password("ComandaPOS", "pac") or ""
    except Exception:  # pragma: no cover - keyring no instalado
        return ""


def proveedor() -> ProveedorFiscal | None:
    tipo = configuracion.obtener("fiscal.proveedor")
    if tipo == "simulado":
        return (
            PACSimulado() if current_app.config["DEMO"] else None
        )  # nunca fuera de la demostración
    if tipo == "http":
        url = configuracion.obtener("fiscal.pac_url")
        token = _token_pac()
        if url_pac_valida(url) and token:
            return PACHttp(url, token)
    return None


# --------------------------------------------------------------------------- carga
def _detalle(doc) -> dict:
    try:
        datos = json.loads(doc.detalle or "{}")
    except ValueError:
        datos = {}
    if isinstance(datos, list):
        datos = {"items": datos}
    return datos if isinstance(datos, dict) else {}


def items(doc) -> list:
    return _detalle(doc).get("items", [])


def pagos(doc) -> list:
    return _detalle(doc).get("pagos", [])


def armar_carga(doc, url_consulta: str = "") -> dict:
    es_nc = isinstance(doc, NotaCredito)
    carga = {
        "tipo": "04" if es_nc else "01",
        "numero": doc.numero,
        "punto": configuracion.obtener("emisor.punto_facturacion"),
        "sucursal": configuracion.obtener("emisor.sucursal"),
        "fecha": doc.emitido_en.isoformat(timespec="seconds") + "Z",
        "emisor": {
            "ruc": configuracion.obtener("emisor.ruc"),
            "dv": configuracion.obtener("emisor.dv"),
            "razon_social": configuracion.obtener("emisor.razon_social"),
            "direccion": configuracion.obtener("emisor.direccion"),
        },
        "receptor": {
            "ruc": doc.receptor_ruc,
            "dv": doc.receptor_dv or "",
            "nombre": doc.receptor_nombre,
        },
        "items": items(doc),
        "totales": {
            "subtotal": str(doc.subtotal),
            "descuento": str(doc.descuento_producto + doc.descuento_jubilado),
            "itbms": str(doc.itbms),
            "total": str(doc.total),
        },
        "impuestos": json.loads(doc.impuestos or "{}"),
        "pagos": pagos(doc),
        "url_consulta": url_consulta,
    }
    if es_nc:
        carga["referencia"] = {
            "numero": doc.documento.numero,
            "cufe": doc.documento.cufe,
            "motivo": doc.motivo,
        }
    return carga


# --------------------------------------------------------------------------- autorización
def autorizar(doc, url_consulta: str = "") -> str:
    """Intenta autorizar el documento con el PAC. Devuelve el estado final. El que llama confirma."""
    doc.intentos = (doc.intentos or 0) + 1
    prov = proveedor()
    etiqueta = f"{'NC' if isinstance(doc, NotaCredito) else 'FE'} {doc.numero}"
    if prov is None:
        doc.estado = "contingencia"
        doc.mensaje = (
            "Sin proveedor fiscal configurado: queda pendiente de autorización."
        )
        auditar("fiscal_contingencia", f"{etiqueta}: {doc.mensaje}")
        return doc.estado
    try:
        r = prov.emitir(armar_carga(doc, url_consulta))
    except ErrorConexionPAC as e:
        doc.estado = "contingencia"
        doc.mensaje = str(e)[:200]
        auditar("fiscal_contingencia", f"{etiqueta}: {doc.mensaje}")
        return doc.estado
    if r.ok:
        doc.cufe = r.cufe
        doc.protocolo = r.protocolo
        doc.qr = r.qr or url_consulta
        doc.autorizado_en = ahora()
        doc.estado = "simulado" if prov.simulado else "autorizado"
        doc.mensaje = None
        auditar("fiscal_autorizado", f"{etiqueta}: {doc.cufe[:24]}… ({prov.nombre})")
    else:
        doc.estado = "rechazado"
        doc.mensaje = r.mensaje
        auditar("fiscal_rechazado", f"{etiqueta}: {r.mensaje}")
    return doc.estado


def pendientes(limite: int = 50) -> list:
    docs = (
        Documento.query.filter(Documento.estado.in_(ESTADOS_PENDIENTES))
        .order_by(Documento.id)
        .limit(limite)
        .all()
    )
    ncs = (
        NotaCredito.query.filter(NotaCredito.estado.in_(ESTADOS_PENDIENTES))
        .order_by(NotaCredito.id)
        .limit(limite)
        .all()
    )
    return docs + ncs


def reenviar_pendientes(url_de, limite: int = 20) -> tuple[int, int]:
    """Reintenta los documentos en contingencia (uno por uno, confirmando cada resultado)."""
    autorizados = fallidos = 0
    for doc in pendientes(limite):
        estado = autorizar(doc, url_de(doc))
        db.session.commit()
        if estado in ("autorizado", "simulado"):
            autorizados += 1
        else:
            fallidos += 1
            if estado == "contingencia":
                break  # el PAC sigue caído: no insistir con los demás ahora
    return autorizados, fallidos


# --------------------------------------------------------------------------- folios
def folios() -> dict:
    total = int(configuracion.obtener("fiscal.folios_total") or 0)
    usados = (
        Documento.query.filter(Documento.estado.in_(("autorizado", "simulado"))).count()
        + NotaCredito.query.filter(
            NotaCredito.estado.in_(("autorizado", "simulado"))
        ).count()
    )
    disponibles = max(0, total - usados) if total else None
    alerta = bool(total) and disponibles < max(1, total // 10)
    return {
        "total": total,
        "usados": usados,
        "disponibles": disponibles,
        "alerta": alerta,
    }


def leyenda(doc) -> str:
    return {
        "simulado": "DOCUMENTO DE PRUEBA — SIN VALIDEZ FISCAL",
        "pendiente": "PENDIENTE DE AUTORIZACIÓN DE LA DGI",
        "contingencia": "EMITIDO EN CONTINGENCIA — PENDIENTE DE AUTORIZACIÓN",
        "rechazado": "RECHAZADO POR EL PAC — NO ENTREGAR",
    }.get(doc.estado, "")

