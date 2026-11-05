"""Administración de archivos: catálogos, receta, inventario, operadores, configuración e impresoras."""

from __future__ import annotations

import ipaddress
import re

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..config import NOMBRE_ROL, ROLES
from ..extensions import db
from ..models import (
    Impresora,
    Insumo,
    MovimientoInventario,
    Operador,
    Producto,
    TrabajoImpresion,
)
from ..seguridad import desde, rol_requerido, validar_credencial
from ..services import configuracion, fiscal, impresion, inventario
from ..services.auditoria import auditar
from ..services.calculos import ReglaNegocioError
from .catalogos import CATALOGOS, NOMBRE_CONDICION, aplicar, lista

bp = Blueprint("admin", __name__, url_prefix="/admin")
ADMIN = desde("administrador")
_USUARIO = re.compile(r"^[a-z0-9._-]{3,30}$")


def _catalogo(clave: str):
    cat = CATALOGOS.get(clave)
    if cat is None:
        abort(404)
    return cat


# --------------------------------------------------------------------------- inicio
@bp.get("/")
@rol_requerido(*ADMIN)
def inicio():
    bajos = Insumo.query.filter(Insumo.activo.is_(True)).all()
    return render_template(
        "admin/inicio.html",
        catalogos=CATALOGOS,
        insumos_bajos=[i for i in bajos if i.bajo],
        pendientes_impresion=TrabajoImpresion.query.filter_by(estado="error").count(),
        folios=fiscal.folios(),
    )


# --------------------------------------------------------------------------- catálogos genéricos
@bp.get("/c/<clave>")
@rol_requerido(*ADMIN)
def catalogo(clave: str):
    cat = _catalogo(clave)
    q = (request.args.get("q") or "").strip()[:40]
    return render_template(
        "admin/lista.html",
        cat=cat,
        registros=lista(cat, q),
        q=q,
        condiciones=NOMBRE_CONDICION,
    )


@bp.route("/c/<clave>/nuevo", methods=["GET", "POST"])
@rol_requerido(*ADMIN)
def nuevo(clave: str):
    cat = _catalogo(clave)
    obj = cat.modelo()
    for campo in cat.campos:  # valores por defecto razonables
        if campo.tipo == "si_no" and campo.nombre in (
            "activa",
            "activo",
            "aplica_jubilado",
        ):
            setattr(obj, campo.nombre, True)
    if request.method == "POST":
        return _guardar(cat, obj, nuevo=True)
    return render_template("admin/form.html", cat=cat, obj=obj, previo=None)


@bp.route("/c/<clave>/<int:oid>", methods=["GET", "POST"])
@rol_requerido(*ADMIN)
def editar(clave: str, oid: int):
    cat = _catalogo(clave)
    obj = db.get_or_404(cat.modelo, oid)
    if request.method == "POST":
        return _guardar(cat, obj, nuevo=False)
    extra = {}
    if clave == "productos":
        extra["insumos"] = (
            Insumo.query.filter_by(activo=True).order_by(Insumo.nombre).all()
        )
    return render_template("admin/form.html", cat=cat, obj=obj, previo=None, **extra)


def _guardar(cat, obj, nuevo: bool):
    try:
        cambios = aplicar(cat, obj, request.form)
        if nuevo:
            db.session.add(obj)
        db.session.flush()
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
        return (
            render_template("admin/form.html", cat=cat, obj=obj, previo=request.form),
            422,
        )
    except IntegrityError:
        db.session.rollback()
        flash("Ya existe un registro con ese código, número o nombre.", "error")
        return (
            render_template("admin/form.html", cat=cat, obj=obj, previo=request.form),
            422,
        )
    nombre = cat.valor(obj, cat.columnas[1][0]) if len(cat.columnas) > 1 else obj.id
    if nuevo:
        auditar("catalogo_nuevo", f"{cat.clave}: {nombre}")
    elif cambios:
        auditar(
            "catalogo_cambio", f"{cat.clave} {obj.id} ({nombre}): " + "; ".join(cambios)
        )
    db.session.commit()
    fem = cat.nuevo == "Nueva"
    hecho = ("creada" if fem else "creado") if nuevo else ("guardada" if fem else "guardado")
    flash(f"{cat.singular.capitalize()} {hecho}.", "ok")
    return redirect(url_for("admin.editar", clave=cat.clave, oid=obj.id))


