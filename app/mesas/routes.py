"""Control — ocupación de mesas (pantalla principal)."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import ESTADOS_MESA, Comanda, Cuenta, LineaPedido, Mesa, Sala, ahora
from ..seguridad import con_sesion, publica
from ..services import pedidos, secuencias

bp = Blueprint("mesas", __name__)

#: Texto de cada estado (el color nunca va solo: también va el texto).
LEYENDA = {
    "disponible": "Disponible",
    "ocupada": "Ocupada",
    "precuenta": "Pre-cuenta",
    "pagada": "Pagada",
    "fuera": "Fuera de servicio",
    "llevar": "Llevar / pagada",
}
#: Versión corta para la tarjeta de la mesa (cabe en una línea).
CORTO = dict(LEYENDA, fuera="Fuera serv.", llevar="Llevar")
assert set(LEYENDA) == set(ESTADOS_MESA)


@bp.get("/")
@publica
def inicio():
    if current_user.is_authenticated:
        return redirect(url_for("mesas.control"))
    return redirect(url_for("auth.acceso"))


@bp.get("/mesas")
@con_sesion
def control():
    salas = Sala.query.filter_by(activa=True).order_by(Sala.orden).all()
    sala = None
    if request.args.get("sala", "").isdigit():
        sala = db.session.get(Sala, int(request.args["sala"]))
    if sala is None or not sala.activa:
        sala = salas[0] if salas else None
    mesas = sala.mesas if sala else []
    conteo = {e: 0 for e in ESTADOS_MESA}
    for m in Mesa.query.all():
        conteo[m.estado] += 1

    momento = ahora()
    abiertas = Comanda.query.filter_by(estado="abierta").all()
    info = {}
    for c in abiertas:
        if c.mesa_id is not None:
            info[c.mesa_id] = {
                "mesero": c.mesero.iniciales,
                "propia": pedidos.puede_operar(current_user, c),
                "total": pedidos.total_comanda(c),
                "minutos": int((momento - c.abierta_en).total_seconds() // 60),
            }
    rapidas = [
        c
        for c in abiertas
        if c.tipo == "rapido" and pedidos.puede_operar(current_user, c)
    ]

    consulta = (
        LineaPedido.query.join(Cuenta)
        .join(Comanda)
        .filter(LineaPedido.estado == "PRE", Comanda.estado == "abierta")
    )
    if not current_user.puede("cajero"):
        consulta = consulta.filter(Comanda.mesero_id == current_user.id)
    listos = consulta.order_by(LineaPedido.listo_en).limit(30).all()

    return render_template(
        "mesas/control.html",
        salas=salas,
        sala=sala,
        mesas=mesas,
        leyenda=LEYENDA,
        corto=CORTO,
        conteo=conteo,
        info=info,
        rapidas=rapidas,
        listos=listos,
        ultima_comanda=secuencias.actual("comanda"),
    )
