"""Configuración guardada en la base (datos del emisor, porcentajes, umbrales).

Los valores por defecto viven aquí para que el sistema funcione recién instalado. Los temas
fiscales quedan marcados como «por confirmar con el contador» (ver docs/SUPOSICIONES.md).
"""

from __future__ import annotations

from ..extensions import db
from ..models import Config

#: Emisor ficticio: SOLO en la demostración (H-01). En producción el emisor arranca vacío y el
#: sistema no cobra hasta que el administrador escriba los datos reales.
RUC_DEMO = "155000000-2-2026"
EMISOR_DEMO = {
    "emisor.razon_social": "RESTAURANTE EL FOGON, S.A. (DEMO)",
    "emisor.nombre_comercial": "Restaurante El Fogón",
    "emisor.ruc": RUC_DEMO,
    "emisor.dv": "00",
    "emisor.direccion": "Calle Central, David, Chiriquí",
    "emisor.telefono": "775-0000",
}
#: Diferencias de la demostración respecto de producción.
SOLO_DEMO = {
    **EMISOR_DEMO,
    "fiscal.proveedor": "simulado",
    "fiscal.folios_total": "7200",
}

VALORES_POR_DEFECTO = {
    "emisor.razon_social": "",
    "emisor.nombre_comercial": "",
    "emisor.ruc": "",
    "emisor.dv": "",
    "emisor.direccion": "",
    "emisor.telefono": "",
    "emisor.sucursal": "0000",
    "emisor.punto_facturacion": "001",
    "emisor.contribuyente_itbms": "1",
    # Ley 6 de 1987: 25 % restaurante, 15 % franquicia de comida rápida, 0 % fonda.
    "negocio.tipo_establecimiento": "restaurante",
    "descuento.jubilado.restaurante": "25",
    "descuento.jubilado.franquicia": "15",
    "descuento.jubilado.fonda": "0",
    # RN-07: por encima de este % un descuento de producto requiere supervisor.
    "descuento.tope_sin_supervisor": "10",
    "cocina.umbral_amarillo_min": "10",
    "cocina.umbral_rojo_min": "20",
    # Facturación electrónica: «simulado» solo funciona en la demostración; «http» = PAC real.
    # En producción arranca en «ninguno» (todo en contingencia) hasta configurar el PAC.
    "fiscal.proveedor": "ninguno",
    "fiscal.pac_url": "",
    "fiscal.folios_total": "0",
    "fiscal.simular_caida": "0",
    # Impresión: id de la impresora de caja (comprobantes y gaveta) y opciones.
    "impresion.caja": "",
    "impresion.comprobante_en_ticket": "1",
    "impresion.abrir_gaveta": "1",
    # Inventario: marcar agotado un producto cuando un insumo de su receta llega a 0.
    "inventario.agotar_en_cero": "1",
    # H-13: no enviar a cocina lo que el inventario no cubre (productos con control de inventario).
    "inventario.bloquear_sin_existencia": "1",
    # Red local: IP o redes (CIDR) de las terminales permitidas, separadas por coma. Vacío = solo este equipo.
    "red.terminales": "",
}