@bp.post("/c/<clave>/<int:oid>/estado")
@rol_requerido(*ADMIN)
def estado(clave: str, oid: int):
    cat = _catalogo(clave)
    if not cat.activo:
        abort(404)
    obj = db.get_or_404(cat.modelo, oid)
    setattr(obj, cat.activo, not getattr(obj, cat.activo))
    auditar(
        "catalogo_estado",
        f"{cat.clave} {oid}: {'activo' if getattr(obj, cat.activo) else 'inactivo'}",
    )
    db.session.commit()
    return redirect(url_for("admin.catalogo", clave=clave))


@bp.post("/productos/<int:pid>/receta")
@rol_requerido(*ADMIN)
def receta(pid: int):
    producto = db.get_or_404(Producto, pid)
    filas = list(zip(request.form.getlist("insumo"), request.form.getlist("cantidad")))
    try:
        inventario.fijar_receta(producto, filas)
        db.session.commit()
        flash("Receta guardada.", "ok")
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
    return redirect(url_for("admin.editar", clave="productos", oid=pid) + "#receta")


# --------------------------------------------------------------------------- inventario
@bp.get("/inventario")
@rol_requerido(*ADMIN)
def inventario_lista():
    insumos = Insumo.query.order_by(Insumo.activo.desc(), Insumo.nombre).all()
    movimientos = (
        MovimientoInventario.query.order_by(MovimientoInventario.id.desc())
        .limit(40)
        .all()
    )
    return render_template(
        "admin/inventario.html", insumos=insumos, movimientos=movimientos
    )


@bp.post("/inventario/<int:iid>/<any(entrada, ajuste):accion>")
@rol_requerido(*ADMIN)
def inventario_movimiento(iid: int, accion: str):
    insumo = db.get_or_404(Insumo, iid)
    try:
        if accion == "entrada":
            inventario.entrada(
                insumo,
                request.form.get("cantidad"),
                request.form.get("referencia"),
                current_user,
            )
        else:
            inventario.ajustar(
                insumo,
                request.form.get("existencia"),
                request.form.get("motivo"),
                current_user,
            )
        db.session.commit()
        flash(
            f"{insumo.nombre}: existencia {insumo.existencia.normalize()} {insumo.unidad}.",
            "ok",
        )
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
    return redirect(url_for("admin.inventario_lista"))


# --------------------------------------------------------------------------- operadores
def _puede_tocar(objetivo_rol: str) -> bool:
    """Solo el programador crea o modifica cuentas de programador."""
    return objetivo_rol != "programador" or current_user.rol == "programador"


def _quedan_admins(excepto: Operador) -> bool:
    return (
        Operador.query.filter(
            Operador.activo.is_(True),
            Operador.rol.in_(ADMIN),
            Operador.id != excepto.id,
        ).count()
        > 0
    )


@bp.get("/operadores")
@rol_requerido(*ADMIN)
def operadores():
    lista_ops = Operador.query.order_by(Operador.activo.desc(), Operador.codigo).all()
    return render_template(
        "admin/operadores.html", operadores=lista_ops, roles=NOMBRE_ROL
    )


@bp.route("/operadores/nuevo", methods=["GET", "POST"])
@rol_requerido(*ADMIN)
def operador_nuevo():
    if request.method == "POST":
        f = request.form
        try:
            rol = f.get("rol") if f.get("rol") in ROLES else "operador"
            if not _puede_tocar(rol):
                raise ReglaNegocioError(
                    "Solo el programador crea cuentas de programador."
                )
            usuario = (f.get("usuario") or "").strip().lower()
            if not _USUARIO.match(usuario):
                raise ReglaNegocioError(
                    "El usuario: 3 a 30 letras minúsculas, números, punto, guion o guion bajo."
                )
            if Operador.query.filter_by(usuario=usuario).first():
                raise ReglaNegocioError("Ese usuario ya existe.")
            nombre = " ".join((f.get("nombre") or "").split())[:80]
            if len(nombre) < 3:
                raise ReglaNegocioError("Escribe el nombre completo.")
            op = Operador(
                codigo=(db.session.query(func.max(Operador.codigo)).scalar() or 0) + 1,
                nombre=nombre,
                cargo=" ".join((f.get("cargo") or "").split())[:40] or NOMBRE_ROL[rol],
                usuario=usuario,
                rol=rol,
            )
            errores = validar_credencial(op, f.get("credencial") or "")
            if errores:
                raise ReglaNegocioError(" ".join(errores))
            op.fijar_clave(f.get("credencial"))
            db.session.add(op)
            auditar("operador_nuevo", f"{usuario} ({rol})")
            db.session.commit()
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return (
                render_template(
                    "admin/operador_form.html",
                    op=None,
                    roles=_roles_asignables(),
                    previo=f,
                ),
                422,
            )
        flash(f"Operador {op.usuario} creado.", "ok")
        return redirect(url_for("admin.operadores"))
    return render_template(
        "admin/operador_form.html", op=None, roles=_roles_asignables(), previo={}
    )


