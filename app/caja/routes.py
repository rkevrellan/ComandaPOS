"""Caja: turno (apertura, corte X, corte Z), gaveta, abonos a crédito, facturas pendientes e impresión."""

from __future__ import annotations

from flask import (
    Blueprint,
    Response,
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
    Abono,
    Cliente,
    Documento,
    NotaCredito,
    Pago,
    TrabajoImpresion,
    Turno,
)
from ..seguridad import desde, rol_requerido
from ..services import caja, configuracion, fiscal, impresion, pdf
from ..services.calculos import ReglaNegocioError

bp = Blueprint("caja", __name__)


def _url_de(doc) -> str:
    from ..salon.routes import url_de

    return url_de(doc)


@bp.get("/caja")
@rol_requerido(*desde("cajero"))
def inicio():
    turno = caja.turno_abierto()
    datos = caja.resumen(turno) if turno else None
    documentos, notas = [], []
    if turno is not None:
        documentos = (
            Documento.query.join(Pago, Pago.cuenta_id == Documento.cuenta_id)
            .filter(Pago.turno_id == turno.id)
            .distinct()
            .order_by(Documento.numero.desc())
            .limit(60)
            .all()
        )
        notas = (
            NotaCredito.query.filter_by(turno_id=turno.id)
            .order_by(NotaCredito.numero.desc())
            .all()
        )
    anteriores = (
        Turno.query.filter(Turno.cerrado_en.is_not(None))
        .order_by(Turno.id.desc())
        .limit(8)
        .all()
    )
    impresiones = (
        TrabajoImpresion.query.filter(TrabajoImpresion.estado != "impreso")
        .order_by(TrabajoImpresion.id.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "caja/inicio.html",
        turno=turno,
        datos=datos,
        formas=FORMAS_PAGO,
        documentos=documentos,
        notas=notas,
        anteriores=anteriores,
        pendientes=fiscal.pendientes(),
        folios=fiscal.folios(),
        impresiones=impresiones,
        impresora_caja=impresion.impresora_de_caja(),
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
    return redirect(url_for("caja.corte", tid=turno.id, cerrado=1))


@bp.get("/caja/corte-x.pdf")
@rol_requerido(*desde("cajero"))
def corte_x():
    turno = caja.turno_abierto()
    if turno is None:
        flash("No hay turno abierto.", "info")
        return redirect(url_for("caja.inicio"))
    from ..services.auditoria import auditar

    auditar("corte_x", f"turno {turno.numero}")
    db.session.commit()
    return Response(
        pdf.corte_pdf(turno, caja.resumen(turno), "X"),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="corte-x-turno-{turno.numero}.pdf"'
        },
    )


@bp.get("/caja/turno/<int:tid>")
@rol_requerido(*desde("cajero"))
def corte(tid: int):
    turno = db.get_or_404(Turno, tid)
    return render_template(
        "caja/turno.html", turno=turno, datos=caja.resumen(turno), formas=FORMAS_PAGO
    )


@bp.get("/caja/turno/<int:tid>/corte-z.pdf")
@rol_requerido(*desde("cajero"))
def corte_z(tid: int):
    turno = db.get_or_404(Turno, tid)
    if turno.cerrado_en is None:
        flash("El corte Z se imprime al cerrar el turno.", "info")
        return redirect(url_for("caja.inicio"))
    return Response(
        pdf.corte_pdf(turno, caja.resumen(turno), "Z"),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="corte-z-turno-{turno.numero}.pdf"'
        },
    )


@bp.post("/caja/gaveta")
@rol_requerido(*desde("cajero"))
def gaveta():
    try:
        caja.abrir_gaveta(current_user, request.form.get("motivo"))
        imp = impresion.impresora_de_caja()
        if imp is not None:
            impresion.encolar(
                imp,
                "Apertura de gaveta sin venta",
                impresion.Ticket().gaveta().bytes(cortar=False),
            )
        db.session.commit()
        impresion.procesar_pendientes()
        flash(
            (
                "Gaveta abierta (queda en la auditoría)."
                if imp
                else "Apertura registrada. No hay impresora de caja configurada."
            ),
            "ok",
        )
    except ReglaNegocioError as e:
        db.session.rollback()
        flash(str(e), "error")
    return redirect(url_for("caja.inicio"))


@bp.post("/caja/fiscal/reenviar")
@rol_requerido(*desde("cajero"))
def reenviar():
    autorizados, fallidos = fiscal.reenviar_pendientes(_url_de)
    flash(
        f"Autorizados: {autorizados}. Sin autorizar: {fallidos}.",
        "ok" if not fallidos else "error",
    )
    return redirect(url_for("caja.inicio"))


@bp.post("/caja/impresion/reintentar")
@rol_requerido(*desde("cajero"))
def reimprimir():
    TrabajoImpresion.query.filter_by(estado="error").update({"intentos": 0})
    db.session.commit()
    impresos, errores = impresion.procesar_pendientes()
    flash(
        f"Impresos: {impresos}. Con error: {errores}.", "ok" if not errores else "error"
    )
    return redirect(url_for("caja.inicio"))


# --------------------------------------------------------------------------- abonos a crédito
@bp.route("/clientes/<int:cid>/abono", methods=["GET", "POST"])
@rol_requerido(*desde("cajero"))
def abono(cid: int):
    cliente = db.get_or_404(Cliente, cid)
    if request.method == "POST":
        try:
            a = caja.abonar(
                cliente,
                request.form.get("monto"),
                request.form.get("forma") or "efectivo",
                request.form.get("referencia"),
                current_user,
            )
            db.session.commit()
        except ReglaNegocioError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for("caja.abono", cid=cid))
        if a.forma == "efectivo":
            imp = impresion.impresora_de_caja()
            if (
                imp is not None
                and configuracion.obtener("impresion.abrir_gaveta") == "1"
            ):
                impresion.encolar(
                    imp,
                    "Apertura de gaveta",
                    impresion.Ticket().gaveta().bytes(cortar=False),
                )
                db.session.commit()
                impresion.procesar_pendientes()
        flash(f"Abono registrado. Recibo {a.recibo:06d}.", "ok")
        return redirect(url_for("caja.abono", cid=cid, recibo=a.id))
    deuda = caja.credito_usado(cliente)
    historial = (
        Abono.query.filter_by(cliente_id=cid).order_by(Abono.id.desc()).limit(20).all()
    )
    return render_template(
        "caja/abono.html",
        cliente=cliente,
        deuda=deuda,
        historial=historial,
        formas={k: v for k, v in FORMAS_PAGO.items() if k != "credito"},
        recibo=request.args.get("recibo", type=int),
    )


@bp.get("/abono/<int:aid>.pdf")
@rol_requerido(*desde("cajero"))
def recibo(aid: int):
    a = db.get_or_404(Abono, aid)
    return Response(
        pdf.recibo_abono_pdf(a),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="recibo-{a.recibo:06d}.pdf"'
        },
    )
