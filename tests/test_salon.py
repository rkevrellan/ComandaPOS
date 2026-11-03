"""Fase 2–4: mesa → comanda → cocina → pre-cuenta → cobro → comprobante → liberar.

Incluye control de acceso por comanda (A01/IDOR), autorizaciones de supervisor, idempotencia (RN-05),
multipago (RN-09), crédito (RN-10), RN-11, RN-12, RN-15, jubilado (RN-06) y turnos (RN-13).
"""

import re
import secrets
import zlib
from decimal import Decimal as D

import pytest

from app.extensions import db
from app.models import (
    Anulacion,
    Auditoria,
    Cliente,
    Comanda,
    Documento,
    LineaPedido,
    Mesa,
    NotaFija,
    Pago,
    Producto,
    Turno,
)
from app.seguridad import AUTORIZACION, CLAVE_DEMO
from app.services import auditoria
from tests.conftest import entrar


# --------------------------------------------------------------------------- ayudas
def token(c) -> str:
    c.get("/mesas")
    with c.session_transaction() as s:
        return s["_csrf"]


def post(c, ruta, **datos):
    datos.setdefault("csrf_token", token(c))
    return c.post(ruta, data=datos)


def idem() -> str:
    return secrets.token_hex(16)


def producto(app, corta: str) -> Producto:
    with app.app_context():
        p = Producto.query.filter_by(descripcion_corta=corta).one()
        db.session.expunge(p)
        return p


def abrir(c, mesa=5, puestos=2) -> int:
    r = post(c, f"/mesas/{mesa}/abrir", puestos=puestos)
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    return int(re.search(r"/comanda/(\d+)", r.headers["Location"]).group(1))


def agregar(c, cid, app, corta, cuenta=1, acomp=None, clave=None):
    datos = {
        "producto": producto(app, corta).id,
        "cuenta": cuenta,
        "idem": clave or idem(),
    }
    if acomp is not None:
        datos["acompanamiento"] = acomp
    return post(c, f"/comanda/{cid}/agregar", **datos)


def lineas(app, cid):
    with app.app_context():
        c = db.session.get(Comanda, cid)
        return [
            (ln.id, ln.descripcion, ln.estado, ln.cuenta.numero)
            for cu in c.cuentas
            for ln in cu.lineas
        ]


def texto_pdf(datos: bytes) -> bytes:
    """Texto plano del PDF (descomprime los streams de reportlab)."""
    import base64

    salida = datos
    # Anclado a «>>» para no confundir el «stream» que contiene cada «endstream».
    for m in re.finditer(rb">>\s*stream\r?\n(.*?)endstream", datos, re.S):
        crudo = m.group(1).strip()
        try:
            if crudo.endswith(b"~>"):  # reportlab: ASCII85 + Flate
                crudo = base64.a85decode(crudo[:-2])
            salida += zlib.decompress(crudo)
        except (ValueError, zlib.error):
            pass
    return salida


def cobrar(c, cuenta_id, **pagos):
    pagos.setdefault("idem", idem())
    return post(c, f"/cuenta/{cuenta_id}/cobrar", **pagos)


def cuenta_id(app, cid, numero=1):
    with app.app_context():
        c = db.session.get(Comanda, cid)
        return next(cu.id for cu in c.cuentas if cu.numero == numero)


@pytest.fixture(autouse=True)
def _limpiar_limitador():
    AUTORIZACION.reiniciar()


@pytest.fixture
def ana(client):
    entrar(client, "ana")
    return client


@pytest.fixture
def otro(app):
    """Un segundo navegador (otra terminal)."""

    def _otro(usuario):
        c = app.test_client()
        assert entrar(c, usuario).status_code == 302
        return c

    return _otro


# --------------------------------------------------------------------------- mapa
def test_mesas_se_pueden_tocar(ana):
    html = ana.get("/mesas").get_data(as_text=True)
    assert (
        'href="/mesas/1"' in html and "disabled" not in html.split("barra-inferior")[1]
    )


