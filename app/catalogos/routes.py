"""Notas fijas y clientes (los accesos de la barra inferior del mapa de mesas)."""

from __future__ import annotations

import re
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from ..extensions import db
from ..models import TIPOS_CLIENTE, TIPOS_PAGO_CLIENTE, Cliente, NotaFija
from ..seguridad import con_sesion, desde, rol_requerido
from ..services import caja
from ..services.auditoria import auditar
from ..services.calculos import ReglaNegocioError, validar_precio

bp = Blueprint("catalogos", __name__)

_RUC = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,28}[A-Z0-9]$")
_DV = re.compile(r"^\d{1,3}$")
_CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
NOMBRE_TIPO = {
    "natural": "Persona natural",
    "juridico": "Persona jurídica",
    "extranjero": "Extranjero",
    "consumidor_final": "Consumidor final",
}
NOMBRE_PAGO = {
    "contado": "Contado",
    "autorizado": "Autorizado",
    "personal": "Personal",
    "credito": "Crédito",
}


# --------------------------------------------------------------------------- notas fijas
@bp.get("/notas")
@con_sesion
def notas():
    lista = NotaFija.query.order_by(NotaFija.activa.desc(), NotaFija.codigo).all()
    return render_template(
        "catalogos/notas.html",
        notas=lista,
        puede_editar=current_user.puede("supervisor"),
    )


@bp.post("/notas")
@rol_requerido(*desde("supervisor"))
def nota_nueva():
    texto = " ".join((request.form.get("descripcion") or "").split()).upper()[:60]
    if len(texto) < 3:
        flash("Escribe la nota (mínimo 3 caracteres).", "error")
        return redirect(url_for("catalogos.notas"))
    if NotaFija.query.filter(func.upper(NotaFija.descripcion) == texto).first():
        flash("Esa nota ya existe.", "error")
        return redirect(url_for("catalogos.notas"))
    codigo = (db.session.query(func.max(NotaFija.codigo)).scalar() or 0) + 1
    db.session.add(NotaFija(codigo=codigo, descripcion=texto))
    auditar("nota_fija", f"nueva {codigo}: {texto}")
    db.session.commit()
    flash("Nota agregada.", "ok")
    return redirect(url_for("catalogos.notas"))


@bp.post("/notas/<int:nid>/estado")
@rol_requerido(*desde("supervisor"))
def nota_estado(nid: int):
    nota = db.get_or_404(NotaFija, nid)
    nota.activa = not nota.activa
    auditar("nota_fija", f"{nota.codigo} {'activa' if nota.activa else 'inactiva'}")
    db.session.commit()
    return redirect(url_for("catalogos.notas"))


# --------------------------------------------------------------------------- clientes
@bp.get("/clientes")
@rol_requerido(*desde("cajero"))
def clientes():
    q = (request.args.get("q") or "").strip()[:40]
    consulta = Cliente.query
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(
            db.or_(Cliente.nombre.ilike(patron), Cliente.ruc.ilike(patron))
        )
    lista = consulta.order_by(Cliente.activo.desc(), Cliente.nombre).limit(200).all()
    usado = {
        c.id: caja.credito_usado(c)
        for c in lista
        if c.tipo_pago in ("credito", "autorizado")
    }
    return render_template(
        "catalogos/clientes.html",
        clientes=lista,
        q=q,
        usado=usado,
        tipos=NOMBRE_TIPO,
        pagos=NOMBRE_PAGO,
        previo={},
    )


@bp.post("/clientes")
@rol_requerido(*desde("cajero"))
def cliente_nuevo():
    f = request.form
    try:
        tipo = f.get("tipo") if f.get("tipo") in TIPOS_CLIENTE else "juridico"
        if tipo == "consumidor_final":
            raise ReglaNegocioError("El consumidor final ya existe; no se crea otro.")
        ruc = (f.get("ruc") or "").strip().upper()
        if not _RUC.match(ruc):
            raise ReglaNegocioError(
                "Escribe un RUC, cédula o pasaporte válido (letras, números y guiones)."
            )
        dv = (f.get("dv") or "").strip()
        if tipo in ("natural", "juridico") and not _DV.match(dv):
            raise ReglaNegocioError(
                "El DV es obligatorio para contribuyentes (1 a 3 dígitos)."
            )
        nombre = " ".join((f.get("nombre") or "").split()).upper()[:120]
        if len(nombre) < 3:
            raise ReglaNegocioError("Escribe el nombre o la razón social.")
        correo = (f.get("correo") or "").strip()[:120]
        if correo and not _CORREO.match(correo):
            raise ReglaNegocioError("El correo no es válido.")
        pago = (
            f.get("tipo_pago")
            if f.get("tipo_pago") in TIPOS_PAGO_CLIENTE
            else "contado"
        )
        limite = validar_precio(
            f.get("limite") or "0", "límite de crédito", permitir_cero=True
        )
        if pago in ("credito", "autorizado") and limite <= 0:
            raise ReglaNegocioError("Indica el límite de crédito.")
        if limite > 0 and not current_user.puede("supervisor"):
            raise ReglaNegocioError("Solo un supervisor o superior asigna crédito.")
        if Cliente.query.filter_by(ruc=ruc).first():
            raise ReglaNegocioError("Ya existe un cliente con ese RUC o cédula.")
        cliente = Cliente(
            ruc=ruc,
            dv=dv or None,
            tipo=tipo,
            nombre=nombre,
            correo=correo or None,
            tipo_pago=pago,
            limite_credito=(
                limite if pago in ("credito", "autorizado") else Decimal("0.00")
            ),
        )
        db.session.add(cliente)
        auditar("cliente_nuevo", f"{ruc} {nombre} ({pago})")
        db.session.commit()
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
        lista = Cliente.query.order_by(Cliente.nombre).limit(200).all()
        usado = {
            c.id: caja.credito_usado(c)
            for c in lista
            if c.tipo_pago in ("credito", "autorizado")
        }
        return (
            render_template(
                "catalogos/clientes.html",
                clientes=lista,
                q="",
                usado=usado,
                tipos=NOMBRE_TIPO,
                pagos=NOMBRE_PAGO,
                previo=f,
            ),
            422,
        )
    flash(f"Cliente {cliente.nombre} creado.", "ok")
    volver = request.form.get("cuenta", type=int)
    if volver:
        return redirect(url_for("salon.cobrar", cuenta_id=volver, q=ruc))
    return redirect(url_for("catalogos.clientes", q=ruc))
