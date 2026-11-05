"""PDF imprimibles: ticket de 80 mm (impresora térmica) y carta (oficina o correo).

- Pre-cuenta («NO ES FACTURA»).
- CAFE (Comprobante Auxiliar de Factura Electrónica) de factura y de nota de crédito, en 80 mm y carta.
  Se arma con el DETALLE CONGELADO del documento, no con la comanda.
- Corte X / corte Z del turno y recibo de abono a crédito.
La leyenda del estado fiscal (prueba, contingencia, rechazado) siempre se imprime arriba.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import NOMBRE, VERSION
from ..models import FORMAS_PAGO, Cuenta, NotaCredito
from . import configuracion
from .fiscal import items as items_de
from .fiscal import leyenda
from .fiscal import pagos as pagos_de
from .pedidos import totales

ANCHO = 80 * mm
MARGEN = 4 * mm
UTIL = ANCHO - 2 * MARGEN


def hora_local(valor, fmt="%d/%m/%Y %I:%M %p") -> str:
    """Se guarda en UTC; Panamá es UTC−5 todo el año."""
    return (valor - timedelta(hours=5)).strftime(fmt) if valor else ""


def _b(valor) -> str:
    return f"{Decimal(str(valor)):,.2f}"


def _qr(dato: str, lado: float) -> Drawing:
    widget = QrCodeWidget(dato or "-")
    x0, y0, x1, y1 = widget.getBounds()
    dibujo = Drawing(
        lado, lado, transform=[lado / (x1 - x0), 0, 0, lado / (y1 - y0), 0, 0]
    )
    dibujo.add(widget)
    return dibujo


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
        ancho_der = stringWidth(str(derecha), fuente, tam) + 4
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
        alto = max(sum(item[-1] for item in self.items) + 2 * MARGEN, 60 * mm)
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(ANCHO, alto))
        c.setTitle(titulo)
        c.setAuthor(NOMBRE)
        c.setCreator(f"{NOMBRE} {VERSION}")
        y = alto - MARGEN
        for item in self.items:
            tipo, paso = item[0], item[-1]
            if tipo == "texto":
                _, linea, fuente, tam, centro, _ = item
                c.setFont(fuente, tam)
                (
                    c.drawCentredString(ANCHO / 2, y - tam, linea)
                    if centro
                    else c.drawString(MARGEN, y - tam, linea)
                )
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
                renderPDF.draw(_qr(dato, lado), c, (ANCHO - lado) / 2, y - lado)
            y -= paso
        c.showPage()
        c.save()
        return buffer.getvalue()


def _emisor() -> dict:
    o = configuracion.obtener
    return {
        "nombre": o("emisor.nombre_comercial"),
        "razon": o("emisor.razon_social"),
        "ruc": o("emisor.ruc"),
        "dv": o("emisor.dv"),
        "direccion": o("emisor.direccion"),
        "telefono": o("emisor.telefono"),
        "sucursal": o("emisor.sucursal"),
        "punto": o("emisor.punto_facturacion"),
    }


def _encabezado(t: _Ticket) -> None:
    e = _emisor()
    t.texto(e["nombre"], 11, True, True)
    t.texto(e["razon"], 7.5, centro=True)
    t.texto(f"RUC {e['ruc']}  DV {e['dv']}", 7.5, centro=True)
    t.texto(e["direccion"], 7.5, centro=True)
    t.texto(f"Tel. {e['telefono']}", 7.5, centro=True)
    t.raya()


# --------------------------------------------------------------------------- pre-cuenta
def precuenta_pdf(cuenta: Cuenta) -> bytes:
    from ..models import ahora

    t = _Ticket()
    _encabezado(t)
    t.texto("PRE-CUENTA", 12, True, True)
    t.texto("NO ES FACTURA", 10, True, True)
    t.raya()
    comanda = cuenta.comanda
    lugar = f"Mesa {comanda.mesa.numero}" if comanda.mesa else "Mostrador"
    t.par(f"{lugar} · Cuenta {cuenta.numero}", f"Comanda {comanda.numero}", 8)
    t.par(f"Mesero: {comanda.mesero.nombre}", "", 8)
    t.par(hora_local(ahora()), "", 8)
    t.raya()
    tot = totales(cuenta)
    t.par("Cant. Descripción", "Total", 7.5, True)
    for ln, r in zip(cuenta.activas, tot.lineas):
        t.par(f"{ln.cantidad.normalize():f} x {ln.descripcion}", _b(r.bruto), 8)
        if ln.acompanamiento:
            t.texto(f"     + {ln.acompanamiento}", 6.5)
        if r.descuento:
            t.texto(
                f"     Descuento {'jubilado' if r.es_jubilado else str(ln.descuento_pct) + '%'}: -{_b(r.descuento)}",
                6.5,
            )
    t.raya()
    t.par("Subtotal", _b(tot.subtotal))
    if tot.descuento_producto:
        t.par("Descuento", f"-{_b(tot.descuento_producto)}")
    if tot.descuento_jubilado:
        t.par(
            f"Desc. jubilado ({configuracion.porcentaje_jubilado()}%)",
            f"-{_b(tot.descuento_jubilado)}",
        )
    t.par("ITBMS", _b(tot.itbms))
    t.par("TOTAL B/.", _b(tot.total), 11, True)
    t.espacio(6)
    t.texto("Solicite su factura al pagar.", 7.5, centro=True)
    t.texto("La propina es voluntaria.", 7.5, centro=True)
    return t.pdf(f"Pre-cuenta comanda {comanda.numero}")


# --------------------------------------------------------------------------- CAFE
def _datos_documento(doc) -> dict:
    es_nc = isinstance(doc, NotaCredito)
    cuenta = doc.documento.cuenta if es_nc else doc.cuenta
    comanda = cuenta.comanda
    detalle = json.loads(doc.detalle or "{}")
    jubilado = detalle.get("jubilado") if isinstance(detalle, dict) else None
    return {
        "es_nc": es_nc,
        "titulo": "NOTA DE CRÉDITO ELECTRÓNICA" if es_nc else "FACTURA ELECTRÓNICA",
        "lugar": f"Mesa {comanda.mesa.numero}" if comanda.mesa else "Mostrador",
        "comanda": comanda,
        "cuenta": cuenta,
        "items": items_de(doc),
        "pagos": [] if es_nc else pagos_de(doc),
        "impuestos": json.loads(doc.impuestos or "{}"),
        "jubilado": jubilado,
    }


def comprobante_pdf(doc, url_consulta: str) -> bytes:
    """CAFE en ticket de 80 mm (factura o nota de crédito)."""
    d = _datos_documento(doc)
    t = _Ticket()
    if leyenda(doc):
        for parte in leyenda(doc).split(
            " — "
        ):  # «DOCUMENTO DE PRUEBA» / «SIN VALIDEZ FISCAL»
            t.texto(parte, 9.5, True, True)
        t.raya()
    t.texto("COMPROBANTE AUXILIAR DE", 9, True, True)
    t.texto(d["titulo"], 9, True, True)
    t.texto(doc.tipo_nombre, 7.5, centro=True)
    t.raya()
    _encabezado(t)
    e = _emisor()
    t.par(f"No. {doc.numero:010d}", f"Punto {e['punto']}", 8, True)
    t.par(f"Sucursal {e['sucursal']}", hora_local(doc.emitido_en), 7.5)
    t.par(
        f"{d['lugar']} · Comanda {d['comanda'].numero} · Cta {d['cuenta'].numero}",
        "",
        7.5,
    )
    if d["es_nc"]:
        t.texto(f"Referencia: comprobante No. {doc.documento.numero:010d}", 7.5, True)
        t.texto(f"CUFE de referencia: {doc.documento.cufe}", 6.5)
        t.texto(f"Motivo: {doc.motivo}", 7.5)
    else:
        t.par(f"Atendió: {d['comanda'].mesero.nombre}", "", 7.5)
    t.raya()
    t.texto(f"Cliente: {doc.receptor_nombre}", 8, True)
    t.texto(
        f"RUC/Cédula: {doc.receptor_ruc}"
        + (f"  DV {doc.receptor_dv}" if doc.receptor_dv else ""),
        7.5,
    )
    t.raya()
    t.par("Cant. Descripción", "Total", 7.5, True)
    for it in d["items"]:
        t.par(f"{it['cantidad']} x {it['descripcion']}", _b(it["bruto"]), 8)
        t.texto(
            f"     {_b(it['precio'])} c/u · ITBMS {it['tasa']}%: {_b(it['itbms'])}", 6.5
        )
        if it.get("acompanamiento"):
            t.texto(f"     + {it['acompanamiento']}", 6.5)
        if Decimal(it["descuento"]):
            t.texto(
                f"     Descuento {'jubilado' if it.get('es_jubilado') else it['descuento_pct'] + '%'}: -{_b(it['descuento'])}",
                6.5,
            )
    t.raya()
    t.par("Subtotal", _b(doc.subtotal))
    if doc.descuento_producto:
        t.par("Descuento", f"-{_b(doc.descuento_producto)}")
    if doc.descuento_jubilado:
        t.par("Descuento jubilado", f"-{_b(doc.descuento_jubilado)}")
        if d["jubilado"]:
            t.texto(
                f"Beneficiario: {d['jubilado'].get('nombre') or ''} céd. {d['jubilado'].get('cedula')}",
                6.5,
            )
    for tasa, (base, imp) in sorted(d["impuestos"].items(), key=lambda x: int(x[0])):
        t.par("Exento" if tasa == "0" else f"Base {tasa}%", _b(base), 7.5)
        if tasa != "0":
            t.par(f"ITBMS {tasa}%", _b(imp), 7.5)
    t.par(
        "TOTAL B/." if not d["es_nc"] else "TOTAL ACREDITADO B/.",
        _b(doc.total),
        11,
        True,
    )
    t.raya()
    if d["es_nc"]:
        t.par(
            f"Devolución: {FORMAS_PAGO.get(doc.forma_devolucion, doc.forma_devolucion)}",
            _b(doc.total),
            8,
        )
    for p in d["pagos"]:
        nombre = FORMAS_PAGO.get(p["forma"], p["forma"]) + (
            f" ({p['referencia']})" if p.get("referencia") else ""
        )
        t.par(nombre, _b(p["recibido"]), 8)
        if Decimal(p.get("vuelto") or "0"):
            t.par("Vuelto", _b(p["vuelto"]), 8, True)
    t.raya()
    if doc.estado in ("autorizado", "simulado"):
        t.texto("CUFE:", 7, True)
        t.texto(doc.cufe, 7)
        t.texto(
            f"Protocolo de autorización: {doc.protocolo or ''} · {hora_local(doc.autorizado_en)}",
            6.5,
        )
        t.espacio(3)
        t.qr(doc.qr or url_consulta)
        t.texto("Consulte la validez de este documento", 6.5, centro=True)
        t.texto("escaneando el código QR.", 6.5, centro=True)
    else:
        t.texto(f"Código provisional: {doc.cufe}", 7)
        t.texto(
            "El CUFE y el código QR se entregan cuando la DGI autorice el documento.",
            6.5,
        )
    t.espacio(4)
    t.texto("¡Gracias por su visita!", 8, True, True)
    return t.pdf(f"{d['titulo'].title()} {doc.numero}")


def comprobante_carta_pdf(doc, url_consulta: str) -> bytes:
    """CAFE en tamaño carta (para enviar por correo o imprimir en oficina)."""
    d = _datos_documento(doc)
    e = _emisor()
    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{d['titulo'].title()} {doc.numero}",
        author=NOMBRE,
    )
    normal = ParagraphStyle("n", fontName="Helvetica", fontSize=9, leading=12)
    negrita = ParagraphStyle("b", parent=normal, fontName="Helvetica-Bold")
    titulo = ParagraphStyle("t", parent=negrita, fontSize=13, leading=16)
    alerta = ParagraphStyle(
        "a",
        parent=negrita,
        fontSize=12,
        textColor=colors.HexColor("#b91c1c"),
        alignment=1,
    )
    gris = colors.HexColor("#e2e8f0")
    contenido = []
    if leyenda(doc):
        contenido += [Paragraph(leyenda(doc), alerta), Spacer(1, 6)]
    encabezado = Table(
        [
            [
                [
                    Paragraph(e["nombre"], titulo),
                    Paragraph(e["razon"], normal),
                    Paragraph(f"RUC {e['ruc']} DV {e['dv']}", normal),
                    Paragraph(e["direccion"], normal),
                    Paragraph(f"Tel. {e['telefono']}", normal),
                ],
                [
                    Paragraph("COMPROBANTE AUXILIAR DE " + d["titulo"], negrita),
                    Paragraph(doc.tipo_nombre, normal),
                    Paragraph(f"No. <b>{doc.numero:010d}</b>", normal),
                    Paragraph(f"Sucursal {e['sucursal']} · Punto {e['punto']}", normal),
                    Paragraph(f"Emisión: {hora_local(doc.emitido_en)}", normal),
                ],
            ]
        ],
        colWidths=[95 * mm, 80 * mm],
    )
    encabezado.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (1, 0), (1, 0), 0.8, colors.black),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
            ]
        )
    )
    contenido += [encabezado, Spacer(1, 8)]
    receptor = (
        f"<b>Cliente:</b> {doc.receptor_nombre} &nbsp; <b>RUC/Cédula:</b> {doc.receptor_ruc}"
        + (f" DV {doc.receptor_dv}" if doc.receptor_dv else "")
    )
    contenido.append(Paragraph(receptor, normal))
    contenido.append(
        Paragraph(
            f"{d['lugar']} · comanda {d['comanda'].numero} · cuenta {d['cuenta'].numero}",
            normal,
        )
    )
    if d["es_nc"]:
        contenido.append(
            Paragraph(
                f"<b>Referencia:</b> comprobante No. {doc.documento.numero:010d} · CUFE "
                f"{doc.documento.cufe}<br/><b>Motivo:</b> {doc.motivo}",
                normal,
            )
        )
    contenido.append(Spacer(1, 8))
    filas = [["Código", "Descripción", "Cant.", "Precio", "Desc.", "ITBMS", "Total"]]
    for it in d["items"]:
        desc = it["descripcion"] + (
            f" + {it['acompanamiento']}" if it.get("acompanamiento") else ""
        )
        filas.append(
            [
                str(it.get("codigo", "")),
                Paragraph(desc, normal),
                it["cantidad"],
                _b(it["precio"]),
                _b(it["descuento"]),
                f"{it['tasa']}% {_b(it['itbms'])}",
                _b(it["total"]),
            ]
        )
    tabla = Table(
        filas,
        colWidths=[16 * mm, 66 * mm, 14 * mm, 19 * mm, 17 * mm, 22 * mm, 21 * mm],
        repeatRows=1,
    )
    tabla.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), gris),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    contenido += [tabla, Spacer(1, 8)]
    resumen = [["Subtotal", _b(doc.subtotal)]]
    if doc.descuento_producto:
        resumen.append(["Descuento", "-" + _b(doc.descuento_producto)])
    if doc.descuento_jubilado:
        resumen.append(["Descuento jubilado", "-" + _b(doc.descuento_jubilado)])
    for tasa, (base, imp) in sorted(d["impuestos"].items(), key=lambda x: int(x[0])):
        resumen.append(
            ["Exento" if tasa == "0" else f"Base gravable {tasa}%", _b(base)]
        )
        if tasa != "0":
            resumen.append([f"ITBMS {tasa}%", _b(imp)])
    resumen.append(["TOTAL B/.", _b(doc.total)])
    for p in d["pagos"]:
        resumen.append([FORMAS_PAGO.get(p["forma"], p["forma"]), _b(p["recibido"])])
        if Decimal(p.get("vuelto") or "0"):
            resumen.append(["Vuelto", _b(p["vuelto"])])
    tabla_tot = Table(resumen, colWidths=[45 * mm, 28 * mm])
    fila_total = next(i for i, fila in enumerate(resumen) if fila[0] == "TOTAL B/.")
    tabla_tot.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("FONT", (0, fila_total), (-1, fila_total), "Helvetica-Bold", 11),
                ("LINEABOVE", (0, fila_total), (-1, fila_total), 0.8, colors.black),
            ]
        )
    )
    if doc.estado in ("autorizado", "simulado"):
        validez = [
            Paragraph(f"<b>CUFE:</b> {doc.cufe}", normal),
            Paragraph(
                f"<b>Protocolo de autorización:</b> {doc.protocolo or ''} · {hora_local(doc.autorizado_en)}",
                normal,
            ),
            Paragraph(
                "Consulte la validez de este documento escaneando el código QR.", normal
            ),
        ]
        pie = Table(
            [[_qr(doc.qr or url_consulta, 32 * mm), validez, tabla_tot]],
            colWidths=[36 * mm, 66 * mm, 73 * mm],
        )
    else:
        validez = [
            Paragraph(f"<b>Código provisional:</b> {doc.cufe}", normal),
            Paragraph(
                "El CUFE y el código QR se entregan cuando la DGI autorice el documento.",
                normal,
            ),
        ]
        pie = Table([[validez, tabla_tot]], colWidths=[102 * mm, 73 * mm])
    pie.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    contenido.append(pie)
    pdf.build(contenido)
    return buffer.getvalue()


# --------------------------------------------------------------------------- caja
def corte_pdf(turno, datos: dict, tipo: str) -> bytes:
    """Corte X (parcial, no cierra) o Z (cierre del turno)."""
    from ..models import ahora

    t = _Ticket()
    _encabezado(t)
    t.texto(f"CORTE {tipo}", 13, True, True)
    t.texto(
        "Parcial — el turno sigue abierto" if tipo == "X" else "Cierre de turno",
        8,
        centro=True,
    )
    t.raya()
    t.par(f"Turno {turno.numero}", f"Cajero: {turno.cajero.nombre}", 8)
    t.par("Apertura", hora_local(turno.abierto_en), 8)
    t.par(
        "Corte" if tipo == "X" else "Cierre", hora_local(turno.cerrado_en or ahora()), 8
    )
    t.raya()
    t.texto("VENTAS POR FORMA DE PAGO", 8, True)
    for forma, nombre in FORMAS_PAGO.items():
        t.par(nombre, _b(datos["por_forma"][forma]), 8)
    t.par("Total ventas", _b(datos["total"]), 9, True)
    if any(datos["devoluciones"].values()):
        t.texto("DEVOLUCIONES (notas de crédito)", 8, True)
        for forma, monto in datos["devoluciones"].items():
            if monto:
                t.par(FORMAS_PAGO[forma], "-" + _b(monto), 8)
    if any(datos["abonos"].values()):
        t.texto("ABONOS A CRÉDITO", 8, True)
        for forma, monto in datos["abonos"].items():
            if monto:
                t.par(FORMAS_PAGO[forma], _b(monto), 8)
    t.raya()
    t.par("Comprobantes", str(datos["documentos"]), 8)
    t.par("Notas de crédito", str(datos["notas_credito"]), 8)
    t.par("ITBMS neto", _b(datos["itbms"]), 8)
    t.par("Descuentos a jubilados", _b(datos["descuento_jubilado"]), 8)
    t.raya()
    t.par("Fondo inicial", _b(turno.fondo), 8)
    t.par("Efectivo esperado", _b(datos["efectivo_esperado"]), 9, True)
    if tipo == "Z":
        t.par("Efectivo contado", _b(turno.efectivo_contado), 9)
        t.par("Diferencia", _b(turno.diferencia), 10, True)
        if turno.justificacion:
            t.texto(f"Justificación: {turno.justificacion}", 7.5)
    t.espacio(16)
    t.texto("_______________________", 8, centro=True)
    t.texto("Firma del cajero", 7.5, centro=True)
    return t.pdf(f"Corte {tipo} turno {turno.numero}")


def recibo_abono_pdf(abono) -> bytes:
    t = _Ticket()
    _encabezado(t)
    t.texto("RECIBO DE ABONO", 12, True, True)
    t.texto("A cuenta de crédito — no es factura", 7.5, centro=True)
    t.raya()
    t.par(f"Recibo No. {abono.recibo:06d}", hora_local(abono.fecha), 8, True)
    t.texto(f"Cliente: {abono.cliente.nombre}", 8)
    t.texto(
        f"RUC/Cédula: {abono.cliente.ruc}"
        + (f"  DV {abono.cliente.dv}" if abono.cliente.dv else ""),
        7.5,
    )
    t.raya()
    nombre = FORMAS_PAGO.get(abono.forma, abono.forma) + (
        f" ({abono.referencia})" if abono.referencia else ""
    )
    t.par(nombre, _b(abono.monto), 9)
    t.par("MONTO ABONADO B/.", _b(abono.monto), 11, True)
    t.texto(f"Recibió: {abono.cajero.nombre} · turno {abono.turno.numero}", 7.5)
    return t.pdf(f"Recibo de abono {abono.recibo}")
