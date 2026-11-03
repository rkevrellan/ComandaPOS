"""Reglas de negocio de dinero e impuestos (independientes de Flask y de la base de datos).

RN-01  Dinero en `Decimal`, redondeo half-up a 2 decimales. El ITBMS se calcula POR LÍNEA
       (base × tasa, redondeado) y los totales son la SUMA de las líneas: así el documento
       cuadra al centavo con el detalle del XML fiscal.
RN-02  Los descuentos reducen la base gravable antes del ITBMS.
RN-03  Montos y cantidades no finitos, negativos o cero se rechazan; la pantalla solo manda
       la intención (producto y cantidad) y el servidor recalcula todo.
RN-06  Descuento de jubilado (Ley 6 de 1987): porcentaje configurable sobre el consumo
       individual de comida (solo productos que aplican). No se combina con otro descuento
       en la misma línea: se aplica el MAYOR de los dos (lo más favorable al cliente).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTAVO = Decimal("0.01")
MILESIMA = Decimal("0.001")
CIEN = Decimal("100")

#: Tasas de ITBMS permitidas (en %). La tasa de cada producto la confirma el contador.
TASAS_ITBMS = (0, 7, 10, 15)

#: Límites de cordura (RN-03): un error de dedo no puede crear una cuenta de millones.
PRECIO_MAXIMO = Decimal("99999.99")
CANTIDAD_MAXIMA = Decimal("999.999")


class ReglaNegocioError(ValueError):
    """Se lanza cuando un dato viola una regla de negocio (se muestra al usuario, código 422)."""


def a_decimal(valor, campo: str = "valor") -> Decimal:
    """Convierte a `Decimal` sin pasar por float y rechaza NaN e infinitos (RN-03)."""
    if isinstance(valor, bool):
        raise ReglaNegocioError(f"El campo «{campo}» debe ser numérico.")
    if isinstance(valor, Decimal):
        d = valor
    else:
        texto = str(valor).strip().replace(",", "") if valor is not None else ""
        try:
            d = Decimal(texto)
        except (InvalidOperation, ValueError):
            raise ReglaNegocioError(f"El campo «{campo}» debe ser numérico.") from None
    if not d.is_finite():
        raise ReglaNegocioError(f"El campo «{campo}» debe ser un número finito.")
    return d


def redondear(valor) -> Decimal:
    """RN-01: half-up a 2 decimales (0.005 → 0.01)."""
    return a_decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def validar_precio(
    valor, campo: str = "precio", permitir_cero: bool = False
) -> Decimal:
    p = a_decimal(valor, campo)
    if p < 0 or (p == 0 and not permitir_cero):
        raise ReglaNegocioError(f"El {campo} debe ser mayor que 0.")
    if p > PRECIO_MAXIMO:
        raise ReglaNegocioError(
            f"El {campo} no puede pasar de B/. {PRECIO_MAXIMO:,.2f}."
        )
    if p != p.quantize(CENTAVO):
        raise ReglaNegocioError(f"El {campo} admite como máximo 2 decimales.")
    return p.quantize(CENTAVO)


def validar_cantidad(valor) -> Decimal:
    c = a_decimal(valor, "cantidad")
    if c <= 0:
        raise ReglaNegocioError("La cantidad debe ser mayor que 0.")
    if c > CANTIDAD_MAXIMA:
        raise ReglaNegocioError("La cantidad es demasiado grande.")
    if c != c.quantize(MILESIMA):
        raise ReglaNegocioError("La cantidad admite como máximo 3 decimales.")
    return c.quantize(MILESIMA)


def validar_porcentaje(valor, campo: str = "descuento") -> Decimal:
    p = a_decimal(valor, campo)
    if p < 0 or p > CIEN:
        raise ReglaNegocioError(f"El {campo} debe estar entre 0 y 100 %.")
    return p


def validar_tasa(valor) -> int:
    d = a_decimal(valor, "tasa de ITBMS")
    if d not in TASAS_ITBMS:  # Decimal("7.0") == 7, Decimal("7.5") no está
        raise ReglaNegocioError("La tasa de ITBMS debe ser 0, 7, 10 o 15 %.")
    return int(d)


@dataclass(frozen=True)
class LineaCalculo:
    """Datos congelados de una línea de pedido (lo que se cobra y se factura)."""

    cantidad: Decimal
    precio_unitario: Decimal
    tasa_itbms: int = 7
    descuento_pct: Decimal = Decimal("0")
    aplica_jubilado: bool = False

    @classmethod
    def crear(
        cls,
        cantidad,
        precio_unitario,
        tasa_itbms=7,
        descuento_pct=0,
        aplica_jubilado=False,
    ) -> "LineaCalculo":
        return cls(
            validar_cantidad(cantidad),
            validar_precio(precio_unitario, "precio unitario", permitir_cero=True),
            validar_tasa(tasa_itbms),
            validar_porcentaje(descuento_pct),
            bool(aplica_jubilado),
        )


@dataclass(frozen=True)
class ResultadoLinea:
    bruto: Decimal  # cantidad × precio
    descuento: Decimal  # monto descontado (producto o jubilado)
    es_jubilado: bool  # True si el descuento aplicado fue el de jubilado
    base: Decimal  # bruto − descuento (base gravable o exenta)
    tasa: int
    itbms: Decimal
    total: Decimal  # base + itbms


def calcular_linea(linea: LineaCalculo, jubilado_pct=0) -> ResultadoLinea:
    """RN-01, RN-02 y RN-06 para una línea."""
    jub = validar_porcentaje(jubilado_pct, "descuento de jubilado")
    bruto = redondear(linea.cantidad * linea.precio_unitario)
    pct_prd = linea.descuento_pct
    pct_jub = jub if linea.aplica_jubilado else Decimal("0")
    es_jubilado = pct_jub > 0 and pct_jub >= pct_prd
    pct = pct_jub if es_jubilado else pct_prd
    descuento = redondear(bruto * pct / CIEN)
    base = bruto - descuento
    itbms = redondear(base * linea.tasa_itbms / CIEN)
    return ResultadoLinea(
        bruto, descuento, es_jubilado, base, linea.tasa_itbms, itbms, base + itbms
    )


@dataclass
class Totales:
    """Lo que se muestra como SB-TOT, DES-PRD, DES-JUB, ITBMS y TOTAL."""

    subtotal: Decimal = Decimal("0.00")
    descuento_producto: Decimal = Decimal("0.00")
    descuento_jubilado: Decimal = Decimal("0.00")
    itbms: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    base_por_tasa: dict = field(default_factory=dict)
    itbms_por_tasa: dict = field(default_factory=dict)
    lineas: list = field(default_factory=list)

    @property
    def base_gravable(self) -> Decimal:
        return sum((v for t, v in self.base_por_tasa.items() if t > 0), Decimal("0.00"))

    @property
    def base_exenta(self) -> Decimal:
        return self.base_por_tasa.get(0, Decimal("0.00"))


def totalizar(lineas, jubilado_pct=0) -> Totales:
    """RN-01: los totales son la suma exacta de las líneas ya redondeadas."""
    t = Totales()
    for linea in lineas:
        r = calcular_linea(linea, jubilado_pct)
        t.lineas.append(r)
        t.subtotal += r.bruto
        if r.es_jubilado:
            t.descuento_jubilado += r.descuento
        else:
            t.descuento_producto += r.descuento
        t.itbms += r.itbms
        t.total += r.total
        t.base_por_tasa[r.tasa] = t.base_por_tasa.get(r.tasa, Decimal("0.00")) + r.base
        t.itbms_por_tasa[r.tasa] = (
            t.itbms_por_tasa.get(r.tasa, Decimal("0.00")) + r.itbms
        )
    return t


def vuelto(total, recibido) -> Decimal:
    """Vuelto de un pago en efectivo (RN-09: el efectivo puede exceder el saldo)."""
    total = redondear(total)
    recibido = redondear(recibido)
    if recibido < total:
        raise ReglaNegocioError(
            f"Falta dinero: el total es B/. {total:,.2f} y se recibió B/. {recibido:,.2f}."
        )
    return recibido - total
