"""Fase final — facturación (PAC, contingencia, folios, notas de crédito), impresión ESC/POS,
inventario por receta, abonos a crédito, cortes X/Z y migración de bases anteriores."""

import json
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models import (
    Documento,
    Impresora,
    Insumo,
    LineaPedido,
    MovimientoInventario,
    NotaCredito,
    Producto,
    TrabajoImpresion,
)
from app.seguridad import CLAVE_DEMO
from app.services import configuracion, fiscal, impresion
from tests.test_salon import (
    _comanda_enviada,
    abrir,
    agregar,
    cobrar,
    cuenta_id,
    idem,
    lineas,
    post,
    texto_pdf,
)


@pytest.fixture
def marta(otro):
    return otro("marta")


def _cobrada(app, ana, marta, productos=("TASAJO", "SODA LATA"), mesa=5, **pago):
    cid = _comanda_enviada(app, ana, productos, mesa)
    r = cobrar(marta, cuenta_id(app, cid), **(pago or {"efectivo": "20"}))
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    with app.app_context():
        return Documento.query.order_by(Documento.id.desc()).first().id


# --------------------------------------------------------------------------- facturación
def test_comprobante_autorizado_con_detalle_congelado(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    did = _cobrada(app, client, marta)
    with app.app_context():
        doc = db.session.get(Documento, did)
        assert (
            doc.estado == "simulado" and doc.cufe.startswith("SIM01") and doc.protocolo
        )
        items = fiscal.items(doc)
        assert [i["descripcion"] for i in items] == ["TASAJO", "SODA LATA"]
        # cambiar el precio del menú NO altera el comprobante emitido
        Producto.query.filter_by(descripcion_corta="TASAJO").one().precio = D("99.00")
        db.session.commit()
    contenido = texto_pdf(marta.get(f"/documento/{did}.pdf").data)
    assert b"3.75" in contenido and b"99.00" not in contenido
    carta = marta.get(f"/documento/{did}.pdf?formato=carta")
    assert carta.data.startswith(b"%PDF") and b"SIN VALIDEZ FISCAL" in texto_pdf(
        carta.data
    )


def test_contingencia_y_reenvio(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    with app.app_context():
        configuracion.fijar("fiscal.simular_caida", "1")
        db.session.commit()
    did = _cobrada(app, client, marta)
    with app.app_context():
        doc = db.session.get(Documento, did)
        assert (
            doc.estado == "contingencia"
            and doc.cufe.startswith("PEND-")
            and doc.intentos == 1
        )
    pdf = texto_pdf(marta.get(f"/documento/{did}.pdf").data)
    assert (
        b"CONTINGENCIA" in pdf and b"CUFE:" not in pdf
    )  # nunca se presenta un código provisional como CUFE
    post(marta, "/caja/fiscal/reenviar")  # el PAC sigue caído
    with app.app_context():
        assert db.session.get(Documento, did).estado == "contingencia"
        configuracion.fijar("fiscal.simular_caida", "0")
        db.session.commit()
    post(marta, "/caja/fiscal/reenviar")
    with app.app_context():
        doc = db.session.get(Documento, did)
        assert (
            doc.estado == "simulado"
            and doc.cufe.startswith("SIM")
            and doc.intentos == 3
        )


def test_simulado_no_funciona_fuera_de_la_demostracion(app):
    with app.test_request_context():
        app.config["DEMO"] = False
        try:
            assert (
                fiscal.proveedor() is None
            )  # → contingencia, nunca un «CUFE» de prueba
            configuracion.fijar("fiscal.proveedor", "http")
            configuracion.fijar(
                "fiscal.pac_url", "http://pac.ejemplo.com/api"
            )  # http externo: no
            assert fiscal.proveedor() is None
        finally:
            app.config["DEMO"] = True


def test_url_del_pac_solo_https():
    assert fiscal.url_pac_valida("https://pac.ejemplo.pa/v1/facturas")
    assert fiscal.url_pac_valida("http://127.0.0.1:8080/pac")
    for mala in (
        "http://pac.ejemplo.pa",
        "ftp://x",
        "file:///etc/passwd",
        "",
        "https://",
    ):
        assert not fiscal.url_pac_valida(mala)


def test_folios(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    with app.app_context():
        configuracion.fijar("fiscal.folios_total", "5")
        db.session.commit()
    _cobrada(app, client, marta)
    with app.app_context():
        f = fiscal.folios()
        assert (f["total"], f["usados"], f["disponibles"]) == (5, 1, 4)
    import re

    assert re.search(
        r"Folios disponibles</dt>\s*<dd>\s*4\s+de\s+5",
        marta.get("/caja").get_data(as_text=True),
    )


def test_nota_de_credito_parcial_y_limites(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    did = _cobrada(app, client, marta, ("TASAJO", "SODA LATA", "SODA LATA"))
    with app.app_context():
        items = fiscal.items(db.session.get(Documento, did))
        soda = next(i for i, it in enumerate(items) if it["descripcion"] == "SODA LATA")
    ruta = f"/documento/{did}/nota-credito"
    assert (
        post(
            marta, ruta, **{f"cant_{soda}": "1", "motivo": "Soda caliente devuelta"}
        ).status_code
        == 422
    )
    r = post(
        marta,
        ruta,
        **{
            f"cant_{soda}": "1",
            "motivo": "Soda caliente devuelta",
            "sup_usuario": "jose",
            "sup_clave": CLAVE_DEMO,
        },
    )
    assert r.status_code == 302
    with app.app_context():
        nc = NotaCredito.query.one()
        assert (
            nc.total == D("1.61")
            and nc.estado == "simulado"
            and nc.autorizador.usuario == "jose"
        )
        assert nc.cufe.startswith("SIM04")
        nid = nc.id
    # ya no se puede acreditar otra vez la misma soda (vendida 1 línea de cantidad 1 por cada toque)
    r = post(
        marta,
        ruta,
        **{
            f"cant_{soda}": "2",
            "motivo": "Intento de acreditar de más",
            "sup_usuario": "jose",
            "sup_clave": CLAVE_DEMO,
        },
    )
    assert r.status_code == 422
    contenido = texto_pdf(marta.get(f"/nota-credito/{nid}.pdf").data)
    assert b"NOTA DE CR" in contenido and b"Referencia" in contenido
    html = marta.get("/caja").get_data(as_text=True)
    assert "NC 0000000001" in html


def test_nota_credito_reduce_el_efectivo_esperado(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    did = _cobrada(app, client, marta, ("TASAJO",))
    with app.app_context():
        esperado_antes = __import__("app.services.caja", fromlist=["x"]).resumen(
            __import__("app.services.caja", fromlist=["x"]).turno_abierto()
        )["efectivo_esperado"]
    post(
        marta,
        f"/documento/{did}/nota-credito",
        cant_0="1",
        motivo="Plato equivocado devuelto",
        forma="efectivo",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    with app.app_context():
        from app.services import caja

        datos = caja.resumen(caja.turno_abierto())
        assert datos["efectivo_esperado"] == esperado_antes - D("4.01")
        assert datos["notas_credito"] == 1


# --------------------------------------------------------------------------- impresión
def test_limpiar_bytes_de_control():
    t = impresion.Ticket()
    t.linea("Cliente \x1b@\x1bp\x00\x19\xfa\x1dV\x42 malicioso")
    datos = t.bytes(cortar=False)
    cuerpo = datos[len(impresion.INICIAR) :]
    assert impresion.GAVETA not in datos and b"\x1dV" not in cuerpo
    assert b"Cliente" in datos and b"malicioso" in datos


def test_comandas_por_area_y_aviso_de_anulacion(app, client):
    from tests.conftest import entrar

    entrar(client, "ana")
    cid = _comanda_enviada(app, client, ("TASAJO", "SODA LATA"))
    with app.app_context():
        trabajos = TrabajoImpresion.query.order_by(TrabajoImpresion.id).all()
        assert {t.impresora.nombre for t in trabajos} == {
            "Cocina (demo)",
            "Frente (demo)",
        }
        assert all(t.estado == "impreso" for t in trabajos)
        cocina = next(t for t in trabajos if t.impresora.nombre == "Cocina (demo)")
        texto = impresion.vista_previa(cocina.contenido)
        assert "TASAJO" in texto and "SODA" not in texto and "MESA 5" in texto
    lid = next(x[0] for x in lineas(app, cid) if x[1] == "TASAJO")
    post(
        client,
        f"/linea/{lid}/anular",
        motivo="Cliente ya no lo quiere",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    with app.app_context():
        ultimo = TrabajoImpresion.query.order_by(TrabajoImpresion.id.desc()).first()
        assert (
            ultimo.impresora.nombre == "Cocina (demo)"
            and "ANULACION" in impresion.vista_previa(ultimo.contenido)
        )


def test_cobro_imprime_ticket_y_abre_gaveta(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    _cobrada(app, client, marta)
    with app.app_context():
        caja_trabajos = (
            TrabajoImpresion.query.join(Impresora)
            .filter(Impresora.nombre == "Caja (demo)")
            .all()
        )
        assert any("Comprobante" in t.descripcion for t in caja_trabajos)
        assert any(impresion.GAVETA in t.contenido for t in caja_trabajos)


def test_impresora_caida_queda_en_cola(app, client):
    from tests.conftest import entrar

    entrar(client, "ana")
    with app.app_context():
        imp = Impresora.query.filter_by(nombre="Cocina (demo)").one()
        imp.tipo, imp.destino = "red", "127.0.0.1:9"  # puerto cerrado
        db.session.commit()
    _comanda_enviada(app, client, ("TASAJO",))
    with app.app_context():
        t = (
            TrabajoImpresion.query.join(Impresora)
            .filter(Impresora.nombre == "Cocina (demo)")
            .one()
        )
        assert t.estado == "error" and t.intentos == 1 and t.error


@pytest.mark.parametrize(
    "tipo, destino",
    [
        ("red", "impresora.local:9100"),
        ("red", "10.0.0.5:99999"),
        ("archivo", "../../etc/passwd"),
        ("windows", ""),
    ],
)
def test_destinos_de_impresora_invalidos(tipo, destino):
    with pytest.raises(ValueError):
        impresion.validar_destino(tipo, destino)


# --------------------------------------------------------------------------- inventario
def test_rn14_receta_descuenta_al_enviar_y_reversa_al_anular(app, client):
    from tests.conftest import entrar

    entrar(client, "ana")
    cid = abrir(client, 6)
    agregar(client, cid, app, "SODA LATA")
    agregar(client, cid, app, "SODA LATA")
    with app.app_context():
        assert Insumo.query.filter_by(nombre="Soda en lata").one().existencia == D(
            "48"
        )  # aún en PED
    post(client, f"/comanda/{cid}/enviar", idem=idem())
    with app.app_context():
        assert Insumo.query.filter_by(nombre="Soda en lata").one().existencia == D("46")
    lid = lineas(app, cid)[0][0]
    post(
        client,
        f"/linea/{lid}/anular",
        motivo="Se pidió por error",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    with app.app_context():
        assert Insumo.query.filter_by(nombre="Soda en lata").one().existencia == D("47")
        assert MovimientoInventario.query.filter_by(tipo="reverso").count() == 1


def test_rn15_se_agota_solo_y_se_reactiva_con_entrada(app, client, otro):
    from tests.conftest import entrar

    entrar(client, "ana")
    with app.app_context():
        Insumo.query.filter_by(nombre="Tasajo").one().existencia = D("0.25")
        db.session.commit()
    cid = abrir(client, 6)
    agregar(client, cid, app, "TASAJO")
    post(client, f"/comanda/{cid}/enviar", idem=idem())
    with app.app_context():
        p = Producto.query.filter_by(descripcion_corta="TASAJO").one()
        assert p.agotado and p.agotado_auto
        insumo_id = Insumo.query.filter_by(nombre="Tasajo").one().id
    admin = otro("admin")
    post(
        admin,
        f"/admin/inventario/{insumo_id}/entrada",
        cantidad="5",
        referencia="Compra semanal",
    )
    with app.app_context():
        p = Producto.query.filter_by(descripcion_corta="TASAJO").one()
        assert not p.agotado and not p.agotado_auto


# --------------------------------------------------------------------------- abonos y cortes
def test_abono_a_credito_y_recibo(app, client, marta):
    from tests.conftest import entrar
    from app.models import Cliente

    entrar(client, "ana")
    cid = _comanda_enviada(app, client, ("TASAJO",))
    with app.app_context():
        agro = Cliente.query.filter_by(ruc="155700001-2-2026").one().id
    post(marta, f"/cuenta/{cuenta_id(app, cid)}/cliente", cliente=agro)
    assert cobrar(marta, cuenta_id(app, cid), credito="4.01").status_code == 302
    assert (
        post(marta, f"/clientes/{agro}/abono", monto="10", forma="efectivo").status_code
        == 302
    )
    with app.app_context():
        from app.models import Abono

        assert Abono.query.count() == 0  # no puede pasar del saldo
    r = post(marta, f"/clientes/{agro}/abono", monto="4.01", forma="efectivo")
    assert r.status_code == 302
    with app.app_context():
        from app.models import Abono, Cliente as C
        from app.services import caja

        a = Abono.query.one()
        assert caja.credito_usado(db.session.get(C, agro)) == D("0.00")
        aid = a.id
    assert b"RECIBO DE ABONO" in texto_pdf(marta.get(f"/abono/{aid}.pdf").data)


def test_corte_x_y_z(app, client, marta):
    from tests.conftest import entrar

    entrar(client, "ana")
    _cobrada(app, client, marta)
    x = marta.get("/caja/corte-x.pdf")
    assert x.data.startswith(b"%PDF") and b"CORTE X" in texto_pdf(x.data)
    r = post(marta, "/caja/cerrar", contado="55.62")  # fondo 50 + 5.62 en efectivo
    assert "/caja/turno/" in r.headers["Location"]
    with app.app_context():
        from app.models import Turno

        tid = Turno.query.one().id
    z = texto_pdf(marta.get(f"/caja/turno/{tid}/corte-z.pdf").data)
    assert b"CORTE Z" in z and b"55.62" in z


def test_gaveta_sin_venta_requiere_motivo_y_se_audita(app, marta):
    post(marta, "/caja/gaveta", motivo="")
    post(marta, "/caja/gaveta", motivo="Cambio de billetes de 20")
    with app.app_context():
        from app.models import Auditoria

        assert Auditoria.query.filter_by(accion="gaveta_sin_venta").count() == 1


# --------------------------------------------------------------------------- migración
def test_migracion_agrega_columnas_a_una_base_anterior(app):
    from app.migracion import migrar

    with app.app_context():
        db.session.execute(text("ALTER TABLE documentos DROP COLUMN mensaje"))
        db.session.execute(text("ALTER TABLE operadores DROP COLUMN totp_secreto"))
        db.session.commit()
        agregadas = migrar(app)
        assert {"documentos.mensaje", "operadores.totp_secreto"} <= set(agregadas)
        assert migrar(app) == []


def test_cobro_rapido_no_rompe_con_detalle(app, marta):
    import re

    r = post(marta, "/rapido")
    cid = int(re.search(r"/comanda/(\d+)", r.headers["Location"]).group(1))
    agregar(marta, cid, app, "HOJALDRA")
    post(marta, f"/comanda/{cid}/enviar", idem=idem())
    assert cobrar(marta, cuenta_id(app, cid), efectivo="1").status_code == 302
    with app.app_context():
        doc = Documento.query.one()
        detalle = json.loads(doc.detalle)
        assert (
            detalle["pagos"][0]["forma"] == "efectivo"
            and detalle["items"][0]["descripcion"] == "HOJALDRA"
        )
        assert LineaPedido.query.count() == 1
