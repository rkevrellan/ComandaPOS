"""PDF imprimibles en ticket de 80 mm (impresora térmica de caja): pre-cuenta y comprobante.

El comprobante sigue la estructura del CAFE (Comprobante Auxiliar de Factura Electrónica). Mientras
no exista integración con un PAC (fase 5) lleva la marca «DOCUMENTO DE PRUEBA — SIN VALIDEZ FISCAL»
y un código de prueba en lugar del CUFE.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from ..config import NOMBRE, VERSION
from ..models import FORMAS_PAGO, Cuenta, Documento, Pago
from . import configuracion
from .pedidos import totales

ANCHO = 80 * mm
MARGEN = 4 * mm
UTIL = ANCHO - 2 * MARGEN


def _hora_local(valor) -> str:
    return (valor - timedelta(hours=5)).strftime("%d/%m/%Y %I:%M %p") if valor else ""


def _b(valor: Decimal) -> str:
    return f"{valor:,.2f}"


class _Ticket:
    """Arma el ticket en dos pasos: primero mide la altura y luego dibuja (papel continuo)."""

    def __init__(self):
        self.items = []

    def texto(self, texto, tam=8, negrita=False, centro=False):
        fuente = "Helvetica-Bold" if negrita else "Helvetica"
        for linea in simpleSplit(str(texto), fuente, tam, UTIL) or [""]:
            self.items.append(("texto", linea, fuente, tam, centro, tam + 2.2))

    def par(self, izquierda, derecha, tam=8, negrita=False):
        fuente = "Helvetica-Bold" if negrita else "Helvetica"
        ancho_der = canvas.Canvas(BytesIO()).stringWidth(str(derecha), fuente, tam) + 4
        lineas = simpleSplit(str(izquierda), fuente, tam, UTIL - ancho_der) or [""]
        for i, linea in enumerate(lineas):
            self.items.append(
                (
                    "par",
                    linea,
                    str(derecha) if i == len(lineas) - 1 else "",
                    fuente,
                    tam,
                    tam + 2.2,
                )
            )

    def raya(self):
        self.items.append(("raya", 5))

    def espacio(self, alto=4):
        self.items.append(("espacio", alto))

    def qr(self, dato, lado=30 * mm):
        self.items.append(("qr", dato, lado, lado + 4))

    def pdf(self, titulo: str) -> bytes:
        alto = sum(item[-1] for item in self.items) + 2 * MARGEN
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(ANCHO, max(alto, 60 * mm)))
        c.setTitle(titulo)
        c.setAuthor(NOMBRE)
        c.setCreator(f"{NOMBRE} {VERSION}")
        y = max(alto, 60 * mm) - MARGEN
        for item in self.items:
            tipo, paso = item[0], item[-1]
            if tipo == "texto":
                _, linea, fuente, tam, centro, _ = item
                c.setFont(fuente, tam)
                if centro:
                    c.drawCentredString(ANCHO / 2, y - tam, linea)
                else:
                    c.drawString(MARGEN, y - tam, linea)
            elif tipo == "par":
                _, izq, der, fuente, tam, _ = item
                c.setFont(fuente, tam)
                c.drawString(MARGEN, y - tam, izq)
                if der:
                    c.drawRightString(ANCHO - MARGEN, y - tam, der)
            elif tipo == "raya":
                c.setDash(1, 2)
                c.line(MARGEN, y - 2.5, ANCHO - MARGEN, y - 2.5)
                c.setDash()
            elif tipo == "qr":
                _, dato, lado, _ = item
                widget = QrCodeWidget(dato)
                x0, y0, x1, y1 = widget.getBounds()
                dibujo = Drawing(
                    lado,
                    lado,
                    transform=[lado / (x1 - x0), 0, 0, lado / (y1 - y0), 0, 0],
                )
                dibujo.add(widget)
                renderPDF.draw(dibujo, c, (ANCHO - lado) / 2, y - lado)
            y -= paso
        c.showPage()
        c.save()
        return buffer.getvalue()


def _encabezado(t: _Ticket) -> None:
    t.texto(configuracion.obtener("emisor.nombre_comercial"), 11, True, True)
    t.texto(configuracion.obtener("emisor.razon_social"), 7.5, centro=True)
    t.texto(
        f"RUC {configuracion.obtener('emisor.ruc')}  DV {configuracion.obtener('emisor.dv')}",
        7.5,
        centro=True,
    )
    t.texto(configuracion.obtener("emisor.direccion"), 7.5, centro=True)
    t.texto(f"Tel. {configuracion.obtener('emisor.telefono')}", 7.5, centro=True)
    t.raya()


def _detalle(t: _Ticket, cuenta: Cuenta, con_itbms: bool) -> None:
    t.par("Cant. Descripción", "Total", 7.5, True)
    tot = totales(cuenta)
    for ln, r in zip(cuenta.activas, tot.lineas):
        cantidad = f"{ln.cantidad.normalize():f}"
        t.par(f"{cantidad} x {ln.descripcion}", _b(r.bruto), 8)
        t.texto(
            f"     {_b(ln.precio)} c/u"
            + (f" · ITBMS {ln.tasa_itbms}%: {_b(r.itbms)}" if con_itbms else ""),
            6.5,
        )
        if ln.acompanamiento:
            t.texto(f"     + {ln.acompanamiento}", 6.5)
        if r.descuento:
            t.texto(
                f"     Descuento {'jubilado' if r.es_jubilado else str(ln.descuento_pct) + '%'}: -{_b(r.descuento)}",
                6.5,
            )
    t.raya()


def _totales(t: _Ticket, cuenta: Cuenta) -> None:
    tot = totales(cuenta)
    t.par("Subtotal", _b(tot.subtotal))
    if tot.descuento_producto:
        t.par("Descuento", f"-{_b(tot.descuento_producto)}")
    if tot.descuento_jubilado:
        t.par(
            f"Desc. jubilado ({configuracion.porcentaje_jubilado()}%)",
            f"-{_b(tot.descuento_jubilado)}",
        )
        t.texto(
            f"Beneficiario: {cuenta.jubilado_nombre or ''} céd. {cuenta.jubilado_cedula}",
            6.5,
        )
    for tasa in sorted(tot.base_por_tasa):
        etiqueta = "Exento" if tasa == 0 else f"Base {tasa}%"
        t.par(etiqueta, _b(tot.base_por_tasa[tasa]), 7.5)
        if tasa:
            t.par(f"ITBMS {tasa}%", _b(tot.itbms_por_tasa[tasa]), 7.5)
    t.par("TOTAL B/.", _b(tot.total), 11, True)


def precuenta_pdf(cuenta: Cuenta) -> bytes:
    t = _Ticket()
    _encabezado(t)
    t.texto("PRE-CUENTA", 12, True, True)
    t.texto("NO ES FACTURA", 10, True, True)
    t.raya()
    comanda = cuenta.comanda
    lugar = f"Mesa {comanda.mesa.numero}" if comanda.mesa else "Mostrador"
    t.par(f"{lugar} · Cuenta {cuenta.numero}", f"Comanda {comanda.numero}", 8)
    t.par(f"Mesero: {comanda.mesero.nombre}", "", 8)
    from .. import models

    t.par(_hora_local(models.ahora()), "", 8)
    t.raya()
    _detalle(t, cuenta, con_itbms=False)
    _totales(t, cuenta)
    t.espacio(6)
    t.texto("Solicite su factura al pagar.", 7.5, centro=True)
    t.texto("La propina es voluntaria.", 7.5, centro=True)
    return t.pdf(f"Pre-cuenta comanda {comanda.numero}")


def comprobante_pdf(doc: Documento, url_consulta: str) -> bytes:
    t = _Ticket()
    if doc.estado == "simulado":
        t.texto("DOCUMENTO DE PRUEBA", 10, True, True)
        t.texto("SIN VALIDEZ FISCAL", 10, True, True)
        t.raya()
    t.texto("COMPROBANTE AUXILIAR DE", 9, True, True)
    t.texto("FACTURA ELECTRÓNICA", 9, True, True)
    t.texto("Factura de operación interna", 7.5, centro=True)
    t.raya()
    _encabezado(t)
    t.par(
        f"No. {doc.numero:010d}",
        f"Punto {configuracion.obtener('emisor.punto_facturacion')}",
        8,
        True,
    )
    t.par(
        f"Sucursal {configuracion.obtener('emisor.sucursal')}",
        _hora_local(doc.emitido_en),
        7.5,
    )
    comanda = doc.cuenta.comanda
    lugar = f"Mesa {comanda.mesa.numero}" if comanda.mesa else "Mostrador"
    t.par(f"{lugar} · Comanda {comanda.numero} · Cta {doc.cuenta.numero}", "", 7.5)
    t.par(f"Atendió: {comanda.mesero.nombre}", "", 7.5)
    t.raya()
    t.texto(f"Cliente: {doc.receptor_nombre}", 8, True)
    t.texto(
        f"RUC/Cédula: {doc.receptor_ruc}"
        + (f"  DV {doc.receptor_dv}" if doc.receptor_dv else ""),
        7.5,
    )
    t.raya()
    _detalle(t, doc.cuenta, con_itbms=True)
    _totales(t, doc.cuenta)
    t.raya()
    pagos = Pago.query.filter_by(cuenta_id=doc.cuenta_id).order_by(Pago.id).all()
    for p in sorted(
        pagos, key=lambda x: x.forma == "efectivo"
    ):  # el efectivo (y su vuelto) al final
        t.par(
            FORMAS_PAGO.get(p.forma, p.forma)
            + (f" ({p.referencia})" if p.referencia else ""),
            _b(p.recibido),
            8,
        )
        if p.vuelto:
            t.par("Vuelto", _b(p.vuelto), 8, True)
    t.raya()
    t.texto("CUFE:", 7, True)
    t.texto(doc.cufe, 7)
    impuestos = json.loads(doc.impuestos or "{}")
    if impuestos:
        t.texto(
            (
                "Protocolo de autorización: simulado (fase 5: PAC)"
                if doc.estado == "simulado"
                else "Protocolo de autorización:"
            ),
            6.5,
        )
    t.espacio(3)
    t.qr(url_consulta)
    t.texto("Consulte la validez de este documento", 6.5, centro=True)
    t.texto("escaneando el código QR.", 6.5, centro=True)
    t.espacio(4)
    t.texto("¡Gracias por su visita!", 8, True, True)
    return t.pdf(f"Comprobante {doc.numero}")
