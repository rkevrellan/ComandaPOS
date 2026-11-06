"""1.2 — Suscripción mensual (SaaS): códigos firmados, planes Básico/Pro, gracia y modo limitado."""

from __future__ import annotations

import base64
import re
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.extensions import db
from app.models import Cliente, Mesa, Operador, PagoSuscripcion
from app.services import configuracion, pedidos, suscripcion
from app.services.calculos import ReglaNegocioError
from tests.conftest import entrar
from tests.test_salon import _comanda_enviada, abrir, cobrar, cuenta_id, post

LLAVE_DEV = Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(
        (Path(__file__).parent / "llave_desarrollo.txt").read_text().strip()
    )
)


@pytest.fixture(autouse=True)
def _llave_de_pruebas(monkeypatch):
    """La app verifica con la pública de pruebas (la del proveedor puede ser otra)."""
    from cryptography.hazmat.primitives import serialization

    publica = LLAVE_DEV.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    monkeypatch.setattr(suscripcion, "LLAVE_PUBLICA", base64.b64encode(publica).decode())


@pytest.fixture
def cobra(app):
    """Las reglas de la suscripción, sobre la base de demostración."""
    app.config["SUSCRIPCION_EN_DEMO"] = True
    return app


@pytest.fixture
def ana(client):
    entrar(client, "ana")
    return client


def _hoy(app) -> date:
    with app.app_context():
        return suscripcion.hoy()


def codigo(app, plan="pro", dias=30, serie=5001, instalacion=None, llave=LLAVE_DEV):
    with app.app_context():
        inst = instalacion or suscripcion.id_instalacion_crudo()
        hasta = suscripcion.hoy() + timedelta(days=dias)
    return suscripcion.armar_codigo(
        suscripcion.Codigo(inst, plan, hasta, serie), llave.sign
    )


def pagar(app, plan="pro", hasta_dias=30, serie=5001):
    """Deja un pago ya activado (sin pasar por la pantalla)."""
    with app.app_context():
        db.session.add(
            PagoSuscripcion(
                serie=serie,
                plan=plan,
                hasta=suscripcion.hoy() + timedelta(days=hasta_dias),
                codigo="prueba",
            )
        )
        db.session.commit()


def estado(app):
    with app.app_context():
        return suscripcion.estado()


# --------------------------------------------------------------------------- códigos
def test_demostracion_es_pro_sin_cobro(app):
    e = estado(app)
    assert e.fase == "demo" and e.pro and not e.limitado and e.aviso is None


def test_id_de_instalacion_estable_y_legible(app):
    with app.app_context():
        uno = suscripcion.id_instalacion()
        assert re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", uno)
        assert suscripcion.id_instalacion() == uno
    archivo = Path(app.config["DATOS"]) / suscripcion.ARCHIVO_ID
    assert archivo.read_text().strip() == uno


def test_codigo_ida_y_vuelta_y_tolerante_al_copiar(cobra):
    texto = codigo(cobra, plan="basico", dias=10, serie=77)
    assert texto.startswith("CPOS-")
    with cobra.app_context():
        leido = suscripcion.leer_codigo(texto)
        assert leido.plan == "basico" and leido.serie == 77
        assert leido.instalacion == suscripcion.id_instalacion_crudo()
        # minúsculas, espacios y saltos de línea al pegarlo desde WhatsApp
        sucio = "  " + texto.lower().replace("-", " ").replace(" ", "\n", 3) + " "
        assert suscripcion.leer_codigo(sucio) == leido


def test_codigo_alterado_o_de_otra_llave_no_vale(cobra):
    texto = codigo(cobra)
    cambiado = texto[:-3] + ("A" if texto[-3] != "A" else "B") + texto[-2:]
    with cobra.app_context():
        with pytest.raises(ReglaNegocioError, match="no es válido|no se pudo leer"):
            suscripcion.leer_codigo(cambiado)
        with pytest.raises(ReglaNegocioError, match="no es válido"):
            suscripcion.leer_codigo(codigo(cobra, llave=Ed25519PrivateKey.generate()))
        with pytest.raises(ReglaNegocioError, match="completo"):
            suscripcion.leer_codigo(texto[:40])


# --------------------------------------------------------------------------- fases
def test_instalacion_nueva_empieza_con_prueba_pro(cobra):
    e = estado(cobra)
    assert e.fase == "prueba" and e.plan == "pro" and e.pro
    assert e.dias == suscripcion.PRUEBA_DIAS - 1


