"""Salón: mesa, comanda (toma de pedidos), cuentas, anulaciones, pre-cuenta y cobro."""

from __future__ import annotations

from decimal import Decimal
from functools import wraps

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from ..extensions import db
from ..models import (
    FORMAS_PAGO,
    Acompanamiento,
    Cliente,
    Comanda,
    Cuenta,
    Documento,
    LineaPedido,
    Mesa,
    NotaCredito,
    NotaFija,
    Operador,
    Producto,
    Seccion,
)
from ..seguridad import con_sesion, desde, ip_cliente, rol_requerido
from ..services import caja, configuracion, fiscal, impresion, pdf, pedidos
from ..services.autorizacion import autorizar
from ..services.calculos import ReglaNegocioError

bp = Blueprint("salon", __name__)


# --------------------------------------------------------------------------- ayudas
def _comanda(cid: int) -> Comanda:
    comanda = db.get_or_404(Comanda, cid)
    if not pedidos.puede_operar(current_user, comanda):
        abort(403)  # A01: un mesero no opera comandas ajenas
    return comanda


def _linea(lid: int) -> LineaPedido:
    linea = db.get_or_404(LineaPedido, lid)
    _comanda(linea.cuenta.comanda_id)
    return linea


def _cuenta(cuenta_id: int) -> Cuenta:
    cuenta = db.get_or_404(Cuenta, cuenta_id)
    _comanda(cuenta.comanda_id)
    return cuenta


def _destino_error(kw: dict) -> str:
    """Adónde volver cuando una regla de negocio rechaza la acción."""
    cid = kw.get("cid")
    if cid is None and kw.get("lid") is not None:
        linea = db.session.get(LineaPedido, kw["lid"])
        if linea is not None:
            return url_for(
                "salon.comanda",
                cid=linea.cuenta.comanda_id,
                cuenta=linea.cuenta.numero,
                linea=linea.id,
            )
    if cid is None and kw.get("cuenta_id") is not None:
        cuenta = db.session.get(Cuenta, kw["cuenta_id"])
        if cuenta is not None:
            return url_for("salon.comanda", cid=cuenta.comanda_id, cuenta=cuenta.numero)
    if cid is not None:
        return url_for("salon.comanda", cid=cid)
    return url_for("mesas.control")


def _amable(vista):
    """Una regla de negocio rechazada se muestra como aviso y vuelve a la pantalla (sin error 422)."""

    @wraps(vista)
    def envoltura(**kw):
        try:
            return vista(**kw)
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(_destino_error(kw))

    return envoltura


def _a_comanda(comanda: Comanda, cuenta=None, linea=None, **extra):
    args = {"cid": comanda.id}
    if cuenta is not None:
        args["cuenta"] = cuenta.numero if hasattr(cuenta, "numero") else cuenta
    if linea is not None:
        args["linea"] = linea
    args.update(extra)
    return redirect(url_for("salon.comanda", **args))


def _autorizador(rol: str) -> Operador:
    return autorizar(
        rol,
        current_user,
        request.form.get("sup_usuario"),
        request.form.get("sup_clave"),
        ip_cliente(),
    )


# --------------------------------------------------------------------------- mesa
@bp.get("/mesas/<int:numero>")
@con_sesion
def mesa(numero: int):
    m = Mesa.query.filter_by(numero=numero).first_or_404()
    if m.estado in ("ocupada", "precuenta"):
        comanda = pedidos.comanda_abierta_de(m)
        if comanda is not None:
            if not pedidos.puede_operar(current_user, comanda):
                flash(
                    f"La mesa {numero} la atiende {comanda.mesero.nombre}. "
                    "Pide a un supervisor que te la pase («Otro mesero»).",
                    "error",
                )
                return redirect(url_for("mesas.control", sala=m.sala_id))
            return redirect(url_for("salon.comanda", cid=comanda.id))
    documentos = []
    if m.estado == "pagada":
        ultima = (
            Comanda.query.filter_by(mesa_id=m.id, estado="cerrada")
            .order_by(Comanda.cerrada_en.desc())
            .first()
        )
        if ultima is not None:
            documentos = (
                Documento.query.join(Cuenta)
                .filter(Cuenta.comanda_id == ultima.id)
                .all()
            )
    return render_template("salon/mesa.html", mesa=m, documentos=documentos)


