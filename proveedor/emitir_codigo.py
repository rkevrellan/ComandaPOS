"""Herramienta del PROVEEDOR de ComandaPOS: emite los códigos mensuales de suscripción.

Se usa en la PC del proveedor, nunca en la del restaurante. La llave privada vive fuera del
repositorio (por defecto en ~/.comandapos-proveedor/); quien la tenga puede emitir códigos.

Primera vez (una sola vez, ANTES de compilar el instalador):
    python proveedor/emitir_codigo.py crear-llave
        → crea la llave privada y reescribe app/services/llave_proveedor.py con la pública.

Cada mes, cuando un restaurante paga:
    python proveedor/emitir_codigo.py emitir --instalacion ABCD-EFGH-IJKL-MNOP --plan pro \
        --cliente "Restaurante El Fogón" [--meses 1 | --hasta 2026-12-31]
        → imprime el código CPOS-… para enviárselo (WhatsApp o correo).

Si el cliente todavía tiene días pagados, el mes nuevo empieza al día siguiente del último
vencimiento; si ya venció, empieza hoy. Todo lo emitido queda en emitidos.csv.

    python proveedor/emitir_codigo.py historial [--instalacion …]
"""

from __future__ import annotations

import argparse
import base64
import csv
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.suscripcion import Codigo, _desde_b32, armar_codigo  # noqa: E402

CARPETA = Path(
    os.environ.get("COMANDAPOS_PROVEEDOR") or Path.home() / ".comandapos-proveedor"
)
LLAVE_DESARROLLO = RAIZ / "tests" / "llave_desarrollo.txt"
ARCHIVO_LLAVE_PUBLICA = RAIZ / "app" / "services" / "llave_proveedor.py"
COLUMNAS = (
    "emitido",
    "cliente",
    "instalacion",
    "plan",
    "desde",
    "hasta",
    "serie",
    "codigo",
)


def _hoy() -> date:
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _sumar_meses(dia: date, meses: int) -> date:
    """Mismo día N meses después, menos un día (1 mes desde el 6/11 cubre hasta el 5/12)."""
    mes = dia.month - 1 + meses
    anio, mes = dia.year + mes // 12, mes % 12 + 1
    ultimo = [
        31,
        29 if anio % 4 == 0 and (anio % 100 or anio % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ][mes - 1]
    return date(anio, mes, min(dia.day, ultimo)) - timedelta(days=1)


def _llave_privada(desarrollo: bool):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    ruta = LLAVE_DESARROLLO if desarrollo else CARPETA / "llave_privada.txt"
    if not ruta.exists():
        sys.exit(
            f"No encuentro la llave privada en {ruta}. "
            "Créala con «crear-llave» (o usa --desarrollo para pruebas)."
        )
    return Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(ruta.read_text().strip())
    )


def crear_llave(reemplazar: bool) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    ruta = CARPETA / "llave_privada.txt"
    if ruta.exists() and not reemplazar:
        sys.exit(
            f"Ya existe {ruta}. Si la reemplazas, los restaurantes necesitarán un instalador nuevo "
            "y códigos nuevos. Usa --reemplazar solo si la llave se filtró."
        )
    CARPETA.mkdir(parents=True, exist_ok=True)
    privada = Ed25519PrivateKey.generate()
    crudo = privada.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    ruta.write_text(base64.b64encode(crudo).decode() + "\n", encoding="ascii")
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass
    publica = privada.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    texto = ARCHIVO_LLAVE_PUBLICA.read_text(encoding="utf-8")
    inicio = texto.index("ES_DE_DESARROLLO")
    ARCHIVO_LLAVE_PUBLICA.write_text(
        texto[:inicio]
        + "ES_DE_DESARROLLO = False\n"
        + f'LLAVE_PUBLICA = "{base64.b64encode(publica).decode()}"\n',
        encoding="utf-8",
    )
    print(f"Llave privada: {ruta}  (guárdala con respaldo y NO la compartas)")
    print(f"Llave pública escrita en: {ARCHIVO_LLAVE_PUBLICA}")
    print("Ahora compila el instalador (build.bat): solo él aceptará tus códigos.")


