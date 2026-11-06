"""Suscripción mensual de ComandaPOS (SaaS): planes, códigos firmados y modo limitado.

Cómo funciona
-------------
* Cada instalación tiene un **ID de instalación** (archivo `instalacion.id` en la carpeta de datos;
  sobrevive a «nueva base»). El restaurante se lo da al proveedor al pagar.
* El proveedor emite un **código mensual** con `proveedor/emitir_codigo.py`: plan, fecha hasta la
  que cubre, número de serie y el ID de instalación, firmados con su llave privada Ed25519.
  ComandaPOS solo tiene la llave pública (`llave_proveedor.py`): no se puede falsificar un código
  ni usarlo en otra PC, y cada serie se activa una sola vez.
* Fases: prueba (14 días, todo Pro) → activa → por vencer (avisos 5 días antes) → gracia (7 días
  con aviso) → **limitada**: se pueden terminar, cobrar y facturar las cuentas abiertas, cerrar
  caja y ver todo, pero no abrir mesas ni pedidos nuevos hasta activar un código.
* Retroceder el reloj de Windows no alarga la suscripción: se guarda la fecha más alta vista.
* En la demostración no se cobra: todo funciona como Pro.

Planes: **Básico** = el punto de venta (salón, comandas, cobro, factura electrónica, caja, notas
de crédito, catálogos) en esta PC. **Pro** = todo, más cocina, reportes, inventario, crédito de
clientes y terminales en red.
"""

from __future__ import annotations

import base64
import os
import secrets
import struct
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from flask import current_app, g, has_request_context

from ..extensions import db
from ..models import PagoSuscripcion
from . import configuracion
from .calculos import ReglaNegocioError
from .llave_proveedor import LLAVE_PUBLICA

PRUEBA_DIAS = 14
GRACIA_DIAS = 7
AVISO_DIAS = 5

#: Precios de ejemplo en B/. por mes: el proveedor los cambia aquí.
PLANES = {
    "basico": {
        "nombre": "Básico",
        "precio": "29.00",
        "lema": "El punto de venta completo para una caja.",
    },
    "pro": {
        "nombre": "Pro",
        "precio": "59.00",
        "lema": "Todo ComandaPOS: cocina, reportes, inventario y red.",
    },
}

#: Lo que trae cada plan (se muestra en la comparación de planes).
INCLUYE_BASICO = (
    "Mapa de mesas, comandas y servicio rápido",
    "Cobro con todas las formas de pago y vuelto",
    "Factura electrónica DGI y notas de crédito",
    "Apertura, corte X y cierre Z de caja",
    "Descuento de jubilado y anulaciones autorizadas",
    "Productos, secciones, acompañamientos y operadores",
    "Verificación en dos pasos y auditoría encadenada",
)

#: Funciones Pro: clave → (nombre, descripción corta).
FUNCIONES_PRO = {
    "cocina": (
        "Pantalla de cocina",
        "Las comandas llegan solas a cocina y el mesero ve cuándo están listas.",
    ),
    "reportes": (
        "Reportes avanzados",
        "Ventas por hora, mesero, sección y producto; ITBMS y tiempos de cocina en CSV.",
    ),
    "inventario": (
        "Inventario y recetas",
        "Insumos que se descuentan solos con cada venta, entradas y ajustes.",
    ),
    "credito": (
        "Crédito a clientes",
        "Ventas a crédito con límite por cliente, abonos y recibos.",
    ),
    "red": (
        "Terminales en red",
        "Meseros, cocina y caja en varias PC o tabletas del local, por HTTPS.",
    ),
}

#: Pantallas que pertenecen a una función Pro (por endpoint de Flask).
_ENDPOINTS_PRO = {
    "cocina.tablero": "cocina",
    "cocina.marcar": "cocina",
    "reportes.inicio": "reportes",
    "reportes.csv": "reportes",
    "admin.inventario_lista": "inventario",
    "admin.inventario_movimiento": "inventario",
    "admin.receta": "inventario",
    "caja.abono": "credito",
    "caja.recibo": "credito",
}
#: Catálogos genéricos de administración que son Pro.
_CATALOGOS_PRO = {"insumos": "inventario"}

#: Lo único que se puede pedir desde otra PC sin el plan Pro (la pantalla que lo explica).
ENDPOINTS_SIN_RED = {"static", "salud", "service_worker", "sin_servidor"}

ARCHIVO_ID = "instalacion.id"
_EPOCA = date(2024, 1, 1)
_VERSION_CODIGO = 1
_PLAN_A_BYTE = {"basico": 1, "pro": 2}
_BYTE_A_PLAN = {v: k for k, v in _PLAN_A_BYTE.items()}
_FORMATO = ">B10sBHI"  # versión, instalación, plan, días desde 2024-01-01, serie
_LARGO_DATOS = struct.calcsize(_FORMATO)
_LARGO_FIRMA = 64


# --------------------------------------------------------------------------- ID de instalación
def _b32(datos: bytes) -> str:
    return base64.b32encode(datos).decode("ascii").rstrip("=")