@bp.post("/mesas/<int:numero>/abrir")
@con_sesion
@_amable
def abrir(numero: int):
    m = Mesa.query.filter_by(numero=numero).first_or_404()
    comanda = pedidos.abrir_mesa(m, current_user, request.form.get("puestos"))
    db.session.commit()
    return redirect(url_for("salon.comanda", cid=comanda.id))


@bp.post("/mesas/<int:numero>/liberar")
@con_sesion
@_amable
def liberar(numero: int):
    m = Mesa.query.filter_by(numero=numero).first_or_404()
    pedidos.liberar_mesa(m)
    db.session.commit()
    flash(f"Mesa {numero} disponible.", "ok")
    return redirect(url_for("mesas.control", sala=m.sala_id))


@bp.post("/mesas/<int:numero>/servicio")
@rol_requerido(*desde("supervisor"))
@_amable
def servicio(numero: int):
    m = Mesa.query.filter_by(numero=numero).first_or_404()
    pedidos.fuera_de_servicio(m, request.form.get("fuera") == "1")
    db.session.commit()
    return redirect(url_for("mesas.control", sala=m.sala_id))


@bp.post("/rapido")
@con_sesion
@_amable
def rapido():
    comanda = pedidos.abrir_rapida(current_user)
    db.session.commit()
    return redirect(url_for("salon.comanda", cid=comanda.id))


# --------------------------------------------------------------------------- comanda
@bp.get("/comanda/<int:cid>")
@con_sesion
def comanda(cid: int):
    c = _comanda(cid)
    cuenta = pedidos.cuenta_de(c, request.args.get("cuenta", 1))
    secciones = Seccion.query.filter_by(activa=True).order_by(Seccion.orden).all()
    seccion = None
    if request.args.get("seccion", "").isdigit():
        seccion = db.session.get(Seccion, int(request.args["seccion"]))
    seccion = seccion if seccion in secciones else (secciones[0] if secciones else None)
    productos = []
    if seccion is not None:
        productos = (
            Producto.query.filter(
                Producto.seccion_id == seccion.id, Producto.condicion != "inactivo"
            )
            .order_by(Producto.codigo)
            .all()
        )
    seleccion = None
    if request.args.get("linea", "").isdigit():
        candidata = db.session.get(LineaPedido, int(request.args["linea"]))
        if candidata is not None and candidata.cuenta_id == cuenta.id:
            seleccion = candidata
    return render_template(
        "salon/comanda.html",
        comanda=c,
        cuenta=cuenta,
        secciones=secciones,
        seccion=seccion,
        productos=productos,
        seleccion=seleccion,
        t=pedidos.totales(cuenta),
        total_mesa=pedidos.total_comanda(c),
        pendientes=sum(1 for cu in c.cuentas for ln in cu.lineas if ln.estado == "PED"),
        es_cajero=current_user.puede("cajero"),
    )


@bp.post("/comanda/<int:cid>/agregar")
@con_sesion
@_amable
def agregar(cid: int):
    c = _comanda(cid)
    cuenta = pedidos.cuenta_de(c, request.form.get("cuenta", 1))
    producto = db.get_or_404(Producto, request.form.get("producto", type=int) or 0)
    acomp = None
    if request.form.get("acompanamiento", "").isdigit():
        acomp = db.get_or_404(Acompanamiento, int(request.form["acompanamiento"]))
    if pedidos.tomar_idempotencia(request.form.get("idem"), "agregar"):
        linea = pedidos.agregar(cuenta, producto, current_user, 1, acomp)
        db.session.commit()
        return _a_comanda(c, cuenta, seccion=producto.seccion_id, linea=linea.id)
    return _a_comanda(c, cuenta, seccion=producto.seccion_id)


@bp.get("/comanda/<int:cid>/acompanamiento/<int:pid>")
@con_sesion
def acompanamiento(cid: int, pid: int):
    c = _comanda(cid)
    producto = db.get_or_404(Producto, pid)
    cuenta = pedidos.cuenta_de(c, request.args.get("cuenta", 1))
    opciones = (
        Acompanamiento.query.filter_by(activo=True)
        .order_by(Acompanamiento.codigo)
        .all()
    )
    return render_template(
        "salon/acompanamiento.html",
        comanda=c,
        cuenta=cuenta,
        producto=producto,
        opciones=opciones,
    )


@bp.post("/comanda/<int:cid>/cuenta-nueva")
@con_sesion
@_amable
def cuenta_nueva(cid: int):
    c = _comanda(cid)
    cuenta = pedidos.nueva_cuenta(c)
    db.session.commit()
    return _a_comanda(c, cuenta)


