"""Arranque de ComandaPOS.

    python run.py                  → servidor en http://127.0.0.1:5000 (abre el navegador)
    python run.py --dev            → modo desarrollo de Flask (recarga automática)
    python run.py --puerto 8080    → otro puerto
    python run.py --no-abrir       → no abre el navegador
    python run.py --nuevas-claves  → cambia los PIN y contraseñas de prueba antes de producción

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
from app.config import MODOS, NOMBRE, VERSION
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


def main() -> int:
    p = argparse.ArgumentParser(description=f"{NOMBRE} {VERSION}")
    p.add_argument("--modo", choices=MODOS, default="servidor")
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="127.0.0.1 = solo este equipo (la red local llega en la fase 7)",
    )
    p.add_argument("--puerto", type=int, default=5000)
    p.add_argument("--dev", action="store_true")
    p.add_argument("--no-abrir", action="store_true")
    p.add_argument("--nuevas-claves", action="store_true")
    args = p.parse_args()

    app = create_app()
    with app.app_context():
        if app.config["DEMO"]:
            from seed import poblar

            if poblar():
                print("   Base nueva: se cargaron los datos de demostración.")
        if args.nuevas_claves:
            nuevas_claves()
            return 0
        if not app.config["DEMO"]:
            pendientes = cuentas_con_clave_de_prueba()
            if pendientes:
                print("\n   ALTO: estas cuentas todavía usan credenciales de prueba:")
                for op in pendientes:
                    print(f"   - {op.usuario} ({op.nombre_rol})")
                print("   Ejecuta: python run.py --nuevas-claves\n")
                return 1

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.puerto}"
    print(
        f"\n   {NOMBRE} {VERSION} · modo {args.modo} · "
        f"{'DEMOSTRACIÓN' if app.config['DEMO'] else 'PRODUCCIÓN'}"
    )
    print(f"   Abre {url}  (Ctrl+C para detener)\n")
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
