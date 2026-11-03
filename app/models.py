"""Modelo de datos de ComandaPOS (fase 1: catálogos, operadores, secuencias y auditoría).

El dinero NUNCA se guarda como float: `Dinero` lo almacena en centavos enteros y lo devuelve
como `Decimal` con 2 decimales; `Cantidad` hace lo mismo con milésimas (RN-01). Las tablas de
comandas, cuentas, pagos y documentos fiscales llegan en las fases 2, 4 y 5.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import types
from werkzeug.security import check_password_hash, generate_password_hash

from .config import NOMBRE_ROL, ROLES, ROLES_CON_PIN
from .extensions import db
from .services.calculos import CENTAVO, MILESIMA, ReglaNegocioError, a_decimal


def ahora() -> datetime:
    """Hora UTC sin zona (SQLite no guarda zonas); se muestra en hora de Panamá."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _Escalado(types.TypeDecorator):
    """Decimal guardado como entero escalado: exacto en SQLite y en PostgreSQL."""

    impl = types.BigInteger
    cache_ok = True
    escala = 100
    paso = CENTAVO

    def process_bind_param(self, valor, dialecto):
        if valor is None:
            return None
        d = a_decimal(valor)
        if d != d.quantize(self.paso):
            raise ReglaNegocioError(f"Valor con demasiados decimales: {d}")
        return int(d * self.escala)

    def process_result_value(self, valor, dialecto):
        if valor is None:
            return None
        return (Decimal(int(valor)) / self.escala).quantize(self.paso)


class Dinero(_Escalado):
    escala = 100
    paso = CENTAVO


class Cantidad(_Escalado):
    escala = 1000
    paso = MILESIMA


# --------------------------------------------------------------------------- personas
class Operador(UserMixin, db.Model):
    """Persona que usa el sistema (mesero, cajero, supervisor, administrador o programador)."""

    __tablename__ = "operadores"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.Integer, unique=True, nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    cargo = db.Column(db.String(40), nullable=False, default="Mesero")
    usuario = db.Column(db.String(30), unique=True, nullable=False, index=True)
    clave_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="operador")
    activo = db.Column(db.Boolean, nullable=False, default=True)
    #: Sube al cerrar sesión en todas las terminales o al cambiar la clave (invalida cookies viejas).
    version_sesion = db.Column(db.Integer, nullable=False, default=1)
    creado = db.Column(db.DateTime, nullable=False, default=ahora)
    ultimo_acceso = db.Column(db.DateTime)

    def get_id(self) -> str:
        return f"{self.id}:{self.version_sesion}"

    @property
    def usa_pin(self) -> bool:
        return self.rol in ROLES_CON_PIN

    @property
    def nivel(self) -> int:
        return ROLES.index(self.rol)

    @property
    def nombre_rol(self) -> str:
        return NOMBRE_ROL.get(self.rol, self.rol)

    @property
    def iniciales(self) -> str:
        partes = self.nombre.split()
        return "".join(p[0] for p in partes[:2]).upper() or "?"

    def puede(self, rol_minimo: str) -> bool:
        return self.nivel >= ROLES.index(rol_minimo)

    def fijar_clave(self, clave: str) -> None:
        self.clave_hash = generate_password_hash(clave, method="scrypt")
        self.version_sesion = (self.version_sesion or 0) + 1

    def verificar_clave(self, clave: str) -> bool:
        return bool(clave) and check_password_hash(self.clave_hash, clave)


# --------------------------------------------------------------------------- salón
class Sala(db.Model):
    """Sala de venta (Salón, Servicio rápido, Reservado…)."""

    __tablename__ = "salas"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(40), unique=True, nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)
    tipo = db.Column(
        db.String(20), nullable=False, default="salon"
    )  # salon | llevar | rapido
    activa = db.Column(db.Boolean, nullable=False, default=True)
    mesas = db.relationship("Mesa", back_populates="sala", order_by="Mesa.numero")


ESTADOS_MESA = ("disponible", "ocupada", "precuenta", "pagada", "fuera", "llevar")


class Mesa(db.Model):
    __tablename__ = "mesas"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, unique=True, nullable=False)
    sala_id = db.Column(db.Integer, db.ForeignKey("salas.id"), nullable=False)
    nombre_especial = db.Column(db.String(40))
    puestos = db.Column(db.Integer, nullable=False, default=4)
    estado = db.Column(db.String(12), nullable=False, default="disponible")
    sala = db.relationship("Sala", back_populates="mesas")

    __table_args__ = (
        db.CheckConstraint("puestos BETWEEN 1 AND 40", name="ck_mesa_puestos"),
        db.CheckConstraint(
            "estado IN ('disponible','ocupada','precuenta','pagada','fuera','llevar')",
            name="ck_mesa_estado",
        ),
    )


# --------------------------------------------------------------------------- menú
class AreaProduccion(db.Model):
    """Cocina, Frente/Bar… cada una con su impresora y su pantalla."""

    __tablename__ = "areas_produccion"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.Integer, unique=True, nullable=False)
    descripcion = db.Column(db.String(40), nullable=False)
    impresora = db.Column(db.String(120))
    activa = db.Column(db.Boolean, nullable=False, default=True)


class Seccion(db.Model):
    __tablename__ = "secciones"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(40), unique=True, nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)
    color = db.Column(db.String(7), nullable=False, default="#1d4ed8")
    activa = db.Column(db.Boolean, nullable=False, default=True)
    productos = db.relationship("Producto", back_populates="seccion")


