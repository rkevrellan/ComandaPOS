"""Fase final — administración (catálogos, operadores, configuración), verificación en dos pasos,
reportes con CSV seguro y lista de terminales permitidas en la red local."""

import re

import pytest

from app.extensions import db
from app.models import Auditoria, Operador, Producto, Seccion
from app.seguridad import CLAVE_DEMO, DOS_PASOS
from app.services import configuracion, dos_pasos, reportes
from tests.conftest import csrf, entrar
from tests.test_final_caja import _cobrada
from tests.test_salon import post


@pytest.fixture(autouse=True)
def _limpiar():
    DOS_PASOS.reiniciar()


def _eventos(app, accion):
    with app.app_context():
        return [a.detalle for a in Auditoria.query.filter_by(accion=accion).all()]


# --------------------------------------------------------------------------- permisos
@pytest.mark.parametrize(
    "usuario,ruta,permitido",
    [
        ("ana", "/admin/", False),
        ("marta", "/admin/", False),
        ("jose", "/admin/", False),
        ("admin", "/admin/", True),
        ("dev", "/admin/", True),
        ("ana", "/reportes/", False),
        ("marta", "/reportes/", False),
        ("jose", "/reportes/", True),
        ("admin", "/reportes/", True),
        ("ana", "/cuenta", True),
    ],
)
def test_permisos_por_nivel(como, usuario, ruta, permitido):
    r = como(usuario).get(ruta)
    assert (r.status_code == 200) is permitido, (usuario, ruta, r.status_code)
    if not permitido:
        assert r.status_code in (302, 403)


def test_todas_las_pantallas_de_administracion_abren(app, como):
    from app.admin.catalogos import CATALOGOS

    c = como("admin")
    rutas = [
        "/admin/",
        "/admin/operadores",
        "/admin/operadores/nuevo",
        "/admin/configuracion",
        "/admin/impresiones",
        "/admin/inventario",
        "/cuenta",
    ]
    with app.app_context():
        for clave, cat in CATALOGOS.items():
            rutas += [f"/admin/c/{clave}", f"/admin/c/{clave}/nuevo"]
            primero = cat.modelo.query.first()
            if primero is not None:
                rutas.append(f"/admin/c/{clave}/{primero.id}")
    for ruta in rutas:
        r = c.get(ruta)
        assert r.status_code == 200, (ruta, r.status_code)
        html = r.get_data(as_text=True)
        assert "Traceback" not in html and "<script>" not in html, ruta


def test_cabecera_muestra_menu_segun_nivel(como, otro):
    html = como("admin").get("/mesas").get_data(as_text=True)
    assert "Administración" in html and "Reportes" in html
    html = otro("ana").get("/mesas").get_data(as_text=True)
    assert "Administración" not in html and "Reportes" not in html


