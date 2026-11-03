"""Control — ocupación de mesas (pantalla principal)."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import ESTADOS_MESA, Mesa, Sala
from ..seguridad import con_sesion, publica
from ..services import secuencias

bp = Blueprint("mesas", __name__)

#: Texto y clase CSS de cada estado (el color nunca va solo: también va el texto).
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
    return render_template(
        "mesas/control.html",
        salas=salas,
        sala=sala,
        mesas=mesas,
        leyenda=LEYENDA,
        corto=CORTO,
        conteo=conteo,
        ultima_comanda=secuencias.actual("comanda"),
    )
