"""Caja: turnos, cobro con multipago, comprobantes, notas de crédito, abonos a crédito y gaveta.

RN-09  Un pago no excede el saldo salvo en efectivo (la diferencia es vuelto). Las formas que no
       son efectivo no pueden pasar del total, y entre todas deben cubrirlo EXACTO.
RN-10  Crédito solo a clientes «crédito» o «autorizado», activos y con límite disponible.
RN-11  No se cobra una cuenta con líneas sin enviar.
RN-13  Cierre de turno con arqueo: la diferencia se justifica si pasa del umbral.
RN-16  Una nota de crédito no puede devolver más de lo que queda por acreditar de cada ítem ni del
       total del comprobante; requiere supervisor y motivo.
Tarjetas: se guarda solo el código de autorización (nunca el número de la tarjeta).
"""

from __future__ import annotations

import json
import re
import secrets
from decimal import Decimal

from sqlalchemy import func

from ..extensions import db
from ..models import (
    FORMAS_PAGO,
    Abono,
    Cliente,
    Cuenta,
    Documento,
    NotaCredito,
    Operador,
    Pago,
    Turno,
    ahora,
)
from . import configuracion, secuencias
from .auditoria import auditar
from .calculos import (
    LineaCalculo,
    ReglaNegocioError,
    calcular_linea,
    redondear,
    validar_cantidad,
    validar_precio,
)
from .pedidos import actualizar_mesa, totales

UMBRAL_DIFERENCIA = Decimal("1.00")
CERO = Decimal("0.00")
_REFERENCIA = re.compile(r"^[A-Za-z0-9-]{4,12}$")
FORMAS_CON_REFERENCIA = ("visa", "mastercard", "clave", "yappy")


def _dinero_sql(valor) -> Decimal:
    """SUM conserva el tipo Dinero (llega en balboas); por si acaso, acepta centavos enteros."""
    if isinstance(valor, Decimal):
        return valor.quantize(Decimal("0.01"))
    return (Decimal(int(valor or 0)) / 100).quantize(Decimal("0.01"))


def codigo_provisional(prefijo: str, numero: int) -> str:
    """Identificador único mientras el PAC no devuelve el CUFE (nunca se presenta como CUFE)."""
    return f"{prefijo}-{numero:010d}-{secrets.token_hex(4).upper()}"


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
    por_forma = {f: CERO for f in FORMAS_PAGO}
    for p in turno.pagos:
        por_forma[p.forma] += p.monto
    abonos = {f: CERO for f in FORMAS_PAGO}
    for a in Abono.query.filter_by(turno_id=turno.id):
        abonos[a.forma] += a.monto
    devoluciones = {f: CERO for f in FORMAS_PAGO}
    notas = NotaCredito.query.filter_by(turno_id=turno.id).all()
    for nc in notas:
        devoluciones[nc.forma_devolucion] += nc.total
    documentos = (
        Documento.query.join(Pago, Pago.cuenta_id == Documento.cuenta_id)
        .filter(Pago.turno_id == turno.id)
        .distinct()
        .all()
    )
    ventas = sum(por_forma.values(), CERO)
    itbms = sum((d.itbms for d in documentos), CERO) - sum(
        (nc.itbms for nc in notas), CERO
    )
    return {
        "por_forma": por_forma,
        "abonos": abonos,
        "devoluciones": devoluciones,
        "total": ventas,
        "total_neto": ventas - sum(devoluciones.values(), CERO),
        "documentos": len(documentos),
        "notas_credito": len(notas),
        "itbms": itbms,
        "descuento_jubilado": sum((d.descuento_jubilado for d in documentos), CERO),
        # El monto aplicado en efectivo ya es neto (recibido − vuelto).
        "efectivo_esperado": turno.fondo
        + por_forma["efectivo"]
        + abonos["efectivo"]
        - devoluciones["efectivo"],
    }