def _registro() -> list[dict]:
    ruta = CARPETA / "emitidos.csv"
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _guardar(fila: dict) -> None:
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA / "emitidos.csv"
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            escritor.writeheader()
        escritor.writerow(fila)


def emitir(args) -> tuple:
    instalacion_texto = args.instalacion.strip().upper()
    try:
        instalacion = _desde_b32(instalacion_texto)
    except ValueError:
        instalacion = b""
    if len(instalacion) != 10:
        sys.exit("ID de instalación inválido (formato ABCD-EFGH-IJKL-MNOP).")
    registro = _registro()
    previos = [r for r in registro if r["instalacion"] == instalacion_texto]
    hoy = _hoy()
    desde = hoy
    if previos:
        ultimo = max(date.fromisoformat(r["hasta"]) for r in previos)
        if ultimo >= hoy:
            desde = ultimo + timedelta(days=1)
    hasta = (
        date.fromisoformat(args.hasta)
        if args.hasta
        else _sumar_meses(desde, args.meses)
    )
    if hasta < hoy:
        sys.exit("La fecha «hasta» ya pasó.")
    serie = max([int(r["serie"]) for r in registro] + [1000]) + 1
    privada = _llave_privada(args.desarrollo)
    codigo = armar_codigo(Codigo(instalacion, args.plan, hasta, serie), privada.sign)
    if not args.no_guardar:
        _guardar(
            {
                "emitido": datetime.now().isoformat(timespec="seconds"),
                "cliente": args.cliente or "",
                "instalacion": instalacion_texto,
                "plan": args.plan,
                "desde": desde.isoformat(),
                "hasta": hasta.isoformat(),
                "serie": serie,
                "codigo": codigo,
            }
        )
    return codigo, desde, hasta, serie


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description="Códigos de suscripción de ComandaPOS (proveedor)"
    )
    sub = p.add_subparsers(dest="orden", required=True)
    c = sub.add_parser(
        "crear-llave", help="crea la llave privada del proveedor (una vez)"
    )
    c.add_argument("--reemplazar", action="store_true")
    e = sub.add_parser("emitir", help="emite un código mensual")
    e.add_argument(
        "--instalacion", required=True, help="ID que muestra la pantalla Suscripción"
    )
    e.add_argument("--plan", choices=("basico", "pro"), required=True)
    e.add_argument("--meses", type=int, default=1)
    e.add_argument("--hasta", help="fecha exacta AAAA-MM-DD (en lugar de --meses)")
    e.add_argument("--cliente", help="nombre del restaurante (para tu registro)")
    e.add_argument("--desarrollo", action="store_true", help="usa la llave de pruebas")
    e.add_argument(
        "--no-guardar", action="store_true", help="no lo anota en emitidos.csv"
    )
    h = sub.add_parser("historial", help="lista los códigos emitidos")
    h.add_argument("--instalacion")
    args = p.parse_args(argv)

    if args.orden == "crear-llave":
        crear_llave(args.reemplazar)
    elif args.orden == "emitir":
        if not 1 <= args.meses <= 24:
            sys.exit("--meses debe estar entre 1 y 24.")
        codigo, desde, hasta, serie = emitir(args)
        print(
            f"Plan {args.plan} · del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} · serie {serie}"
        )
        print()
        print(codigo)
    else:
        for r in _registro():
            if not args.instalacion or r["instalacion"] == args.instalacion.upper():
                print(
                    f'{r["emitido"][:10]}  {r["cliente"][:28]:28}  {r["instalacion"]}  '
                    f'{r["plan"]:6}  {r["desde"]} → {r["hasta"]}  #{r["serie"]}'
                )


if __name__ == "__main__":
    main()
