"""Configuración guardada en la base (datos del emisor, porcentajes, umbrales).

Los valores por defecto viven aquí para que el sistema funcione recién instalado. Los temas
fiscales quedan marcados como «por confirmar con el contador» (ver docs/SUPOSICIONES.md).
"""

from __future__ import annotations

from ..extensions import db
from ..models import Config

VALORES_POR_DEFECTO = {
    "emisor.razon_social": "RESTAURANTE EL FOGON, S.A. (DEMO)",
    "emisor.nombre_comercial": "Restaurante El Fogón",
    "emisor.ruc": "155000000-2-2026",
    "emisor.dv": "00",
    "emisor.direccion": "Calle Central, David, Chiriquí",
    "emisor.telefono": "775-0000",
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
}


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


def asegurar_valores() -> None:
    """Guarda los valores por defecto que falten (no pisa lo que ya configuró el administrador)."""
    for clave, valor in VALORES_POR_DEFECTO.items():
        if db.session.get(Config, clave) is None:
            db.session.add(Config(clave=clave, valor=valor))
    db.session.commit()


def porcentaje_jubilado() -> str:
    tipo = obtener("negocio.tipo_establecimiento")
    return obtener(f"descuento.jubilado.{tipo}", "25")
