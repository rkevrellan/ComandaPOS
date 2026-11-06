"""1.1.1 — Pantalla propia cuando el servidor no responde (service worker) y vigía de conexión."""

import re
import time
from pathlib import Path

from app.config import NOMBRE, VERSION

ESTATICOS = Path(__file__).resolve().parent.parent / "app" / "static"


def test_service_worker_en_la_raiz(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.mimetype == "application/javascript"
    assert r.headers["Service-Worker-Allowed"] == "/"
    js = r.get_data(as_text=True)
    # la versión del service worker sigue a la de la app (así reemplaza la copia anterior)
    assert f'VERSION = "comandapos-{VERSION}"' in js
    # borra cachés ajenas (p. ej., de otra app que usó 127.0.0.1:5000)
    assert "caches.delete" in js and "k !== VERSION" in js


def test_lo_que_guarda_el_service_worker_existe(client):
    js = client.get("/sw.js").get_data(as_text=True)
    rutas = re.findall(r'"(/static/[^"]+[.][a-z]+|/sin-servidor[^"]*)"', js)
    assert "/sin-servidor" in rutas and "/sin-servidor?envio=1" in rutas
    for ruta in rutas:
        assert client.get(ruta).status_code == 200, ruta


def test_pantalla_sin_servidor_publica_y_sin_datos_de_sesion(client):
    html = client.get("/sin-servidor").get_data(as_text=True)
    assert f"El servidor de {NOMBRE} no responde" in html
    assert "data-sin-servidor" in html and "data-envio" not in html
    assert "csrf" not in html.lower()  # no lleva formularios ni datos de una sesión
    # rutas fijas a /static: funciona desde la copia guardada
    assert 'href="/static/css/comanda.css"' in html
    assert 'src="/static/js/sin-servidor.js"' in html


def test_variante_tras_un_envio_avisa_que_puede_no_haberse_guardado(client):
    html = client.get("/sin-servidor?envio=1").get_data(as_text=True)
    assert "data-envio" in html and "no haberse guardado" in html


def test_pantalla_sin_servidor_no_usa_ilustraciones_ajenas(client):
    html = client.get("/sin-servidor").get_data(as_text=True)
    assert "Comanda desconectada del servidor" in html
    assert "manda2" not in html.lower()


def test_sondeo_de_conexion_no_cuenta_como_actividad(como):
    c = como("ana")
    hace_un_rato = time.time() - 30
    with c.session_transaction() as s:
        s["ult"] = hace_un_rato
    assert c.get("/salud", headers={"X-Sondeo": "1"}).status_code == 200
    with c.session_transaction() as s:
        assert (
            s["ult"] == hace_un_rato
        )  # el vigía de conexión no mantiene viva la sesión


def test_interfaz_registra_el_service_worker_y_vigila_la_conexion():
    js = (ESTATICOS / "js" / "comanda.js").read_text(encoding="utf-8")
    assert 'register("/sw.js"' in js and "isSecureContext" in js
    assert '"X-Sondeo": "1"' in js and "aviso-conexion" in js
    # la cocina no recarga a ciegas: primero pregunta si el servidor responde
    bloque = js[js.index("[data-autorecarga]") :]
    assert "servidorResponde()" in bloque