def test_fases_activa_por_vencer_gracia_y_limitada(cobra):
    pagar(cobra, hasta_dias=20, serie=1)
    assert estado(cobra).fase == "activa"
    with cobra.app_context():
        PagoSuscripcion.query.delete()
        db.session.commit()
    pagar(cobra, hasta_dias=3, serie=2)
    e = estado(cobra)
    assert e.fase == "por_vencer" and "vence en 3 días" in e.aviso
    with cobra.app_context():
        PagoSuscripcion.query.delete()
        db.session.commit()
    pagar(cobra, hasta_dias=-2, serie=3)
    e = estado(cobra)
    assert e.fase == "gracia" and not e.limitado and "5 días de gracia" in e.aviso
    with cobra.app_context():
        PagoSuscripcion.query.delete()
        db.session.commit()
    pagar(cobra, hasta_dias=-(suscripcion.GRACIA_DIAS + 1), serie=4)
    e = estado(cobra)
    assert e.fase == "limitada" and e.limitado and not e.pro


def test_atrasar_el_reloj_no_alarga_la_suscripcion(cobra):
    pagar(cobra, hasta_dias=10, serie=9)
    with cobra.app_context():
        futuro = suscripcion.hoy() + timedelta(days=30)
        configuracion.fijar("suscripcion.ultimo_dia", futuro.isoformat())
        db.session.commit()
        # La PC «vuelve» a la fecha real (más atrás): se usa la más alta ya vista.
        assert suscripcion.hoy() == futuro
    assert estado(cobra).fase == "limitada"


# --------------------------------------------------------------------------- activar
def test_activar_codigo_desde_la_pantalla(cobra, como):
    c = como("admin")
    html = c.get("/suscripcion").get_data(as_text=True)
    with cobra.app_context():
        assert suscripcion.id_instalacion() in html
    texto = codigo(cobra, plan="basico", dias=30, serie=3001)
    r = c.post("/suscripcion/activar", data={"codigo": texto, "csrf_token": _token(c)})
    assert r.status_code == 302
    e = estado(cobra)
    assert e.fase == "activa" and e.plan == "basico" and not e.pro
    # el mismo código no se activa dos veces
    r = c.post("/suscripcion/activar", data={"codigo": texto, "csrf_token": _token(c)})
    assert r.status_code == 400 and "ya se activó" in r.get_data(as_text=True)
    with cobra.app_context():
        assert PagoSuscripcion.query.count() == 1


def test_codigo_de_otra_instalacion_o_vencido(cobra):
    with cobra.app_context():
        admin = Operador.query.filter_by(usuario="admin").one()
        with pytest.raises(ReglaNegocioError, match="otra instalación"):
            suscripcion.activar(codigo(cobra, instalacion=b"\x01" * 10), admin)
        with pytest.raises(ReglaNegocioError, match="ya venció"):
            suscripcion.activar(codigo(cobra, dias=-1, serie=8), admin)


def test_solo_administracion_ve_la_suscripcion(cobra, como):
    assert como("marta").get("/suscripcion").status_code == 403


def _token(c) -> str:
    html = c.get("/suscripcion").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


# --------------------------------------------------------------------------- planes
def test_basico_lleva_las_pantallas_pro_a_la_explicacion(cobra, como):
    pagar(cobra, plan="basico")
    c = como("admin")
    for ruta, funcion in (
        ("/cocina", "cocina"),
        ("/reportes/", "reportes"),
        ("/admin/inventario", "inventario"),
        ("/admin/c/insumos", "inventario"),
    ):
        r = c.get(ruta)
        assert r.status_code == 302 and r.headers["Location"].endswith(
            f"/plan-pro/{funcion}"
        ), ruta
    r = c.get("/plan-pro/cocina")
    assert r.status_code == 403 and "es parte del plan Pro" in r.get_data(as_text=True)
    # lo del plan Básico sigue abierto
    for ruta in ("/mesas", "/caja", "/admin/", "/admin/c/productos"):
        assert c.get(ruta).status_code == 200, ruta


def test_pro_abre_todo(cobra, como):
    pagar(cobra, plan="pro")
    c = como("admin")
    for ruta in ("/cocina", "/reportes/", "/admin/inventario"):
        assert c.get(ruta).status_code == 200, ruta