# --------------------------------------------------------------------------- catálogos
def test_catalogo_crea_valida_y_audita(app, como):
    c = como("admin")
    r = post(
        c,
        "/admin/c/secciones/nuevo",
        nombre="Especiales",
        orden="30",
        color="#22aa55",
        activa="1",
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    with app.app_context():
        s = Seccion.query.filter_by(nombre="Especiales").one()
        assert s.color == "#22aa55" and s.activa
    assert any("Especiales" in d for d in _eventos(app, "catalogo_nuevo"))

    malo = post(c, "/admin/c/secciones/nuevo", nombre="X", orden="31", color="rojo")
    assert malo.status_code == 422
    with app.app_context():
        assert Seccion.query.filter_by(nombre="X").count() == 0


def test_cambio_de_precio_queda_en_auditoria(app, como):
    c = como("admin")
    with app.app_context():
        p = Producto.query.filter_by(descripcion_corta="TASAJO").one()
        pid = p.id
        datos = {
            "codigo": str(p.codigo),
            "descripcion": p.descripcion,
            "descripcion_corta": p.descripcion_corta,
            "seccion_id": str(p.seccion_id),
            "area1_id": str(p.area1_id),
            "area2_id": str(p.area2_id or ""),
            "tipo": p.tipo,
            "precio": "9.75",
            "tasa_itbms": str(p.tasa_itbms),
            "condicion": p.condicion,
            "aplica_jubilado": "1" if p.aplica_jubilado else "",
            "con_acompanamiento": "1" if p.con_acompanamiento else "",
            "codigo_barras": p.codigo_barras or "",
        }
    r = post(
        c, f"/admin/c/productos/{pid}", **{k: v for k, v in datos.items() if v != ""}
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:600]
    with app.app_context():
        assert str(db.session.get(Producto, pid).precio) == "9.75"
    assert any("precio" in d and "9.75" in d for d in _eventos(app, "catalogo_cambio"))


def test_catalogo_desconocido_da_404(como):
    assert como("admin").get("/admin/c/operadores").status_code == 404


# --------------------------------------------------------------------------- operadores
def test_crear_operador_y_reglas_de_nivel(app, como):
    c = como("admin")
    r = post(
        c,
        "/admin/operadores/nuevo",
        usuario="pedro.p",
        nombre="Pedro Pérez",
        rol="operador",
        credencial="135792",
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    with app.app_context():
        assert Operador.query.filter_by(usuario="pedro.p").one().rol == "operador"
    # El administrador no crea programadores
    r = post(
        c,
        "/admin/operadores/nuevo",
        usuario="otro.dev",
        nombre="Otro Programador",
        rol="programador",
        credencial="Larga-y-segura-2026",
    )
    assert r.status_code == 422
    # PIN débil rechazado
    r = post(
        c,
        "/admin/operadores/nuevo",
        usuario="debil",
        nombre="Débil Uno",
        rol="operador",
        credencial="111111",
    )
    assert r.status_code == 422
    # Usuario repetido o con caracteres raros
    r = post(
        c,
        "/admin/operadores/nuevo",
        usuario="Ana<b>",
        nombre="Ana B",
        rol="operador",
        credencial="135792",
    )
    assert r.status_code == 422


def test_admin_no_se_degrada_ni_toca_al_programador(app, como):
    c = como("admin")
    with app.app_context():
        yo = Operador.query.filter_by(usuario="admin").one()
        dev = Operador.query.filter_by(usuario="dev").one()
        yo_id, dev_id = yo.id, dev.id
    post(c, f"/admin/operadores/{yo_id}", nombre=yo.nombre, rol="cajero", activo="1")
    with app.app_context():
        assert db.session.get(Operador, yo_id).rol == "administrador"
    assert c.get(f"/admin/operadores/{dev_id}").status_code == 403


def test_cambio_de_nivel_cierra_sus_sesiones(app, como, otro):
    ana = otro("ana")
    assert ana.get("/mesas").status_code == 200
    c = como("admin")
    with app.app_context():
        op = Operador.query.filter_by(usuario="ana").one()
        oid, nombre = op.id, op.nombre
    post(c, f"/admin/operadores/{oid}", nombre=nombre, rol="cajero", activo="1")
    with app.app_context():
        assert db.session.get(Operador, oid).rol == "cajero"
    r = ana.get("/mesas")
    assert r.status_code == 302 and "/acceso" in r.headers["Location"]


def test_restablecer_credencial_de_otro(app, como):
    c = como("admin")
    with app.app_context():
        oid = Operador.query.filter_by(usuario="luis").one().id
    post(c, f"/admin/operadores/{oid}/credencial", credencial="975310")
    nuevo = app.test_client()
    assert entrar(nuevo, "luis", "975310").status_code == 302
    assert _eventos(app, "clave_restablecida")


# --------------------------------------------------------------------------- configuración
def _form_config(app, **cambios):
    with app.app_context():
        datos = {
            clave: configuracion.obtener(clave)
            for _g, campos in configuracion.EDITABLES
            for clave, _e, tipo in campos
            if not (tipo == "si_no" and configuracion.obtener(clave) == "0")
        }
    datos.update(cambios)
    return datos


def test_configuracion_valida_y_audita(app, como):
    c = como("admin")
    post(
        c,
        "/admin/configuracion",
        **_form_config(app, **{"descuento.tope_sin_supervisor": "15"}),
    )
    with app.app_context():
        assert configuracion.obtener("descuento.tope_sin_supervisor") == "15"
    assert any("tope_sin_supervisor" in d for d in _eventos(app, "configuracion"))

    for clave, malo in (
        ("descuento.tope_sin_supervisor", "150"),
        ("descuento.jubilado.restaurante", "-5"),
        ("red.terminales", "192.168.1.0/24, no-es-ip"),
        ("fiscal.pac_url", "http://sin-cifrar.example"),
        ("fiscal.proveedor", "otro"),
    ):
        r = post(c, "/admin/configuracion", **_form_config(app, **{clave: malo}))
        assert r.status_code == 302
        with app.app_context():
            assert configuracion.obtener(clave) != malo, clave


def test_pac_simulado_no_se_elige_fuera_de_la_demo(app, como):
    c = como("admin")
    post(c, "/admin/configuracion", **_form_config(app, **{"fiscal.proveedor": "ninguno"}))
    app.config["DEMO"] = False
    with app.app_context():
        # sin 2FA el admin no puede tocar nada fuera de la demo: se activa primero
        op = Operador.query.filter_by(usuario="admin").one()
        op.totp_secreto = dos_pasos.nuevo_secreto()
        db.session.commit()
    post(
        c, "/admin/configuracion", **_form_config(app, **{"fiscal.proveedor": "simulado"})
    )
    with app.app_context():
        assert configuracion.obtener("fiscal.proveedor") == "ninguno"


# --------------------------------------------------------------------------- 2FA
def _activar_2fa(app, c, usuario):
    assert c.get("/cuenta/2fa").status_code == 200
    with app.app_context():
        op = Operador.query.filter_by(usuario=usuario).one()
        pendiente = op.totp_pendiente
    assert pendiente
    r = post(c, "/cuenta/2fa", codigo=dos_pasos.codigo_actual(pendiente), clave=CLAVE_DEMO)
    assert r.status_code == 200
    codigos = re.findall(r"[A-Z2-9]{5}-[A-Z2-9]{5}", r.get_data(as_text=True))
    assert len(set(codigos)) == 8
    return pendiente, codigos


def test_activar_2fa_y_entrar_con_codigo(app, como):
    c = como("jose")
    secreto, codigos = _activar_2fa(app, c, "jose")
    assert _eventos(app, "2fa_activada")

    nuevo = app.test_client()
    r = entrar(nuevo, "jose")
    assert r.status_code == 302 and "/acceso/verificacion" in r.headers["Location"]
    assert nuevo.get("/mesas").status_code == 302  # todavía no hay sesión
    token = csrf(nuevo, "/acceso/verificacion")
    assert (
        nuevo.post(
            "/acceso/verificacion", data={"codigo": "000000", "csrf_token": token}
        ).status_code
        == 401
    )
    # El código ya usado al activar no se acepta de nuevo (anti-repetición): se usa uno de recuperación
    r = nuevo.post(
        "/acceso/verificacion", data={"codigo": codigos[0], "csrf_token": token}
    )
    assert r.status_code == 302
    assert nuevo.get("/mesas").status_code == 200
    with app.app_context():
        assert dos_pasos.restantes(Operador.query.filter_by(usuario="jose").one()) == 7

    # El mismo código de recuperación no sirve dos veces
    tercero = app.test_client()
    entrar(tercero, "jose")
    token = csrf(tercero, "/acceso/verificacion")
    r = tercero.post(
        "/acceso/verificacion", data={"codigo": codigos[0], "csrf_token": token}
    )
    assert r.status_code == 401


def test_totp_rechaza_repeticion_y_desfase():
    class Op:
        totp_ultimo_paso = None

    op, secreto, t = Op(), dos_pasos.nuevo_secreto(), 1_800_000_000
    codigo = dos_pasos.codigo_actual(secreto, t)
    assert dos_pasos.verificar(op, codigo, secreto, t)
    assert not dos_pasos.verificar(op, codigo, secreto, t)  # repetición
    assert not dos_pasos.verificar(
        Op(), dos_pasos.codigo_actual(secreto, t - 120), secreto, t
    )
    assert dos_pasos.verificar(
        Op(), dos_pasos.codigo_actual(secreto, t - 30), secreto, t
    )
    assert not dos_pasos.verificar(Op(), "12345", secreto, t)


def test_codigos_de_2fa_se_limitan(app, como):
    c = como("jose")
    c.get("/cuenta/2fa")
    for _ in range(12):
        post(c, "/cuenta/2fa", codigo="000000", clave=CLAVE_DEMO)
    with app.app_context():
        pendiente = Operador.query.filter_by(usuario="jose").one().totp_pendiente
    r = post(c, "/cuenta/2fa", codigo=dos_pasos.codigo_actual(pendiente), clave=CLAVE_DEMO)
    assert r.status_code == 302  # bloqueado aunque el código sea bueno
    with app.app_context():
        assert not Operador.query.filter_by(usuario="jose").one().tiene_2fa


def test_fuera_de_la_demo_el_admin_debe_activar_2fa(app, como):
    c = como("admin")
    app.config["DEMO"] = False
    r = c.get("/admin/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cuenta")
    assert c.get("/cuenta").status_code == 200
    assert c.get("/cuenta/2fa").status_code == 200
    _activar_2fa(app, c, "admin")
    assert c.get("/admin/").status_code == 200
    # y no la puede quitar
    with app.app_context():
        secreto = Operador.query.filter_by(usuario="admin").one().totp_secreto
    post(c, "/cuenta/2fa/quitar", codigo=dos_pasos.codigo_actual(secreto, 0), clave=CLAVE_DEMO)
    with app.app_context():
        assert Operador.query.filter_by(usuario="admin").one().tiene_2fa


def test_cambiar_clave_propia_requiere_la_actual(app, como):
    c = como("jose")
    post(
        c,
        "/cuenta/clave",
        actual="equivocada",
        nueva="Nueva-Clave-2026",
        repetir="Nueva-Clave-2026",
    )
    nuevo = app.test_client()
    assert entrar(nuevo, "jose", "Nueva-Clave-2026").status_code != 302
    post(
        c,
        "/cuenta/clave",
        actual=CLAVE_DEMO,
        nueva="Nueva-Clave-2026",
        repetir="Nueva-Clave-2026",
    )
    assert entrar(app.test_client(), "jose", "Nueva-Clave-2026").status_code == 302
    assert c.get("/mesas").status_code == 200  # esta terminal sigue dentro


# --------------------------------------------------------------------------- reportes
def test_reportes_cuadran_con_las_ventas(app, client, otro):
    entrar(client, "ana")
    marta = otro("marta")
    _cobrada(app, client, marta)
    jose = otro("jose")
    html = jose.get("/reportes/").get_data(as_text=True)
    with app.app_context():
        from app.models import Documento

        total = sum(d.total for d in Documento.query.all())
    assert f"{total:,.2f}" in html
    for nombre in (
        "dias",
        "meseros",
        "secciones",
        "productos",
        "formas",
        "itbms",
        "jubilados",
        "anulaciones",
    ):
        r = jose.get(f"/reportes/{nombre}.csv")
        assert r.status_code == 200 and r.mimetype == "text/csv", nombre
        assert r.data.startswith("﻿".encode())
    assert jose.get("/reportes/../../etc.csv").status_code == 404
    assert jose.get("/reportes/x.csv").status_code == 404
    assert _eventos(app, "exportacion")


def test_rango_de_fechas_invalido(como):
    r = como("jose").get("/reportes/?desde=2026-13-40&hasta=x")
    assert r.status_code == 302


def test_csv_neutraliza_formulas():
    datos = reportes.a_csv(
        [('=HYPERLINK("http://x")', "+1", "-2", "@SUM(A1)", "normal")],
        ["a", "b", "c", "d", "e"],
    )
    texto = datos.decode("utf-8")
    assert (
        "'=HYPERLINK" in texto
        and "'+1" in texto
        and "'-2" in texto
        and "'@SUM" in texto
    )
    assert ";normal" in texto


# --------------------------------------------------------------------------- red local
def test_terminal_fuera_de_la_lista_se_rechaza(app):
    lejos = app.test_client()
    lejos.environ_base["REMOTE_ADDR"] = "192.168.1.50"
    assert lejos.get("/acceso").status_code == 403
    with app.app_context():
        configuracion.fijar("red.terminales", "192.168.1.0/24")
        db.session.commit()
    assert lejos.get("/acceso").status_code == 200
    otra_red = app.test_client()
    otra_red.environ_base["REMOTE_ADDR"] = "10.0.0.7"
    assert otra_red.get("/acceso").status_code == 403


def test_activar_2fa_exige_la_clave_actual(app, como):
    """H-14: con una sesión robada no se registra otro autenticador."""
    c = como("jose")
    c.get("/cuenta/2fa")
    with app.app_context():
        pendiente = Operador.query.filter_by(usuario="jose").one().totp_pendiente
    r = post(c, "/cuenta/2fa", codigo=dos_pasos.codigo_actual(pendiente))  # sin clave
    assert r.status_code == 302
    r = post(c, "/cuenta/2fa", codigo=dos_pasos.codigo_actual(pendiente), clave="equivocada")
    with app.app_context():
        assert not Operador.query.filter_by(usuario="jose").one().tiene_2fa


def test_nuevos_codigos_y_quitar_exigen_clave_y_tienen_limite(app, como):
    c = como("jose")
    secreto, _codigos = _activar_2fa(app, c, "jose")
    r = post(c, "/cuenta/2fa/codigos", codigo=dos_pasos.codigo_actual(secreto))  # sin clave
    assert r.status_code == 302
    for _ in range(6):  # fuerza bruta del código con la clave correcta
        post(c, "/cuenta/2fa/quitar", codigo="000000", clave=CLAVE_DEMO)
    from app.seguridad import DOS_PASOS

    with app.app_context():
        oid = Operador.query.filter_by(usuario="jose").one().id
    assert DOS_PASOS.espera(f"2fa|{oid}") > 0
    with app.app_context():
        assert Operador.query.filter_by(usuario="jose").one().tiene_2fa
