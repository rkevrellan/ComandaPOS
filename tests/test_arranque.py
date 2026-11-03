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