def pendientes_de_cierre() -> list:
    """H-10: lo que queda abierto al cerrar el turno (mesas con consumo y documentos sin autorizar)."""
    from ..models import Comanda
    from . import fiscal

    avisos = []
    for c in Comanda.query.filter_by(estado="abierta").order_by(Comanda.numero).all():
        if any(cu.activas for cu in c.cuentas if cu.estado != "pagada"):
            lugar = f"mesa {c.mesa.numero}" if c.mesa else f"pedido directo {c.numero}"
            avisos.append(f"{lugar} sin cobrar ({c.mesero.nombre})")
    pend = fiscal.pendientes() + fiscal.rechazados()
    if pend:
        avisos.append(f"{len(pend)} documento(s) sin autorizar por el PAC")
    return avisos


def cerrar_turno(
    turno: Turno,
    cajero: Operador,
    contado,
    justificacion: str,
    autorizador: Operador | None = None,
) -> Turno:
    if turno.cerrado_en is not None:
        raise ReglaNegocioError("Ese turno ya está cerrado.")
    abiertos = pendientes_de_cierre()
    if abiertos and (autorizador is None or not autorizador.puede("supervisor")):
        raise ReglaNegocioError(
            "No se cierra el turno con pendientes: "
            + "; ".join(abiertos)
            + ". Resuélvelos (cobra las mesas, reenvía los documentos) o pide a un supervisor que autorice el cierre."
        )
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
        f"diferencia {diferencia}"
        + (f"; con pendientes: {'; '.join(abiertos)}" if abiertos else ""),
        autorizador=autorizador if abiertos else None,
    )
    return turno


def abrir_gaveta(cajero: Operador, motivo: str) -> None:
    """Apertura sin venta: solo cajero o superior, con motivo; queda auditada."""
    motivo = " ".join((motivo or "").split())[:120]
    if len(motivo) < 5:
        raise ReglaNegocioError("Escribe el motivo para abrir la gaveta.")
    if turno_abierto() is None:
        raise ReglaNegocioError("No hay un turno abierto.")
    auditar("gaveta_sin_venta", motivo, operador=cajero)


# --------------------------------------------------------------------------- crédito
def credito_usado(cliente: Cliente) -> Decimal:
    cargado = (
        db.session.query(func.coalesce(func.sum(Pago.monto), 0))
        .join(Cuenta, Cuenta.id == Pago.cuenta_id)
        .filter(Cuenta.cliente_id == cliente.id, Pago.forma == "credito")
        .scalar()
    )
    abonado = (
        db.session.query(func.coalesce(func.sum(Abono.monto), 0))
        .filter(Abono.cliente_id == cliente.id)
        .scalar()
    )
    devuelto = (
        db.session.query(func.coalesce(func.sum(NotaCredito.total), 0))
        .join(Documento, Documento.id == NotaCredito.documento_id)
        .join(Cuenta, Cuenta.id == Documento.cuenta_id)
        .filter(
            Cuenta.cliente_id == cliente.id, NotaCredito.forma_devolucion == "credito"
        )
        .scalar()
    )
    return _dinero_sql(cargado) - _dinero_sql(abonado) - _dinero_sql(devuelto)