def _roles_asignables() -> dict:
    return {k: v for k, v in NOMBRE_ROL.items() if _puede_tocar(k)}


@bp.route("/operadores/<int:oid>", methods=["GET", "POST"])
@rol_requerido(*ADMIN)
def operador_editar(oid: int):
    op = db.get_or_404(Operador, oid)
    if not _puede_tocar(op.rol):
        abort(403)
    if request.method == "POST":
        f = request.form
        try:
            rol = f.get("rol") if f.get("rol") in ROLES else op.rol
            activo = f.get("activo") == "1"
            if not _puede_tocar(rol):
                raise ReglaNegocioError("Solo el programador asigna ese nivel.")
            if op.id == current_user.id and (rol != op.rol or not activo):
                raise ReglaNegocioError(
                    "No puedes cambiar tu propio nivel ni desactivarte."
                )
            if (
                op.rol in ADMIN
                and (rol not in ADMIN or not activo)
                and not _quedan_admins(op)
            ):
                raise ReglaNegocioError("Debe quedar al menos un administrador activo.")
            cambios = []
            nombre = " ".join((f.get("nombre") or "").split())[:80] or op.nombre
            cargo = " ".join((f.get("cargo") or "").split())[:40] or op.cargo
            for campo, valor in (
                ("nombre", nombre),
                ("cargo", cargo),
                ("rol", rol),
                ("activo", activo),
            ):
                if getattr(op, campo) != valor:
                    cambios.append(f"{campo}: {getattr(op, campo)} → {valor}")
                    setattr(op, campo, valor)
            if any(c.startswith(("rol", "activo")) for c in cambios):
                op.version_sesion += (
                    1  # el cambio de nivel o la baja cierran sus sesiones abiertas
                )
            if cambios:
                auditar("operador_cambio", f"{op.usuario}: " + "; ".join(cambios))
            db.session.commit()
            flash("Operador guardado.", "ok")
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
        return redirect(url_for("admin.operador_editar", oid=oid))
    return render_template(
        "admin/operador_form.html", op=op, roles=_roles_asignables(), previo={}
    )


@bp.post("/operadores/<int:oid>/<any(credencial, sesiones, dos_pasos):accion>")
@rol_requerido(*ADMIN)
def operador_accion(oid: int, accion: str):
    op = db.get_or_404(Operador, oid)
    if not _puede_tocar(op.rol):
        abort(403)
    if accion == "credencial":
        nueva = request.form.get("credencial") or ""
        errores = validar_credencial(op, nueva)
        if errores:
            flash(" ".join(errores), "error")
            return redirect(url_for("admin.operador_editar", oid=oid))
        op.fijar_clave(nueva)
        auditar("clave_restablecida", f"{op.usuario} (por {current_user.usuario})")
        flash("Credencial restablecida; sus sesiones abiertas se cerraron.", "ok")
    elif accion == "sesiones":
        op.version_sesion += 1
        auditar("sesiones_cerradas", f"{op.usuario} (por {current_user.usuario})")
        flash("Se cerraron sus sesiones.", "ok")
    else:
        op.totp_secreto = op.totp_pendiente = op.codigos_recuperacion = None
        op.version_sesion += 1
        auditar("2fa_restablecida", f"{op.usuario} (por {current_user.usuario})")
        flash(
            "Verificación en dos pasos restablecida: deberá activarla de nuevo.", "ok"
        )
    db.session.commit()
    if op.id == current_user.id:
        return redirect(url_for("auth.acceso"))
    return redirect(url_for("admin.operador_editar", oid=oid))