def test_basico_no_atiende_terminales_en_red(cobra, client):
    with cobra.app_context():
        configuracion.fijar("red.terminales", "192.168.1.0/24")
        db.session.commit()
    pagar(cobra, plan="basico")
    r = client.get("/acceso", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/plan-pro/red")
    r = client.get("/plan-pro/red", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403 and "Terminales en red" in r.get_data(as_text=True)
    # en este mismo equipo sí
    assert client.get("/acceso").status_code == 200


def test_basico_no_vende_a_credito(cobra, ana, otro):
    pagar(cobra, plan="basico")
    cid = _comanda_enviada(cobra, ana)
    cta = cuenta_id(cobra, cid)
    marta = otro("marta")
    with cobra.app_context():
        agro = Cliente.query.filter(Cliente.ruc == "155700001-2-2026").one()
        agro.limite_credito = D("50.00")
        db.session.commit()
        agro_id = agro.id
    post(marta, f"/cuenta/{cta}/cliente", cliente=agro_id)
    r = cobrar(marta, cta, credito="5.62")
    assert r.status_code == 422 and "plan Pro" in r.get_data(as_text=True)
    assert cobrar(marta, cta, efectivo="10").status_code == 302


# --------------------------------------------------------------------------- modo limitado
def test_modo_limitado_no_abre_mesas_pero_termina_lo_abierto(cobra, ana, otro):
    cid = _comanda_enviada(cobra, ana)  # abierta antes de vencer
    pagar(cobra, hasta_dias=-(suscripcion.GRACIA_DIAS + 2), serie=11)
    r = post(ana, "/mesas/6/abrir", puestos=2)
    assert "modo limitado" in r.get_data(as_text=True) or r.status_code in (302, 422)
    with cobra.app_context():
        assert (
            db.session.get(Mesa, 6) is None
            or Mesa.query.filter_by(numero=6).one().estado == "disponible"
        )
        with pytest.raises(ReglaNegocioError, match="modo limitado"):
            pedidos.abrir_rapida(Operador.query.filter_by(usuario="ana").one())
    # la cuenta que ya estaba abierta se cobra y se factura
    assert (
        cobrar(otro("marta"), cuenta_id(cobra, cid), efectivo="10").status_code == 302
    )


def test_barra_de_aviso_para_el_personal(cobra, como):
    pagar(cobra, hasta_dias=-1, serie=12)
    html = como("marta").get("/mesas").get_data(as_text=True)
    assert "de gracia" in html and "Avisa a administración" in html


def test_build_no_empaqueta_con_la_llave_de_pruebas(monkeypatch):
    import run
    from app.services import llave_proveedor

    monkeypatch.setattr(llave_proveedor, "ES_DE_DESARROLLO", True)
    assert run.verificar_llave() == 1
    monkeypatch.setattr(llave_proveedor, "ES_DE_DESARROLLO", False)
    assert run.verificar_llave() == 0


def test_herramienta_del_proveedor_alarga_desde_el_ultimo_vencimiento(
    cobra, tmp_path, monkeypatch, capsys
):
    from proveedor import emitir_codigo as herramienta

    monkeypatch.setattr(herramienta, "CARPETA", tmp_path / "proveedor")
    with cobra.app_context():
        inst = suscripcion.id_instalacion()
    base = ["emitir", "--instalacion", inst, "--plan", "pro", "--desarrollo"]
    herramienta.main(base + ["--cliente", "El Fogón"])
    primero = capsys.readouterr().out.strip().splitlines()[-1]
    herramienta.main(base)
    segundo = capsys.readouterr().out.strip().splitlines()[-1]
    with cobra.app_context():
        a, b = suscripcion.leer_codigo(primero), suscripcion.leer_codigo(segundo)
    assert b.serie == a.serie + 1
    assert b.hasta > a.hasta + timedelta(
        days=27
    )  # el segundo mes empieza al acabar el primero


def test_crear_llave_del_proveedor_y_emitir_con_ella(cobra, tmp_path, monkeypatch, capsys):
    import shutil

    from proveedor import emitir_codigo as herramienta

    copia = tmp_path / "llave_proveedor.py"
    shutil.copy(herramienta.ARCHIVO_LLAVE_PUBLICA, copia)
    monkeypatch.setattr(herramienta, "CARPETA", tmp_path / "proveedor")
    monkeypatch.setattr(herramienta, "ARCHIVO_LLAVE_PUBLICA", copia)
    herramienta.main(["crear-llave"])
    texto = copia.read_text(encoding="utf-8")
    assert "ES_DE_DESARROLLO = False" in texto
    publica = re.search(r'LLAVE_PUBLICA = "([^"]+)"', texto).group(1)
    with pytest.raises(SystemExit):  # no pisa una llave existente sin --reemplazar
        herramienta.main(["crear-llave"])
    with cobra.app_context():
        inst = suscripcion.id_instalacion()
    capsys.readouterr()
    herramienta.main(["emitir", "--instalacion", inst, "--plan", "basico"])
    emitido = capsys.readouterr().out.strip().splitlines()[-1]
    with cobra.app_context():
        assert suscripcion.leer_codigo(emitido, publica).plan == "basico"
        with pytest.raises(ReglaNegocioError):
            suscripcion.leer_codigo(emitido)  # la llave de pruebas no la acepta
