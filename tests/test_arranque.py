"""Arranque seguro: nada de credenciales de prueba en producción (A05/A07, hallazgo C1 de Manda2)."""

import run
from app.models import Operador
from app.seguridad import validar_clave, validar_pin


def test_detecta_cuentas_con_credenciales_de_prueba(app):
    with app.app_context():
        assert len(run.cuentas_con_clave_de_prueba()) == 6


def test_nuevas_claves_reemplaza_todas_y_son_fuertes(app, capsys):
    with app.app_context():
        assert run.nuevas_claves() == 6
        assert run.cuentas_con_clave_de_prueba() == []
        salida = capsys.readouterr().out
        for linea in salida.splitlines()[1:]:
            usuario, *_, valor = linea.split()
            op = Operador.query.filter_by(usuario=usuario).one()
            assert op.verificar_clave(valor)
            assert (
                validar_pin(valor)
                if op.usa_pin
                else validar_clave(valor, op.usuario, op.nombre)
            ) == []
        assert run.nuevas_claves() == 0  # segunda vez no hay nada que cambiar


def test_produccion_no_arranca_con_credenciales_de_prueba(app, monkeypatch, tmp_path):
    monkeypatch.setenv("COMANDAPOS_PRODUCCION", "1")
    monkeypatch.setenv("COMANDAPOS_DATA", app.config["DATOS"])
    monkeypatch.setattr("sys.argv", ["run.py", "--no-abrir"])
    llamado = []
    monkeypatch.setattr("waitress.serve", lambda *a, **k: llamado.append(1))
    assert run.main() == 1 and not llamado


def test_nombres_demo_se_actualizan_en_una_base_existente(app):
    """Una base creada con un nombre anterior se pone al día al arrancar (sin tocar la clave)."""
    from app.extensions import db
    from seed import poblar

    with app.app_context():
        dev = Operador.query.filter_by(usuario="dev").one()
        hash_antes = dev.clave_hash
        dev.nombre = "Kevin Rojas"
        db.session.commit()
        assert poblar() is False
        dev = Operador.query.filter_by(usuario="dev").one()
        assert dev.nombre == "Kevin Rellán" and dev.clave_hash == hash_antes