# --------------------------------------------------------------------------- configuración
def _validar_config(clave: str, tipo: str, valor: str) -> str:
    valor = " ".join((valor or "").split())
    if tipo == "si_no":
        return "1" if valor in ("1", "on") else "0"
    if tipo in ("porcentaje", "entero"):
        if (
            not valor.isdigit()
            or (tipo == "porcentaje" and int(valor) > 100)
            or int(valor) > 10**7
        ):
            raise ReglaNegocioError(f"«{clave}» debe ser un número entero válido.")
        return str(int(valor))
    if tipo == "url":
        if valor and not fiscal.url_pac_valida(valor):
            raise ReglaNegocioError("La URL del PAC debe ser https://…")
        return valor
    if tipo == "proveedor":
        if valor not in ("simulado", "http", "ninguno"):
            raise ReglaNegocioError("Proveedor fiscal no válido.")
        if valor == "simulado" and not current_app.config["DEMO"]:
            raise ReglaNegocioError("El PAC simulado solo existe en la demostración.")
        return valor
    if tipo == "establecimiento":
        if valor not in ("restaurante", "franquicia", "fonda"):
            raise ReglaNegocioError("Tipo de establecimiento no válido.")
        return valor
    if tipo == "red":
        partes = [p.strip() for p in valor.split(",") if p.strip()]
        for p in partes:
            try:
                ipaddress.ip_network(p, strict=False)
            except ValueError:
                raise ReglaNegocioError(
                    f"«{p}» no es una IP ni una red válida (ej. 192.168.1.0/24)."
                ) from None
        return ", ".join(partes)
    if len(valor) > 200:
        raise ReglaNegocioError(f"«{clave}» es demasiado largo.")
    return valor


@bp.route("/configuracion", methods=["GET", "POST"])
@rol_requerido(*ADMIN)
def config():
    if request.method == "POST":
        try:
            cambios = []
            for _grupo, campos in configuracion.EDITABLES:
                for clave, etiqueta, tipo in campos:
                    nuevo = _validar_config(etiqueta, tipo, request.form.get(clave, ""))
                    anterior = configuracion.obtener(clave)
                    if nuevo != anterior:
                        configuracion.fijar(clave, nuevo)
                        cambios.append(f"{clave}: {anterior} → {nuevo}")
            if cambios:
                auditar("configuracion", "; ".join(cambios)[:300])
            db.session.commit()
            flash("Configuración guardada." if cambios else "No hubo cambios.", "ok")
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
        return redirect(url_for("admin.config"))
    valores = {
        clave: configuracion.obtener(clave)
        for _g, campos in configuracion.EDITABLES
        for clave, _e, _t in campos
    }
    try:
        import keyring  # noqa: F401

        almacen = True
    except ImportError:
        almacen = False
    return render_template(
        "admin/config.html",
        grupos=configuracion.EDITABLES,
        valores=valores,
        almacen=almacen,
        tiene_token=bool(fiscal._token_pac()),
    )


@bp.post("/configuracion/pac-token")
@rol_requerido(*ADMIN)
def pac_token():
    token = (request.form.get("token") or "").strip()
    if not 8 <= len(token) <= 4000:
        flash("El token no es válido.", "error")
        return redirect(url_for("admin.config"))
    try:
        import keyring

        keyring.set_password("ComandaPOS", "pac", token)
    except Exception:
        flash(
            "No hay almacén seguro disponible: define la variable de entorno COMANDAPOS_PAC_TOKEN.",
            "error",
        )
        return redirect(url_for("admin.config"))
    auditar("pac_token", "credencial del PAC actualizada (no se registra su valor)")
    db.session.commit()
    flash("Credencial del PAC guardada en el almacén seguro del sistema.", "ok")
    return redirect(url_for("admin.config"))


# --------------------------------------------------------------------------- impresoras
@bp.get("/impresiones")
@rol_requerido(*ADMIN)
def impresiones():
    trabajos = (
        TrabajoImpresion.query.order_by(TrabajoImpresion.id.desc()).limit(40).all()
    )
    return render_template(
        "admin/impresiones.html",
        trabajos=trabajos,
        vista=impresion.vista_previa,
        impresoras=Impresora.query.order_by(Impresora.nombre).all(),
    )


@bp.post("/impresoras/<int:iid>/prueba")
@rol_requerido(*ADMIN)
def prueba_impresora(iid: int):
    imp = db.get_or_404(Impresora, iid)
    t = impresion.Ticket(imp.columnas)
    t.linea("PRUEBA DE IMPRESION", negrita=True, doble=True, centro=True)
    t.linea(f"Impresora: {imp.nombre}")
    t.linea("Acentos: á é í ó ú ñ Ñ ¿? ¡!")
    t.raya()
    impresion.encolar(imp, f"Prueba · {imp.nombre}", t.bytes())
    db.session.commit()
    impresos, errores = impresion.procesar_pendientes()
    flash(
        (
            "Página de prueba enviada."
            if not errores
            else "La impresora no respondió; quedó en la cola."
        ),
        "ok" if not errores else "error",
    )
    return redirect(url_for("admin.impresiones"))