#: Claves que se editan en Administración → Configuración (con su etiqueta y tipo).
EDITABLES = [
    (
        "Emisor (datos fiscales)",
        [
            ("emisor.razon_social", "Razón social", "texto"),
            ("emisor.nombre_comercial", "Nombre comercial", "texto"),
            ("emisor.ruc", "RUC", "texto"),
            ("emisor.dv", "DV", "texto"),
            ("emisor.direccion", "Dirección", "texto"),
            ("emisor.telefono", "Teléfono", "texto"),
            ("emisor.sucursal", "Código de sucursal", "texto"),
            ("emisor.punto_facturacion", "Punto de facturación", "texto"),
            ("emisor.contribuyente_itbms", "Contribuyente de ITBMS", "si_no"),
        ],
    ),
    (
        "Descuentos",
        [
            (
                "negocio.tipo_establecimiento",
                "Tipo de establecimiento (Ley 6 de 1987)",
                "establecimiento",
            ),
            (
                "descuento.jubilado.restaurante",
                "% jubilado en restaurante",
                "porcentaje",
            ),
            (
                "descuento.jubilado.franquicia",
                "% jubilado en franquicia de comida rápida",
                "porcentaje",
            ),
            ("descuento.jubilado.fonda", "% jubilado en fonda", "porcentaje"),
            (
                "descuento.tope_sin_supervisor",
                "Descuento máximo sin supervisor (%)",
                "porcentaje",
            ),
        ],
    ),
    (
        "Cocina",
        [
            ("cocina.umbral_amarillo_min", "Minutos para amarillo", "entero"),
            ("cocina.umbral_rojo_min", "Minutos para rojo", "entero"),
        ],
    ),
    (
        "Facturación electrónica",
        [
            ("fiscal.proveedor", "Proveedor fiscal", "proveedor"),
            ("fiscal.pac_url", "URL del PAC (https)", "url"),
            ("fiscal.folios_total", "Folios comprados", "entero"),
            (
                "fiscal.simular_caida",
                "Simular caída del PAC (solo demostración)",
                "si_no",
            ),
        ],
    ),
    (
        "Impresión",
        [
            (
                "impresion.comprobante_en_ticket",
                "Imprimir el comprobante en la impresora de caja",
                "si_no",
            ),
            (
                "impresion.abrir_gaveta",
                "Abrir la gaveta al cobrar en efectivo",
                "si_no",
            ),
        ],
    ),
    (
        "Inventario y red",
        [
            (
                "inventario.agotar_en_cero",
                "Marcar agotado cuando un insumo llega a 0",
                "si_no",
            ),
            (
                "inventario.bloquear_sin_existencia",
                "No enviar pedidos que el inventario no cubre",
                "si_no",
            ),
            (
                "red.terminales",
                "Terminales permitidas (IP o red CIDR, separadas por coma)",
                "red",
            ),
        ],
    ),
]


def obtener(clave: str, defecto: str | None = None) -> str:
    fila = db.session.get(Config, clave)
    if fila is not None:
        return fila.valor
    if defecto is not None:
        return defecto
    return VALORES_POR_DEFECTO.get(clave, "")


def fijar(clave: str, valor) -> None:
    fila = db.session.get(Config, clave)
    if fila is None:
        db.session.add(Config(clave=clave, valor=str(valor)))
    else:
        fila.valor = str(valor)


def asegurar_valores(demo: bool = False) -> None:
    """Guarda los valores por defecto que falten (no pisa lo que ya configuró el administrador)."""
    valores = {**VALORES_POR_DEFECTO, **(SOLO_DEMO if demo else {})}
    for clave, valor in valores.items():
        if db.session.get(Config, clave) is None:
            db.session.add(Config(clave=clave, valor=valor))
    db.session.commit()


def base_es_demo() -> bool:
    """¿Esta base nació como demostración? (H-01: nunca se usa así en producción)."""
    from ..models import Documento

    if obtener("base.demo") == "1" or obtener("emisor.ruc") == RUC_DEMO:
        return True
    return Documento.query.filter_by(estado="simulado").first() is not None


def emisor_incompleto() -> list:
    """Datos del emisor que faltan para facturar (en producción no se cobra sin ellos)."""
    faltan = []
    for clave, nombre in (
        ("emisor.razon_social", "razón social"),
        ("emisor.ruc", "RUC"),
        ("emisor.dv", "DV"),
        ("emisor.direccion", "dirección"),
    ):
        if not (obtener(clave) or "").strip():
            faltan.append(nombre)
    return faltan


def porcentaje_jubilado() -> str:
    tipo = obtener("negocio.tipo_establecimiento")
    return obtener(f"descuento.jubilado.{tipo}", "25")
