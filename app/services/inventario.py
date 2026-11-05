"""Inventario por receta.

RN-14  La salida de inventario ocurre al ENVIAR el pedido (no al tocar el producto) y se revierte si
       la línea se anula antes de estar lista. Solo descuentan los productos «activo con inventario».
RN-15  Si un insumo de la receta llega a 0 (y así está configurado), el producto queda agotado
       automáticamente; vuelve a estar disponible cuando entra mercancía.
"""

from __future__ import annotations

from decimal import Decimal

from ..extensions import db
from ..models import Insumo, MovimientoInventario, Producto, RecetaItem
from . import configuracion
from .auditoria import auditar
from .calculos import ReglaNegocioError, a_decimal

MAXIMO = Decimal("999999.999")


def _cantidad(valor, campo="cantidad", permitir_cero=False) -> Decimal:
    c = a_decimal(valor, campo)
    if c < 0 or (c == 0 and not permitir_cero) or c > MAXIMO:
        raise ReglaNegocioError(f"La {campo} no es válida.")
    if c != c.quantize(Decimal("0.001")):
        raise ReglaNegocioError(f"La {campo} admite como máximo 3 decimales.")
    return c.quantize(Decimal("0.001"))


def _revisar_agotados(insumo_ids) -> None:
    if configuracion.obtener("inventario.agotar_en_cero") != "1" or not insumo_ids:
        return
    afectados = (
        Producto.query.join(RecetaItem, RecetaItem.producto_id == Producto.id)
        .filter(
            RecetaItem.insumo_id.in_(insumo_ids), Producto.condicion == "activo_cinv"
        )
        .all()
    )
    for p in afectados:
        sin_existencia = any(r.insumo.existencia <= 0 for r in p.receta)
        if sin_existencia and not p.agotado:
            p.agotado, p.agotado_auto = True, True
            auditar(
                "agotado_auto", f"{p.descripcion}: un insumo de la receta llegó a 0"
            )
        elif not sin_existencia and p.agotado and p.agotado_auto:
            p.agotado, p.agotado_auto = False, False
            auditar("reactivado_auto", f"{p.descripcion}: hay existencia otra vez")


def faltantes(lineas) -> list:
    """H-13: insumos que NO alcanzan para estas líneas (suma de recetas). [(insumo, necesita)]"""
    necesita = {}
    for ln in lineas:
        # Una línea recién agregada aún no tiene cargada la relación: se busca por su id.
        producto = ln.producto or (
            db.session.get(Producto, ln.producto_id) if ln.producto_id else None
        )
        if producto is None or producto.condicion != "activo_cinv" or ln.estado == "ANU":
            continue
        for item in producto.receta:
            cantidad = (item.cantidad * ln.cantidad).quantize(Decimal("0.001"))
            necesita[item.insumo] = necesita.get(item.insumo, Decimal("0")) + cantidad
    return [(ins, n) for ins, n in necesita.items() if n > ins.existencia]


def revisar_existencia(lineas) -> None:
    """Bloquea (por defecto) un pedido que la existencia no cubre, con el detalle de lo que falta."""
    from .calculos import ReglaNegocioError

    if configuracion.obtener("inventario.bloquear_sin_existencia", "1") != "1":
        return
    faltan = faltantes(lineas)
    if faltan:
        detalle = "; ".join(
            f"{ins.nombre}: hay {ins.existencia.normalize()} {ins.unidad}, "
            f"se necesitan {n.normalize()}"
            for ins, n in faltan
        )
        raise ReglaNegocioError(f"No alcanza el inventario — {detalle}.")


