"""Acceso, roles, sesión, CSRF y cabeceras (OWASP A01, A05, A07)."""

import time

import pytest

from app.extensions import db
from app.models import Auditoria, Operador
from app.seguridad import (
    CLAVE_DEMO,
    PIN_DEMO,
    destino_seguro,
    validar_clave,
    validar_pin,
)
from tests.conftest import csrf, entrar


# ---------------------------------------------------------------- acceso
def test_pantalla_de_acceso_con_teclado(client):
    html = client.get("/acceso").get_data(as_text=True)
    assert "Control de acceso" in html and 'data-tecla="Q"' in html and "CLR" in html


def test_inicio_sin_sesion_va_al_acceso(client):
    assert client.get("/").headers["Location"].endswith("/acceso")
    assert "/acceso" in client.get("/mesas").headers["Location"]


def test_acceso_correcto_con_pin_y_con_contrasena(client):
    r = entrar(client, "ana")
    assert r.status_code == 302 and r.headers["Location"].endswith("/mesas")
    html = client.get("/mesas").get_data(as_text=True)
    assert "Ana Pinzón" in html and "ocupación de mesas" in html
    client.post("/salir", data={"csrf_token": csrf(client, "/mesas")})
    assert entrar(client, "dev").status_code == 302


def test_acceso_incorrecto_mensaje_unico(client):
    r1 = entrar(client, "ana", "999999")
    r2 = entrar(client, "fantasma", "999999")
    assert r1.status_code == r2.status_code == 401
    t1, t2 = r1.get_data(as_text=True), r2.get_data(as_text=True)
    assert "Usuario o clave incorrectos." in t1 and "Usuario o clave incorrectos." in t2


def test_bloqueo_tras_cinco_fallos(client):
    for _ in range(5):
        assert entrar(client, "luis", "000000").status_code == 401
    r = entrar(client, "luis", PIN_DEMO)  # aunque ahora sea correcta
    assert r.status_code == 429 and "Demasiados intentos" in r.get_data(as_text=True)


def test_bloqueo_por_terminal_aunque_rote_usuarios(client):
    for i in range(30):
        entrar(client, f"inventado{i}", "x")
    assert entrar(client, "ana").status_code == 429


def test_operador_inactivo_no_entra(app, client):
    with app.app_context():
        Operador.query.filter_by(usuario="luis").one().activo = False
        db.session.commit()
    assert entrar(client, "luis").status_code == 401


def test_acceso_se_audita(app, client):
    entrar(client, "ana", "111112")
    entrar(client, "ana")
    with app.app_context():
        acciones = [a.accion for a in Auditoria.query.order_by(Auditoria.id).all()]
        assert "acceso_fallido" in acciones and "acceso" in acciones
        assert (
            Auditoria.query.filter(Auditoria.sello.is_(None)).count() == 0
        )  # sellado al final


def test_sesion_rotada_al_entrar(client):
    client.get("/acceso")
    with client.session_transaction() as s:
        s["marca_atacante"] = "x"
    entrar(client, "ana")
    with client.session_transaction() as s:
        assert "marca_atacante" not in s


def test_redireccion_solo_interna(client):
    token = csrf(client)
    r = client.post(
        "/acceso?siguiente=//malo.com",
        data={"usuario": "ana", "clave": PIN_DEMO, "csrf_token": token},
    )
    assert r.headers["Location"].endswith("/mesas")


@pytest.mark.parametrize(
    "destino",
    ["//malo.com", "https://malo.com", "/\\malo.com", "javascript:alert(1)", "malo"],
)
def test_destino_seguro_rechaza(destino):
    assert destino_seguro(destino, "/mesas") == "/mesas"


def test_salir_solo_por_post(como):
    c = como("ana")
    assert c.get("/salir").status_code == 405


def test_cambiar_clave_invalida_sesiones_abiertas(app, como):
    c = como("ana")
    with app.app_context():
        op = Operador.query.filter_by(usuario="ana").one()
        op.fijar_clave("852963")
        db.session.commit()
    assert "/acceso" in c.get("/mesas").headers["Location"]


def test_bloqueo_por_inactividad(app, como):
    c = como("ana")
    with c.session_transaction() as s:
        s["ult"] = time.time() - app.config["INACTIVIDAD_SEG"]["operador"] - 5
    r = c.get("/mesas")
    assert r.status_code == 302 and "/acceso" in r.headers["Location"]


# ---------------------------------------------------------------- roles (A01)
def test_cada_ruta_declara_publica_o_roles(app):
    sin_marca = []
    for regla in app.url_map.iter_rules():
        if regla.endpoint == "static":
            continue
        vista = app.view_functions[regla.endpoint]
        if not getattr(vista, "_publica", False) and not getattr(vista, "_roles", None):
            sin_marca.append(regla.rule)
    assert not sin_marca, f"Rutas sin @publica ni @rol_requerido: {sin_marca}"


@pytest.mark.parametrize("usuario", ["ana", "marta", "jose", "admin"])
def test_consola_solo_para_programador(como, usuario):
    assert como(usuario).get("/dev/").status_code == 403


def test_consola_del_programador(como):
    c = como("dev")
    html = c.get("/dev/").get_data(as_text=True)
    assert "Cadena íntegra" in html and "comanda" in html
    assert "Cadena íntegra" in c.get("/dev/auditoria").get_data(as_text=True)


def test_acceso_denegado_se_audita(app, como):
    como("ana").get("/dev/")
    with app.app_context():
        assert Auditoria.query.filter_by(accion="acceso_denegado").count() == 1


# ---------------------------------------------------------------- CSRF y cabeceras
def test_csrf_obligatorio(client):
    r = client.post("/acceso", data={"usuario": "ana", "clave": PIN_DEMO})
    assert r.status_code == 400


def test_cabeceras_de_seguridad(client):
    r = client.get("/acceso")
    h = r.headers
    assert "script-src 'self'" in h["Content-Security-Policy"]
    assert "'unsafe-inline'" not in h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Cache-Control"] == "no-store"
    assert "Server" not in h


def test_cookie_de_sesion_protegida(client):
    r = entrar(client, "ana")
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_sin_javascript_en_linea(como):
    html = como("dev").get("/mesas").get_data(as_text=True)
    assert "<script>" not in html and "onclick=" not in html


def test_errores_genericos(client):
    r = client.get("/no-existe")
    assert r.status_code == 404 and "Traceback" not in r.get_data(as_text=True)


# ---------------------------------------------------------------- políticas de PIN y clave
@pytest.mark.parametrize(
    "pin",
    ["123456", "000000", "12345", "1234567", "abcdef", "987654", "112233", "345678"],
)
def test_pin_trivial_o_mal_formado(pin):
    assert validar_pin(pin)


@pytest.mark.parametrize("pin", [PIN_DEMO, "852963", "305817"])
def test_pin_valido(pin):
    assert validar_pin(pin) == []


def test_politica_de_contrasenas():
    assert validar_clave("corta1")
    assert validar_clave("comandapos123")
    assert validar_clave("solamenteletras")
    assert validar_clave("josesamudio2026", usuario="jose", nombre="José Samudio")
    assert validar_clave("Brisa-del-Baru-42") == []
    assert validar_clave(
        CLAVE_DEMO
    )  # la de demostración es común a propósito: nunca en producción
