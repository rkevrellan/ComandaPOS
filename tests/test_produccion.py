"""H-01 / H-03: puesta en producción limpia, modo guardado y credenciales de prueba fuera de la red."""

import os
import tempfile

import pytest

from app import create_app
from app.config import fijar_modo, modo_demo
from app.extensions import db
from app.models import Mesa, Operador, Producto
from app.services import configuracion
from tests.conftest import csrf, entrar


@pytest.fixture
def prod(monkeypatch):
    """Una instalación nueva en producción (carpeta de datos vacía)."""
    monkeypatch.delenv("COMANDAPOS_PRODUCCION", raising=False)
    datos = tempfile.mkdtemp()
    fijar_modo(datos, produccion=True)
    app = create_app({"TESTING": True, "DATOS": datos})
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def test_modo_por_archivo_y_variable(monkeypatch, tmp_path):
    monkeypatch.delenv("COMANDAPOS_PRODUCCION", raising=False)
    assert modo_demo(str(tmp_path)) is True  # sin archivo: desarrollo = demostración
    fijar_modo(str(tmp_path), produccion=True)
    assert modo_demo(str(tmp_path)) is False
    monkeypatch.setenv("COMANDAPOS_PRODUCCION", "0")
    assert modo_demo(str(tmp_path)) is True  # la variable manda


def test_produccion_arranca_sin_datos_de_prueba(prod):
    assert prod.config["DEMO"] is False
    with prod.app_context():
        assert Operador.query.count() == 0
        assert configuracion.obtener("emisor.ruc") == ""
        assert configuracion.obtener("fiscal.proveedor") == "ninguno"
        assert not configuracion.base_es_demo()


def test_primer_administrador_solo_desde_este_equipo(prod):
    lejos = prod.test_client()
    lejos.environ_base["REMOTE_ADDR"] = "192.168.1.40"
    with prod.app_context():
        configuracion.fijar("red.terminales", "192.168.1.0/24")
        db.session.commit()
    assert lejos.get("/primer-inicio").status_code == 403

    c = prod.test_client()
    r = c.get("/acceso")
    assert r.status_code == 302 and r.headers["Location"].endswith("/primer-inicio")
    token = csrf(c, "/primer-inicio")
    r = c.post(
        "/primer-inicio",
        data={
            "usuario": "gerente",
            "nombre": "Gerencia General",
            "clave": "corta",
            "repetir": "corta",
            "csrf_token": token,
        },
    )
    assert r.status_code == 422
    r = c.post(
        "/primer-inicio",
        data={
            "usuario": "gerente",
            "nombre": "Gerencia General",
            "clave": "Fogon-Real-2026",
            "repetir": "Fogon-Real-2026",
            "ejemplo": "1",
            "csrf_token": token,
        },
    )
    assert r.status_code == 302
    with prod.app_context():
        op = Operador.query.one()
        assert (op.usuario, op.rol) == ("gerente", "administrador")
        assert Mesa.query.count() == 38 and Producto.query.count() > 50
        assert (
            Operador.query.filter_by(usuario="ana").count() == 0
        )  # sin usuarios de prueba
        assert not configuracion.base_es_demo()
    # Ya existe un administrador: la página desaparece
    assert c.get("/primer-inicio").status_code == 302
    # Y al entrar exige activar la verificación en dos pasos
    assert entrar(c, "gerente", "Fogon-Real-2026").status_code == 302
    r = c.get("/mesas")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cuenta")


def test_produccion_no_factura_sin_emisor(prod):
    from app.models import Comanda
    from app.services import caja, pedidos
    from app.services.calculos import ReglaNegocioError
    from seed import crear_catalogo

    with prod.app_context():
        assert configuracion.emisor_incompleto() == ["razón social", "RUC", "DV", "dirección"]
        jefe = Operador(codigo=1, nombre="Gerencia", usuario="gerente", rol="administrador")
        jefe.fijar_clave("Fogon-Real-2026")
        db.session.add(jefe)
        crear_catalogo(demo=False)
        db.session.commit()
        caja.abrir_turno(jefe, "50.00")
        comanda = pedidos.abrir_mesa(Mesa.query.filter_by(numero=1).one(), jefe, 2)
        db.session.flush()
        with pytest.raises(ReglaNegocioError, match="faltan datos del emisor"):
            caja.cobrar(comanda.cuentas[0], {}, jefe)
        assert isinstance(comanda, Comanda)


def test_base_de_demo_no_arranca_en_produccion(app, monkeypatch):
    import run

    datos = app.config["DATOS"]
    with app.app_context():
        assert configuracion.base_es_demo()
    fijar_modo(datos, produccion=True)
    monkeypatch.delenv("COMANDAPOS_PRODUCCION", raising=False)
    prod = create_app({"TESTING": True, "DATOS": datos})
    assert run.preparar(prod) == run.SALIDA_BASE_DEMO
    with prod.app_context():
        db.session.remove()
        db.engine.dispose()
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    destino = run.apartar_base(datos)
    assert os.path.exists(os.path.join(destino, "comandapos.db"))
    assert not os.path.exists(os.path.join(datos, "comandapos.db"))
    limpia = create_app({"TESTING": True, "DATOS": datos})
    assert run.preparar(limpia) is None
    with limpia.app_context():
        assert Operador.query.count() == 0


def test_credenciales_de_prueba_solo_en_este_equipo(app):
    local = app.test_client().get("/acceso").get_data(as_text=True)
    assert "comandapos123" in local
    lejos = app.test_client()
    lejos.environ_base["REMOTE_ADDR"] = "192.168.1.40"
    with app.app_context():
        configuracion.fijar("red.terminales", "192.168.1.0/24")
        db.session.commit()
    html = lejos.get("/acceso").get_data(as_text=True)
    assert "comandapos123" not in html and "246810" not in html