def consumir(lineas, operador) -> int:
    """RN-14: descuenta la receta de cada línea enviada. Devuelve cuántos movimientos hizo."""
    movimientos, tocados = 0, set()
    for ln in lineas:
        producto = ln.producto
        if producto is None or producto.condicion != "activo_cinv":
            continue
        for item in producto.receta:
            cantidad = (item.cantidad * ln.cantidad).quantize(Decimal("0.001"))
            item.insumo.existencia = item.insumo.existencia - cantidad
            db.session.add(
                MovimientoInventario(
                    insumo=item.insumo,
                    tipo="salida",
                    cantidad=-cantidad,
                    referencia=f"comanda {ln.cuenta.comanda.numero}",
                    linea_id=ln.id,
                    operador_id=operador.id,
                )
            )
            tocados.add(item.insumo_id)
            movimientos += 1
    db.session.flush()
    _revisar_agotados(tocados)
    return movimientos


def reversar(linea, operador) -> int:
    """Devuelve al inventario lo que salió por una línea anulada antes de estar lista."""
    salidas = MovimientoInventario.query.filter_by(
        linea_id=linea.id, tipo="salida"
    ).all()
    if MovimientoInventario.query.filter_by(linea_id=linea.id, tipo="reverso").first():
        return 0
    tocados = set()
    for m in salidas:
        m.insumo.existencia = m.insumo.existencia - m.cantidad  # la salida es negativa
        db.session.add(
            MovimientoInventario(
                insumo=m.insumo,
                tipo="reverso",
                cantidad=-m.cantidad,
                referencia=f"anulación línea {linea.id}",
                linea_id=linea.id,
                operador_id=operador.id,
            )
        )
        tocados.add(m.insumo_id)
    db.session.flush()
    _revisar_agotados(tocados)
    return len(salidas)


def entrada(
    insumo: Insumo, cantidad, referencia: str, operador
) -> MovimientoInventario:
    cantidad = _cantidad(cantidad)
    insumo.existencia = insumo.existencia + cantidad
    mov = MovimientoInventario(
        insumo=insumo,
        tipo="entrada",
        cantidad=cantidad,
        referencia=" ".join((referencia or "compra").split())[:80],
        operador_id=operador.id,
    )
    db.session.add(mov)
    db.session.flush()
    auditar(
        "inventario_entrada",
        f"{insumo.nombre}: +{cantidad.normalize()} {insumo.unidad} ({mov.referencia})",
    )
    _revisar_agotados({insumo.id})
    return mov


def ajustar(
    insumo: Insumo, nueva_existencia, motivo: str, operador
) -> MovimientoInventario:
    nueva = _cantidad(nueva_existencia, "existencia", permitir_cero=True)
    motivo = " ".join((motivo or "").split())[:80]
    if len(motivo) < 5:
        raise ReglaNegocioError("Escribe el motivo del ajuste.")
    diferencia = nueva - insumo.existencia
    insumo.existencia = nueva
    mov = MovimientoInventario(
        insumo=insumo,
        tipo="ajuste",
        cantidad=diferencia,
        referencia=motivo,
        operador_id=operador.id,
    )
    db.session.add(mov)
    db.session.flush()
    auditar(
        "inventario_ajuste",
        f"{insumo.nombre}: {diferencia.normalize():+f} → {nueva.normalize()} ({motivo})",
    )
    _revisar_agotados({insumo.id})
    return mov


def fijar_receta(producto: Producto, filas) -> None:
    """`filas` = [(insumo_id, cantidad), …]; reemplaza la receta completa."""
    nuevas = {}
    for insumo_id, cantidad in filas:
        if not str(insumo_id).isdigit() or not str(cantidad).strip():
            continue
        insumo = db.session.get(Insumo, int(insumo_id))
        if insumo is None:
            raise ReglaNegocioError("Insumo desconocido.")
        nuevas[insumo.id] = _cantidad(cantidad)
    for item in list(producto.receta):
        db.session.delete(item)
    db.session.flush()
    for insumo_id, cantidad in nuevas.items():
        db.session.add(
            RecetaItem(producto_id=producto.id, insumo_id=insumo_id, cantidad=cantidad)
        )
    auditar("receta", f"{producto.descripcion}: {len(nuevas)} insumo(s)")
