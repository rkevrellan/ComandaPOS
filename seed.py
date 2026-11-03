"""Datos de demostración de ComandaPOS: «Restaurante El Fogón (demo)», David, Chiriquí.

Todo es ficticio: el restaurante, su RUC, los operadores y los clientes. Los precios del menú
son referenciales de un restaurante panameño.

    python seed.py            → crea la base si está vacía
    python seed.py --reiniciar → BORRA la base y la vuelve a crear (solo en demostración)
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from app import create_app
from app.extensions import db
from app.models import (
    Acompanamiento,
    AreaProduccion,
    Cliente,
    Mesa,
    NotaFija,
    Operador,
    Producto,
    Sala,
    Seccion,
)
from app.seguridad import CLAVE_DEMO, CUENTAS_DEMO, PIN_DEMO
from app.config import ROLES_CON_PIN
from app.services import auditoria, caja, configuracion, secuencias

CARGOS = {
    "operador": "Mesero",
    "cajero": "Cajera",
    "supervisor": "Supervisor de salón",
    "administrador": "Administración",
    "programador": "Soporte del sistema",
}

SECCIONES = [
    # nombre, color
    ("Bebidas", "#0891b2"),
    ("Desayunos", "#ca8a04"),
    ("Almuerzo", "#16a34a"),
    ("Sopas", "#ea580c"),
    ("Carnes (porción)", "#b91c1c"),
    ("Porciones", "#65a30d"),
    ("Picadas", "#9333ea"),
    ("Postres", "#db2777"),
    ("Pastas", "#d97706"),
    ("Cortes de carne", "#7f1d1d"),
    ("Hamburguesas", "#a16207"),
    ("Mariscos", "#0284c7"),
    ("Órdenes de arroz", "#4d7c0f"),
    ("Entradas", "#0d9488"),
    ("Órdenes de pollo", "#c2410c"),
    ("Cargos y envases", "#475569"),
]

# (sección, descripción, corta, precio, área, extras)
#   extras: "acomp" = lleva acompañamiento, "alcohol" = bebida alcohólica (tasa por confirmar),
#           "sin_jub" = no aplica descuento de jubilado
PRODUCTOS = [
    ("Almuerzo", "Tasajo", "TASAJO", "3.75", "C", ""),
    ("Almuerzo", "Almuerzo completo", "ALMUERZO COMPLETO", "5.50", "C", ""),
    ("Almuerzo", "Almuerzo completo especial", "ALMUERZO ESPECIAL", "8.00", "C", ""),
    ("Almuerzo", "Almuerzo del día", "ALMUERZO", "3.50", "C", ""),
    ("Almuerzo", "Concha a la criolla", "CONCHA A LA CRIOLLA", "8.95", "C", "acomp"),
    ("Almuerzo", "Bistec picado", "BISTEC PICADO", "8.95", "C", "acomp"),
    ("Almuerzo", "Mondongo a la culona", "MONDONGO", "7.95", "C", ""),
    ("Almuerzo", "Torta de huevo", "TORTA", "7.50", "C", "acomp"),
    ("Órdenes de pollo", "Pollo asado (1/4)", "POLLO ASADO", "7.50", "C", "acomp"),
    (
        "Órdenes de pollo",
        "Pollo a la plancha",
        "POLLO A LA PLANCHA",
        "8.95",
        "C",
        "acomp",
    ),
    ("Órdenes de arroz", "Arroz con pollo", "ARROZ CON POLLO", "7.25", "C", ""),
    ("Carnes (porción)", "Chuleta fresca", "CHULETA FRESCA", "8.95", "C", "acomp"),
    (
        "Carnes (porción)",
        "Carne ahumada de cerdo",
        "CARNE AHUMADA CERDO",
        "8.95",
        "C",
        "acomp",
    ),
    ("Carnes (porción)", "Carne frita", "CARNE FRITA", "8.75", "C", "acomp"),
    ("Sopas", "Sopa de costilla grande", "SOPA COSTILLA GDE", "3.95", "C", ""),
    ("Sopas", "Guacho pequeño", "GUACHO PEQUEÑO", "4.50", "C", ""),
    ("Sopas", "Sancocho de gallina", "SANCOCHO", "4.75", "C", ""),
    (
        "Desayunos",
        "Desayuno típico (tortilla, carne y huevo)",
        "DESAYUNO TIPICO",
        "4.25",
        "C",
        "",
    ),
    ("Desayunos", "Hojaldra", "HOJALDRA", "0.75", "C", ""),
    ("Porciones", "Puré de papas", "PURE", "3.00", "C", ""),
    ("Porciones", "Verduras de sopa", "VERDURAS DE SOPA", "1.00", "C", ""),
    ("Porciones", "Patacones", "PATACONES", "2.50", "C", ""),
    ("Porciones", "Tajadas", "PORCION TAJADAS", "1.00", "C", ""),
    ("Porciones", "Yuca frita", "PORCION DE YUCA", "1.75", "C", ""),
    ("Porciones", "Papas fritas", "PAPAS FRITAS", "2.25", "C", ""),
    ("Porciones", "Papas salteadas", "PAPAS SALTEADAS", "3.50", "C", ""),
    ("Porciones", "Plátano en tentación", "PLATANO TENTACION", "1.00", "C", ""),
    ("Porciones", "Arroz blanco", "PORCION ARROZ BLANCO", "1.75", "C", ""),
    ("Porciones", "Ensalada verde", "ENSALADA VERDE", "2.50", "C", ""),
    ("Porciones", "Ensalada de papas", "ENSALADA DE PAPAS", "2.00", "C", ""),
    ("Porciones", "Pico de gallo", "PICO DE GALLO", "1.50", "C", ""),
    ("Porciones", "Menestras", "MENESTRAS", "1.00", "C", ""),
    ("Porciones", "Tamales", "TAMALES", "3.00", "C", ""),
    ("Porciones", "Pan de ajo", "PAN DE AJO", "1.50", "C", ""),
    ("Porciones", "Soufflé de zapallo", "SOUFLE DE ZAPALLO", "2.00", "C", ""),
    ("Entradas", "Copita de salsa", "COPITA DE SALSA", "0.50", "C", ""),
    ("Postres", "Flan de caramelo", "FLAN", "2.50", "F", ""),
    ("Postres", "Tres leches", "TRES LECHES", "3.00", "F", ""),
    ("Bebidas", "Té frío", "TE FRIO", "2.00", "F", ""),
    ("Bebidas", "Té caliente", "TE", "1.00", "F", ""),
    ("Bebidas", "Jarra de té frío", "JARRA DE TE FRIO", "6.50", "F", ""),
    ("Bebidas", "Batido de melocotón", "BATIDO MELOCOTON", "4.50", "F", ""),
    ("Bebidas", "Batido de papaya", "BATIDO DE PAPAYA", "4.50", "F", ""),
    ("Bebidas", "Batido de fresa", "BATIDO DE FRESA", "4.50", "F", ""),
    ("Bebidas", "Batido de melón", "BATIDO DE MELON", "4.50", "F", ""),
    ("Bebidas", "Batido de piña", "BATIDO DE PIÑA", "4.50", "F", ""),
    ("Bebidas", "Licuado", "LICUADO", "3.50", "F", ""),
    ("Bebidas", "Jarra de chicha", "JARRA DE CHICHA", "6.50", "F", ""),
    ("Bebidas", "Refresco de nance", "REFRESCO DE NANCE", "2.00", "F", ""),
    ("Bebidas", "Jugo de caña", "JUGO DE CAÑA", "2.00", "F", ""),
    ("Bebidas", "Maracuyá", "MARACUYA", "2.00", "F", ""),
    ("Bebidas", "Jugo natural", "JUGO NATURAL", "2.00", "F", ""),
    ("Bebidas", "Jugo de cartón", "JUGO DE CARTON", "0.75", "F", ""),
    ("Bebidas", "Limón con raspadura", "LIMON CON RASPADURA", "2.00", "F", ""),
    ("Bebidas", "Naranja con raspadura", "NARANJA RASPADURA", "2.00", "F", ""),
    ("Bebidas", "Limonada frozen", "LIMONADA FROZEN", "3.00", "F", ""),
    ("Bebidas", "Soda en lata", "SODA LATA", "1.50", "F", ""),
    ("Bebidas", "Soda en botella", "SODA EN BOTELLA", "1.75", "F", ""),
    ("Bebidas", "Agua en botella", "AGUA BOTELLA", "1.00", "F", ""),
    ("Bebidas", "Agua Perrier", "AGUA PERRIER", "2.75", "F", ""),
    ("Bebidas", "Cerveza nacional", "CERVEZA NACIONAL", "2.00", "F", "alcohol"),
    ("Bebidas", "Cerveza importada", "CERVEZA IMPORTADA", "2.75", "F", "alcohol"),
    ("Bebidas", "Copa de vino", "COPA DE VINO", "6.00", "F", "alcohol"),
    ("Bebidas", "Sangría", "SANGRIA", "5.50", "F", "alcohol"),
    (
        "Bebidas",
        "Jarra de ponche (con licor)",
        "JARRA DE PONCHE",
        "18.00",
        "F",
        "alcohol",
    ),
    ("Bebidas", "Trago de whisky", "OLD TRAGO", "5.00", "F", "alcohol"),
    ("Cargos y envases", "Envase para llevar", "ENVASE LLEVAR", "0.25", "F", "sin_jub"),
    ("Cargos y envases", "Envase de sopa", "ENVASE DE SOPA", "0.15", "F", "sin_jub"),
    (
        "Cargos y envases",
        "Cubiertos desechables",
        "CUBIERTOS DESECH",
        "0.25",
        "F",
        "sin_jub",
    ),
    (
        "Cargos y envases",
        "Cuchara plástica",
        "CUCHARA PLASTICA",
        "0.10",
        "F",
        "sin_jub",
    ),
]

ACOMPANAMIENTOS = [
    (310, "Papas salteadas", "0.00"),
    (320, "Vegetales hervidos", "0.00"),
    (350, "Arroz blanco", "0.00"),
    (370, "Sin acompañamiento", "0.00"),
    (380, "Arroz con guandú", "0.00"),
    (390, "Ensalada verde", "0.00"),
    (400, "Ensalada blanca", "0.00"),
    (420, "Papas fritas", "0.50"),
]

NOTAS = [
    "Copita de salsa",
    "Doble ensalada",
    "Encuentro",
    "Ensalada sin mayonesa",
    "Ensalada verde",
    "Las dos ensaladas",
    "Muslo",
    "Muslo encuentro",
    "Patitas, alitas y pescuezo",
    "Sin cebolla",
    "Término medio",
    "Bien cocido",
    "Sin sal",
    "Salsa aparte",
]

CLIENTES = [
    # ruc, dv, tipo, nombre, tipo de pago, límite
    ("00-00-00", "", "consumidor_final", "CONSUMIDOR FINAL", "contado", "0.00"),
    (
        "155700001-2-2026",
        "11",
        "juridico",
        "AGROSERVICIOS DEL BARÚ, S.A. (DEMO)",
        "credito",
        "500.00",
    ),
    (
        "155700002-2-2026",
        "22",
        "juridico",
        "CONSTRUCTORA LOS LLANOS, S.A. (DEMO)",
        "contado",
        "0.00",
    ),
    (
        "155700003-2-2026",
        "33",
        "juridico",
        "TRANSPORTES CHIRICANOS, S.A. (DEMO)",
        "autorizado",
        "250.00",
    ),
    ("4-700-1234", "45", "natural", "MARÍA ELENA GUERRA (DEMO)", "personal", "0.00"),
]


def sincronizar_nombres_demo() -> int:
    """Pone al día los nombres de las cuentas de demostración en una base que ya existía.

    `poblar()` solo actúa con la base vacía; si después cambia un nombre en `CUENTAS_DEMO`,
    esta función lo aplica (solo al nombre, nunca a credenciales ni roles) y lo audita.
    """
    cambios = 0
    for usuario, nombre, _rol in CUENTAS_DEMO:
        op = Operador.query.filter_by(usuario=usuario).first()
        if op is not None and op.nombre != nombre:
            auditoria.auditar(
                "nombre_actualizado", f"{usuario}: {op.nombre} → {nombre}", operador=op
            )
            op.nombre = nombre
            cambios += 1
    if cambios:
        db.session.commit()
        auditoria.sellar_pendientes()
    return cambios


def poblar() -> bool:
    """Crea los datos si la base está vacía. Devuelve True si creó algo."""
    if Operador.query.first() is not None:
        sincronizar_nombres_demo()
        return False

    for i, (usuario, nombre, rol) in enumerate(CUENTAS_DEMO, start=1):
        op = Operador(
            codigo=i * 2 + 1, nombre=nombre, cargo=CARGOS[rol], usuario=usuario, rol=rol
        )
        op.fijar_clave(PIN_DEMO if rol in ROLES_CON_PIN else CLAVE_DEMO)
        db.session.add(op)

    cocina = AreaProduccion(codigo=1, descripcion="Cocina")
    frente = AreaProduccion(codigo=2, descripcion="Frente")
    db.session.add_all([cocina, frente])

    salon = Sala(nombre="Salón", orden=1, tipo="salon")
    rapido = Sala(nombre="Servicio rápido", orden=2, tipo="rapido")
    reservado = Sala(nombre="Reservado", orden=3, tipo="salon")
    db.session.add_all([salon, rapido, reservado])
    db.session.flush()
    for n in range(1, 31):
        db.session.add(
            Mesa(
                numero=n,
                sala=salon,
                puestos=6 if n in (13, 14, 15) else 4,
                estado="fuera" if n == 30 else "disponible",
            )
        )
    for n in range(31, 35):
        db.session.add(
            Mesa(
                numero=n, sala=rapido, puestos=1, nombre_especial=f"Mostrador {n - 30}"
            )
        )
    for n in range(35, 39):
        db.session.add(
            Mesa(numero=n, sala=reservado, puestos=10, nombre_especial="Eventos")
        )

    secciones = {}
    for orden, (nombre, color) in enumerate(SECCIONES, start=1):
        secciones[nombre] = Seccion(nombre=nombre, orden=orden, color=color)
        db.session.add(secciones[nombre])
    db.session.flush()

    for codigo, (sec, desc, corta, precio, area, extras) in enumerate(
        PRODUCTOS, start=101
    ):
        alcohol = "alcohol" in extras
        db.session.add(
            Producto(
                codigo=codigo,
                descripcion=desc,
                descripcion_corta=corta[:30],
                seccion=secciones[sec],
                area1=cocina if area == "C" else frente,
                precio=Decimal(precio),
                tasa_itbms=7,
                es_alcoholica=alcohol,
                aplica_jubilado=not (alcohol or "sin_jub" in extras),
                con_acompanamiento="acomp" in extras,
                tipo="menu" if area == "C" else "directo",
            )
        )

    for codigo, desc, precio in ACOMPANAMIENTOS:
        db.session.add(
            Acompanamiento(codigo=codigo, descripcion=desc, precio=Decimal(precio))
        )
    for codigo, desc in enumerate(NOTAS, start=1):
        db.session.add(NotaFija(codigo=codigo, descripcion=desc.upper()))
    for ruc, dv, tipo, nombre, pago, limite in CLIENTES:
        db.session.add(
            Cliente(
                ruc=ruc,
                dv=dv or None,
                tipo=tipo,
                nombre=nombre,
                tipo_pago=pago,
                limite_credito=Decimal(limite),
            )
        )

    configuracion.asegurar_valores()
    secuencias.asegurar_secuencias()
    auditoria.auditar("datos_demo", "Se crearon los datos de demostración")
    db.session.commit()
    # Turno de caja abierto para que la demostración permita cobrar desde el primer momento.
    cajera = Operador.query.filter_by(usuario="marta").one()
    caja.abrir_turno(cajera, "50.00")
    db.session.commit()
    auditoria.sellar_pendientes()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Datos de demostración de ComandaPOS")
    parser.add_argument(
        "--reiniciar", action="store_true", help="borra y recrea la base"
    )
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        if args.reiniciar:
            if not app.config["DEMO"]:
                print("No se reinicia la base fuera del modo demostración.")
                return 1
            db.drop_all()
            import os

            ancla = os.path.join(app.config["DATOS"], "auditoria.ancla")
            if os.path.exists(ancla):
                os.remove(ancla)
            db.create_all()
            secuencias.asegurar_secuencias()
            configuracion.asegurar_valores()
        creado = poblar()
        print(
            "Datos de demostración creados."
            if creado
            else "La base ya tenía datos; no se tocó."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