def abonar(
    cliente: Cliente, monto, forma: str, referencia: str, cajero: Operador
) -> Abono:
    turno = turno_abierto()
    if turno is None:
        raise ReglaNegocioError("No hay un turno de caja abierto.")
    if forma not in FORMAS_PAGO or forma == "credito":
        raise ReglaNegocioError("Forma de pago no válida para un abono.")
    monto = validar_precio(monto, "monto del abono")
    deuda = credito_usado(cliente)
    if deuda <= 0:
        raise ReglaNegocioError("Ese cliente no tiene saldo pendiente.")
    if monto > deuda:
        raise ReglaNegocioError(
            f"El saldo pendiente es B/. {deuda:,.2f}; el abono no puede pasarlo."
        )
    referencia = (referencia or "").strip()
    if forma in FORMAS_CON_REFERENCIA and not _REFERENCIA.match(referencia):
        raise ReglaNegocioError(
            "Escribe el código de autorización (4 a 12 letras o números)."
        )
    abono = Abono(
        recibo=secuencias.siguiente("recibo"),
        cliente=cliente,
        turno=turno,
        cajero_id=cajero.id,
        forma=forma,
        monto=monto,
        referencia=referencia if forma in FORMAS_CON_REFERENCIA else None,
    )
    db.session.add(abono)
    auditar("abono", f"{cliente.ruc}: B/. {monto} ({forma}), recibo {abono.recibo}")
    return abono


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
        if forma in FORMAS_CON_REFERENCIA:
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
    from flask import current_app

    if not current_app.config["DEMO"]:
        faltan = configuracion.emisor_incompleto()
        if faltan:
            raise ReglaNegocioError(
                "No se puede facturar: faltan datos del emisor ("
                + ", ".join(faltan)
                + "). Complétalos en Administración → Configuración."
            )
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
    efectivo = pagos.pop("efectivo", (CERO, ""))[0]
    no_efectivo = sum((m for m, _ in pagos.values()), CERO)
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
        from . import suscripcion

        if not suscripcion.tiene("credito"):
            raise ReglaNegocioError(
                "La venta a crédito es del plan Pro. Cobra con otra forma de pago."
            )
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
    registro_pagos = []
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
        registro_pagos.append(
            {
                "forma": forma,
                "monto": str(monto),
                "recibido": str(monto),
                "vuelto": "0.00",
                "referencia": referencia,
            }
        )
    if falta > 0:  # el efectivo va al final (como en el comprobante)
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
        registro_pagos.append(
            {
                "forma": "efectivo",
                "monto": str(falta),
                "recibido": str(efectivo),
                "vuelto": str(vuelto),
                "referencia": "",
            }
        )

    documento = emitir(cuenta, t, cajero, registro_pagos)
    cuenta.estado = "pagada"
    cuenta.pagada_en = momento
    comanda = cuenta.comanda
    if all(c.estado == "pagada" or not c.activas for c in comanda.cuentas):
        comanda.estado = "cerrada"
        comanda.cerrada_en = momento
    actualizar_mesa(comanda)
    formas = ", ".join(p["forma"] for p in registro_pagos)
    auditar(
        "cobro",
        f"comanda {comanda.numero}, cuenta {cuenta.numero}: B/. {total} ({formas}), "
        f"comprobante {documento.numero}",
    )
    return documento


def _items_de(cuenta: Cuenta, t) -> list:
    salida = []
    for ln, r in zip(cuenta.activas, t.lineas):
        pct = (
            (r.descuento * 100 / r.bruto).quantize(Decimal("0.01")) if r.bruto else CERO
        )
        salida.append(
            {
                "codigo": ln.producto.codigo if ln.producto else 0,
                "descripcion": ln.descripcion,
                "acompanamiento": ln.acompanamiento or "",
                "cantidad": str(ln.cantidad.normalize()),
                "precio": str(ln.precio),
                "bruto": str(r.bruto),
                "descuento": str(r.descuento),
                "descuento_pct": str(ln.descuento_pct if not r.es_jubilado else pct),
                "es_jubilado": r.es_jubilado,
                "base": str(r.base),
                "tasa": r.tasa,
                "itbms": str(r.itbms),
                "total": str(r.total),
            }
        )
    return salida


def emitir(cuenta: Cuenta, t, cajero: Operador, registro_pagos: list) -> Documento:
    """Crea el comprobante con su detalle congelado. La autorización del PAC va DESPUÉS de confirmar."""
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
    detalle = {
        "items": _items_de(cuenta, t),
        "pagos": registro_pagos,
        "jubilado": (
            {"cedula": cuenta.jubilado_cedula, "nombre": cuenta.jubilado_nombre}
            if cuenta.jubilado_cedula
            else None
        ),
    }
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
        detalle=json.dumps(detalle, ensure_ascii=False),
        cufe=codigo_provisional("PEND", numero),
        estado="pendiente",
    )
    db.session.add(documento)
    return documento


# --------------------------------------------------------------------------- notas de crédito
def acreditado_por_item(doc: Documento) -> dict:
    """Cantidad ya acreditada de cada ítem del comprobante (por notas de crédito anteriores)."""
    from .fiscal import items as items_de

    ya = {}
    for nc in doc.notas_credito:
        for it in items_de(nc):
            ya[it["indice"]] = ya.get(it["indice"], Decimal("0")) + Decimal(it["cantidad"])
    return ya


