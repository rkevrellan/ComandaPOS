"""Correcciones del diagnóstico — operación, red e impresión:
H-06, H-07, H-08, H-10, H-13, H-15, H-17, H-18, H-20, H-21, H-22."""

import socket
import time

import pytest

from app.extensions import db
from app.models import (
    AreaProduccion,
    Comanda,
    Impresora,
    Insumo,
    Operador,
    Producto,
    RecetaItem,
    Turno,
)
from app.seguridad import CLAVE_DEMO
from app.services import impresion, reportes, tls
from tests.conftest import entrar
from tests.test_salon import abrir, agregar, idem, post


@pytest.fixture
def ana(client):
    entrar(client, "ana")
    return client


def _avisos(r):
    import re

    return " ".join(
        re.findall(r'class="aviso[^"]*"[^>]*>\s*([^<]{3,})<', r.get_data(as_text=True))
    )


# --------------------------------------------------------------------------- H-07
def test_impresora_colgada_no_congela_al_mesero(app, ana):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(0)
    puerto = srv.getsockname()[1]
    relleno = []
    for _ in range(
        3
    ):  # llena la cola de conexiones: las nuevas esperan hasta el tiempo límite
        try:
            relleno.append(socket.create_connection(("127.0.0.1", puerto), timeout=1))
        except OSError:
            break
    try:
        with app.app_context():
            imp = Impresora(
                nombre="Cocina colgada", tipo="red", destino=f"127.0.0.1:{puerto}"
            )
            db.session.add(imp)
            db.session.flush()
            for a in AreaProduccion.query.all():
                a.impresora_id = imp.id
            db.session.commit()
        app.config["IMPRESION_EN_SEGUNDO_PLANO"] = True
        tiempos = []
        for mesa in (3, 4, 6):
            cid = abrir(ana, mesa)
            agregar(ana, cid, app, "TASAJO")
            t = time.time()
            post(ana, f"/comanda/{cid}/enviar", cuenta=1, idem=idem())
            tiempos.append(time.time() - t)
        assert max(tiempos) < 1.0, tiempos  # antes: 4, 8 y 12 s
    finally:
        app.config["IMPRESION_EN_SEGUNDO_PLANO"] = False
        for s in relleno:
            s.close()
        srv.close()


