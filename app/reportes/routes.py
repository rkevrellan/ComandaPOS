"""Reportes de gestión (supervisor o superior) con exportación a CSV."""

from __future__ import annotations

from flask_login import current_user
from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..models import FORMAS_PAGO
from ..seguridad import desde, rol_requerido
from ..services import reportes
from ..services.auditoria import auditar
from ..services.calculos import ReglaNegocioError
from ..extensions import db

bp = Blueprint("reportes", __name__, url_prefix="/reportes")
NOMBRES_CSV = (
    "dias",
    "meseros",
    "secciones",
    "productos",
    "formas",
    "itbms",
    "jubilados",
    "anulaciones",
)


@bp.get("/")
@rol_requerido(*desde("supervisor"))
def inicio():
    try:
        inicio_utc, fin_utc, d, h = reportes.rango(
            request.args.get("desde"), request.args.get("hasta")
        )
    except ReglaNegocioError as e:
        flash(str(e), "error")
        return redirect(url_for("reportes.inicio"))
    r = reportes.calcular(inicio_utc, fin_utc)
    return render_template(
        "reportes/inicio.html",
        r=r,
        desde=d,
        hasta=h,
        formas=FORMAS_PAGO,
        dias=reportes.DIAS,
        nivel=reportes.nivel_calor,
        local=reportes.local,
        enmascarar=reportes.enmascarar_cedula,
    )


@bp.get("/<nombre>.csv")
@rol_requerido(*desde("supervisor"))
def csv(nombre: str):
    if nombre not in NOMBRES_CSV:
        return Response("Reporte desconocido.", status=404)
    try:
        inicio_utc, fin_utc, d, h = reportes.rango(
            request.args.get("desde"), request.args.get("hasta")
        )
    except ReglaNegocioError as e:
        flash(str(e), "error")
        return redirect(url_for("reportes.inicio"))
    # H-21: la cédula completa solo la baja un administrador, a propósito, y queda auditado.
    completa = (
        nombre == "jubilados"
        and request.args.get("cedula") == "completa"
        and current_user.puede("administrador")
    )
    encabezado, filas = reportes.filas_csv(
        nombre, reportes.calcular(inicio_utc, fin_utc), cedula_completa=completa
    )
    auditar(
        "exportacion",
        f"reporte {nombre} {d}..{h} ({len(filas)} filas)"
        + (" CON CÉDULA COMPLETA" if completa else ""),
    )
    db.session.commit()
    return Response(
        reportes.a_csv(filas, encabezado),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}_{d}_{h}.csv"'},
    )
