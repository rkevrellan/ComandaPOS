"""Impresión térmica ESC/POS (80 mm): comandas por área, avisos de anulación, comprobante y gaveta.

- Cola PERSISTENTE (`TrabajoImpresion`): si la impresora no responde, el trabajo queda pendiente y se
  reintenta; nunca se pierde una comanda.
- A03: todo texto que viene de personas (nombres, notas, productos) se limpia de bytes de control
  ANTES de mezclarse con los comandos ESC/POS: un nombre de cliente no puede cortar papel, cambiar
  la configuración de la impresora ni abrir la gaveta.
- Destinos: «red» (IP:puerto, normalmente 9100), «windows» (cola de Windows, en bruto) y «archivo»
  (demostración: guarda el trabajo en la carpeta de datos).
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import threading
from datetime import timedelta

from flask import current_app

from ..extensions import db
from ..models import AreaProduccion, Impresora, TrabajoImpresion, ahora
from . import configuracion

ESC, GS = b"\x1b", b"\x1d"
INICIAR = (
    ESC + b"@" + ESC + b"t\x02"
)  # reinicia e indica página de códigos 850 (español)
CORTAR = b"\n\n\n" + GS + b"V\x42\x00"
GAVETA = ESC + b"p\x00\x19\xfa"
MAX_INTENTOS = 5
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_NOMBRE_ARCHIVO = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


# Signos tipográficos que la página de códigos 850 no tiene: se cambian por su equivalente simple.
_SIMPLES = str.maketrans(
    {
        "—": "-",
        "–": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
        "•": "*",
    }
)


def limpiar(texto) -> str:
    """Quita TODO byte de control (incluido ESC y GS) del texto de las personas."""
    return _CONTROL.sub(" ", str(texto or "")).translate(_SIMPLES)


def _partir(texto: str, ancho: int) -> list:
    """Corta en renglones de `ancho` por palabras; solo parte una palabra si no cabe sola."""
    sangria = " " * min(len(texto) - len(texto.lstrip(" ")), ancho // 2)
    if sangria:  # «   + Arroz con guandú»: la sangría se respeta en cada renglón
        return [sangria + r for r in _partir(texto.lstrip(" "), ancho - len(sangria))]
    renglones, actual = [], ""
    for palabra in texto.split(" "):
        while len(palabra) > ancho:
            if actual:
                renglones.append(actual)
                actual = ""
            renglones.append(palabra[:ancho])
            palabra = palabra[ancho:]
        if not actual:
            actual = palabra
        elif len(actual) + 1 + len(palabra) <= ancho:
            actual += " " + palabra
        else:
            renglones.append(actual)
            actual = palabra
    renglones.append(actual)
    return renglones


class Ticket:
    """Arma un trabajo ESC/POS. El texto siempre pasa por `limpiar`; los comandos los pone el sistema."""

    def __init__(self, columnas: int = 42):
        self.columnas = max(24, min(64, columnas))
        self.datos = bytearray(INICIAR)

    def _texto(self, texto: str) -> bytes:
        return limpiar(texto).encode("cp850", errors="replace")

    def linea(self, texto="", negrita=False, doble=False, centro=False):
        self.datos += ESC + b"a" + (b"\x01" if centro else b"\x00")
        self.datos += ESC + b"E" + (b"\x01" if negrita else b"\x00")
        self.datos += GS + b"!" + (b"\x11" if doble else b"\x00")
        ancho = self.columnas // 2 if doble else self.columnas
        for parte in _partir(limpiar(texto), ancho):
            self.datos += self._texto(parte) + b"\n"
        self.datos += GS + b"!\x00" + ESC + b"E\x00" + ESC + b"a\x00"
        return self

    def par(self, izquierda, derecha, negrita=False):
        izquierda, derecha = limpiar(izquierda), limpiar(derecha)
        espacio = self.columnas - len(derecha) - 1
        return self.linea(
            izquierda[:espacio].ljust(espacio) + " " + derecha, negrita=negrita
        )

    def raya(self):
        return self.linea("-" * self.columnas)

    def qr(self, dato: str):
        dato = limpiar(dato).encode("ascii", errors="ignore")[:700]
        largo = len(dato) + 3
        self.datos += ESC + b"a\x01"
        self.datos += GS + b"(k\x04\x00\x31\x41\x32\x00"  # modelo 2
        self.datos += GS + b"(k\x03\x00\x31\x43\x06"  # tamaño del módulo
        self.datos += GS + b"(k\x03\x00\x31\x45\x31"  # corrección de errores M
        self.datos += (
            GS + b"(k" + bytes([largo % 256, largo // 256]) + b"\x31\x50\x30" + dato
        )
        self.datos += GS + b"(k\x03\x00\x31\x51\x30" + b"\n" + ESC + b"a\x00"
        return self

    def gaveta(self):
        self.datos += GAVETA
        return self

    def bytes(self, cortar=True) -> bytes:
        return bytes(self.datos + (CORTAR if cortar else b""))


def _hora(valor) -> str:
    return (valor - timedelta(hours=5)).strftime("%d/%m/%Y %I:%M %p") if valor else ""


# --------------------------------------------------------------------------- contenido
def comanda_area(comanda, area: AreaProduccion, lineas, columnas=42) -> bytes:
    t = Ticket(columnas)
    t.linea(f"COMANDA · {area.descripcion.upper()}", negrita=True, centro=True)
    lugar = (
        f"MESA {comanda.mesa.numero}" if comanda.mesa else f"DIRECTO {comanda.numero}"
    )
    t.linea(lugar, doble=True, centro=True)
    t.par(f"Rec# {comanda.numero}", _hora(ahora()))
    t.linea(f"Mesero: {comanda.mesero.nombre}")
    t.raya()
    for ln in lineas:
        t.linea(
            f"{ln.cantidad.normalize():f} x {ln.descripcion}", negrita=True, doble=True
        )
        if ln.acompanamiento:
            t.linea(f"   + {ln.acompanamiento}")
        if ln.notas:
            t.linea(f"   * {ln.notas}")
        if ln.para_llevar:
            t.linea("   PARA LLEVAR", negrita=True)
        if ln.cuenta.numero > 1:
            t.linea(f"   (cuenta {ln.cuenta.numero})")
    t.raya()
    return t.bytes()


def aviso_anulacion(linea, autorizador, motivo, columnas=42) -> bytes:
    comanda = linea.cuenta.comanda
    t = Ticket(columnas)
    t.linea("*** ANULACION ***", negrita=True, doble=True, centro=True)
    t.linea(
        f"MESA {comanda.mesa.numero}" if comanda.mesa else f"DIRECTO {comanda.numero}",
        doble=True,
        centro=True,
    )
    t.par(f"Rec# {comanda.numero}", _hora(ahora()))
    t.raya()
    t.linea(
        f"NO PREPARAR: {linea.cantidad.normalize():f} x {linea.descripcion}",
        negrita=True,
    )
    t.linea(f"Motivo: {motivo}")
    t.linea(f"Autorizó: {autorizador.nombre}")
    return t.bytes()


def comprobante_ticket(doc, url_consulta: str, columnas=42) -> bytes:
    from .fiscal import items, leyenda, pagos

    o = configuracion.obtener
    t = Ticket(columnas)
    if leyenda(doc):
        t.linea(leyenda(doc), negrita=True, centro=True)
    t.linea("COMPROBANTE AUXILIAR DE FACTURA ELECTRONICA", negrita=True, centro=True)
    t.linea(o("emisor.nombre_comercial"), negrita=True, doble=True, centro=True)
    t.linea(o("emisor.razon_social"), centro=True)
    t.linea(f"RUC {o('emisor.ruc')} DV {o('emisor.dv')}", centro=True)
    t.raya()
    t.par(f"No. {doc.numero:010d}", _hora(doc.emitido_en))
    t.linea(f"Cliente: {doc.receptor_nombre} {doc.receptor_ruc}")
    t.raya()
    for it in items(doc):
        t.par(f"{it['cantidad']} x {it['descripcion']}", it["bruto"])
    t.raya()
    t.par("ITBMS", str(doc.itbms))
    t.par("TOTAL B/.", str(doc.total), negrita=True)
    for p in pagos(doc):
        t.par(p["forma"].capitalize(), p["recibido"])
        if p.get("vuelto") not in (None, "0.00"):
            t.par("Vuelto", p["vuelto"])
    t.raya()
    if doc.estado in ("autorizado", "simulado"):
        t.linea("CUFE:")
        t.linea(doc.cufe)
        t.qr(doc.qr or url_consulta)
    else:
        t.linea(f"Provisional: {doc.cufe}")
    return t.bytes()


# --------------------------------------------------------------------------- cola
def impresora_de_caja() -> Impresora | None:
    valor = configuracion.obtener("impresion.caja")
    imp = db.session.get(Impresora, int(valor)) if valor.isdigit() else None
    return imp if imp is not None and imp.activa else None


def encolar(
    impresora: Impresora | None, descripcion: str, contenido: bytes
) -> TrabajoImpresion | None:
    if impresora is None or not impresora.activa:
        return None
    trabajo = TrabajoImpresion(
        impresora=impresora, descripcion=limpiar(descripcion)[:120], contenido=contenido
    )
    db.session.add(trabajo)
    return trabajo


def encolar_comandas(comanda, lineas) -> int:
    """Una comanda por área de producción (y por segunda área si el producto la tiene)."""
    por_area = {}
    for ln in lineas:
        por_area.setdefault(ln.area_id, []).append(ln)
        if (
            ln.producto is not None
            and ln.producto.area2_id
            and ln.producto.area2_id != ln.area_id
        ):
            por_area.setdefault(ln.producto.area2_id, []).append(ln)
    n = 0
    for area_id, grupo in por_area.items():
        area = db.session.get(AreaProduccion, area_id)
        if area is not None and area.impresora_obj is not None:
            if encolar(
                area.impresora_obj,
                f"Comanda {comanda.numero} · {area.descripcion}",
                comanda_area(comanda, area, grupo, area.impresora_obj.columnas),
            ):
                n += 1
    return n


#: Puertos «RAW» de impresoras térmicas (JetDirect).
PUERTOS_IMPRESORA = range(9100, 9110)


def validar_destino(tipo: str, destino: str) -> str:
    destino = (destino or "").strip()
    if tipo == "red":
        host, _, puerto = destino.partition(":")
        try:
            # Solo IP literal: nada de nombres que resuelvan a otro lado.
            ip = ipaddress.ip_address(host)
            puerto = int(puerto or "9100")
        except ValueError:
            raise ValueError(
                "Escribe la IP y el puerto, por ejemplo 192.168.1.50:9100."
            ) from None
        # H-17: una impresora es otro aparato de la red del local: IP privada, nunca este mismo
        # equipo, una dirección de enlace local (metadatos de la nube) ni multidifusión.
        if (
            ip.version != 4
            or not ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise ValueError(
                "La impresora debe tener una IP privada de la red del local (ej. 192.168.1.50)."
            )
        if puerto not in PUERTOS_IMPRESORA:
            raise ValueError("Las impresoras térmicas usan los puertos 9100 a 9109.")
        return f"{host}:{puerto}"
    if tipo == "windows":
        if not destino or len(destino) > 120 or _CONTROL.search(destino):
            raise ValueError("Escribe el nombre exacto de la impresora en Windows.")
        return destino
    if tipo == "archivo":
        if not _NOMBRE_ARCHIVO.match(destino):
            raise ValueError(
                "El nombre del archivo solo admite letras, números, - y _."
            )
        return destino
    raise ValueError("Tipo de impresora desconocido.")


def _enviar(impresora: Impresora, datos: bytes) -> None:
    if impresora.tipo == "red":
        host, _, puerto = impresora.destino.partition(":")
        with socket.create_connection((host, int(puerto or 9100)), timeout=4) as s:
            s.sendall(datos)
    elif impresora.tipo == "windows":
        try:
            import win32print  # pywin32 (solo Windows)
        except ImportError:
            raise OSError("Falta pywin32 para imprimir en Windows.") from None
        h = win32print.OpenPrinter(impresora.destino)
        try:
            win32print.StartDocPrinter(h, 1, ("ComandaPOS", None, "RAW"))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, datos)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    elif impresora.tipo == "archivo":
        carpeta = os.path.join(current_app.config["DATOS"], "impresiones")
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, impresora.destino + ".bin"), "ab") as f:
            f.write(datos)
    else:
        raise OSError("Tipo de impresora desconocido.")


_CANDADO = threading.Lock()
_DESPERTAR = threading.Event()
_TRABAJADOR: dict = {}


def procesar_pendientes(limite: int = 30, esperar: bool = False) -> tuple[int, int]:
    """Envía los trabajos pendientes. Devuelve (impresos, con error). Confirma cada resultado.

    H-07: una sola pasada a la vez (candado: nunca se imprime dos veces lo mismo) y una impresora que
    falla se salta en el resto de la pasada (una impresora apagada cuesta 4 s, no 4 s por trabajo).
    """
    if not _CANDADO.acquire(blocking=esperar, timeout=10 if esperar else -1):
        return 0, 0  # otra pasada ya está imprimiendo
    try:
        impresos = errores = 0
        caidas: set = set()
        trabajos = (
            TrabajoImpresion.query.filter(
                TrabajoImpresion.estado.in_(("pendiente", "error")),
                TrabajoImpresion.intentos < MAX_INTENTOS,
            )
            .order_by(TrabajoImpresion.id)
            .limit(limite)
            .all()
        )
        for trabajo in trabajos:
            if trabajo.impresora_id in caidas:
                continue
            trabajo.intentos += 1
            impresora, contenido = trabajo.impresora, trabajo.contenido
            # Se confirma ANTES de hablar con la impresora: la base no queda bloqueada para
            # escribir mientras se espera a un aparato lento (las ventas siguen, H-07).
            db.session.commit()
            try:
                _enviar(impresora, contenido)
                trabajo.estado = "impreso"
                trabajo.impreso_en = ahora()
                trabajo.error = None
                impresos += 1
            except (OSError, ValueError) as e:
                trabajo.estado = "error"
                trabajo.error = limpiar(f"{type(e).__name__}: {e}")[:200]
                errores += 1
                caidas.add(trabajo.impresora_id)
            db.session.commit()
        return impresos, errores
    finally:
        _CANDADO.release()


def despertar() -> None:
    """Pide imprimir lo pendiente SIN hacer esperar a quien envió el pedido (H-07).

    En las pruebas (`IMPRESION_EN_SEGUNDO_PLANO` apagado) se imprime en el momento."""
    app = current_app._get_current_object()
    if not app.config.get("IMPRESION_EN_SEGUNDO_PLANO"):
        try:
            procesar_pendientes()
        except Exception:  # pragma: no cover - imprimir nunca tumba la venta
            db.session.rollback()
        return
    hilo = _TRABAJADOR.get(id(app))
    if hilo is None or not hilo.is_alive():
        hilo = threading.Thread(
            target=_trabajar, args=(app,), name="impresion", daemon=True
        )
        _TRABAJADOR[id(app)] = hilo
        hilo.start()
    _DESPERTAR.set()


def _trabajar(app) -> None:  # pragma: no cover - hilo de fondo (se prueba en test_correcciones)
    """Imprime al recibir aviso y, además, cada 30 s reintenta lo que quedó en la cola."""
    while True:
        _DESPERTAR.wait(timeout=30)
        _DESPERTAR.clear()
        if not app.config.get("IMPRESION_EN_SEGUNDO_PLANO"):
            _TRABAJADOR.pop(id(app), None)
            return  # se apagó (pruebas): termina el hilo
        with app.app_context():
            try:
                procesar_pendientes()
            except Exception:
                db.session.rollback()
                app.logger.exception("Error en la cola de impresión")
            finally:
                db.session.remove()


def vista_previa(contenido: bytes) -> str:
    """Texto legible de un trabajo ESC/POS: quita los comandos conocidos (para revisar en pantalla)."""
    largos = {b"@": 2, b"t": 3, b"a": 3, b"E": 3, b"p": 5}
    salida, i = bytearray(), 0
    while i < len(contenido):
        b = contenido[i : i + 1]
        if b == ESC:
            i += largos.get(contenido[i + 1 : i + 2], 2)
        elif b == GS:
            cmd = contenido[i + 1 : i + 2]
            if cmd == b"(":
                i += 5 + contenido[i + 3] + contenido[i + 4] * 256
            elif cmd == b"V":
                i += 4
            else:
                i += 3
        else:
            salida += b
            i += 1
    texto = salida.decode("cp850", errors="replace").strip()
    if not texto and ESC + b"p" in contenido:
        return "(pulso de apertura de gaveta)"
    return texto