@bp.post("/comanda/<int:cid>/enviar")
@con_sesion
@_amable
def enviar(cid: int):
    c = _comanda(cid)
    cuenta = request.form.get("cuenta", 1)
    if pedidos.tomar_idempotencia(request.form.get("idem"), "enviar"):
        n = pedidos.enviar(c, current_user)
        db.session.commit()
        _imprimir()
        flash(
            (
                f"Se enviaron {n} producto(s) a cocina y frente."
                if n
                else "No hay pedidos nuevos para enviar."
            ),
            "ok" if n else "info",
        )
    return _a_comanda(c, cuenta)


# --------------------------------------------------------------------------- líneas
@bp.post("/linea/<int:lid>/<any(mas, menos, borrar, llevar):accion>")
@con_sesion
@_amable
def linea_accion(lid: int, accion: str):
    linea = _linea(lid)
    c, cuenta = linea.cuenta.comanda, linea.cuenta
    if accion == "mas":
        pedidos.cambiar_cantidad(linea, 1)
    elif accion == "menos":
        pedidos.cambiar_cantidad(linea, -1)
    elif accion == "borrar":
        pedidos.borrar(linea)
    else:
        pedidos.alternar_llevar(linea)
    db.session.commit()
    sigue = db.session.get(LineaPedido, lid)
    return _a_comanda(c, cuenta, linea=lid if sigue else None)


@bp.route("/linea/<int:lid>/notas", methods=["GET", "POST"])
@con_sesion
@_amable
def notas(lid: int):
    linea = _linea(lid)
    if request.method == "POST":
        pedidos.fijar_notas(
            linea, request.form.getlist("nota"), request.form.get("libre")
        )
        db.session.commit()
        return _a_comanda(linea.cuenta.comanda, linea.cuenta, linea=lid)
    fijas = NotaFija.query.filter_by(activa=True).order_by(NotaFija.codigo).all()
    return render_template("salon/notas.html", linea=linea, fijas=fijas)


@bp.route("/linea/<int:lid>/anular", methods=["GET", "POST"])
@con_sesion
def anular(lid: int):
    linea = _linea(lid)
    if request.method == "POST":
        try:
            autorizador = _autorizador("supervisor")
            pedidos.anular(linea, current_user, autorizador, request.form.get("motivo"))
            db.session.commit()
            _imprimir()
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return (
                render_template(
                    "salon/autorizar.html",
                    linea=linea,
                    modo="anular",
                    motivo=request.form.get("motivo", ""),
                ),
                422,
            )
        flash(f"Se anuló {linea.descripcion}.", "ok")
        return _a_comanda(linea.cuenta.comanda, linea.cuenta)
    return render_template(
        "salon/autorizar.html", linea=linea, modo="anular", motivo=""
    )


@bp.route("/linea/<int:lid>/descuento", methods=["GET", "POST"])
@con_sesion
def descuento(lid: int):
    linea = _linea(lid)
    if request.method == "POST":
        try:
            from ..services import configuracion

            pct = request.form.get("pct", "0")
            tope = int(configuracion.obtener("descuento.tope_sin_supervisor") or 10)
            necesita = pct.isdigit() and int(pct) > tope
            autorizador = _autorizador("supervisor") if necesita else current_user
            pedidos.descontar(linea, pct, autorizador)
            db.session.commit()
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return (
                render_template("salon/autorizar.html", linea=linea, modo="descuento"),
                422,
            )
        return _a_comanda(linea.cuenta.comanda, linea.cuenta, linea=lid)
    return render_template("salon/autorizar.html", linea=linea, modo="descuento")


@bp.post("/linea/<int:lid>/mover")
@con_sesion
@_amable
def mover_linea(lid: int):
    linea = _linea(lid)
    c = linea.cuenta.comanda
    destino = pedidos.cuenta_de(c, request.form.get("destino"))
    if destino.id == linea.cuenta_id:
        destino = pedidos.nueva_cuenta(c)
    pedidos.mover_linea(linea, destino)
    db.session.commit()
    flash(f"{linea.descripcion} pasó a la cuenta {destino.numero}.", "ok")
    return _a_comanda(c, destino, linea=lid)