def test_abrir_mesa_y_ver_comanda(app, ana):
    cid = abrir(ana, 5, 3)
    html = ana.get(f"/comanda/{cid}").get_data(as_text=True)
    assert (
        "Enviar pedidos" in html and "TE FRIO" in html
    )  # Bebidas es la primera sección
    with app.app_context():
        almuerzo = Producto.query.filter_by(descripcion_corta="TASAJO").one().seccion_id
    assert "TASAJO" in ana.get(f"/comanda/{cid}?seccion={almuerzo}").get_data(
        as_text=True
    )
    with app.app_context():
        assert Mesa.query.filter_by(numero=5).one().estado == "ocupada"
        assert db.session.get(Comanda, cid).puestos == 3
    assert ana.get("/mesas/5").headers["Location"].endswith(f"/comanda/{cid}")


def test_no_se_abre_mesa_ocupada_ni_fuera_de_servicio(app, ana, otro):
    abrir(ana, 5)
    luis = otro("luis")
    r = post(luis, "/mesas/5/abrir", puestos=2)
    assert r.status_code == 302
    r = post(ana, "/mesas/30/abrir", puestos=2)
    with app.app_context():
        assert Mesa.query.filter_by(numero=30).one().estado == "fuera"
        assert Comanda.query.count() == 1


# --------------------------------------------------------------------------- pedidos
def test_agregar_enviar_y_cocina(app, ana):
    cid = abrir(ana)
    assert agregar(ana, cid, app, "TASAJO").status_code == 302
    assert agregar(ana, cid, app, "SODA LATA").status_code == 302
    assert [x[2] for x in lineas(app, cid)] == ["PED", "PED"]
    r = post(ana, f"/comanda/{cid}/enviar", idem=idem(), cuenta=1)
    assert r.status_code == 302
    assert [x[2] for x in lineas(app, cid)] == ["ORD", "ORD"]
    with app.app_context():
        cocina_id = Producto.query.filter_by(descripcion_corta="TASAJO").one().area1_id
        frente_id = (
            Producto.query.filter_by(descripcion_corta="SODA LATA").one().area1_id
        )
    html_cocina = ana.get(f"/cocina?area={cocina_id}").get_data(as_text=True)
    html_frente = ana.get(f"/cocina?area={frente_id}").get_data(as_text=True)
    assert (
        "TASAJO" in html_cocina and "SODA LATA" not in html_cocina
    )  # cada área ve lo suyo
    assert "SODA LATA" in html_frente and "TASAJO" not in html_frente
    post(ana, f"/cocina/{cid}/{cocina_id}/P")
    post(ana, f"/cocina/{cid}/{cocina_id}/L")
    estados = {x[1]: x[2] for x in lineas(app, cid)}
    assert estados == {"TASAJO": "PRE", "SODA LATA": "ORD"}
    assert (
        "TASAJO" in ana.get("/mesas").get_data(as_text=True).split("Pedidos listos")[1]
    )
    lid = next(x[0] for x in lineas(app, cid) if x[1] == "TASAJO")
    post(ana, f"/linea/{lid}/entregar")
    assert {x[1]: x[2] for x in lineas(app, cid)}["TASAJO"] == "ENT"


def test_rn05_doble_toque_no_duplica(app, ana):
    cid = abrir(ana)
    clave = idem()
    agregar(ana, cid, app, "TASAJO", clave=clave)
    agregar(ana, cid, app, "TASAJO", clave=clave)
    assert len(lineas(app, cid)) == 1
    clave = idem()
    post(ana, f"/comanda/{cid}/enviar", idem=clave)
    agregar(ana, cid, app, "PATACONES")
    post(ana, f"/comanda/{cid}/enviar", idem=clave)  # repetido: no envía lo nuevo
    assert {x[1]: x[2] for x in lineas(app, cid)}["PATACONES"] == "PED"


