"""Migración ligera: agrega a las tablas existentes las columnas nuevas del modelo.

Así una base creada con una versión anterior se actualiza sola al arrancar, sin perder datos.
Solo AGREGA columnas (nunca borra ni cambia tipos). Toda columna nueva en una tabla existente debe
ser opcional o tener un valor por defecto fijo; si no, se avisa y no se toca la tabla.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from .extensions import db


def _literal(valor) -> str:
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def migrar(app) -> list:
    """Devuelve la lista de columnas agregadas («tabla.columna»)."""
    inspector = inspect(db.engine)
    existentes = set(inspector.get_table_names())
    agregadas = []
    for tabla in db.metadata.sorted_tables:
        if tabla.name not in existentes:
            continue  # create_all() ya la creó completa
        actuales = {c["name"] for c in inspector.get_columns(tabla.name)}
        for columna in tabla.columns:
            if columna.name in actuales:
                continue
            tipo = columna.type.compile(dialect=db.engine.dialect)
            sql = f'ALTER TABLE "{tabla.name}" ADD COLUMN "{columna.name}" {tipo}'
            defecto = (
                columna.default.arg
                if columna.default is not None and columna.default.is_scalar
                else None
            )
            if defecto is not None:
                # Dinero/Cantidad guardan enteros escalados: se convierte con el propio tipo.
                procesar = columna.type.bind_processor(db.engine.dialect)
                sql += " DEFAULT " + _literal(
                    procesar(defecto) if procesar else defecto
                )
            elif not columna.nullable:
                app.logger.warning(
                    "No se agregó %s.%s: es obligatoria y no tiene valor por defecto.",
                    tabla.name,
                    columna.name,
                )
                continue
            with db.engine.begin() as conexion:
                conexion.execute(text(sql))
            agregadas.append(f"{tabla.name}.{columna.name}")
    if agregadas:
        app.logger.info("Migración: columnas agregadas %s", ", ".join(agregadas))
    return agregadas
