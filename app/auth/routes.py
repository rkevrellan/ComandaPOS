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


def _es_este_equipo() -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address((ip_cliente() or "").split("%")[0]).is_loopback
    except ValueError:
        return False


def _plantilla(codigo: int = 200, usuario: str = ""):
    demo = None
    # H-03: las credenciales de prueba solo se muestran en el propio equipo, nunca en la red.
    if current_app.config["DEMO"] and _es_este_equipo():
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
    if Operador.query.first() is None:  # H-01: instalación nueva en producción
        return redirect(url_for("auth.primer_inicio"))
    if request.method == "GET":
        return _plantilla()

    usuario = (request.form.get("usuario") or "").strip().lower()[:30]
    clave = (request.form.get("clave") or "")[:128]
    ip = ip_cliente()
    llave = f"{usuario}|{ip}"

    # H-16: revisar y contar en un solo paso. H-24: en este mismo equipo (127.0.0.1) todos los
    # usuarios comparten IP, así que no se aplica el límite por terminal: un empleado que falla
    # no bloquea a los demás (el límite por usuario sigue).
    espera = ACCESO.tomar(llave)
    terminal_contada = False
    if not espera and not _es_este_equipo():
        espera = ACCESO_TERMINAL.tomar(ip)
        if espera:
            ACCESO.devolver(llave)
        else:
            terminal_contada = True
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
        # el intento ya quedó contado por tomar()
        auditar_ya(
            "acceso_fallido",
            f"usuario={usuario or '(vacío)'}",
            operador=operador if operador is not None else None,
        )
        flash("Usuario o clave incorrectos.", "error")
        return _plantilla(401, usuario)

    ACCESO.limpiar(llave)
    if terminal_contada:
        ACCESO_TERMINAL.devolver(ip)
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
        if DOS_PASOS.tomar(llave):
            evento_seguridad("2fa_bloqueado", operador.usuario)
            flash("Demasiados códigos incorrectos. Espera unos minutos.", "error")
            return render_template("auth/verificacion.html", operador=operador), 429
        codigo = request.form.get("codigo") or ""
        valido = dos_pasos.verificar(
            operador, codigo
        ) or dos_pasos.usar_codigo_recuperacion(operador, codigo)
        if not valido:
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


# --------------------------------------------------------------------------- primer arranque (H-01)
@bp.route("/primer-inicio", methods=["GET", "POST"])
@publica
def primer_inicio():
    """Instalación nueva: crea el primer administrador.

    Solo existe mientras la base no tiene operadores, y solo desde el propio equipo (127.0.0.1):
    nadie en la red puede adueñarse de una instalación recién hecha.
    """
    from ..seguridad import validar_clave

    if Operador.query.first() is not None:
        return redirect(url_for("auth.acceso"))
    if not _es_este_equipo():
        evento_seguridad("primer_inicio_remoto", ip_cliente())
        return (
            render_template("auth/primer_inicio.html", remoto=True, datos={}),
            403,
        )
    datos = {}
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip().lower()[:30]
        nombre = " ".join((request.form.get("nombre") or "").split())[:60]
        clave = request.form.get("clave") or ""
        datos = {"usuario": usuario, "nombre": nombre}
        errores = []
        import re

        if not re.fullmatch(r"[a-z][a-z0-9._-]{2,29}", usuario):
            errores.append(
                "El usuario va en minúsculas, de 3 a 30 letras o números (puede llevar . _ -)."
            )
        if len(nombre) < 3:
            errores.append("Escribe el nombre completo.")
        errores += validar_clave(clave, usuario, nombre)
        if clave != (request.form.get("repetir") or ""):
            errores.append("La confirmación no coincide.")
        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("auth/primer_inicio.html", datos=datos), 422
        op = Operador(
            codigo=1, nombre=nombre, cargo="Administración", usuario=usuario, rol="administrador"
        )
        op.fijar_clave(clave)
        db.session.add(op)
        if request.form.get("ejemplo") == "1" and not current_app.config["DEMO"]:
            from seed import crear_catalogo

            crear_catalogo(demo=False)
        auditar(
            "primer_inicio",
            f"administrador {usuario} creado"
            + (" con salas, mesas y menú de ejemplo" if request.form.get("ejemplo") == "1" else ""),
            operador=op,
        )
        db.session.commit()
        flash(
            "Listo. Entra con tu usuario: el sistema te pedirá activar la verificación en dos pasos.",
            "ok",
        )
        return redirect(url_for("auth.acceso"))
    return render_template("auth/primer_inicio.html", datos=datos)