def _desde_b32(texto: str) -> bytes:
    limpio = "".join(c for c in texto.upper() if c.isalnum())
    limpio = limpio.replace("0", "O").replace("1", "I").replace("8", "B")
    return base64.b32decode(limpio + "=" * (-len(limpio) % 8))


def _formatear_id(crudo: bytes) -> str:
    t = _b32(crudo)
    return "-".join(t[i : i + 4] for i in range(0, len(t), 4))


def id_instalacion_crudo() -> bytes:
    """10 bytes aleatorios, creados la primera vez y guardados junto a la base."""
    ruta = os.path.join(current_app.config["DATOS"], ARCHIVO_ID)
    try:
        with open(ruta, encoding="ascii") as f:
            crudo = _desde_b32(f.read().strip())
        if len(crudo) == 10:
            return crudo
    except (OSError, ValueError):
        pass
    crudo = secrets.token_bytes(10)
    with open(ruta, "w", encoding="ascii") as f:
        f.write(_formatear_id(crudo) + "\n")
    return crudo


def id_instalacion() -> str:
    """Para mostrar y dictar: «ABCD-EFGH-IJKL-MNOP»."""
    return _formatear_id(id_instalacion_crudo())


# --------------------------------------------------------------------------- códigos
@dataclass(frozen=True)
class Codigo:
    instalacion: bytes
    plan: str
    hasta: date
    serie: int


def armar_codigo(datos: Codigo, firmar) -> str:
    """Arma el texto del código; `firmar(bytes) -> 64 bytes` (lo usa la herramienta del proveedor)."""
    dias = (datos.hasta - _EPOCA).days
    if not 0 <= dias <= 0xFFFF:
        raise ValueError("Fecha fuera de rango.")
    crudo = struct.pack(
        _FORMATO,
        _VERSION_CODIGO,
        datos.instalacion,
        _PLAN_A_BYTE[datos.plan],
        dias,
        datos.serie,
    )
    texto = _b32(crudo + firmar(crudo))
    return "CPOS-" + "-".join(texto[i : i + 6] for i in range(0, len(texto), 6))


