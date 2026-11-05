"""Reportes de gestión. Las fechas se piden en hora de Panamá (UTC−5) y se consultan en UTC.

- Ventas: por día, por hora (mapa de calor), por mesero, por sección, por producto y por forma de pago.
- ITBMS por tasa (bases e impuesto, netos de notas de crédito) para preparar la declaración mensual.
- Descuentos a jubilados con cédula (soporte ante ACODECO), anulaciones y notas de crédito.
- Tiempos de cocina por área (enviado → listo → entregado).
- CSV sin fórmulas (A03): una celda que empieza con = + - @ se neutraliza con un apóstrofo.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..models import ahora, Anulacion, Cuenta, Documento, LineaPedido, NotaCredito, Pago
from .calculos import ReglaNegocioError

CERO = Decimal("0.00")
DESFASE = timedelta(hours=5)  # Panamá = UTC−5, sin horario de verano
DIAS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def local(valor: datetime) -> datetime:
    return valor - DESFASE


def rango(desde: str | None, hasta: str | None) -> tuple:
    hoy = local(ahora()).date()
    try:
        d = date.fromisoformat(desde) if desde else hoy
        h = date.fromisoformat(hasta) if hasta else d
    except ValueError:
        raise ReglaNegocioError("Fecha no válida (usa AAAA-MM-DD).") from None
    if h < d:
        d, h = h, d
    if (h - d).days > 366:
        raise ReglaNegocioError("El rango máximo es de un año.")
    inicio = datetime.combine(d, datetime.min.time()) + DESFASE
    fin = datetime.combine(h + timedelta(days=1), datetime.min.time()) + DESFASE
    return inicio, fin, d, h


def _documentos(inicio, fin):
    return (
        Documento.query.filter(
            Documento.emitido_en >= inicio, Documento.emitido_en < fin
        )
        .order_by(Documento.emitido_en)
        .all()
    )


def _notas(inicio, fin):
    return NotaCredito.query.filter(
        NotaCredito.emitido_en >= inicio, NotaCredito.emitido_en < fin
    ).all()


def calcular(inicio, fin) -> dict:
    docs = _documentos(inicio, fin)
    notas = _notas(inicio, fin)
    r = {
        "documentos": len(docs),
        "ventas": sum((d.total for d in docs), CERO),
        "notas_total": sum((n.total for n in notas), CERO),
        "notas": notas,
    }
    r["neto"] = r["ventas"] - r["notas_total"]
    r["ticket_promedio"] = (
        (r["ventas"] / len(docs)).quantize(Decimal("0.01")) if docs else CERO
    )
    r["descuentos"] = sum(
        (d.descuento_producto + d.descuento_jubilado for d in docs), CERO
    )

    # por día y mapa de calor (día de la semana × hora)
    por_dia = defaultdict(lambda: [0, CERO])
    calor = defaultdict(lambda: CERO)
    for d in docs:
        momento = local(d.emitido_en)
        por_dia[momento.date()][0] += 1
        por_dia[momento.date()][1] += d.total
        calor[(momento.weekday(), momento.hour)] += d.total
    r["por_dia"] = sorted(por_dia.items())
    maximo = max(calor.values(), default=CERO)
    # Siempre el horario típico de servicio (10 a 22 h) y, si hubo ventas fuera de él, se amplía.
    horas = {h for _, h in calor} | {10, 22}
    r["calor"] = {
        "horas": list(range(min(horas), max(horas) + 1)),
        "celdas": calor,
        "maximo": maximo,
    }

    # por mesero
    por_mesero = defaultdict(lambda: [0, CERO])
    for d in docs:
        nombre = d.cuenta.comanda.mesero.nombre
        por_mesero[nombre][0] += 1
        por_mesero[nombre][1] += d.total
    r["por_mesero"] = sorted(por_mesero.items(), key=lambda x: -x[1][1])

    # por forma de pago
    pagos = Pago.query.filter(Pago.fecha >= inicio, Pago.fecha < fin).all()
    por_forma = defaultdict(lambda: CERO)
    for p in pagos:
        por_forma[p.forma] += p.monto
    r["por_forma"] = sorted(por_forma.items(), key=lambda x: -x[1])

    # por sección y producto (líneas cobradas, no anuladas)
    lineas = (
        LineaPedido.query.join(Cuenta)
        .filter(
            Cuenta.pagada_en >= inicio,
            Cuenta.pagada_en < fin,
            LineaPedido.estado != "ANU",
        )
        .all()
    )
    por_seccion = defaultdict(lambda: CERO)
    por_producto = defaultdict(lambda: [Decimal("0"), CERO])
    for ln in lineas:
        bruto = (ln.cantidad * ln.precio).quantize(Decimal("0.01"))
        seccion = ln.producto.seccion.nombre if ln.producto else "—"
        por_seccion[seccion] += bruto
        por_producto[ln.descripcion][0] += ln.cantidad
        por_producto[ln.descripcion][1] += bruto
    r["por_seccion"] = sorted(por_seccion.items(), key=lambda x: -x[1])
    r["por_producto"] = sorted(por_producto.items(), key=lambda x: -x[1][1])[:25]

    # ITBMS por tasa (neto de notas de crédito)
    impuestos = defaultdict(lambda: [CERO, CERO])
    for d in docs:
        for tasa, (base, imp) in json.loads(d.impuestos or "{}").items():
            impuestos[int(tasa)][0] += Decimal(base)
            impuestos[int(tasa)][1] += Decimal(imp)
    for n in notas:
        for tasa, (base, imp) in json.loads(n.impuestos or "{}").items():
            impuestos[int(tasa)][0] -= Decimal(base)
            impuestos[int(tasa)][1] -= Decimal(imp)
    r["itbms"] = sorted(impuestos.items())
    r["itbms_total"] = sum((v[1] for v in impuestos.values()), CERO)

    # jubilados
    jub = []
    for d in docs:
        if d.descuento_jubilado:
            detalle = json.loads(d.detalle or "{}")
            persona = (
                (detalle.get("jubilado") or {}) if isinstance(detalle, dict) else {}
            )
            jub.append(
                (
                    d,
                    persona.get("cedula") or d.cuenta.jubilado_cedula or "",
                    persona.get("nombre") or d.cuenta.jubilado_nombre or "",
                )
            )
    r["jubilados"] = jub
    r["jubilados_total"] = sum((d.descuento_jubilado for d, _, _ in jub), CERO)

    # anulaciones
    r["anulaciones"] = (
        Anulacion.query.filter(Anulacion.fecha >= inicio, Anulacion.fecha < fin)
        .order_by(Anulacion.fecha)
        .all()
    )

    # tiempos de cocina
    tiempos = defaultdict(lambda: {"prep": [], "entrega": []})
    for ln in LineaPedido.query.filter(
        LineaPedido.enviado_en >= inicio,
        LineaPedido.enviado_en < fin,
        LineaPedido.listo_en.is_not(None),
    ).all():
        area = ln.area.descripcion if ln.area else "—"
        tiempos[area]["prep"].append((ln.listo_en - ln.enviado_en).total_seconds() / 60)
        if ln.entregado_en:
            tiempos[area]["entrega"].append(
                (ln.entregado_en - ln.listo_en).total_seconds() / 60
            )
    r["tiempos"] = sorted(
        (area, len(t["prep"]), _prom(t["prep"]), _prom(t["entrega"]))
        for area, t in tiempos.items()
    )
    return r


def _prom(valores) -> float | None:
    return round(sum(valores) / len(valores), 1) if valores else None


def nivel_calor(valor: Decimal, maximo: Decimal) -> int:
    if not valor or not maximo:
        return 0
    return min(4, 1 + int(valor * 4 / (maximo + Decimal("0.01"))))


# --------------------------------------------------------------------------- CSV
def _celda(valor) -> str:
    texto = "" if valor is None else str(valor)
    if texto[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto  # nunca se interpreta como fórmula al abrir en Excel
    return texto


def a_csv(filas: list, encabezado: list) -> bytes:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow([_celda(c) for c in encabezado])
    for fila in filas:
        escritor.writerow([_celda(c) for c in fila])
    return ("﻿" + salida.getvalue()).encode("utf-8")  # BOM: Excel abre bien las tildes


def filas_csv(nombre: str, r: dict) -> tuple[list, list]:
    if nombre == "dias":
        return ["Fecha", "Comprobantes", "Ventas"], [
            (d.isoformat(), n, t) for d, (n, t) in r["por_dia"]
        ]
    if nombre == "meseros":
        return ["Mesero", "Comprobantes", "Ventas"], [
            (m, n, t) for m, (n, t) in r["por_mesero"]
        ]
    if nombre == "secciones":
        return ["Sección", "Ventas brutas"], list(r["por_seccion"])
    if nombre == "productos":
        return ["Producto", "Cantidad", "Ventas brutas"], [
            (p, c.normalize(), t) for p, (c, t) in r["por_producto"]
        ]
    if nombre == "formas":
        return ["Forma de pago", "Monto"], list(r["por_forma"])
    if nombre == "itbms":
        return ["Tasa %", "Base", "ITBMS"], [(t, b, i) for t, (b, i) in r["itbms"]]
    if nombre == "jubilados":
        return (
            ["Comprobante", "Fecha", "Cédula", "Nombre", "Descuento", "Total"],
            [
                (
                    f"{d.numero:010d}",
                    local(d.emitido_en).strftime("%d/%m/%Y %H:%M"),
                    c,
                    n,
                    d.descuento_jubilado,
                    d.total,
                )
                for d, c, n in r["jubilados"]
            ],
        )
    if nombre == "anulaciones":
        return (
            [
                "Fecha",
                "Comanda",
                "Producto",
                "Cantidad",
                "Solicitó",
                "Autorizó",
                "Motivo",
            ],
            [
                (
                    local(a.fecha).strftime("%d/%m/%Y %H:%M"),
                    a.linea.cuenta.comanda.numero,
                    a.linea.descripcion,
                    a.linea.cantidad.normalize(),
                    a.solicitante.usuario,
                    a.autorizador.usuario,
                    a.motivo,
                )
                for a in r["anulaciones"]
            ],
        )
    raise ReglaNegocioError("Reporte desconocido.")
