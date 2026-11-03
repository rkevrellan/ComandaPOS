"""RN-04 secuencias atómicas, tipo Dinero exacto y auditoría encadenada (A08/A09)."""

import json
import os
import threading
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models import Auditoria, Producto
from app.services import auditoria, secuencias
from app.services.calculos import ReglaNegocioError


# ---------------------------------------------------------------- RN-04
def test_rn04_secuencia_sin_duplicados_ni_huecos_con_hilos(app):
    resultados, errores = [], []

    def trabajador():
        for _ in range(25):
            with app.app_context():
                try:
                    n = secuencias.siguiente("comanda")
                    db.session.commit()
                    resultados.append(n)
                except Exception as e:  # pragma: no cover - se reporta abajo
                    db.session.rollback()
                    errores.append(repr(e))

    hilos = [threading.Thread(target=trabajador) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert not errores
    assert sorted(resultados) == list(range(1, 201))


def test_rn04_numero_revertido_vuelve(app):
    with app.app_context():
        assert secuencias.siguiente("factura") == 1
        db.session.rollback()
        assert secuencias.siguiente("factura") == 1
        db.session.commit()
        assert secuencias.actual("factura") == 1


def test_rn04_secuencia_desconocida(app):
    with app.app_context(), pytest.raises(ReglaNegocioError):
        secuencias.siguiente("no-existe")


# ---------------------------------------------------------------- Dinero
def test_dinero_se_guarda_exacto_en_centavos(app):
    with app.app_context():
        p = Producto.query.filter_by(descripcion_corta="CONCHA A LA CRIOLLA").one()
        assert p.precio == D("8.95") and isinstance(p.precio, D)
        crudo = db.session.execute(
            text("SELECT precio FROM productos WHERE id=:i"), {"i": p.id}
        ).scalar()
        assert crudo == 895  # entero, nunca float
        p.precio = D("0.1") + D("0.2")
        db.session.commit()
        db.session.refresh(p)
        assert p.precio == D("0.30")


def test_dinero_rechaza_mas_de_dos_decimales(app):
    with app.app_context():
        p = Producto.query.first()
        p.precio = D("1.005")
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_tasa_itbms_restringida_en_la_base(app):
    with app.app_context():
        p = Producto.query.first()
        p.tasa_itbms = 8
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


# ---------------------------------------------------------------- auditoría
def _registrar(app, n=3):
    with app.app_context():
        for i in range(n):
            auditoria.auditar("prueba", f"registro {i}")
        db.session.commit()
        auditoria.sellar_pendientes()


def test_cadena_integra(app):
    _registrar(app)
    with app.app_context():
        v = auditoria.verificar()
        assert v["ok"], v
        assert v["sellados"] >= 4 and v["pendientes"] == 0


def test_detecta_registro_editado(app):
    _registrar(app)
    with app.app_context():
        db.session.execute(
            text("UPDATE auditoria SET detalle='nada pasó' WHERE detalle='registro 1'")
        )
        db.session.commit()
        v = auditoria.verificar()
        assert not v["ok"] and "modificado" in v["error"]


def test_detecta_registro_borrado_del_medio(app):
    _registrar(app)
    with app.app_context():
        db.session.execute(text("DELETE FROM auditoria WHERE detalle='registro 1'"))
        db.session.commit()
        v = auditoria.verificar()
        assert not v["ok"] and "borrado" in v["error"]


def test_detecta_ultimos_registros_truncados(app):
    _registrar(app)
    with app.app_context():
        maximo = db.session.execute(text("SELECT MAX(sello) FROM auditoria")).scalar()
        db.session.execute(text("DELETE FROM auditoria WHERE sello=:s"), {"s": maximo})
        db.session.commit()
        v = auditoria.verificar()
        assert not v["ok"] and "últimos" in v["error"]


def test_detecta_ancla_alterada_o_faltante(app):
    _registrar(app)
    with app.app_context():
        ruta = os.path.join(app.config["DATOS"], "auditoria.ancla")
        with open(ruta, encoding="utf-8") as f:
            ancla = json.load(f)
        ancla["sello"] = 1
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(ancla, f)
        assert "alterado" in auditoria.verificar()["error"]
        os.remove(ruta)
        assert "ancla" in auditoria.verificar()["error"]


def test_recalcular_sin_la_clave_no_sirve(app):
    """Quien edita la base y recalcula SHA-256 «a mano» no tiene la llave del HMAC."""
    import hashlib

    _registrar(app)
    with app.app_context():
        r = Auditoria.query.filter_by(detalle="registro 2").one()
        falso = hashlib.sha256(b"intento").hexdigest()
        db.session.execute(
            text("UPDATE auditoria SET detalle='editado', hash=:h WHERE id=:i"),
            {"h": falso, "i": r.id},
        )
        db.session.commit()
        assert not auditoria.verificar()["ok"]


def test_auditoria_concurrente_mantiene_la_cadena(app):
    def trabajador(k):
        with app.app_context():
            for i in range(10):
                auditoria.auditar("hilo", f"{k}-{i}")
                db.session.commit()
                auditoria.sellar_pendientes()

    hilos = [threading.Thread(target=trabajador, args=(k,)) for k in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    with app.app_context():
        v = auditoria.verificar()
        assert v["ok"], v
        assert Auditoria.query.filter_by(accion="hilo").count() == 60


def test_auditoria_limpia_caracteres_de_control(app):
    with app.app_context():
        r = auditoria.auditar("x\nfalso", "linea1\r\nlinea2\x1b[31m")
        db.session.commit()
        assert (
            "\n" not in r.accion and "\n" not in r.detalle and "\x1b" not in r.detalle
        )


def test_auditoria_se_revierte_con_la_operacion(app):
    with app.app_context():
        antes = Auditoria.query.count()
        auditoria.auditar("anulacion", "debe desaparecer")
        db.session.rollback()
        assert Auditoria.query.count() == antes