@bp.post("/linea/<int:lid>/entregar")
@con_sesion
@_amable
def entregar(lid: int):
    linea = _linea(lid)
    pedidos.entregar(linea)
    db.session.commit()
    if request.form.get("volver") == "comanda":
        return _a_comanda(linea.cuenta.comanda, linea.cuenta)
    return redirect(url_for("mesas.control"))


# --------------------------------------------------------------------------- cuenta
@bp.route("/cuenta/<int:cuenta_id>/jubilado", methods=["GET", "POST"])
@con_sesion
@_amable
def jubilado(cuenta_id: int):
    cuenta = _cuenta(cuenta_id)
    if request.method == "POST":
        pedidos.fijar_jubilado(
            cuenta, request.form.get("cedula"), request.form.get("nombre")
        )
        db.session.commit()
        return _a_comanda(cuenta.comanda, cuenta)
    from ..services import configuracion

    return render_template(
        "salon/jubilado.html", cuenta=cuenta, pct=configuracion.porcentaje_jubilado()
    )


@bp.post("/cuenta/<int:cuenta_id>/precuenta")
@con_sesion
@_amable
def precuenta(cuenta_id: int):
    cuenta = _cuenta(cuenta_id)
    pedidos.precuenta(cuenta)
    db.session.commit()
    flash("Pre-cuenta lista para imprimir.", "ok")
    return _a_comanda(cuenta.comanda, cuenta, pdf=1)


@bp.get("/cuenta/<int:cuenta_id>/precuenta.pdf")
@con_sesion
def precuenta_pdf(cuenta_id: int):
    cuenta = _cuenta(cuenta_id)
    return Response(
        pdf.precuenta_pdf(cuenta),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="precuenta-{cuenta.comanda.numero}-{cuenta.numero}.pdf"'
        },
    )


@bp.route("/comanda/<int:cid>/mover", methods=["GET", "POST"])
@con_sesion
@_amable
def mover(cid: int):
    c = _comanda(cid)
    if request.method == "POST":
        destino = Mesa.query.filter_by(
            numero=request.form.get("mesa", type=int) or 0
        ).first_or_404()
        pedidos.mover_mesa(c, destino)
        db.session.commit()
        flash(f"La comanda {c.numero} pasó a la mesa {destino.numero}.", "ok")
        return _a_comanda(c)
    libres = Mesa.query.filter_by(estado="disponible").order_by(Mesa.numero).all()
    return render_template("salon/mover.html", comanda=c, libres=libres)


@bp.route("/comanda/<int:cid>/mesero", methods=["GET", "POST"])
@con_sesion
def otro_mesero(cid: int):
    c = _comanda(cid)
    meseros = (
        Operador.query.filter(Operador.activo.is_(True), Operador.id != c.mesero_id)
        .order_by(Operador.nombre)
        .all()
    )
    if request.method == "POST":
        try:
            autorizador = _autorizador("supervisor")
            nuevo = db.get_or_404(Operador, request.form.get("mesero", type=int) or 0)
            pedidos.cambiar_mesero(c, nuevo, autorizador)
            db.session.commit()
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return render_template("salon/mesero.html", comanda=c, meseros=meseros), 422
        flash(f"La mesa ahora la atiende {nuevo.nombre}.", "ok")
        if pedidos.puede_operar(current_user, c):
            return _a_comanda(c)
        return redirect(url_for("mesas.control"))
    return render_template("salon/mesero.html", comanda=c, meseros=meseros)


# --------------------------------------------------------------------------- cobro
@bp.route("/cuenta/<int:cuenta_id>/cobrar", methods=["GET", "POST"])
@rol_requerido(*desde("cajero"))
def cobrar(cuenta_id: int):
    cuenta = _cuenta(cuenta_id)
    if request.method == "POST":
        if not pedidos.tomar_idempotencia(request.form.get("idem"), "cobrar"):
            doc = Documento.query.filter_by(cuenta_id=cuenta.id).first()
            return redirect(
                url_for("salon.documento", did=doc.id)
                if doc
                else url_for("salon.cobrar", cuenta_id=cuenta.id)
            )
        try:
            doc = caja.cobrar(cuenta, request.form, current_user)
            db.session.commit()  # la venta queda firme ANTES de hablar con el PAC
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return _pantalla_cobro(cuenta, request.form), 422
        estado = fiscal.autorizar(doc, url_de(doc))
        db.session.commit()
        if estado in ("autorizado", "simulado"):
            fiscal.reenviar_pendientes(
                url_de, limite=3
            )  # aprovecha que el PAC responde
        elif estado == "contingencia":
            flash(
                "El PAC no respondió: el comprobante quedó en contingencia y se reenviará.",
                "info",
            )
        _ticket_y_gaveta(doc)
        return redirect(url_for("salon.documento", did=doc.id, imprimir=1))
    if cuenta.estado == "pagada":
        doc = Documento.query.filter_by(cuenta_id=cuenta.id).first()
        if doc is not None:
            return redirect(url_for("salon.documento", did=doc.id))
    return _pantalla_cobro(cuenta, {})