TIPOS_PRODUCTO = ("directo", "menu", "combo")
CONDICIONES = ("activo_sinv", "activo_cinv", "inactivo")


class Producto(db.Model):
    __tablename__ = "productos"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.Integer, unique=True, nullable=False)
    codigo_barras = db.Column(db.String(32))
    descripcion = db.Column(db.String(120), nullable=False)
    descripcion_corta = db.Column(db.String(30), nullable=False)
    seccion_id = db.Column(db.Integer, db.ForeignKey("secciones.id"), nullable=False)
    area1_id = db.Column(
        db.Integer, db.ForeignKey("areas_produccion.id"), nullable=False
    )
    area2_id = db.Column(db.Integer, db.ForeignKey("areas_produccion.id"))
    tipo = db.Column(db.String(10), nullable=False, default="menu")
    precio = db.Column(Dinero, nullable=False)
    #: 0, 7, 10 o 15 (%). La confirma el contador; queda auditado quién la cambia.
    tasa_itbms = db.Column(db.Integer, nullable=False, default=7)
    es_alcoholica = db.Column(db.Boolean, nullable=False, default=False)
    aplica_jubilado = db.Column(db.Boolean, nullable=False, default=True)
    con_acompanamiento = db.Column(db.Boolean, nullable=False, default=False)
    agotado = db.Column(db.Boolean, nullable=False, default=False)
    condicion = db.Column(db.String(12), nullable=False, default="activo_sinv")
    imagen = db.Column(db.String(64))
    creado = db.Column(db.DateTime, nullable=False, default=ahora)

    seccion = db.relationship("Seccion", back_populates="productos")
    area1 = db.relationship("AreaProduccion", foreign_keys=[area1_id])
    area2 = db.relationship("AreaProduccion", foreign_keys=[area2_id])

    __table_args__ = (
        db.CheckConstraint("tasa_itbms IN (0, 7, 10, 15)", name="ck_producto_tasa"),
        db.CheckConstraint("precio >= 0", name="ck_producto_precio"),
        db.CheckConstraint(
            "tipo IN ('directo','menu','combo')", name="ck_producto_tipo"
        ),
    )

    @property
    def disponible(self) -> bool:
        return self.condicion != "inactivo" and not self.agotado


class Acompanamiento(db.Model):
    __tablename__ = "acompanamientos"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.Integer, unique=True, nullable=False)
    descripcion = db.Column(db.String(40), nullable=False)
    precio = db.Column(Dinero, nullable=False, default=Decimal("0.00"))
    activo = db.Column(db.Boolean, nullable=False, default=True)


class NotaFija(db.Model):
    __tablename__ = "notas_fijas"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.Integer, unique=True, nullable=False)
    descripcion = db.Column(db.String(60), nullable=False)
    activa = db.Column(db.Boolean, nullable=False, default=True)


# --------------------------------------------------------------------------- clientes
TIPOS_CLIENTE = ("natural", "juridico", "extranjero", "consumidor_final")
TIPOS_PAGO_CLIENTE = ("contado", "autorizado", "personal", "credito")


class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    ruc = db.Column(db.String(30), unique=True, nullable=False)
    dv = db.Column(db.String(3))
    tipo = db.Column(db.String(16), nullable=False, default="juridico")
    nombre = db.Column(db.String(120), nullable=False)
    correo = db.Column(db.String(120))
    tipo_pago = db.Column(db.String(12), nullable=False, default="contado")
    limite_credito = db.Column(Dinero, nullable=False, default=Decimal("0.00"))
    activo = db.Column(db.Boolean, nullable=False, default=True)


# --------------------------------------------------------------------------- sistema
class Config(db.Model):
    """Pares clave-valor: datos del emisor, porcentajes de jubilado, umbrales…"""

    __tablename__ = "config"
    clave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.Text, nullable=False, default="")


class Secuencia(db.Model):
    """Contadores atómicos sin huecos: # comanda, # documento fiscal… (RN-04)."""

    __tablename__ = "secuencias"
    nombre = db.Column(db.String(40), primary_key=True)
    valor = db.Column(db.BigInteger, nullable=False, default=0)


class Auditoria(db.Model):
    """Bitácora encadenada con HMAC: editar, borrar o truncar registros se detecta (A08/A09)."""

    __tablename__ = "auditoria"
    __table_args__ = {"sqlite_autoincrement": True}  # los id nunca se reutilizan
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, nullable=False, default=ahora)
    operador_id = db.Column(db.Integer, db.ForeignKey("operadores.id"))
    autorizador_id = db.Column(db.Integer, db.ForeignKey("operadores.id"))
    accion = db.Column(db.String(40), nullable=False, index=True)
    detalle = db.Column(db.String(300), nullable=False, default="")
    terminal = db.Column(db.String(60), nullable=False, default="")
    #: Se llenan al «sellar», justo después de confirmar la transacción. `sello` define el orden
    #: de la cadena (1, 2, 3…); `hash_previo` es el `hash` del registro con el sello anterior.
    sello = db.Column(db.Integer, unique=True)
    hash_previo = db.Column(db.String(64), unique=True)
    hash = db.Column(db.String(64), unique=True)

    operador = db.relationship("Operador", foreign_keys=[operador_id])
    autorizador = db.relationship("Operador", foreign_keys=[autorizador_id])
