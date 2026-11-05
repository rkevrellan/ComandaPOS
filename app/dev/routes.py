"""Consola del programador (superusuario): estado del sistema y auditoría verificable."""

from __future__ import annotations

import os

from flask import Blueprint, current_app, render_template
from sqlalchemy import func, inspect, select, table

from ..config import NOMBRE_ROL
from ..extensions import db
from ..models import Auditoria, Operador, Secuencia
from ..seguridad import EVENTOS, rol_requerido
from ..services import auditoria

bp = Blueprint("dev", __name__)


@bp.get("/")
@rol_requerido("programador")
def inicio():
    motor = db.engine
    tablas = []
    for nombre in sorted(inspect(motor).get_table_names()):
        total = db.session.execute(
            select(func.count()).select_from(table(nombre))  # el nombre se cita, no se concatena
        ).scalar()
        tablas.append((nombre, total))
    ruta_bd = motor.url.database or ""
    # En modo WAL los cambios recientes viven en «-wal»: se suman para dar el tamaño real.
    tamano = sum(
        os.path.getsize(ruta_bd + sufijo)
        for sufijo in ("", "-wal", "-shm")
        if ruta_bd and os.path.exists(ruta_bd + sufijo)
    )
    por_rol = dict(
        db.session.query(Operador.rol, func.count()).group_by(Operador.rol).all()
    )
    return render_template(
        "dev/inicio.html",
        tablas=tablas,
        tamano=tamano,
        datos=current_app.config["DATOS"],
        motor=motor.url.get_backend_name(),
        secuencias=Secuencia.query.all(),
        eventos=sorted(EVENTOS.items()),
        por_rol=por_rol,
        roles=NOMBRE_ROL,
        verificacion=auditoria.verificar(),
    )


@bp.get("/auditoria")
@rol_requerido("programador")
def bitacora():
    registros = Auditoria.query.order_by(Auditoria.id.desc()).limit(300).all()
    return render_template(
        "dev/auditoria.html", registros=registros, verificacion=auditoria.verificar()
    )
