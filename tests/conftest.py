"""Fixtures: cada prueba usa una carpeta de datos nueva (base, clave secreta y ancla propias)."""

from __future__ import annotations

import re

import pytest

from app import create_app
from app import seguridad
from app.extensions import db
from app.seguridad import (
    ACCESO,
    ACCESO_TERMINAL,
    AUTORIZACION,
    CLAVE_DEMO,
    DOS_PASOS,
    PIN_DEMO,
    REAUTENTICAR,
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("COMANDAPOS_PRODUCCION", raising=False)
    monkeypatch.delenv("COMANDAPOS_DB", raising=False)
    monkeypatch.delenv("COMANDAPOS_SECRET", raising=False)
    aplicacion = create_app({"TESTING": True, "DATOS": str(tmp_path)})
    with aplicacion.app_context():
        from seed import poblar

        poblar()
    for limitador in (ACCESO, ACCESO_TERMINAL, AUTORIZACION, DOS_PASOS, REAUTENTICAR):
        limitador.reiniciar()
    seguridad._ULTIMO_EVENTO.clear()
    seguridad.EVENTOS.clear()
    yield aplicacion
    with aplicacion.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, ruta="/acceso") -> str:
    html = client.get(ruta).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "la pantalla no trae token CSRF"
    return m.group(1)


def entrar(client, usuario: str, clave: str | None = None):
    if clave is None:
        clave = PIN_DEMO if usuario in ("ana", "luis", "marta") else CLAVE_DEMO
    token = csrf(client)
    return client.post(
        "/acceso", data={"usuario": usuario, "clave": clave, "csrf_token": token}
    )


@pytest.fixture
def como(client):
    """`como("dev")` deja al cliente con la sesión de ese usuario de demostración."""

    def _como(usuario: str):
        r = entrar(client, usuario)
        assert r.status_code == 302, r.get_data(as_text=True)[:300]
        return client

    return _como


@pytest.fixture
def otro(app):
    """Otra terminal con su propia sesión: `otro("marta")`."""

    def _otro(usuario: str):
        c = app.test_client()
        assert entrar(c, usuario).status_code == 302
        return c

    return _otro
