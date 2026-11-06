"""Suscripción mensual: estado del plan, ID de instalación, activar códigos y comparar planes."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..seguridad import publica, rol_requerido
from ..services import suscripcion
from ..services.calculos import ReglaNegocioError

bp = Blueprint("suscripcion", __name__)


def _pantalla(**extra):
    return render_template(
        "suscripcion/inicio.html",
        estado=suscripcion.estado(),
        instalacion=suscripcion.id_instalacion(),
        planes=suscripcion.PLANES,
        incluye_basico=suscripcion.INCLUYE_BASICO,
        funciones_pro=suscripcion.FUNCIONES_PRO,
        historial=suscripcion.historial(),
        gracia=suscripcion.GRACIA_DIAS,
        **extra,
    )


@bp.get("/suscripcion")
@rol_requerido("administrador", "programador")
def inicio():
    return _pantalla()


@bp.post("/suscripcion/activar")
@rol_requerido("administrador", "programador")
def activar():
    codigo = request.form.get("codigo", "")
    try:
        pago = suscripcion.activar(codigo, current_user)
    except ReglaNegocioError as e:
        flash(str(e), "error")
        return _pantalla(codigo=codigo[:200]), 400
    flash(
        f"¡Listo! Plan {suscripcion.PLANES[pago.plan]['nombre']} activo hasta el "
        f"{pago.hasta:%d/%m/%Y}.",
        "ok",
    )
    return redirect(url_for("suscripcion.inicio"))


@bp.get("/plan-pro/<funcion>")
@publica
def plan_pro(funcion: str):
    """Explica que la pantalla pedida es del plan Pro (también desde otra PC en Básico)."""
    if funcion not in suscripcion.FUNCIONES_PRO:
        funcion = "red"
    return (
        render_template(
            "suscripcion/plan_pro.html",
            funcion=funcion,
            datos=suscripcion.FUNCIONES_PRO[funcion],
            funciones_pro=suscripcion.FUNCIONES_PRO,
            planes=suscripcion.PLANES,
            estado=suscripcion.estado(),
        ),
        403,
    )
