"""RN-04  Números de comanda y de documento fiscal: secuencias atómicas, sin huecos ni duplicados.

`siguiente()` incrementa y lee en UNA sola sentencia (`UPDATE … RETURNING`): dos terminales que
cobran al mismo tiempo nunca reciben el mismo número. El número queda reservado al confirmar la
transacción del que lo pidió; si esa transacción se revierte, el número vuelve (no hay huecos).
"""

from __future__ import annotations

from sqlalchemy import update

from ..extensions import db
from ..models import Secuencia
from .calculos import ReglaNegocioError

#: Secuencias que el sistema necesita y su valor inicial (el siguiente número será inicial + 1).
SECUENCIAS = {
    "comanda": 0,
    "factura": 0,
    "nota_credito": 0,
    "turno": 0,
}


def asegurar_secuencias() -> None:
    """Crea las secuencias que falten (no toca las existentes)."""
    existentes = {s.nombre for s in Secuencia.query.all()}
    for nombre, inicial in SECUENCIAS.items():
        if nombre not in existentes:
            db.session.add(Secuencia(nombre=nombre, valor=inicial))
    db.session.commit()


def siguiente(nombre: str) -> int:
    """Reserva el siguiente número de la secuencia (el que llama debe confirmar la transacción)."""
    resultado = db.session.execute(
        update(Secuencia)
        .where(Secuencia.nombre == nombre)
        .values(valor=Secuencia.valor + 1)
        .returning(Secuencia.valor)
    )
    valor = resultado.scalar_one_or_none()
    if valor is None:
        raise ReglaNegocioError(f"La secuencia «{nombre}» no existe.")
    return int(valor)


def actual(nombre: str) -> int:
    s = db.session.get(Secuencia, nombre)
    return int(s.valor) if s else 0
