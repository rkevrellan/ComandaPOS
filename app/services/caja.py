"""Caja: turnos, cobro con multipago y emisión del comprobante.

RN-09  Un pago no excede el saldo salvo en efectivo (la diferencia es vuelto). Las formas que no
       son efectivo no pueden pasar del total, y entre todas deben cubrirlo EXACTO.
RN-10  Crédito solo a clientes «crédito» o «autorizado», activos y con límite disponible.
RN-11  No se cobra una cuenta con líneas sin enviar.
RN-13  Cierre de turno con arqueo: la diferencia se justifica si pasa del umbral.
Tarjetas: se guarda solo el código de autorización (nunca el número de la tarjeta).
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

from sqlalchemy import func

from ..extensions import db
from ..models import (
    FORMAS_PAGO,
    Cliente,
    Cuenta,
    Documento,
    Operador,
    Pago,
    Turno,
    ahora,
)
from . import configuracion, secuencias
from .auditoria import auditar
from .calculos import ReglaNegocioError, redondear, validar_precio
from .pedidos import actualizar_mesa, totales

UMBRAL_DIFERENCIA = Decimal("1.00")
_REFERENCIA = re.compile(r"^[A-Za-z0-9-]{4,12}$")


# --------------------------------------------------------------------------- turnos
def turno_abierto() -> Turno | None:
    return (
        Turno.query.filter(Turno.cerrado_en.is_(None)).order_by(Turno.id.desc()).first()
    )


def abrir_turno(cajero: Operador, fondo) -> Turno:
    if turno_abierto() is not None:
        raise ReglaNegocioError(
            "Ya hay un turno abierto. Ciérralo antes de abrir otro."
        )
    fondo = validar_precio(fondo or "0", "fondo inicial", permitir_cero=True)
    turno = Turno(
        numero=secuencias.siguiente("turno"), cajero_id=cajero.id, fondo=fondo
    )
    db.session.add(turno)
    auditar("turno_abierto", f"turno {turno.numero}, fondo B/. {fondo}")
    return turno


def resumen(turno: Turno) -> dict:
    por_forma = {f: Decimal("0.00") for f in FORMAS_PAGO}
    vueltos = Decimal("0.00")
    for p in turno.pagos:
        por_forma[p.forma] += p.monto
        vueltos += p.vuelto
    documentos = (
        Documento.query.join(Pago, Pago.cuenta_id == Documento.cuenta_id)
        .filter(Pago.turno_id == turno.id)
        .distinct()
        .all()
    )
    total = sum(por_forma.values(), Decimal("0.00"))
    itbms = sum((d.itbms for d in documentos), Decimal("0.00"))
    jubilado = sum((d.descuento_jubilado for d in documentos), Decimal("0.00"))
    return {
        "por_forma": por_forma,
        "total": total,
        "documentos": len(documentos),
        "itbms": itbms,
        "descuento_jubilado": jubilado,
        # El monto aplicado en efectivo ya es neto (recibido − vuelto).
        "efectivo_esperado": turno.fondo + por_forma["efectivo"],
    }


def cerrar_turno(turno: Turno, cajero: Operador, contado, justificacion: str) -> Turno:
    if turno.cerrado_en is not None:
        raise ReglaNegocioError("Ese turno ya está cerrado.")
    contado = validar_precio(contado or "0", "efectivo contado", permitir_cero=True)
    esperado = resumen(turno)["efectivo_esperado"]
    diferencia = contado - esperado
    justificacion = " ".join((justificacion or "").split())[:200]
    if abs(diferencia) > UMBRAL_DIFERENCIA and len(justificacion) < 10:
        raise ReglaNegocioError(
            f"La diferencia es B/. {diferencia:,.2f}: explica el motivo (mínimo 10 caracteres)."
        )
    turno.efectivo_esperado = esperado
    turno.efectivo_contado = contado
    turno.diferencia = diferencia
    turno.justificacion = justificacion or None
    turno.cerrado_en = ahora()
    turno.cerrado_por_id = cajero.id
    auditar(
        "turno_cerrado",
        f"turno {turno.numero}: esperado {esperado}, contado {contado}, "
        f"diferencia {diferencia}",
    )
    return turno


# --------------------------------------------------------------------------- crédito
def credito_usado(cliente: Cliente) -> Decimal:
    usado = (
        db.session.query(func.coalesce(func.sum(Pago.monto), 0))
        .join(Cuenta, Cuenta.id == Pago.cuenta_id)
        .filter(Cuenta.cliente_id == cliente.id, Pago.forma == "credito")
        .scalar()
    )
    if isinstance(usado, Decimal):  # SUM conserva el tipo Dinero y ya llega en balboas
        return usado.quantize(Decimal("0.01"))
    return (Decimal(int(usado or 0)) / 100).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- cobro
def _leer_pagos(datos) -> dict:
    pagos = {}
    for forma in FORMAS_PAGO:
        texto = (datos.get(forma) or "").strip()
        if not texto:
            continue
        monto = validar_precio(
            texto, f"monto en {FORMAS_PAGO[forma]}", permitir_cero=True
        )
        if monto == 0:
            continue
        referencia = (datos.get(forma + "_ref") or "").strip()
        if forma in ("visa", "mastercard", "clave", "yappy"):
            if (
                referencia.replace(" ", "").replace("-", "").isdigit()
                and len(referencia) > 12
            ):
                raise ReglaNegocioError(
                    "No escribas el número de la tarjeta: solo el código de autorización."
                )
            if not _REFERENCIA.match(referencia):
                raise ReglaNegocioError(
                    f"Escribe el código de autorización de {FORMAS_PAGO[forma]} (4 a 12 letras o números)."
                )
        else:
            referencia = ""
        pagos[forma] = (monto, referencia)
    if not pagos:
        raise ReglaNegocioError("Indica al menos una forma de pago.")
    return pagos


def cobrar(cuenta: Cuenta, datos, cajero: Operador) -> Documento:
    turno = turno_abierto()
    if turno is None:
        raise ReglaNegocioError("No hay un turno de caja abierto. Ábrelo en Caja.")
    if cuenta.estado == "pagada":
        raise ReglaNegocioError("Esa cuenta ya está pagada.")
    if cuenta.comanda.estado != "abierta":
        raise ReglaNegocioError("La comanda ya está cerrada.")
    if not cuenta.activas:
        raise ReglaNegocioError("La cuenta no tiene consumo.")
    if any(ln.estado == "PED" for ln in cuenta.lineas):
        raise ReglaNegocioError(
            "Hay pedidos sin enviar: envíalos o bórralos antes de cobrar."
        )  # RN-11

    t = totales(cuenta)
    total = t.total
    pagos = _leer_pagos(datos)
    efectivo = pagos.pop("efectivo", (Decimal("0.00"), ""))[0]
    no_efectivo = sum((m for m, _ in pagos.values()), Decimal("0.00"))
    if no_efectivo > total:
        raise ReglaNegocioError(
            "Las tarjetas, Yappy y crédito no pueden pasar del total."
        )  # RN-09
    falta = total - no_efectivo
    if efectivo < falta:
        raise ReglaNegocioError(f"Falta cubrir B/. {falta - efectivo:,.2f}.")
    if efectivo > 0 and falta == 0:
        raise ReglaNegocioError(
            "El total ya está cubierto sin efectivo; quita el monto en efectivo."
        )
    vuelto = efectivo - falta

    if "credito" in pagos:  # RN-10
        cliente = cuenta.cliente
        if (
            cliente is None
            or not cliente.activo
            or cliente.tipo_pago not in ("credito", "autorizado")
        ):
            raise ReglaNegocioError(
                "El crédito solo se da a clientes con crédito autorizado."
            )
        disponible = cliente.limite_credito - credito_usado(cliente)
        if pagos["credito"][0] > disponible:
            raise ReglaNegocioError(
                f"El cliente solo tiene B/. {disponible:,.2f} de crédito disponible."
            )

    momento = ahora()
    if falta > 0:
        db.session.add(
            Pago(
                cuenta=cuenta,
                turno=turno,
                cajero_id=cajero.id,
                forma="efectivo",
                monto=falta,
                recibido=efectivo,
                vuelto=vuelto,
                fecha=momento,
            )
        )
    for forma, (monto, referencia) in pagos.items():
        db.session.add(
            Pago(
                cuenta=cuenta,
                turno=turno,
                cajero_id=cajero.id,
                forma=forma,
                monto=monto,
                recibido=monto,
                referencia=referencia or None,
                fecha=momento,
            )
        )

    documento = emitir(cuenta, t, cajero)
    cuenta.estado = "pagada"
    cuenta.pagada_en = momento
    comanda = cuenta.comanda
    if all(c.estado == "pagada" or not c.activas for c in comanda.cuentas):
        comanda.estado = "cerrada"
        comanda.cerrada_en = momento
    actualizar_mesa(comanda)
    auditar(
        "cobro",
        f"comanda {comanda.numero}, cuenta {cuenta.numero}: B/. {total} "
        f"({', '.join(sorted(['efectivo'] if falta else []) + sorted(pagos))}), comprobante {documento.numero}",
    )
    return documento


def emitir(cuenta: Cuenta, t, cajero: Operador) -> Documento:
    """Comprobante de la cuenta. Fase 5: aquí se llamará al PAC para obtener el CUFE real."""
    if cuenta.cliente is not None:
        ruc, dv, nombre = cuenta.cliente.ruc, cuenta.cliente.dv, cuenta.cliente.nombre
    else:
        ruc, dv = "00-00-00", None
        nombre = cuenta.nombre_consumidor or "CONSUMIDOR FINAL"
    numero = secuencias.siguiente("factura")
    impuestos = {
        str(tasa): [str(t.base_por_tasa[tasa]), str(t.itbms_por_tasa[tasa])]
        for tasa in sorted(t.base_por_tasa)
    }
    huella = (
        hashlib.sha256(
            f"{configuracion.obtener('emisor.ruc')}|{numero}|{t.total}|{ahora().isoformat()}".encode()
        )
        .hexdigest()[:40]
        .upper()
    )
    documento = Documento(
        numero=numero,
        cuenta=cuenta,
        cajero_id=cajero.id,
        receptor_ruc=ruc,
        receptor_dv=dv,
        receptor_nombre=nombre,
        subtotal=t.subtotal,
        descuento_producto=t.descuento_producto,
        descuento_jubilado=t.descuento_jubilado,
        itbms=t.itbms,
        total=t.total,
        impuestos=json.dumps(impuestos),
        cufe=f"DEMO-{huella}",
        estado="simulado",
    )
    db.session.add(documento)
    return documento


def redondeo_billete(total: Decimal) -> list:
    """Sugerencias de billetes para el cobro en efectivo."""
    total = redondear(total)
    sugerencias = []
    for billete in (
        Decimal("1"),
        Decimal("5"),
        Decimal("10"),
        Decimal("20"),
        Decimal("50"),
    ):
        monto = (total / billete).to_integral_value(rounding="ROUND_CEILING") * billete
        if monto >= total and monto not in sugerencias:
            sugerencias.append(monto.quantize(Decimal("0.01")))
    return sugerencias[:4]
