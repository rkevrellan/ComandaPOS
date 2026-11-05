"""Mi cuenta: cambiar la propia clave o PIN y la verificación en dos pasos (A07)."""

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
from flask_login import current_user, login_user

from ..extensions import db
from ..seguridad import (
    DOS_PASOS,
    REAUTENTICAR,
    con_sesion,
    evento_seguridad,
    validar_credencial,
)
from ..services import dos_pasos
from ..services.auditoria import auditar

bp = Blueprint("cuenta", __name__)

ROLES_2FA_OBLIGATORIA = ("administrador", "programador")


def exige_2fa(operador) -> bool:
    return not current_app.config["DEMO"] and operador.rol in ROLES_2FA_OBLIGATORIA


def _reautenticar(clave: str) -> bool:
    llave = f"reauth|{current_user.id}"
    if REAUTENTICAR.tomar(llave):  # H-16: revisa y cuenta en un paso
        evento_seguridad("reautenticacion_bloqueada", current_user.usuario)
        flash("Demasiados intentos. Espera unos minutos.", "error")
        return False
    if not current_user.verificar_clave(clave or ""):
        flash("La clave actual no es correcta.", "error")
        return False
    REAUTENTICAR.limpiar(llave)
    return True


def _codigo_valido(codigo: str, secreto: str | None = None) -> bool:
    """H-14: código de 6 dígitos con el mismo límite de intentos que el acceso (DOS_PASOS)."""
    llave = f"2fa|{current_user.id}"
    if DOS_PASOS.tomar(llave):
        evento_seguridad("2fa_bloqueado", current_user.usuario)
        flash("Demasiados códigos incorrectos. Espera unos minutos.", "error")
        return False
    if not dos_pasos.verificar(current_user, codigo, secreto):
        flash("Código incorrecto.", "error")
        return False
    DOS_PASOS.limpiar(llave)
    return True


def _mantener_sesion() -> None:
    """La versión de sesión subió (cierra las demás terminales); esta terminal sigue dentro."""
    login_user(current_user._get_current_object(), remember=False)
    session["ini"] = session["ult"] = time.time()


@bp.get("/cuenta")
@con_sesion
def inicio():
    return render_template(
        "cuenta/inicio.html",
        obligatoria=exige_2fa(current_user),
        restantes=dos_pasos.restantes(current_user),
    )


@bp.post("/cuenta/clave")
@con_sesion
def cambiar_clave():
    nueva = request.form.get("nueva") or ""
    if not _reautenticar(request.form.get("actual")):
        return redirect(url_for("cuenta.inicio"))
    errores = validar_credencial(current_user, nueva)
    if nueva != (request.form.get("repetir") or ""):
        errores.append("La confirmación no coincide.")
    if current_user.verificar_clave(nueva):
        errores.append("La nueva debe ser distinta de la actual.")
    if errores:
        for e in errores:
            flash(e, "error")
        return redirect(url_for("cuenta.inicio"))
    current_user.fijar_clave(nueva)
    auditar(
        "clave_cambiada",
        f"{current_user.usuario} cambió su {'PIN' if current_user.usa_pin else 'contraseña'}",
    )
    db.session.commit()
    _mantener_sesion()
    flash("Listo. Se cerró tu sesión en las demás terminales.", "ok")
    return redirect(url_for("cuenta.inicio"))


@bp.post("/cuenta/salir-de-todo")
@con_sesion
def salir_de_todo():
    current_user.version_sesion += 1
    auditar("sesiones_cerradas", current_user.usuario)
    db.session.commit()
    _mantener_sesion()
    flash("Se cerró tu sesión en todas las demás terminales.", "ok")
    return redirect(url_for("cuenta.inicio"))


@bp.route("/cuenta/2fa", methods=["GET", "POST"])
@con_sesion
def activar_2fa():
    """GET: muestra el QR (crea el secreto pendiente en el servidor). POST: confirma con un código."""
    if current_user.tiene_2fa:
        return redirect(url_for("cuenta.inicio"))
    if request.method == "POST":
        # H-14: con una sesión robada no basta: hace falta también la contraseña o PIN actual.
        if not current_user.totp_pendiente or not _reautenticar(request.form.get("clave")):
            return redirect(url_for("cuenta.activar_2fa"))
        if not _codigo_valido(request.form.get("codigo"), current_user.totp_pendiente):
            flash("Revisa la hora del teléfono e inténtalo otra vez.", "info")
            return redirect(url_for("cuenta.activar_2fa"))
        current_user.totp_secreto, current_user.totp_pendiente = (
            current_user.totp_pendiente,
            None,
        )
        codigos, hashes = dos_pasos.nuevos_codigos_recuperacion()
        current_user.codigos_recuperacion = hashes
        auditar("2fa_activada", current_user.usuario)
        db.session.commit()
        return render_template("cuenta/codigos.html", codigos=codigos)
    if not current_user.totp_pendiente:
        current_user.totp_pendiente = dos_pasos.nuevo_secreto()
        db.session.commit()
    uri = dos_pasos.uri(current_user, current_user.totp_pendiente)
    return render_template(
        "cuenta/activar_2fa.html",
        secreto=current_user.totp_pendiente,
        qr=dos_pasos.qr_svg(uri),
    )


@bp.post("/cuenta/2fa/codigos")
@con_sesion
def nuevos_codigos():
    if (
        not current_user.tiene_2fa
        or not _reautenticar(request.form.get("clave"))
        or not _codigo_valido(request.form.get("codigo"))
    ):
        return redirect(url_for("cuenta.inicio"))
    codigos, hashes = dos_pasos.nuevos_codigos_recuperacion()
    current_user.codigos_recuperacion = hashes
    auditar("2fa_codigos_nuevos", current_user.usuario)
    db.session.commit()
    return render_template("cuenta/codigos.html", codigos=codigos)


@bp.post("/cuenta/2fa/quitar")
@con_sesion
def quitar_2fa():
    if exige_2fa(current_user):
        flash("Tu nivel exige verificación en dos pasos: no se puede quitar.", "error")
        return redirect(url_for("cuenta.inicio"))
    if not _reautenticar(request.form.get("clave")) or not _codigo_valido(
        request.form.get("codigo")
    ):
        return redirect(url_for("cuenta.inicio"))
    current_user.totp_secreto = current_user.codigos_recuperacion = None
    auditar("2fa_desactivada", current_user.usuario)
    db.session.commit()
    flash("Verificación en dos pasos desactivada.", "ok")
    return redirect(url_for("cuenta.inicio"))
