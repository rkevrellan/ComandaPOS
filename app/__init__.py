"""ComandaPOS — punto de venta para restaurantes de Panamá (monolito Flask).

`create_app()` arma la aplicación: configuración, base de datos, sesión, CSRF, cabeceras de
seguridad, control de inactividad por rol, sellado de la auditoría y manejo de errores.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from datetime import timedelta
from decimal import Decimal
from logging.handlers import RotatingFileHandler

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, logout_user
from markupsafe import Markup
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .config import (
    INACTIVIDAD_SEG,
    LEMA,
    NOMBRE,
    NOMBRE_ROL,
    SESION_MAXIMA_H,
    VERSION,
    carpeta_datos,
    modo_demo,
)
from .extensions import db, login_manager
from .services.calculos import ReglaNegocioError

METODOS_CON_EFECTO = ("POST", "PUT", "PATCH", "DELETE")

#: Sin JavaScript en línea ni recursos externos (A03/A05). Todo vive en /static.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


def _csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def _clave_secreta(datos: str) -> str:
    """COMANDAPOS_SECRET o una clave aleatoria por instalación (nunca fija en el código)."""
    if os.environ.get("COMANDAPOS_SECRET"):
        return os.environ["COMANDAPOS_SECRET"]
    ruta = os.path.join(datos, "secret_key")
    if not os.path.exists(ruta):
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    with open(ruta, encoding="utf-8") as f:
        return f.read().strip()


@event.listens_for(Engine, "connect")
def _pragmas_sqlite(conexion, _registro):
    """Integridad referencial, escrituras concurrentes (WAL) y espera ante bloqueos."""
    if conexion.__class__.__module__.startswith("sqlite3"):
        cur = conexion.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=10000")
        try:
            cur.execute("PRAGMA journal_mode=WAL")
        except Exception:  # pragma: no cover - las bases en memoria no aceptan WAL
            pass
        cur.close()


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    config = dict(config or {})
    datos = config.pop("DATOS", None) or carpeta_datos(app.instance_path)
    os.makedirs(datos, exist_ok=True)
    https = os.environ.get("COMANDAPOS_HTTPS") == "1"

    app.config.update(
        DATOS=datos,
        SECRET_KEY=_clave_secreta(datos),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "COMANDAPOS_DB", "sqlite:///" + os.path.join(datos, "comandapos.db")
        ),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        DEMO=modo_demo(),
        CSRF_ENABLED=True,
        SESSION_COOKIE_NAME="__Host-comandapos" if https else "comandapos",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=https,
        REMEMBER_COOKIE_DURATION=timedelta(seconds=0),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESION_MAXIMA_H),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        INACTIVIDAD_SEG=dict(INACTIVIDAD_SEG),
        TEMPLATES_AUTO_RELOAD=False,
    )
    app.config.update(config)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.acceso"
    login_manager.login_message = "Entra con tu usuario para continuar."
    login_manager.login_message_category = "info"

    from .models import Operador

    @login_manager.user_loader
    def cargar(identificador: str):
        """«id:versión»: si la versión de sesión cambió (clave nueva, cerrar en todos lados), sale."""
        try:
            oid, version = (int(x) for x in str(identificador).split(":", 1))
        except ValueError:
            return None
        op = db.session.get(Operador, oid)
        if op is None or not op.activo or op.version_sesion != version:
            return None
        return op

    _configurar_bitacora(app)
    _registrar_blueprints(app)
    _peticiones(app)
    _errores(app)
    _plantillas(app)

    with app.app_context():
        db.create_all()
        from .services import auditoria, configuracion, secuencias

        secuencias.asegurar_secuencias()
        configuracion.asegurar_valores()
        auditoria.sellar_pendientes()
    return app


def _registrar_blueprints(app: Flask) -> None:
    from .auth.routes import bp as auth_bp
    from .caja.routes import bp as caja_bp
    from .catalogos.routes import bp as catalogos_bp
    from .cocina.routes import bp as cocina_bp
    from .dev.routes import bp as dev_bp
    from .mesas.routes import bp as mesas_bp
    from .salon.routes import bp as salon_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(mesas_bp)
    app.register_blueprint(salon_bp)
    app.register_blueprint(cocina_bp)
    app.register_blueprint(caja_bp)
    app.register_blueprint(catalogos_bp)
    app.register_blueprint(dev_bp, url_prefix="/dev")

    from .seguridad import publica

    @app.get("/salud")
    @publica
    def salud():
        return jsonify({"ok": True, "version": VERSION})


def _vigilar_sesion(app: Flask):
    """Bloqueo por inactividad según el rol y duración máxima (A07)."""
    if not current_user.is_authenticated:
        return None
    ahora = time.time()
    if "ini" not in session:
        session["ini"] = session["ult"] = ahora
        return None
    limite = app.config["INACTIVIDAD_SEG"].get(current_user.rol, 300)
    vencida = ahora - session.get("ult", ahora) > limite
    maxima = ahora - session.get("ini", ahora) > SESION_MAXIMA_H * 3600
    if vencida or maxima:
        from .services.auditoria import auditar_ya

        auditar_ya("sesion_expirada", "inactividad" if vencida else "duración máxima")
        logout_user()
        session.clear()
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Sesión bloqueada por inactividad.",
                        "acceso": True,
                    }
                ),
                401,
            )
        flash("La terminal se bloqueó por inactividad. Vuelve a entrar.", "info")
        return redirect(url_for("auth.acceso"))
    if not request.headers.get("X-Sondeo"):
        session["ult"] = ahora
    return None


def _peticiones(app: Flask) -> None:
    @app.before_request
    def antes():
        g.rid = secrets.token_hex(5)
        if request.path.startswith("/static/"):
            return None
        respuesta = _vigilar_sesion(app)
        if respuesta is not None:
            return respuesta
        if request.method in METODOS_CON_EFECTO and app.config.get("CSRF_ENABLED"):
            enviado = (
                request.form.get("csrf_token")
                or request.headers.get("X-CSRF-Token")
                or ""
            )
            esperado = session.get("_csrf", "")
            if (
                not enviado
                or not esperado
                or not hmac.compare_digest(enviado, esperado)
            ):
                from .seguridad import evento_seguridad

                evento_seguridad(
                    "csrf_rechazado", f"{request.method} {request.path[:120]}"
                )
                if request.path.startswith("/api/"):
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "La sesión expiró. Recarga la pantalla.",
                            }
                        ),
                        400,
                    )
                abort(400)
        return None

    @app.after_request
    def despues(resp):
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
        )
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        resp.headers["X-Request-ID"] = getattr(g, "rid", "-")
        resp.headers.pop("Server", None)
        if app.config.get("SESSION_COOKIE_SECURE"):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if not request.path.startswith("/static/"):
            # Pantallas con datos del negocio: que no queden en la caché del equipo.
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.teardown_request
    def sellar(_error):
        """Encadena la auditoría confirmada en esta petición (fuera de la transacción del negocio)."""
        if g.get("auditoria_pendiente"):
            from .services.auditoria import sellar_pendientes

            try:
                sellar_pendientes()
            except (
                Exception
            ):  # pragma: no cover - se vuelve a intentar en la próxima petición
                app.logger.exception("No se pudo sellar la auditoría")


def _errores(app: Flask) -> None:
    def pantalla(codigo: int, titulo: str, mensaje: str):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": mensaje}), codigo
        return (
            render_template(
                "error.html", codigo=codigo, titulo=titulo, mensaje=mensaje
            ),
            codigo,
        )

    @app.errorhandler(400)
    def e400(_e):
        return pantalla(
            400,
            "Solicitud no válida",
            "La pantalla estaba desactualizada. Vuelve a intentarlo.",
        )

    @app.errorhandler(403)
    def e403(_e):
        return pantalla(
            403,
            "Sin permiso",
            "Tu nivel de seguridad no permite esta acción. Pide ayuda a un supervisor.",
        )

    @app.errorhandler(404)
    def e404(_e):
        return pantalla(404, "No encontrado", "Esa pantalla no existe.")

    @app.errorhandler(405)
    def e405(_e):
        return pantalla(405, "Acción no permitida", "Esa acción no se puede hacer así.")

    @app.errorhandler(413)
    def e413(_e):
        return pantalla(
            413, "Archivo muy grande", "El archivo pasa del tamaño permitido."
        )

    @app.errorhandler(ReglaNegocioError)
    def e422(e):
        db.session.rollback()
        return pantalla(422, "No se puede hacer", str(e))

    @app.errorhandler(429)
    def e429(_e):
        return pantalla(
            429,
            "Demasiados intentos",
            "Espera unos minutos antes de volver a intentar.",
        )

    @app.errorhandler(500)
    def e500(e):
        db.session.rollback()
        app.logger.error("Error 500 [%s] en %s: %r", g.get("rid", "-"), request.path, e)
        return pantalla(
            500,
            "Algo salió mal",
            f"Avisa al administrador con la referencia {g.get('rid', '-')}.",
        )


def _plantillas(app: Flask) -> None:
    app.jinja_env.globals.update(
        NOMBRE=NOMBRE,
        VERSION=VERSION,
        LEMA=LEMA,
        NOMBRE_ROL=NOMBRE_ROL,
        csrf_token=_csrf_token,
        csrf_field=lambda: Markup(
            '<input type="hidden" name="csrf_token" value="{}">'.format(_csrf_token())
        ),
        # RN-05: clave de idempotencia por formulario (un doble toque no repite la acción).
        idem_field=lambda: Markup(
            '<input type="hidden" name="idem" value="{}">'.format(secrets.token_hex(16))
        ),
    )

    @app.context_processor
    def contexto():
        inactividad = 0
        turno = None
        if current_user.is_authenticated:
            inactividad = app.config["INACTIVIDAD_SEG"].get(current_user.rol, 300)
            from .services.caja import turno_abierto

            turno = turno_abierto()
        return {"DEMO": app.config["DEMO"], "INACTIVIDAD": inactividad, "TURNO": turno}

    @app.template_filter("dinero")
    def dinero(valor):
        valor = valor if isinstance(valor, Decimal) else Decimal(str(valor or 0))
        return f"{valor:,.2f}"

    @app.template_filter("fecha")
    def fecha(valor, fmt="%d/%m/%Y %I:%M %p"):
        """Las fechas se guardan en UTC; Panamá es UTC−5 todo el año (sin horario de verano)."""
        return (valor - timedelta(hours=5)).strftime(fmt) if valor else ""


def _configurar_bitacora(app: Flask) -> None:
    """Bitácora rotativa en la carpeta de datos (sin datos sensibles; ver services/auditoria)."""
    if app.config.get("TESTING"):
        return
    carpeta = os.path.join(app.config["DATOS"], "bitacoras")
    os.makedirs(carpeta, exist_ok=True)
    manejador = RotatingFileHandler(
        os.path.join(carpeta, "comandapos.log"),
        maxBytes=2_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    manejador.setLevel(logging.INFO)
    app.logger.addHandler(manejador)
    app.logger.setLevel(logging.INFO)
