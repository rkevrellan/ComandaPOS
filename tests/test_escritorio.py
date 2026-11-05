"""Programa de escritorio y arranque: validación de la dirección del servidor y guardias de run.py."""

import escritorio
import run


def test_url_del_servidor_solo_acepta_http_simple():
    assert (
        escritorio._url_servidor("http://192.168.1.10:5000")
        == "http://192.168.1.10:5000"
    )
    assert escritorio._url_servidor(" https://caja.local/ ") == "https://caja.local"
    for malo in (
        "file:///C:/datos",
        "javascript:alert(1)",
        "http://usuario:clave@192.168.1.10:5000",
        "http://192.168.1.10:5000/admin",
        "http://192.168.1.10:5000/?x=1",
        "192.168.1.10:5000",
        "",
    ):
        assert escritorio._url_servidor(malo) is None, malo


def test_no_confunde_otro_programa_con_comandapos():
    assert escritorio._responde("http://127.0.0.1:9") is False


def test_el_depurador_no_se_expone_a_la_red():
    assert run.main(["--dev", "--red"]) == 2
    assert run.main(["--dev", "--host", "0.0.0.0"]) == 2