def _pantalla_cobro(cuenta: Cuenta, previo):
    t = pedidos.totales(cuenta)
    q = (request.args.get("q") or "").strip()[:40]
    clientes = []
    if q:
        patron = f"%{q}%"
        clientes = (
            Cliente.query.filter(
                Cliente.activo.is_(True),
                db.or_(Cliente.nombre.ilike(patron), Cliente.ruc.ilike(patron)),
            )
            .order_by(Cliente.nombre)
            .limit(15)
            .all()
        )
    credito = None
    if cuenta.cliente is not None and cuenta.cliente.tipo_pago in (
        "credito",
        "autorizado",
    ):
        credito = cuenta.cliente.limite_credito - caja.credito_usado(cuenta.cliente)
    return render_template(
        "salon/cobrar.html",
        cuenta=cuenta,
        t=t,
        formas=FORMAS_PAGO,
        previo=previo,
        billetes=caja.redondeo_billete(t.total),
        turno=caja.turno_abierto(),
        q=q,
        clientes=clientes,
        credito=credito,
    )


@bp.post("/cuenta/<int:cuenta_id>/cliente")
@rol_requerido(*desde("cajero"))
@_amable
def cliente(cuenta_id: int):
    cuenta = _cuenta(cuenta_id)
    if cuenta.estado == "pagada":
        raise ReglaNegocioError("Esa cuenta ya está pagada.")
    cid = request.form.get("cliente", type=int)
    if cid:
        cli = db.get_or_404(Cliente, cid)
        if not cli.activo:
            raise ReglaNegocioError("Ese cliente está inactivo.")
        cuenta.cliente = None if cli.tipo == "consumidor_final" else cli
        cuenta.nombre_consumidor = None
    else:
        cuenta.cliente = None
        cuenta.nombre_consumidor = (
            " ".join((request.form.get("nombre") or "").split())[:80] or None
        )
    db.session.commit()
    return redirect(url_for("salon.cobrar", cuenta_id=cuenta.id))


@bp.get("/documento/<int:did>")
@con_sesion
def documento(did: int):
    doc = db.get_or_404(Documento, did)
    _comanda(doc.cuenta.comanda_id)
    comanda = doc.cuenta.comanda
    return render_template(
        "salon/documento.html",
        doc=doc,
        comanda=comanda,
        items=fiscal.items(doc),
        pagos=fiscal.pagos(doc),
        leyenda=fiscal.leyenda(doc),
        es_cajero=current_user.puede("cajero"),
    )


@bp.get("/documento/<int:did>.pdf")
@con_sesion
def documento_pdf(did: int):
    doc = db.get_or_404(Documento, did)
    _comanda(doc.cuenta.comanda_id)
    return _pdf_documento(doc, f"comprobante-{doc.numero:010d}")


@bp.post("/documento/<int:did>/reintentar")
@rol_requerido(*desde("cajero"))
def reintentar(did: int):
    doc = db.get_or_404(Documento, did)
    if doc.estado not in fiscal.ESTADOS_PENDIENTES:
        flash("Ese comprobante no está pendiente.", "info")
    else:
        estado = fiscal.autorizar(doc, url_de(doc))
        db.session.commit()
        flash(
            (
                "Comprobante autorizado."
                if estado in ("autorizado", "simulado")
                else f"Sigue sin autorizar: {doc.mensaje}"
            ),
            "ok" if estado != "contingencia" else "error",
        )
    return redirect(url_for("salon.documento", did=doc.id))