def test_idem_ausente_o_corto_se_rechaza(app, ana):
    cid = abrir(ana)
    post(
        ana,
        f"/comanda/{cid}/agregar",
        producto=producto(app, "TASAJO").id,
        cuenta=1,
        idem="x",
    )
    assert lineas(app, cid) == []


def test_acompanamiento_obligatorio_y_con_precio(app, ana):
    cid = abrir(ana)
    agregar(ana, cid, app, "CONCHA A LA CRIOLLA")
    assert lineas(app, cid) == []
    with app.app_context():
        from app.models import Acompanamiento

        papas = Acompanamiento.query.filter_by(descripcion="Papas fritas").one().id
    agregar(ana, cid, app, "CONCHA A LA CRIOLLA", acomp=papas)
    with app.app_context():
        ln = LineaPedido.query.one()
        assert ln.acompanamiento == "Papas fritas" and ln.precio == D(
            "9.45"
        )  # 8.95 + 0.50


def test_rn15_producto_agotado(app, ana):
    with app.app_context():
        Producto.query.filter_by(descripcion_corta="TASAJO").one().agotado = True
        db.session.commit()
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    assert lineas(app, cid) == []


def test_cantidad_notas_llevar_y_borrar_solo_en_ped(app, ana):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    lid = lineas(app, cid)[0][0]
    post(ana, f"/linea/{lid}/mas")
    with app.app_context():
        nota = NotaFija.query.filter_by(descripcion="SIN CEBOLLA").one().id
    post(ana, f"/linea/{lid}/notas", nota=nota, libre="bien tostado")
    post(ana, f"/linea/{lid}/llevar")
    with app.app_context():
        ln = db.session.get(LineaPedido, lid)
        assert (
            ln.cantidad == D("2.000")
            and ln.notas == "SIN CEBOLLA; bien tostado"
            and ln.para_llevar
        )
    post(ana, f"/comanda/{cid}/enviar", idem=idem())
    post(ana, f"/linea/{lid}/borrar")  # enviada: ya no se borra
    assert len(lineas(app, cid)) == 1
    assert "anularla" in ana.get(f"/comanda/{cid}").get_data(as_text=True)


