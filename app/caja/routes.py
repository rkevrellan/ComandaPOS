"""Caja: apertura y cierre de turno (corte Z con arqueo) y comprobantes emitidos."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import FORMAS_PAGO, Documento, Pago, Turno
from ..seguridad import desde, rol_requerido
from ..services import caja
from ..services.calculos import ReglaNegocioError

bp = Blueprint("caja", __name__)


@bp.get("/caja")
@rol_requerido(*desde("cajero"))
def inicio():
    turno = caja.turno_abierto()
    datos = caja.resumen(turno) if turno else None
    documentos = []
    if turno is not None:
        documentos = (
            Documento.query.join(Pago, Pago.cuenta_id == Documento.cuenta_id)
            .filter(Pago.turno_id == turno.id)
            .distinct()
            .order_by(Documento.numero.desc())
            .limit(50)
            .all()
        )
    anteriores = (
        Turno.query.filter(Turno.cerrado_en.is_not(None))
        .order_by(Turno.id.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "caja/inicio.html",
        turno=turno,
        datos=datos,
        formas=FORMAS_PAGO,
        documentos=documentos,
        anteriores=anteriores,
    )


@bp.post("/caja/abrir")
@rol_requerido(*desde("cajero"))
def abrir():
    try:
        turno = caja.abrir_turno(current_user, request.form.get("fondo"))
        db.session.commit()
        flash(f"Turno {turno.numero} abierto.", "ok")
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
    return redirect(url_for("caja.inicio"))


@bp.post("/caja/cerrar")
@rol_requerido(*desde("cajero"))
def cerrar():
    turno = caja.turno_abierto()
    if turno is None:
        flash("No hay turno abierto.", "info")
        return redirect(url_for("caja.inicio"))
    try:
        caja.cerrar_turno(
            turno,
            current_user,
            request.form.get("contado"),
            request.form.get("justificacion"),
        )
        db.session.commit()
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for("caja.inicio"))
    flash(
        f"Turno {turno.numero} cerrado. Diferencia: B/. {turno.diferencia:,.2f}.", "ok"
    )
    return redirect(url_for("caja.inicio"))
