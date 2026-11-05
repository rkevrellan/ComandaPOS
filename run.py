"""Arranque de ComandaPOS (servidor).

    python run.py                  → servidor en http://127.0.0.1:5000 (abre el navegador)
    python run.py --red            → servidor para la red local (terminales y cocina en otros equipos)
    python run.py --dev            → modo desarrollo de Flask (recarga automática, solo 127.0.0.1)
    python run.py --puerto 8080    → otro puerto
    python run.py --no-abrir       → no abre el navegador
    python run.py --nuevas-claves  → cambia los PIN y contraseñas de prueba antes de producción
    python run.py --modo produccion        → deja este equipo en producción (o «demostracion»)
    python run.py --nueva-base             → aparta la base de demostración para empezar en limpio

En red, solo entran este equipo y las IP o redes de Administración → Configuración → «Terminales
permitidas» (por ejemplo 192.168.1.0/24). Vacío = nadie más que este equipo.

Fuera del modo demostración (COMANDAPOS_PRODUCCION=1) el servidor SE NIEGA A ARRANCAR si alguna
cuenta activa todavía usa el PIN o la contraseña de prueba (OWASP A05/A07).
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
import threading
import webbrowser

from app import create_app
from app.config import NOMBRE, VERSION
from app.extensions import db
from app.models import Operador
from app.seguridad import CLAVE_DEMO, PIN_DEMO, validar_clave, validar_pin
from app.services.auditoria import auditar, sellar_pendientes


def cuentas_con_clave_de_prueba() -> list:
    """Operadores activos que todavía entran con el PIN o la contraseña de la demostración."""
    return [
        op
        for op in Operador.query.filter_by(activo=True).all()
        if op.verificar_clave(PIN_DEMO) or op.verificar_clave(CLAVE_DEMO)
    ]


def _pin_aleatorio() -> str:
    while True:
        pin = "".join(secrets.choice(string.digits) for _ in range(6))
        if not validar_pin(pin):
            return pin


def _clave_aleatoria(op) -> str:
    alfabeto = string.ascii_letters + string.digits
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(14))
        if not validar_clave(clave, op.usuario, op.nombre):
            return clave


def nuevas_claves() -> int:
    """Asigna credenciales aleatorias a cada cuenta que siga con la de prueba y las muestra UNA vez."""
    cuentas = cuentas_con_clave_de_prueba()
    if not cuentas:
        print("   Ninguna cuenta usa credenciales de prueba. Todo en orden.")
        return 0
    nuevas = []
    for op in cuentas:
        valor = _pin_aleatorio() if op.usa_pin else _clave_aleatoria(op)
        op.fijar_clave(valor)  # también cierra sus sesiones abiertas
        auditar(
            "clave_cambiada",
            f"{op.usuario}: credencial de prueba reemplazada",
            operador=op,
        )
        nuevas.append((op, valor))
    db.session.commit()  # primero se guardan; solo después se muestran
    sellar_pendientes()
    print("   Nuevas credenciales (anótalas ahora; no se vuelven a mostrar):")
    for op, valor in nuevas:
        tipo = "PIN" if op.usa_pin else "Contraseña"
        print(f"   {op.usuario:<10} {op.nombre_rol:<20} {tipo:<11} {valor}")
    return len(nuevas)


#: Código de salida cuando una base de demostración intenta arrancar en producción (H-01).
SALIDA_BASE_DEMO = 3


def apartar_base(datos: str) -> str:
    """Mueve la base, el ancla y las impresiones a «respaldo-demo-<fecha>» para empezar en limpio.

    No borra nada: los datos de prueba quedan guardados por si se necesitan."""
    import os
    import shutil
    from datetime import datetime

    destino = os.path.join(
        datos, "respaldo-demo-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    os.makedirs(destino)
    for nombre in os.listdir(datos):
        if nombre.startswith("comandapos.db") or nombre in (
            "auditoria.ancla",
            "impresiones",
        ):
            shutil.move(os.path.join(datos, nombre), os.path.join(destino, nombre))
    return destino


def preparar(app, nuevas: bool = False) -> int | None:
    """Datos de demostración, cambio de credenciales y guardias de producción.

    Devuelve un código de salida si el programa debe terminar, o None para seguir arrancando.
    """
    from app.services.configuracion import base_es_demo

    with app.app_context():
        if app.config["DEMO"]:
            from seed import poblar

            if poblar():
                print("   Base nueva: se cargaron los datos de demostración.")
        elif base_es_demo():
            print()
            print(
                "   ALTO: el equipo está en PRODUCCIÓN pero la base es de DEMOSTRACIÓN"
            )
            print("   (productos, clientes, ventas simuladas y numeración de prueba).")
            print("   Para empezar en limpio:  ComandaPOS-servidor.exe --nueva-base")
            print(
                "   (aparta la base de prueba en una carpeta de respaldo; no borra nada)."
            )
            print()
            return SALIDA_BASE_DEMO
        if nuevas:
            nuevas_claves()
            return 0
        if not app.config["DEMO"]:
            pendientes = cuentas_con_clave_de_prueba()
            if pendientes:
                print()
                print("   ALTO: estas cuentas todavía usan credenciales de prueba:")
                for op in pendientes:
                    print(f"   - {op.usuario} ({op.nombre_rol})")
                print("   Ejecuta: python run.py --nuevas-claves")
                print()
                return 1
    return None


def direcciones_locales() -> list:
    """IP de este equipo en la red local (para indicarlas a las terminales)."""
    import socket

    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # la interfaz por la que saldría el tráfico (UDP sin enviar nada)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _carpeta_respaldo() -> str:
    """La misma carpeta que usa create_app cuando no hay %PROGRAMDATA% ni COMANDAPOS_DATA."""
    from flask import Flask

    return Flask("app").instance_path


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description=f"{NOMBRE} {VERSION}")
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="127.0.0.1 = solo este equipo; usa --red para la red local",
    )
    p.add_argument(
        "--red",
        action="store_true",
        help="escucha en la red local (equivale a --host 0.0.0.0)",
    )
    p.add_argument("--puerto", type=int, default=5000)
    p.add_argument("--dev", action="store_true")
    p.add_argument("--no-abrir", action="store_true")
    p.add_argument("--nuevas-claves", action="store_true")
    p.add_argument(
        "--sin-tls",
        action="store_true",
        help="en red, sin HTTPS (no recomendado: claves y PIN viajan en claro)",
    )
    p.add_argument(
        "--confiar",
        action="store_true",
        help="instala el certificado de ComandaPOS en este usuario de Windows y termina",
    )
    p.add_argument(
        "--verificar",
        action="store_true",
        help="comprueba que estén todas las dependencias y termina",
    )
    p.add_argument(
        "--modo",
        choices=("produccion", "demostracion"),
        help="guarda el modo de este equipo en la carpeta de datos y termina",
    )
    p.add_argument(
        "--nueva-base",
        action="store_true",
        help="aparta la base actual (de demostración) para empezar en limpio y termina",
    )
    args = p.parse_args(argv)
    if args.modo or args.nueva_base:
        from app.config import carpeta_datos, fijar_modo

        datos = carpeta_datos(_carpeta_respaldo())
        if args.modo:
            fijar_modo(datos, args.modo == "produccion")
            print(f"   Modo guardado: {args.modo}. Vuelve a abrir {NOMBRE}.")
        if args.nueva_base:
            try:
                destino = apartar_base(datos)
            except OSError as e:
                print(f"   No se pudo apartar la base ({e.strerror}).")
                print(f"   Cierra {NOMBRE} en este equipo y vuelve a intentarlo.")
                return 1
            print(f"   Base anterior guardada en: {destino}")
            print("   Al abrir de nuevo, se pedirá crear el primer administrador.")
        return 0
    if args.verificar:
        return verificar()
    if args.confiar:
        return confiar()
    if args.red:  # a propósito: la lista «Terminales permitidas» filtra quién entra
        args.host = "0.0.0.0"  # nosec B104
    if args.dev and args.host not in ("127.0.0.1", "localhost", "::1"):
        print("   El modo --dev (depurador de Flask) solo se permite en 127.0.0.1.")
        return 2

    en_red = args.host in ("0.0.0.0", "::")  # nosec B104 (solo se compara)
    tls = en_red and not args.sin_tls and not args.dev
    if tls:
        # H-06: en la red, HTTPS. Las cookies pasan a «Secure» y «__Host-».
        os.environ["COMANDAPOS_HTTPS"] = "1"
    app = create_app()
    codigo = preparar(app, args.nuevas_claves)
    if codigo is not None:
        return codigo

    esquema = "https" if tls else "http"
    url = f"{esquema}://{'127.0.0.1' if en_red else args.host}:{args.puerto}"
    print()
    print(
        f"   {NOMBRE} {VERSION} · servidor{' de red local' if en_red else ''} · "
        f"{'DEMOSTRACIÓN' if app.config['DEMO'] else 'PRODUCCIÓN'}"
    )
    print(f"   Abre {url}  (Ctrl+C para detener)")
    certificado = llave = None
    if en_red:
        from app.services.configuracion import obtener

        with app.app_context():
            permitidas = obtener("red.terminales") or "(ninguna: solo este equipo)"
        ips = direcciones_locales()
        for ip in ips:
            print(f"   En la red local: {esquema}://{ip}:{args.puerto}")
        print(f"   Terminales permitidas: {permitidas}")
        if tls:
            from app.services import tls as tls_mod

            certificado, llave, ca = tls_mod.asegurar(app.config["DATOS"], ips)
            print(f"   Certificado para instalar en cada terminal: {ca}")
            print(f"   Huella SHA-256: {tls_mod.huella_ca(ca)}")
        else:
            print("   ATENCIÓN: sin cifrado (--sin-tls). Claves y PIN viajan en claro.")
        print("   Usa la red del local, nunca la Wi-Fi de clientes.")
    print()
    if not args.no_abrir:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    if args.dev:  # solo desarrollo y solo en 127.0.0.1 (se comprueba arriba)
        app.run(  # nosec B201
            host=args.host, port=args.puerto, debug=True, use_reloader=False
        )
    elif tls:
        from app.services import tls as tls_mod

        tls_mod.servir(app, args.host, args.puerto, certificado, llave)
    else:
        from waitress import serve

        serve(app, host=args.host, port=args.puerto, threads=8, ident=None)
    return 0


def confiar() -> int:
    """H-06: confía en la CA de ComandaPOS en ESTE usuario de Windows (pide confirmación).

    En las demás terminales: copiar «ca.crt» y hacer doble clic → Instalar certificado →
    «Entidades de certificación raíz de confianza» (o este mismo comando con --ca <ruta>).
    """
    import subprocess  # nosec B404 - comando fijo de Windows, sin texto del usuario

    from app.config import carpeta_datos

    ca = os.path.join(carpeta_datos(_carpeta_respaldo()), "tls", "ca.crt")
    if not os.path.exists(ca):
        print(
            "   Todavía no hay certificado: abre una vez el servidor de red local (--red)."
        )
        return 1
    if os.name != "nt":
        print(f"   En este sistema instala a mano: {ca}")
        return 1
    certutil = os.path.join(
        os.environ.get("SystemRoot", "C:/Windows"), "System32", "certutil.exe"
    )
    resultado = subprocess.run(  # nosec B603 - ruta y argumentos fijos
        [certutil, "-user", "-addstore", "Root", ca], check=False
    )
    return resultado.returncode


def verificar() -> int:
    """H-08: comprueba que el paquete trae todo lo que necesita (lo usa build.bat)."""
    import importlib

    modulos = [
        "waitress",
        "reportlab",
        "cheroot.wsgi",
        "cryptography.x509",
        "ssl",
        "sqlite3",
    ]
    if os.name == "nt":
        modulos += ["win32print", "win32api"]
    faltan = []
    for nombre in modulos:
        try:
            importlib.import_module(nombre)
        except ImportError as e:
            faltan.append(f"{nombre} ({e})")
    if faltan:
        print("   FALTAN módulos: " + ", ".join(faltan))
        return 1
    print(f"   {NOMBRE} {VERSION}: dependencias completas ({len(modulos)} módulos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