# --------------------------------------------------------------------------- anulación y autorizaciones
def test_rn08_anular_requiere_supervisor_y_motivo(app, ana):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    post(ana, f"/comanda/{cid}/enviar", idem=idem())
    lid = lineas(app, cid)[0][0]
    r = post(ana, f"/linea/{lid}/anular", motivo="El cliente cambió de opinión")
    assert r.status_code == 422 and lineas(app, cid)[0][2] == "ORD"
    r = post(
        ana,
        f"/linea/{lid}/anular",
        motivo="corto",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    assert r.status_code == 422
    r = post(
        ana,
        f"/linea/{lid}/anular",
        motivo="El cliente cambió de opinión",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    assert r.status_code == 302 and lineas(app, cid)[0][2] == "ANU"
    with app.app_context():
        a = Anulacion.query.one()
        assert a.solicitante.usuario == "ana" and a.autorizador.usuario == "jose"
        reg = Auditoria.query.filter_by(accion="anulacion").one()
        assert reg.autorizador.usuario == "jose"
        assert auditoria.verificar()["ok"]


def test_autorizacion_de_mesero_no_sirve(app, ana):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    post(ana, f"/comanda/{cid}/enviar", idem=idem())
    lid = lineas(app, cid)[0][0]
    from app.seguridad import PIN_DEMO

    r = post(
        ana,
        f"/linea/{lid}/anular",
        motivo="Error de digitación del mesero",
        sup_usuario="luis",
        sup_clave=PIN_DEMO,
    )
    assert r.status_code == 422 and lineas(app, cid)[0][2] == "ORD"


def test_autorizaciones_fallidas_se_limitan(app, ana):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    post(ana, f"/comanda/{cid}/enviar", idem=idem())
    lid = lineas(app, cid)[0][0]
    for _ in range(5):
        post(
            ana,
            f"/linea/{lid}/anular",
            motivo="Probando claves al azar",
            sup_usuario="jose",
            sup_clave="mala",
        )
    r = post(
        ana,
        f"/linea/{lid}/anular",
        motivo="Ahora con la clave buena",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    assert "Demasiadas" in r.get_data(as_text=True) and lineas(app, cid)[0][2] == "ORD"


def test_rn07_descuento_con_tope(app, ana):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    lid = lineas(app, cid)[0][0]
    assert post(ana, f"/linea/{lid}/descuento", pct="5").status_code == 302
    assert post(ana, f"/linea/{lid}/descuento", pct="30").status_code == 422
    assert (
        post(
            ana,
            f"/linea/{lid}/descuento",
            pct="30",
            sup_usuario="jose",
            sup_clave=CLAVE_DEMO,
        ).status_code
        == 302
    )
    with app.app_context():
        assert db.session.get(LineaPedido, lid).descuento_pct == 30


# --------------------------------------------------------------------------- A01
def test_idor_mesero_no_opera_comanda_ajena(app, ana, otro):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    lid = lineas(app, cid)[0][0]
    luis = otro("luis")
    assert luis.get(f"/comanda/{cid}").status_code == 403
    assert (
        post(
            luis,
            f"/comanda/{cid}/agregar",
            producto=producto(app, "TASAJO").id,
            cuenta=1,
            idem=idem(),
        ).status_code
        == 403
    )
    assert post(luis, f"/linea/{lid}/borrar").status_code == 403
    assert luis.get(f"/cuenta/{cuenta_id(app, cid)}/precuenta.pdf").status_code == 403
    r = luis.get("/mesas/5")
    assert r.status_code == 302 and "/mesas" in r.headers["Location"]
    assert len(lineas(app, cid)) == 1


def test_operador_no_cobra_ni_ve_caja(app, ana):
    cid = abrir(ana)
    assert ana.get(f"/cuenta/{cuenta_id(app, cid)}/cobrar").status_code == 403
    assert ana.get("/caja").status_code == 403
    assert ana.get("/clientes").status_code == 403


def test_otro_mesero_pasa_la_mesa(app, ana, otro):
    cid = abrir(ana)
    with app.app_context():
        luis_id = (
            __import__("app.models", fromlist=["Operador"])
            .Operador.query.filter_by(usuario="luis")
            .one()
            .id
        )
    assert post(ana, f"/comanda/{cid}/mesero", mesero=luis_id).status_code == 422
    r = post(
        ana,
        f"/comanda/{cid}/mesero",
        mesero=luis_id,
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    assert r.status_code == 302
    assert ana.get(f"/comanda/{cid}").status_code == 403
    assert otro("luis").get(f"/comanda/{cid}").status_code == 200


def test_mover_mesa(app, ana):
    cid = abrir(ana, 5)
    post(ana, f"/comanda/{cid}/mover", mesa=7)
    with app.app_context():
        assert Mesa.query.filter_by(numero=5).one().estado == "disponible"
        assert Mesa.query.filter_by(numero=7).one().estado == "ocupada"
        assert db.session.get(Comanda, cid).mesa.numero == 7
    otra = abrir(ana, 8)
    post(ana, f"/comanda/{otra}/mover", mesa=7)  # ocupada: no se mueve
    with app.app_context():
        assert db.session.get(Comanda, otra).mesa.numero == 8


# --------------------------------------------------------------------------- pre-cuenta y cobro
def _comanda_enviada(app, c, productos=("TASAJO", "SODA LATA"), mesa=5):
    cid = abrir(c, mesa)
    for p in productos:
        agregar(c, cid, app, p)
    post(c, f"/comanda/{cid}/enviar", idem=idem())
    return cid


def test_rn11_precuenta_y_cobro_con_pendientes(app, ana, otro):
    cid = abrir(ana)
    agregar(ana, cid, app, "TASAJO")
    cta = cuenta_id(app, cid)
    post(ana, f"/cuenta/{cta}/precuenta")
    with app.app_context():
        assert Mesa.query.filter_by(numero=5).one().estado == "ocupada"
    r = cobrar(otro("marta"), cta, efectivo="20")
    assert r.status_code == 422 and "sin enviar" in r.get_data(as_text=True)


def test_precuenta_pdf_y_estado(app, ana):
    cid = _comanda_enviada(app, ana)
    cta = cuenta_id(app, cid)
    r = post(ana, f"/cuenta/{cta}/precuenta")
    assert "pdf=1" in r.headers["Location"]
    with app.app_context():
        assert Mesa.query.filter_by(numero=5).one().estado == "precuenta"
    pdf = ana.get(f"/cuenta/{cta}/precuenta.pdf")
    assert pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    contenido = texto_pdf(pdf.data)
    assert (
        b"PRE-CUENTA" in contenido
        and b"NO ES FACTURA" in contenido
        and b"5.25" in contenido.replace(b"\\", b"")
    )
    agregar(ana, cid, app, "PATACONES")  # agregar después regresa la mesa a «ocupada»
    with app.app_context():
        assert Mesa.query.filter_by(numero=5).one().estado == "ocupada"


def test_flujo_completo_cobro_efectivo_comprobante_y_liberar(app, ana, otro):
    cid = _comanda_enviada(app, ana)  # 3.75 + 1.50 = 5.25 + ITBMS 0.26 + 0.11 = 5.62
    cta = cuenta_id(app, cid)
    marta = otro("marta")
    html = marta.get(f"/cuenta/{cta}/cobrar").get_data(as_text=True)
    assert "5.62" in html
    r = cobrar(marta, cta, efectivo="20.00")
    assert r.status_code == 302 and "/documento/" in r.headers["Location"]
    with app.app_context():
        doc = Documento.query.one()
        assert (
            doc.total == D("5.62")
            and doc.itbms == D("0.37")
            and doc.receptor_ruc == "00-00-00"
        )
        pago = Pago.query.one()
        assert (pago.monto, pago.recibido, pago.vuelto) == (
            D("5.62"),
            D("20.00"),
            D("14.38"),
        )
        assert db.session.get(Comanda, cid).estado == "cerrada"
        assert Mesa.query.filter_by(numero=5).one().estado == "pagada"
        did = doc.id
    pdf = marta.get(f"/documento/{did}.pdf")
    contenido = texto_pdf(pdf.data)
    assert (
        pdf.data.startswith(b"%PDF")
        and b"SIN VALIDEZ FISCAL" in contenido
        and b"CUFE" in contenido
    )
    assert b"Vuelto" in contenido and b"14.38" in contenido
    post(ana, "/mesas/5/liberar")
    with app.app_context():
        assert Mesa.query.filter_by(numero=5).one().estado == "disponible"


def test_rn05_doble_cobro_un_solo_comprobante(app, ana, otro):
    cid = _comanda_enviada(app, ana)
    cta = cuenta_id(app, cid)
    marta = otro("marta")
    clave = idem()
    cobrar(marta, cta, efectivo="10", idem=clave)
    r = cobrar(marta, cta, efectivo="10", idem=clave)
    assert r.status_code == 302
    with app.app_context():
        assert Documento.query.count() == 1 and Pago.query.count() == 1


def test_rn09_multipago_y_tarjetas(app, ana, otro):
    cid = _comanda_enviada(app, ana)
    cta = cuenta_id(app, cid)
    marta = otro("marta")
    assert (
        cobrar(marta, cta, visa="10.00", visa_ref="A1B2C3").status_code == 422
    )  # pasa del total
    r = cobrar(marta, cta, visa="3.00", visa_ref="4111111111111111")
    assert r.status_code == 422 and "número de la tarjeta" in r.get_data(as_text=True)
    assert cobrar(marta, cta, visa="3.00").status_code == 422  # falta la autorización
    assert (
        cobrar(marta, cta, visa="3.00", visa_ref="A1B2C3", efectivo="1").status_code
        == 422
    )  # falta
    r = cobrar(
        marta,
        cta,
        visa="3.00",
        visa_ref="A1B2C3",
        yappy="1.00",
        yappy_ref="YP9988",
        efectivo="5",
    )
    assert r.status_code == 302
    with app.app_context():
        pagos = {p.forma: (p.monto, p.vuelto) for p in Pago.query.all()}
        assert pagos == {
            "visa": (D("3.00"), D("0.00")),
            "yappy": (D("1.00"), D("0.00")),
            "efectivo": (D("1.62"), D("3.38")),
        }


def test_rn09_monto_no_finito(app, ana, otro):
    cid = _comanda_enviada(app, ana)
    r = cobrar(otro("marta"), cuenta_id(app, cid), efectivo="NaN")
    assert r.status_code == 422


def test_rn10_credito(app, ana, otro):
    cid = _comanda_enviada(app, ana)
    cta = cuenta_id(app, cid)
    marta = otro("marta")
    assert (
        cobrar(marta, cta, credito="5.62").status_code == 422
    )  # consumidor final: sin crédito
    with app.app_context():
        agro = Cliente.query.filter(Cliente.ruc == "155700001-2-2026").one()
        agro.limite_credito = D("5.00")
        db.session.commit()
        agro_id = agro.id
    post(marta, f"/cuenta/{cta}/cliente", cliente=agro_id)
    r = cobrar(marta, cta, credito="5.62")
    assert r.status_code == 422 and "5.00" in r.get_data(as_text=True)
    r = cobrar(marta, cta, credito="5.00", efectivo="0.62")
    assert r.status_code == 302
    with app.app_context():
        doc = Documento.query.one()
        assert (
            doc.receptor_nombre.startswith("AGROSERVICIOS") and doc.receptor_dv == "11"
        )


def test_rn06_jubilado_en_cobro(app, ana, otro):
    cid = _comanda_enviada(app, ana, ("TASAJO", "CERVEZA NACIONAL"))
    cta = cuenta_id(app, cid)
    post(ana, f"/cuenta/{cta}/jubilado", cedula="4-123-456", nombre="Rosa Pitti")
    assert cobrar(otro("marta"), cta, efectivo="10").status_code == 302
    with app.app_context():
        doc = Documento.query.one()
        # Tasajo 3.75 − 25 % = 2.81 (+0.20) ; cerveza 2.00 sin descuento (+0.14)
        assert doc.descuento_jubilado == D("0.94") and doc.total == D("5.15")


def test_cuentas_separadas_y_rn12(app, ana, otro):
    cid = _comanda_enviada(app, ana)
    soda = next(x[0] for x in lineas(app, cid) if x[1] == "SODA LATA")
    post(ana, f"/linea/{soda}/mover", destino=1)  # «cuenta nueva»
    assert {x[1]: x[3] for x in lineas(app, cid)} == {"TASAJO": 1, "SODA LATA": 2}
    marta = otro("marta")
    cobrar(marta, cuenta_id(app, cid, 1), efectivo="5")
    with app.app_context():
        assert db.session.get(Comanda, cid).estado == "abierta"
        assert Mesa.query.filter_by(numero=5).one().estado == "ocupada"
    agregar(ana, cid, app, "PATACONES", cuenta=1)  # RN-12: la cuenta 1 ya está pagada
    assert {x[1] for x in lineas(app, cid)} == {"TASAJO", "SODA LATA"}
    cobrar(marta, cuenta_id(app, cid, 2), efectivo="2")
    with app.app_context():
        assert db.session.get(Comanda, cid).estado == "cerrada"
        assert Documento.query.count() == 2


def test_cobro_rapido_sin_mesa(app, otro):
    marta = otro("marta")
    r = post(marta, "/rapido")
    cid = int(re.search(r"/comanda/(\d+)", r.headers["Location"]).group(1))
    agregar(marta, cid, app, "HOJALDRA")
    post(marta, f"/comanda/{cid}/enviar", idem=idem())
    assert cobrar(marta, cuenta_id(app, cid), efectivo="1").status_code == 302
    with app.app_context():
        c = db.session.get(Comanda, cid)
        assert c.tipo == "rapido" and c.mesa is None and c.estado == "cerrada"


def test_sin_turno_no_se_cobra(app, ana, otro):
    with app.app_context():
        t = Turno.query.one()
        t.cerrado_en = t.abierto_en
        db.session.commit()
    cid = _comanda_enviada(app, ana)
    r = cobrar(otro("marta"), cuenta_id(app, cid), efectivo="10")
    assert r.status_code == 422 and "turno" in r.get_data(as_text=True)


# --------------------------------------------------------------------------- caja
def test_rn13_cierre_de_turno_con_arqueo(app, ana, otro):
    cid = _comanda_enviada(app, ana)
    marta = otro("marta")
    cobrar(marta, cuenta_id(app, cid), efectivo="20")
    html = marta.get("/caja").get_data(as_text=True)
    assert "55.62" in html  # fondo 50 + efectivo neto 5.62
    post(marta, "/caja/cerrar", contado="50.00")  # faltan 5.62 sin justificar
    with app.app_context():
        assert Turno.query.one().cerrado_en is None
    post(
        marta,
        "/caja/cerrar",
        contado="50.00",
        justificacion="Se pagó un proveedor con efectivo",
    )
    with app.app_context():
        t = Turno.query.one()
        assert t.cerrado_en is not None and t.diferencia == D("-5.62")
    post(marta, "/caja/abrir", fondo="40")
    with app.app_context():
        assert Turno.query.count() == 2


# --------------------------------------------------------------------------- notas y clientes
def test_notas_fijas_permisos(app, ana, otro):
    assert ana.get("/notas").status_code == 200
    assert post(ana, "/notas", descripcion="sin hielo").status_code == 403
    jose = otro("jose")
    post(jose, "/notas", descripcion="sin hielo")
    with app.app_context():
        assert NotaFija.query.filter_by(descripcion="SIN HIELO").count() == 1


def test_clientes_validacion_y_credito_solo_supervisor(app, otro):
    marta = otro("marta")
    assert (
        post(
            marta, "/clientes", tipo="juridico", ruc="12", dv="1", nombre="X SA"
        ).status_code
        == 422
    )
    assert (
        post(
            marta,
            "/clientes",
            tipo="juridico",
            ruc="155800001-2-2026",
            dv="",
            nombre="NUEVA EMPRESA SA",
        ).status_code
        == 422
    )
    assert (
        post(
            marta,
            "/clientes",
            tipo="juridico",
            ruc="155800001-2-2026",
            dv="45",
            nombre="NUEVA EMPRESA SA",
            tipo_pago="credito",
            limite="100",
        ).status_code
        == 422
    )
    assert (
        post(
            marta,
            "/clientes",
            tipo="juridico",
            ruc="155800001-2-2026",
            dv="45",
            nombre="Nueva Empresa SA",
            tipo_pago="contado",
        ).status_code
        == 302
    )
    with app.app_context():
        assert (
            Cliente.query.filter_by(ruc="155800001-2-2026").one().nombre
            == "NUEVA EMPRESA SA"
        )


def test_todas_las_rutas_nuevas_tienen_rol(app):
    for regla in app.url_map.iter_rules():
        vista = app.view_functions[regla.endpoint]
        if regla.endpoint != "static":
            assert getattr(vista, "_publica", False) or getattr(
                vista, "_roles", None
            ), regla.rule