def nota_credito(
    doc: Documento,
    cantidades: dict,
    motivo: str,
    forma_devolucion: str,
    solicitante: Operador,
    autorizador: Operador,
) -> NotaCredito:
    """RN-16. `cantidades` = {índice del ítem: cantidad a acreditar}."""
    from .fiscal import items as items_de

    if doc.estado not in ("autorizado", "simulado"):
        raise ReglaNegocioError(
            "Solo se acredita un comprobante ya autorizado por el PAC."
        )
    turno = turno_abierto()
    if turno is None:
        raise ReglaNegocioError("No hay un turno de caja abierto.")
    motivo = " ".join((motivo or "").split())[:200]
    if len(motivo) < 10:
        raise ReglaNegocioError(
            "Explica el motivo de la nota de crédito (mínimo 10 caracteres)."
        )
    if forma_devolucion not in FORMAS_PAGO:
        raise ReglaNegocioError("Forma de devolución no válida.")
    if forma_devolucion == "credito" and (doc.cuenta.cliente is None):
        raise ReglaNegocioError("Solo se devuelve a crédito a un cliente registrado.")
    originales = items_de(doc)
    ya = acreditado_por_item(doc)
    seleccion = []
    for indice, cantidad in cantidades.items():
        if not (0 <= indice < len(originales)):
            raise ReglaNegocioError("Ítem desconocido.")
        cantidad = validar_cantidad(cantidad)
        it = originales[indice]
        restante = Decimal(it["cantidad"]) - ya.get(indice, Decimal("0"))
        if cantidad > restante:
            raise ReglaNegocioError(
                f"De «{it['descripcion']}» solo quedan {restante.normalize()} por acreditar."
            )
        seleccion.append((indice, it, cantidad))
    if not seleccion:
        raise ReglaNegocioError("Elige al menos un producto para la nota de crédito.")

    detalle, subtotal, desc_prd, desc_jub, itbms, total, impuestos = (
        [],
        CERO,
        CERO,
        CERO,
        CERO,
        CERO,
        {},
    )
    for indice, it, cantidad in seleccion:
        if cantidad == Decimal(it["cantidad"]) and indice not in ya:
            bruto, descuento, base = (
                Decimal(it["bruto"]),
                Decimal(it["descuento"]),
                Decimal(it["base"]),
            )
            imp, tot = Decimal(it["itbms"]), Decimal(it["total"])
        else:
            r = calcular_linea(
                LineaCalculo.crear(
                    cantidad, it["precio"], it["tasa"], it["descuento_pct"], False
                )
            )
            bruto, descuento, base, imp, tot = (
                r.bruto,
                r.descuento,
                r.base,
                r.itbms,
                r.total,
            )
        detalle.append(
            dict(
                it,
                indice=indice,
                cantidad=str(cantidad.normalize()),
                bruto=str(bruto),
                descuento=str(descuento),
                base=str(base),
                itbms=str(imp),
                total=str(tot),
            )
        )
        subtotal += bruto
        if it.get("es_jubilado"):
            desc_jub += descuento
        else:
            desc_prd += descuento
        itbms += imp
        total += tot
        b, i = impuestos.get(str(it["tasa"]), (CERO, CERO))
        impuestos[str(it["tasa"])] = (b + base, i + imp)
    previas = sum((nc.total for nc in doc.notas_credito), CERO)
    if total + previas > doc.total:
        raise ReglaNegocioError("La nota de crédito pasaría del total del comprobante.")

    numero = secuencias.siguiente("nota_credito")
    nc = NotaCredito(
        numero=numero,
        documento=doc,
        turno_id=turno.id,
        solicitante_id=solicitante.id,
        autorizador_id=autorizador.id,
        motivo=motivo,
        forma_devolucion=forma_devolucion,
        subtotal=subtotal,
        descuento_producto=desc_prd,
        descuento_jubilado=desc_jub,
        itbms=itbms,
        total=total,
        impuestos=json.dumps({k: [str(b), str(i)] for k, (b, i) in impuestos.items()}),
        detalle=json.dumps({"items": detalle}, ensure_ascii=False),
        cufe=codigo_provisional("PNC", numero),
        estado="pendiente",
    )
    db.session.add(nc)
    auditar(
        "nota_credito",
        f"NC {numero} sobre FE {doc.numero}: B/. {total} ({forma_devolucion}). {motivo}",
        operador=solicitante,
        autorizador=autorizador,
    )
    return nc


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

