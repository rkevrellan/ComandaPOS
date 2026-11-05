"""Arranque de ComandaPOS (servidor).

    python run.py                  → servidor en http://127.0.0.1:5000 (abre el navegador)
    python run.py --red            → servidor para la red local (terminales y cocina en otros equipos)
    python run.py --dev            → modo desarrollo de Flask (recarga automática, solo 127.0.0.1)
    python run.py --puerto 8080    → otro puerto
    python run.py --no-abrir       → no abre el navegador
    python run.py --nuevas-claves  → cambia los PIN y contraseñas de prueba antes de producción

En red, solo entran este equipo y las IP o redes de Administración → Configuración → «Terminales
permitidas» (por ejemplo 192.168.1.0/24). Vacío = nadie más que este equipo.

Fuera del modo demostración (COMANDAPOS_PRODUCCION=1) el servidor SE NIEGA A ARRANCAR si alguna
cuenta activa todavía usa el PIN o la contraseña de prueba (OWASP A05/A07).
"""

from __future__ import annotations

import argparse
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


def preparar(app, nuevas: bool = False) -> int | None:
    """Datos de demostración, cambio de credenciales y guardia de producción.

    Devuelve un código de salida si el programa debe terminar, o None para seguir arrancando.
    """
    with app.app_context():
        if app.config["DEMO"]:
            from seed import poblar

            if poblar():
                print("   Base nueva: se cargaron los datos de demostración.")
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
    args = p.parse_args(argv)
    if args.red:  # a propósito: la lista «Terminales permitidas» filtra quién entra
        args.host = "0.0.0.0"  # nosec B104
    if args.dev and args.host not in ("127.0.0.1", "localhost", "::1"):
        print("   El modo --dev (depurador de Flask) solo se permite en 127.0.0.1.")
        return 2

    app = create_app()
    codigo = preparar(app, args.nuevas_claves)
    if codigo is not None:
        return codigo

    en_red = args.host in ("0.0.0.0", "::")  # nosec B104 (solo se compara)
    url = f"http://{'127.0.0.1' if en_red else args.host}:{args.puerto}"
    print()
    print(
        f"   {NOMBRE} {VERSION} · servidor{' de red local' if en_red else ''} · "
        f"{'DEMOSTRACIÓN' if app.config['DEMO'] else 'PRODUCCIÓN'}"
    )
    print(f"   Abre {url}  (Ctrl+C para detener)")
    if en_red:
        from app.services.configuracion import obtener

        with app.app_context():
            permitidas = obtener("red.terminales") or "(ninguna: solo este equipo)"
        for ip in direcciones_locales():
            print(f"   En la red local: http://{ip}:{args.puerto}")
        print(f"   Terminales permitidas: {permitidas}")
        print("   Usa la red del local, nunca la Wi-Fi de clientes.")
    print()
    if not args.no_abrir:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    if args.dev:
        app.run(host=args.host, port=args.puerto, debug=True, use_reloader=False)
    else:
        from waitress import serve

        serve(app, host=args.host, port=args.puerto, threads=8, ident=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