def leer_codigo(texto: str, llave_publica: str | None = None) -> Codigo:
    """Valida forma y firma. Lanza ReglaNegocioError con un mensaje para el usuario."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    limpio = (texto or "").strip().upper()
    if limpio.startswith("CPOS"):
        limpio = limpio[4:]
    try:
        crudo = _desde_b32(limpio)
    except (ValueError, TypeError):
        raise ReglaNegocioError(
            "El código no se pudo leer: revisa que esté completo."
        ) from None
    if len(crudo) != _LARGO_DATOS + _LARGO_FIRMA:
        raise ReglaNegocioError(
            "El código está incompleto o tiene letras de más: cópialo otra vez."
        )
    datos, firma = crudo[:_LARGO_DATOS], crudo[_LARGO_DATOS:]
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(llave_publica or LLAVE_PUBLICA)).verify(
            firma, datos
        )
    except InvalidSignature:
        raise ReglaNegocioError(
            "Este código no es válido: no lo emitió tu proveedor de ComandaPOS o se copió mal."
        ) from None
    version, instalacion, plan, dias, serie = struct.unpack(_FORMATO, datos)
    if version != _VERSION_CODIGO or plan not in _BYTE_A_PLAN:
        raise ReglaNegocioError(
            "Este código es de otra versión de ComandaPOS: actualiza el programa."
        )
    return Codigo(instalacion, _BYTE_A_PLAN[plan], _EPOCA + timedelta(days=dias), serie)


# --------------------------------------------------------------------------- estado
def hoy() -> date:
    """Fecha de Panamá, sin dejar que el reloj de la PC vaya hacia atrás (anti-trampa)."""
    real = (datetime.now(timezone.utc) - timedelta(hours=5)).date()
    visto = configuracion.obtener("suscripcion.ultimo_dia", "")
    try:
        ultimo = date.fromisoformat(visto)
    except ValueError:
        ultimo = None
    if ultimo is None or real > ultimo:
        configuracion.fijar("suscripcion.ultimo_dia", real.isoformat())
        db.session.commit()
        return real
    return ultimo


def aplica() -> bool:
    """La suscripción se cobra en producción (en la demostración, todo es Pro)."""
    return not current_app.config["DEMO"] or bool(
        current_app.config.get("SUSCRIPCION_EN_DEMO")
    )


@dataclass(frozen=True)
class Estado:
    fase: str  # demo · prueba · activa · por_vencer · gracia · limitada
    plan: str  # basico · pro
    hasta: date | None
    dias: int  # días que faltan para «hasta» (negativo si ya pasó)
    gracia_hasta: date | None = None

    @property
    def nombre_plan(self) -> str:
        return PLANES[self.plan]["nombre"]

    @property
    def limitado(self) -> bool:
        return self.fase == "limitada"

    @property
    def pro(self) -> bool:
        return self.plan == "pro" and not self.limitado

    @property
    def aviso(self) -> str | None:
        """Texto de la barra de aviso (None si no hay nada que avisar)."""
        if self.fase == "por_vencer":
            return (
                f"Tu suscripción vence en {self.dias} día{'s' if self.dias != 1 else ''}."
                if self.dias
                else "Tu suscripción vence hoy."
            )
        if self.fase == "gracia":
            restan = (
                self.gracia_hasta - (self.hasta + timedelta(days=-self.dias))
            ).days
            return (
                f"Suscripción vencida: te quedan {restan} día{'s' if restan != 1 else ''} de gracia "
                "antes del modo limitado."
            )
        if self.fase == "limitada":
            return "Suscripción vencida: modo limitado. Solo se pueden terminar las cuentas abiertas."
        if self.fase == "prueba" and self.dias <= AVISO_DIAS:
            return f"Tu prueba gratis termina en {self.dias} día{'s' if self.dias != 1 else ''}."
        return None

    @property
    def tono(self) -> str:
        return {"gracia": "alerta", "limitada": "error"}.get(self.fase, "info")


def _inicio_prueba(dia: date) -> date:
    texto = configuracion.obtener("suscripcion.inicio", "")
    try:
        return date.fromisoformat(texto)
    except ValueError:
        configuracion.fijar("suscripcion.inicio", dia.isoformat())
        db.session.commit()
        return dia


def estado() -> Estado:
    """Estado actual (se calcula una vez por petición)."""
    if has_request_context():
        if "suscripcion" not in g:
            g.suscripcion = _calcular_estado()
        return g.suscripcion
    return _calcular_estado()


def _calcular_estado() -> Estado:
    if not aplica():
        return Estado("demo", "pro", None, 0)
    dia = hoy()
    ultimo = PagoSuscripcion.query.order_by(
        PagoSuscripcion.hasta.desc(), PagoSuscripcion.id.desc()
    ).first()
    if ultimo is None:
        fin = _inicio_prueba(dia) + timedelta(days=PRUEBA_DIAS - 1)
        hasta, plan, prueba = fin, "pro", True
    else:
        hasta, plan, prueba = ultimo.hasta, ultimo.plan, False
    dias = (hasta - dia).days
    gracia = hasta + timedelta(days=GRACIA_DIAS)
    if dias >= 0:
        if prueba:
            fase = "prueba"
        else:
            fase = "por_vencer" if dias <= AVISO_DIAS else "activa"
    elif dia <= gracia:
        fase = "gracia"
    else:
        fase = "limitada"
    return Estado(fase, plan, hasta, dias, gracia)


def tiene(funcion: str) -> bool:
    """¿El plan actual incluye esta función Pro?"""
    if funcion not in FUNCIONES_PRO:
        raise ValueError(f"Función desconocida: {funcion}")
    return estado().pro


def funcion_de(endpoint: str | None, argumentos: dict | None = None) -> str | None:
    """La función Pro a la que pertenece una pantalla (None si es del plan Básico)."""
    if endpoint in _ENDPOINTS_PRO:
        return _ENDPOINTS_PRO[endpoint]
    if endpoint and endpoint.startswith("admin.") and argumentos:
        return _CATALOGOS_PRO.get(str(argumentos.get("clave", "")))
    return None


def exigir_operacion(accion: str = "abrir pedidos nuevos") -> None:
    """En modo limitado no se abren mesas ni pedidos nuevos (lo abierto se puede terminar)."""
    if estado().limitado:
        raise ReglaNegocioError(
            f"La suscripción está vencida (modo limitado): no se pueden {accion}. "
            "Termina y cobra las cuentas abiertas, y pide a administración que active el pago del mes."
        )


def activar(texto: str, operador) -> PagoSuscripcion:
    """Activa un código: debe ser de esta instalación, no usado y con fecha vigente."""
    from .auditoria import auditar

    codigo = leer_codigo(texto)
    if codigo.instalacion != id_instalacion_crudo():
        raise ReglaNegocioError(
            "Este código es de otra instalación. Envía a tu proveedor el ID de instalación que "
            "aparece en esta pantalla."
        )
    if PagoSuscripcion.query.filter_by(serie=codigo.serie).first():
        raise ReglaNegocioError("Este código ya se activó antes.")
    if codigo.hasta < hoy():
        raise ReglaNegocioError(
            "Este código ya venció: pide a tu proveedor el del mes en curso."
        )
    pago = PagoSuscripcion(
        serie=codigo.serie,
        plan=codigo.plan,
        hasta=codigo.hasta,
        codigo=" ".join(texto.split())[:200],
        operador_id=getattr(operador, "id", None),
    )
    db.session.add(pago)
    auditar(
        "suscripcion_activada",
        f"plan {codigo.plan} hasta {codigo.hasta.isoformat()} (serie {codigo.serie})",
    )
    db.session.commit()
    g.pop("suscripcion", None)
    return pago


def historial(limite: int = 24) -> list:
    return PagoSuscripcion.query.order_by(PagoSuscripcion.id.desc()).limit(limite).all()