@bp.route("/documento/<int:did>/nota-credito", methods=["GET", "POST"])
@rol_requerido(*desde("cajero"))
def nota_credito(did: int):
    doc = db.get_or_404(Documento, did)
    items = fiscal.items(doc)
    ya = caja.acreditado_por_item(doc)
    restantes = [
        Decimal(it["cantidad"]) - ya.get(i, Decimal("0")) for i, it in enumerate(items)
    ]
    if request.method == "POST":
        try:
            cantidades = {}
            for i in range(len(items)):
                valor = (request.form.get(f"cant_{i}") or "").strip()
                if valor and valor not in ("0", "0.0", "0.000"):
                    cantidades[i] = valor
            autorizador = _autorizador("supervisor")
            nc = caja.nota_credito(
                doc,
                cantidades,
                request.form.get("motivo"),
                request.form.get("forma") or "efectivo",
                current_user,
                autorizador,
            )
            db.session.commit()
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return (
                render_template(
                    "salon/nota_credito.html",
                    doc=doc,
                    items=items,
                    restantes=restantes,
                    formas=FORMAS_PAGO,
                    previo=request.form,
                ),
                422,
            )
        fiscal.autorizar(nc, url_de(nc))
        db.session.commit()
        if nc.forma_devolucion == "efectivo":
            _gaveta()
        flash(f"Nota de crédito {nc.numero} emitida por B/. {nc.total:,.2f}.", "ok")
        return redirect(url_for("salon.ver_nota", nid=nc.id))
    return render_template(
        "salon/nota_credito.html",
        doc=doc,
        items=items,
        restantes=restantes,
        formas=FORMAS_PAGO,
        previo={},
    )


@bp.get("/nota-credito/<int:nid>")
@rol_requerido(*desde("cajero"))
def ver_nota(nid: int):
    nc = db.get_or_404(NotaCredito, nid)
    return render_template(
        "salon/ver_nota.html", nc=nc, items=fiscal.items(nc), leyenda=fiscal.leyenda(nc)
    )


@bp.get("/nota-credito/<int:nid>.pdf")
@rol_requerido(*desde("cajero"))
def nota_pdf(nid: int):
    nc = db.get_or_404(NotaCredito, nid)
    return _pdf_documento(nc, f"nota-credito-{nc.numero:010d}")


@bp.post("/nota-credito/<int:nid>/reintentar")
@rol_requerido(*desde("cajero"))
def reintentar_nota(nid: int):
    nc = db.get_or_404(NotaCredito, nid)
    if nc.estado in fiscal.ESTADOS_PENDIENTES:
        fiscal.autorizar(nc, url_de(nc))
        db.session.commit()
    return redirect(url_for("salon.ver_nota", nid=nc.id))


# --------------------------------------------------------------------------- ayudas de documentos
def url_de(doc) -> str:
    """Dirección de consulta del documento (va en el QR de la demostración)."""
    if isinstance(doc, NotaCredito):
        return url_for("salon.ver_nota", nid=doc.id, _external=True)
    return url_for("salon.documento", did=doc.id, _external=True)


def _pdf_documento(doc, nombre: str):
    carta = request.args.get("formato") == "carta"
    datos = (pdf.comprobante_carta_pdf if carta else pdf.comprobante_pdf)(
        doc, url_de(doc)
    )
    return Response(
        datos,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{nombre}{"-carta" if carta else ""}.pdf"'
        },
    )


def _imprimir() -> None:
    try:
        impresion.procesar_pendientes()
    except (
        Exception
    ):  # pragma: no cover - imprimir nunca tumba la venta; queda en la cola
        db.session.rollback()


def _gaveta() -> None:
    caja_imp = impresion.impresora_de_caja()
    if caja_imp is not None and configuracion.obtener("impresion.abrir_gaveta") == "1":
        impresion.encolar(
            caja_imp,
            "Apertura de gaveta",
            impresion.Ticket().gaveta().bytes(cortar=False),
        )
        db.session.commit()
        _imprimir()


def _ticket_y_gaveta(doc: Documento) -> None:
    caja_imp = impresion.impresora_de_caja()
    if caja_imp is None:
        return
    if configuracion.obtener("impresion.comprobante_en_ticket") == "1":
        impresion.encolar(
            caja_imp,
            f"Comprobante {doc.numero}",
            impresion.comprobante_ticket(doc, url_de(doc), caja_imp.columnas),
        )
    if (
        any(p["forma"] == "efectivo" for p in fiscal.pagos(doc))
        and configuracion.obtener("impresion.abrir_gaveta") == "1"
    ):
        impresion.encolar(
            caja_imp,
            "Apertura de gaveta",
            impresion.Ticket().gaveta().bytes(cortar=False),
        )
    db.session.commit()
    _imprimir()
