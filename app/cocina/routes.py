"""Pantalla de cocina (KDS) por área de producción: P = en proceso, L = listo, E = entregado."""

from __future__ import annotations

from collections import OrderedDict

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from ..extensions import db
from ..models import AreaProduccion, Comanda, Cuenta, LineaPedido, ahora
from ..seguridad import con_sesion
from ..services import configuracion, pedidos
from ..services.auditoria import auditar

bp = Blueprint("cocina", __name__)


def _area():
    areas = (
        AreaProduccion.query.filter_by(activa=True)
        .order_by(AreaProduccion.codigo)
        .all()
    )
    area = None
    if request.args.get("area", "").isdigit():
        area = db.session.get(AreaProduccion, int(request.args["area"]))
    return areas, (area if area in areas else (areas[0] if areas else None))


@bp.get("/cocina")
@con_sesion
def tablero():
    areas, area = _area()
    tarjetas = OrderedDict()
    if area is not None:
        lineas = (
            LineaPedido.query.join(Cuenta)
            .join(Comanda)
            .filter(
                LineaPedido.area_id == area.id,
                LineaPedido.estado.in_(("ORD", "PRO", "PRE")),
            )
            .order_by(LineaPedido.enviado_en, LineaPedido.id)
            .all()
        )
        for ln in lineas:
            tarjetas.setdefault(
                ln.cuenta.comanda_id, {"comanda": ln.cuenta.comanda, "lineas": []}
            )
            tarjetas[ln.cuenta.comanda_id]["lineas"].append(ln)
    momento = ahora()
    amarillo = int(configuracion.obtener("cocina.umbral_amarillo_min") or 10)
    rojo = int(configuracion.obtener("cocina.umbral_rojo_min") or 20)
    for t in tarjetas.values():
        inicio = min(ln.enviado_en or ln.creado for ln in t["lineas"])
        t["minutos"] = max(0, int((momento - inicio).total_seconds() // 60))
        t["nivel"] = (
            "rojo"
            if t["minutos"] >= rojo
            else ("amarillo" if t["minutos"] >= amarillo else "verde")
        )
        t["estados"] = {ln.estado for ln in t["lineas"]}
    return render_template(
        "cocina/tablero.html",
        areas=areas,
        area=area,
        tarjetas=list(tarjetas.values()),
        recarga=current_app.config.get("COCINA_RECARGA_SEG", 15),
    )


@bp.post("/cocina/<int:cid>/<int:area_id>/<any(P, L, E):accion>")
@con_sesion
def marcar(cid: int, area_id: int, accion: str):
    comanda = db.get_or_404(Comanda, cid)
    n = pedidos.marcar_cocina(comanda, area_id, accion)
    if n:
        auditar("cocina", f"comanda {comanda.numero}, área {area_id}: {accion} ({n})")
    db.session.commit()
    return redirect(url_for("cocina.tablero", area=area_id))