def test_impresora_caida_cuesta_una_espera_por_pasada(app, ana):
    """Sin hilo de fondo: 3 trabajos para una impresora colgada = 1 espera, no 3."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(0)
    puerto = srv.getsockname()[1]
    relleno = []
    for _ in range(3):
        try:
            relleno.append(socket.create_connection(("127.0.0.1", puerto), timeout=1))
        except OSError:
            break
    try:
        app.config["IMPRESION_EN_SEGUNDO_PLANO"] = False
        impresion._DESPERTAR.set()  # si quedó un hilo de otra prueba, termina
        time.sleep(0.1)
        with app.app_context():
            imp = Impresora(nombre="Cocina colgada", tipo="red", destino=f"127.0.0.1:{puerto}")
            db.session.add(imp)
            db.session.flush()
            for _ in range(3):
                impresion.encolar(imp, "prueba", b"x")
            db.session.commit()
            t = time.time()
            impresos, errores = impresion.procesar_pendientes(esperar=True)
            assert errores == 1 and time.time() - t < 6
    finally:
        for s in relleno:
            s.close()
        srv.close()


# --------------------------------------------------------------------------- H-10
def test_corte_z_con_mesa_abierta_exige_supervisor(app, ana, otro):
    cid = abrir(ana, 3)
    agregar(ana, cid, app, "TASAJO")
    post(ana, f"/comanda/{cid}/enviar", cuenta=1, idem=idem())
    marta = otro("marta")
    html = marta.get("/caja").get_data(as_text=True)
    assert "mesa 3 sin cobrar" in html
    r = post(marta, "/caja/cerrar", contado="50.00", justificacion="")
    with app.app_context():
        assert Turno.query.filter_by(cerrado_en=None).count() == 1
    assert "pendientes" in _avisos(marta.get("/caja"))
    post(
        marta, "/caja/cerrar", contado="50.00", sup_usuario="jose", sup_clave=CLAVE_DEMO
    )
    with app.app_context():
        assert Turno.query.filter_by(cerrado_en=None).count() == 0
        from app.models import Auditoria

        detalle = Auditoria.query.filter_by(accion="turno_cerrado").one()
        assert (
            "mesa 3 sin cobrar" in detalle.detalle
            and detalle.autorizador.usuario == "jose"
        )


# --------------------------------------------------------------------------- H-13
def test_no_se_envia_lo_que_el_inventario_no_cubre(app, ana):
    with app.app_context():
        item = (
            RecetaItem.query.join(Producto)
            .filter(Producto.descripcion_corta == "TASAJO")
            .one()
        )
        item.insumo.existencia = item.cantidad * 2  # alcanza para 2
        db.session.commit()
        iid = item.insumo.id
    cid = abrir(ana, 3)
    agregar(ana, cid, app, "TASAJO")
    agregar(ana, cid, app, "TASAJO")
    r = agregar(ana, cid, app, "TASAJO")  # el tercero ya no alcanza
    with app.app_context():
        lineas = [ln for ln in db.session.get(Comanda, cid).cuentas[0].lineas]
        assert len(lineas) == 2
    post(ana, f"/comanda/{cid}/enviar", cuenta=1, idem=idem())
    with app.app_context():
        assert db.session.get(Insumo, iid).existencia == 0  # nunca negativo


def test_otra_mesa_gasto_el_inventario_mientras_tanto(app, ana, otro):
    with app.app_context():
        item = (
            RecetaItem.query.join(Producto)
            .filter(Producto.descripcion_corta == "TASAJO")
            .one()
        )
        item.insumo.existencia = item.cantidad  # alcanza para 1
        db.session.commit()
        iid = item.insumo.id
    luis = otro("luis")
    c1, c2 = abrir(ana, 3), abrir(luis, 4)
    agregar(ana, c1, app, "TASAJO")
    agregar(luis, c2, app, "TASAJO")  # cada mesa por separado sí alcanza
    post(ana, f"/comanda/{c1}/enviar", cuenta=1, idem=idem())
    r = post(luis, f"/comanda/{c2}/enviar", cuenta=1, idem=idem())
    with app.app_context():
        assert db.session.get(Insumo, iid).existencia == 0
        estados = [ln.estado for ln in db.session.get(Comanda, c2).cuentas[0].lineas]
        assert estados == ["PED"]  # el segundo no salió a cocina


# --------------------------------------------------------------------------- H-15
def test_descuento_con_espacios_usa_al_supervisor(app, ana):
    cid = abrir(ana, 3)
    agregar(ana, cid, app, "TASAJO")
    with app.app_context():
        lid = db.session.get(Comanda, cid).cuentas[0].lineas[0].id
    r = post(
        ana,
        f"/linea/{lid}/descuento",
        pct=" 50",
        sup_usuario="jose",
        sup_clave=CLAVE_DEMO,
    )
    assert r.status_code == 302
    with app.app_context():
        from app.models import LineaPedido

        assert db.session.get(LineaPedido, lid).descuento_pct == 50


# --------------------------------------------------------------------------- H-17
@pytest.mark.parametrize(
    "destino",
    [
        "127.0.0.1:9100",
        "169.254.169.254:9100",
        "8.8.8.8:9100",
        "192.168.1.50:80",
        "0.0.0.0:9100",
    ],
)
def test_impresora_de_red_solo_ip_privada_y_puerto_de_impresora(destino):
    with pytest.raises(ValueError):
        impresion.validar_destino("red", destino)


def test_impresora_de_red_valida():
    assert impresion.validar_destino("red", "192.168.1.50") == "192.168.1.50:9100"
    assert impresion.validar_destino("red", "10.0.0.20:9101") == "10.0.0.20:9101"


# --------------------------------------------------------------------------- H-18
def test_mensajes_conservan_la_moneda(app, como):
    c = como("admin")
    with app.app_context():
        p = Producto.query.filter_by(descripcion_corta="SODA LATA").one()
        pid = p.id
    r = post(c, f"/admin/c/productos/{pid}", precio="0", descripcion="x")
    assert "(B/.)" in r.get_data(as_text=True)
    assert "(b/.)" not in r.get_data(as_text=True)


# --------------------------------------------------------------------------- H-20
def test_salud_no_dice_la_version(client):
    datos = client.get("/salud").get_json()
    assert datos == {"ok": True, "app": "ComandaPOS"}


# --------------------------------------------------------------------------- H-21
def test_cedula_enmascarada_en_csv_y_pantalla(app, como, otro):
    assert reportes.enmascarar_cedula("8-123-4567") == "8-***-4567"
    assert reportes.enmascarar_cedula("PE-12-345") == "PE-***-345"
    assert reportes.enmascarar_cedula("123") == "***"
    jose = otro("jose")
    r = jose.get(
        "/reportes/jubilados.csv?cedula=completa"
    )  # un supervisor no la baja completa
    assert r.status_code == 200
    with app.app_context():
        from app.models import Auditoria

        assert (
            "CÉDULA COMPLETA"
            not in Auditoria.query.filter_by(accion="exportacion").one().detalle
        )
    admin = como("admin")
    admin.get("/reportes/jubilados.csv?cedula=completa")
    with app.app_context():
        from app.models import Auditoria

        assert any(
            "CÉDULA COMPLETA" in a.detalle
            for a in Auditoria.query.filter_by(accion="exportacion")
        )


# --------------------------------------------------------------------------- H-22
def test_desactivar_mesero_con_mesas_pide_a_quien_pasarlas(app, ana, otro):
    cid = abrir(ana, 3)
    c = otro("admin")
    with app.app_context():
        aid = Operador.query.filter_by(usuario="ana").one().id
        lid = Operador.query.filter_by(usuario="luis").one().id
    post(
        c, f"/admin/operadores/{aid}", nombre="Ana Pinzón", rol="operador"
    )  # sin «activo»
    with app.app_context():
        assert db.session.get(Operador, aid).activo  # no se desactivó
    post(
        c,
        f"/admin/operadores/{aid}",
        nombre="Ana Pinzón",
        rol="operador",
        reasignar=lid,
    )
    with app.app_context():
        assert not db.session.get(Operador, aid).activo
        assert db.session.get(Comanda, cid).mesero_id == lid


# --------------------------------------------------------------------------- H-06 / H-08
def test_certificados_de_la_red_local(tmp_path):
    from cryptography import x509

    cert, llave, ca = tls.asegurar(str(tmp_path), ["192.168.1.10"])
    with open(cert, "rb") as f:
        c = x509.load_pem_x509_certificate(f.read())
    ips = {
        str(i)
        for i in c.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.IPAddress)
    }
    assert {"192.168.1.10", "127.0.0.1"} <= ips
    import os
    import stat

    if os.name != "nt":
        assert (
            stat.S_IMODE(os.stat(os.path.join(tmp_path, "tls", "ca.key")).st_mode)
            == 0o600
        )
    huella = tls.huella_ca(ca)
    # Misma IP: no se regenera. IP nueva: certificado nuevo con la MISMA CA.
    assert tls.asegurar(str(tmp_path), ["192.168.1.10"])[0] == cert
    with open(cert, "rb") as f:
        antes = f.read()
    tls.asegurar(str(tmp_path), ["192.168.1.22"])
    with open(cert, "rb") as f:
        assert f.read() != antes
    assert tls.huella_ca(ca) == huella


def test_verificar_dependencias():
    import run

    assert run.verificar() == 0
