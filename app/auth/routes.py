"""Control de acceso (A07).

- Límite por terminal y por usuario+terminal revisado ANTES de calcular el hash.
- Mismo mensaje y mismo trabajo (un hash scrypt) exista o no el usuario, esté o no activo.
- La sesión se reinicia al entrar (evita fijación de sesión) y queda auditada.
"""

from __future__ import annotations

import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash

from ..config import ROLES_CON_PIN
from ..extensions import db
from ..models import Operador, ahora
from ..seguridad import (
    ACCESO,
    ACCESO_TERMINAL,
    CLAVE_DEMO,
    CUENTAS_DEMO,
    DOS_PASOS,
    PIN_DEMO,
    con_sesion,
    destino_seguro,
    evento_seguridad,
    hash_relleno,
    ip_cliente,
    publica,
)
from ..services import dos_pasos
from ..services.auditoria import auditar, auditar_ya

bp = Blueprint("auth", __name__)


def _plantilla(codigo: int = 200, usuario: str = ""):
    demo = None
    if current_app.config["DEMO"]:
        demo = [
            (u, n, r, PIN_DEMO if r in ROLES_CON_PIN else CLAVE_DEMO)
            for u, n, r in CUENTAS_DEMO
        ]
    return render_template("auth/acceso.html", usuario=usuario, demo=demo), codigo


@bp.route("/acceso", methods=["GET", "POST"])
@publica
def acceso():
    if current_user.is_authenticated:
        return redirect(url_for("mesas.control"))
    if request.method == "GET":
        return _plantilla()

    usuario = (request.form.get("usuario") or "").strip().lower()[:30]
    clave = (request.form.get("clave") or "")[:128]
    ip = ip_cliente()
    llave = f"{usuario}|{ip}"

    espera = max(ACCESO_TERMINAL.espera(ip), ACCESO.espera(llave))
    if espera:
        evento_seguridad("acceso_bloqueado", f"usuario={usuario}")
        minutos = max(1, round(espera / 60))
        flash(
            f"Demasiados intentos. Espera {minutos} min o pide ayuda a un supervisor.",
            "error",
        )
        return _plantilla(429, usuario)

    operador = Operador.query.filter_by(usuario=usuario).first() if usuario else None
    if operador is not None:
        valida = operador.verificar_clave(clave)
    else:
        check_password_hash(hash_relleno(), clave or "x")
        valida = False

    if not (valida and operador.activo):
        ACCESO.fallo(llave)
        ACCESO_TERMINAL.fallo(ip)
        auditar_ya(
            "acceso_fallido",
            f"usuario={usuario or '(vacío)'}",
            operador=operador if operador is not None else None,
        )
        flash("Usuario o clave incorrectos.", "error")
        return _plantilla(401, usuario)

    ACCESO.limpiar(llave)
    siguiente = destino_seguro(request.args.get("siguiente"), url_for("mesas.control"))
    if operador.tiene_2fa:
        # Paso 2: la sesión todavía NO está iniciada; solo se recuerda quién va, por 5 minutos.
        session.clear()
        session["2fa"] = {
            "id": operador.id,
            "v": operador.version_sesion,
            "t": time.time(),
            "siguiente": siguiente,
        }
        return redirect(url_for("auth.segundo_paso"))
    return _iniciar(operador, siguiente)


def _iniciar(operador: Operador, siguiente: str):
    session.clear()  # sesión nueva: evita fijación de sesión
    login_user(operador, remember=False)
    session["ini"] = session["ult"] = time.time()
    operador.ultimo_acceso = ahora()
    auditar("acceso", f"{operador.usuario} ({operador.rol})", operador=operador)
    db.session.commit()
    return redirect(siguiente)


@bp.route("/acceso/verificacion", methods=["GET", "POST"])
@publica
def segundo_paso():
    pendiente = session.get("2fa")
    operador = (
        db.session.get(Operador, pendiente["id"])
        if isinstance(pendiente, dict)
        else None
    )
    if (
        operador is None
        or not operador.activo
        or operador.version_sesion != pendiente.get("v")
        or time.time() - pendiente.get("t", 0) > 300
    ):
        session.pop("2fa", None)
        flash("Vuelve a escribir tu usuario y clave.", "info")
        return redirect(url_for("auth.acceso"))
    if request.method == "POST":
        llave = f"2fa|{operador.id}"
        if DOS_PASOS.espera(llave):
            evento_seguridad("2fa_bloqueado", operador.usuario)
            flash("Demasiados códigos incorrectos. Espera unos minutos.", "error")
            return render_template("auth/verificacion.html", operador=operador), 429
        codigo = request.form.get("codigo") or ""
        valido = dos_pasos.verificar(
            operador, codigo
        ) or dos_pasos.usar_codigo_recuperacion(operador, codigo)
        if not valido:
            DOS_PASOS.fallo(llave)
            auditar_ya("2fa_fallido", operador.usuario, operador=operador)
            flash("Código incorrecto.", "error")
            return render_template("auth/verificacion.html", operador=operador), 401
        DOS_PASOS.limpiar(llave)
        return _iniciar(
            operador, pendiente.get("siguiente") or url_for("mesas.control")
        )
    return render_template("auth/verificacion.html", operador=operador)


@bp.post("/salir")
@con_sesion
def salir():
    auditar("salida", current_user.usuario)
    db.session.commit()
    logout_user()
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("auth.acceso"))
