"""Correcciones del diagnóstico — ciclo fiscal: H-02 (rechazados), H-04 (redirecciones del PAC),
H-09 (credencial del PAC por equipo), H-11 (folios agotados) y H-12/H-19 (reportes)."""

import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.extensions import db
from app.models import Auditoria, Config, Documento
from app.services import configuracion, fiscal, reportes, secretos
from tests.conftest import entrar
from tests.test_final_caja import _cobrada
from tests.test_salon import post


@pytest.fixture
def marta(otro):
    return otro("marta")


def _servidor(manejador):
    srv = HTTPServer(("127.0.0.1", 0), manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


class _PacAutoriza(BaseHTTPRequestHandler):
    recibidos: list = []

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        _PacAutoriza.recibidos.append(json.loads(self.rfile.read(largo)))
        cuerpo = json.dumps(
            {
                "estado": "autorizado",
                "cufe": f"FE01-REAL-{len(self.recibidos)}",
                "protocolo": "P1",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass


def _usar_pac_http(app, url, monkeypatch, token="TOKEN-DE-PRUEBA"):
    monkeypatch.setenv("COMANDAPOS_PAC_TOKEN", token)
    with app.app_context():
        configuracion.fijar("fiscal.proveedor", "http")
        configuracion.fijar("fiscal.pac_url", url)
        db.session.commit()


# --------------------------------------------------------------------------- H-02
def test_rechazado_se_corrige_y_se_reenvia_con_el_mismo_numero(app, client, marta):
    entrar(client, "ana")
    did = _cobrada(app, client, marta)
    with app.app_context():
        doc = db.session.get(Documento, did)
        doc.estado, doc.mensaje = "rechazado", "RUC del receptor inválido"
        numero = doc.numero
        db.session.commit()
    html = marta.get("/caja").get_data(as_text=True)
    assert "rechazado" in html and "corrígelos" in html
    # RUC mal escrito: no se reenvía
    post(
        marta,
        f"/documento/{did}/corregir",
        tipo="contribuyente",
        ruc="abc",
        dv="5",
        nombre="X",
    )
    with app.app_context():
        assert db.session.get(Documento, did).estado == "rechazado"
    r = post(
        marta,
        f"/documento/{did}/corregir",
        tipo="contribuyente",
        ruc="155612345-2-2026",
        dv="45",
        nombre="Constructora Ejemplo, S.A.",
    )
    assert r.status_code == 302
    with app.app_context():
        doc = db.session.get(Documento, did)
        assert doc.estado == "simulado" and doc.numero == numero
        assert (doc.receptor_ruc, doc.receptor_dv) == ("155612345-2-2026", "45")
        detalle = Auditoria.query.filter_by(accion="fiscal_correccion").one().detalle
        assert "CONSUMIDOR FINAL" in detalle and "155612345-2-2026" in detalle


def test_rechazado_se_puede_reenviar_sin_cambios(app, client, marta):
    entrar(client, "ana")
    did = _cobrada(app, client, marta)
    with app.app_context():
        db.session.get(Documento, did).estado = "rechazado"
        db.session.commit()
    post(marta, f"/documento/{did}/reintentar")
    with app.app_context():
        assert db.session.get(Documento, did).estado == "simulado"


def test_solo_un_cajero_corrige(app, client, marta):
    entrar(client, "ana")
    did = _cobrada(app, client, marta)
    with app.app_context():
        db.session.get(Documento, did).estado = "rechazado"
        db.session.commit()
    r = post(client, f"/documento/{did}/corregir", tipo="consumidor", nombre="Ana")
    assert r.status_code in (302, 403)
    with app.app_context():
        assert db.session.get(Documento, did).estado == "rechazado"


# --------------------------------------------------------------------------- H-04
def test_pac_que_redirige_no_recibe_la_credencial(app, client, marta, monkeypatch):
    vistos = []

    class Otro(BaseHTTPRequestHandler):
        def do_GET(self):
            vistos.append(self.headers.get("Authorization"))
            cuerpo = b'{"estado": "autorizado", "cufe": "FALSO"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *a):
            pass

    otro_srv, otro_url = _servidor(Otro)

    class Redirige(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", otro_url + "/robar")
            self.end_headers()

        def log_message(self, *a):
            pass

    pac_srv, pac_url = _servidor(Redirige)
    try:
        _usar_pac_http(app, pac_url + "/emitir", monkeypatch)
        entrar(client, "ana")
        did = _cobrada(app, client, marta)
        with app.app_context():
            doc = db.session.get(Documento, did)
            assert doc.estado == "contingencia" and doc.cufe != "FALSO"
        assert vistos == []  # la credencial nunca salió hacia el otro servidor
    finally:
        pac_srv.shutdown()
        otro_srv.shutdown()


# --------------------------------------------------------------------------- H-11
def test_folios_agotados_dejan_en_contingencia_y_avisan(
    app, client, marta, monkeypatch
):
    srv, url = _servidor(_PacAutoriza)
    try:
        _usar_pac_http(app, url + "/emitir", monkeypatch)
        entrar(client, "ana")
        primero = _cobrada(app, client, marta, mesa=5)
        with app.app_context():
            assert db.session.get(Documento, primero).estado == "autorizado"
            configuracion.fijar("fiscal.folios_total", "1")
            db.session.commit()
        html = marta.get("/caja").get_data(as_text=True)
        assert "Folios agotados" in html
        segundo = _cobrada(app, client, marta, mesa=6)
        with app.app_context():
            doc = db.session.get(Documento, segundo)
            assert doc.estado == "contingencia" and "Folios agotados" in doc.mensaje
            assert fiscal.folios()["usados"] == 1  # nunca más usados que comprados
            configuracion.fijar("fiscal.folios_total", "100")
            db.session.commit()
        post(marta, "/caja/fiscal/reenviar")
        with app.app_context():
            assert db.session.get(Documento, segundo).estado == "autorizado"
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------- H-09
def test_credencial_del_pac_en_archivo_protegido(app, admin_c):
    r = post(admin_c, "/admin/configuracion/pac-token", token="secreto-del-pac-123")
    assert r.status_code == 302
    ruta = os.path.join(app.config["DATOS"], "pac.credencial")
    assert os.path.exists(ruta)
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600
    with open(ruta, "rb") as f:
        assert b"secreto-del-pac-123" not in f.read()  # ni en texto plano directo
    with app.test_request_context():
        assert secretos.leer("pac") == "secreto-del-pac-123"
        assert fiscal._token_pac() == "secreto-del-pac-123"
        assert all("secreto" not in (c.valor or "") for c in Config.query.all())


def test_aviso_cuando_el_pac_no_tiene_credencial(app, monkeypatch):
    monkeypatch.delenv("COMANDAPOS_PAC_TOKEN", raising=False)
    with app.test_request_context():
        configuracion.fijar("fiscal.proveedor", "http")
        configuracion.fijar("fiscal.pac_url", "https://pac.ejemplo.pa/emitir")
        db.session.commit()
        assert any("no tiene credencial" in a for a in fiscal.avisos())


@pytest.fixture
def admin_c(otro):
    return otro("admin")


# --------------------------------------------------------------------------- H-12 / H-19
def test_reportes_no_cuentan_rechazados(app, client, marta, otro):
    entrar(client, "ana")
    bueno = _cobrada(app, client, marta, mesa=5)
    malo = _cobrada(app, client, marta, mesa=6)
    with app.app_context():
        db.session.get(Documento, malo).estado = "rechazado"
        db.session.commit()
        inicio, fin, _d, _h = reportes.rango(None, None)
        r = reportes.calcular(inicio, fin)
        total_bueno = db.session.get(Documento, bueno).total
        total_malo = db.session.get(Documento, malo).total
        assert r["documentos"] == 1 and r["ventas"] == total_bueno
        assert r["rechazados"] == (1, total_malo)
        assert r["itbms_total"] == db.session.get(Documento, bueno).itbms
        assert r["por_mesero"] == [("Ana Pinzón", [1, total_bueno])]
    html = otro("jose").get("/reportes/").get_data(as_text=True)
    assert "rechazado(s) por el PAC" in html
