"""Motor de catálogos de la administración: cada catálogo se DECLARA (campos, columnas, validación)
y las pantallas de lista, alta y edición son las mismas para todos.

- Validación en el servidor por tipo de campo (A04): textos con largo máximo y sin caracteres de
  control, enteros con rango, dinero con 2 decimales, opciones cerradas y relaciones existentes.
- Nada se borra: los registros se inactivan (el historial de ventas los sigue necesitando).
- Cada alta y cada cambio queda en la auditoría con «campo: antes → después» (precio y tasa incluidos).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..extensions import db
from ..models import (
    CONDICIONES,
    TIPOS_CLIENTE,
    TIPOS_IMPRESORA,
    TIPOS_PAGO_CLIENTE,
    TIPOS_PRODUCTO,
    Acompanamiento,
    AreaProduccion,
    Cliente,
    Impresora,
    Insumo,
    Mesa,
    Producto,
    Sala,
    Seccion,
)
from ..services.calculos import ReglaNegocioError, a_decimal, validar_precio

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class Campo:
    nombre: str
    etiqueta: str
    tipo: str = (
        "texto"  # texto | entero | dinero | cantidad | si_no | opcion | relacion | color
    )
    requerido: bool = True
    maximo: int = 60
    minimo: int = 0
    opciones: object = None  # lista de (valor, etiqueta) o función que la devuelve
    modelo: object = None  # para «relacion»
    texto_relacion: str = "nombre"
    mayusculas: bool = False
    ayuda: str = ""
    opcion_entera: bool = (
        False  # la opción se guarda como entero (p. ej. la tasa de ITBMS)
    )

    def lista_opciones(self) -> list:
        if self.tipo == "relacion":
            return [
                (str(o.id), getattr(o, self.texto_relacion))
                for o in self.modelo.query.order_by(
                    getattr(self.modelo, self.texto_relacion)
                ).all()
            ]
        opciones = self.opciones() if callable(self.opciones) else (self.opciones or [])
        return [(str(v), e) for v, e in opciones]

    def convertir(self, texto: str):
        texto = (texto or "").strip()
        if self.tipo == "si_no":
            return texto in ("1", "on", "si", "true")
        if not texto:
            if self.requerido:
                raise ReglaNegocioError(f"«{self.etiqueta}» es obligatorio.")
            return None
        if self.tipo in ("texto", "color"):
            texto = " ".join(_CONTROL.sub(" ", texto).split())
            if len(texto) > self.maximo:
                raise ReglaNegocioError(
                    f"«{self.etiqueta}» admite hasta {self.maximo} caracteres."
                )
            if self.tipo == "color" and not _COLOR.match(texto):
                raise ReglaNegocioError(
                    f"«{self.etiqueta}» debe ser un color como #1d4ed8."
                )
            return texto.upper() if self.mayusculas else texto
        if (
            self.tipo == "entero"
        ):  # en los enteros, «minimo» y «maximo» son el rango permitido
            if not re.fullmatch(r"-?\d{1,9}", texto):
                raise ReglaNegocioError(f"«{self.etiqueta}» debe ser un número entero.")
            n = int(texto)
            if not self.minimo <= n <= self.maximo:
                raise ReglaNegocioError(
                    f"«{self.etiqueta}» debe estar entre {self.minimo} y {self.maximo}."
                )
            return n
        if self.tipo == "dinero":  # minimo=1 → debe ser mayor que 0
            return validar_precio(
                texto, self.etiqueta[:1].lower() + self.etiqueta[1:], permitir_cero=self.minimo == 0
            )
        if self.tipo == "cantidad":
            c = a_decimal(texto, self.etiqueta)
            if c < 0 or c > Decimal("999999.999") or c != c.quantize(Decimal("0.001")):
                raise ReglaNegocioError(f"«{self.etiqueta}» no es válida.")
            return c
        if self.tipo in ("opcion", "relacion"):
            if texto not in {v for v, _ in self.lista_opciones()}:
                raise ReglaNegocioError(
                    f"Elige una opción válida en «{self.etiqueta}»."
                )
            return (
                int(texto) if (self.tipo == "relacion" or self.opcion_entera) else texto
            )
        raise ReglaNegocioError("Tipo de campo desconocido.")  # pragma: no cover


_FEMENINOS = {"sección", "área", "sala", "mesa", "impresora"}


@dataclass
class Catalogo:
    clave: str
    titulo: str
    singular: str
    modelo: object
    campos: list
    columnas: list  # (atributo con puntos, etiqueta)
    orden: object
    busqueda: tuple = ()
    activo: str | None = None  # atributo booleano de estado
    validar: object = None  # función(obj) que lanza ReglaNegocioError
    solo_editar: bool = False
    ayuda: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def nuevo(self) -> str:
        """«Nueva sección», «Nuevo producto»: concordancia de género en botones y títulos."""
        return "Nueva" if self.singular in _FEMENINOS else "Nuevo"

    def valor(self, obj, atributo: str):
        for parte in atributo.split("."):
            obj = getattr(obj, parte, None) if obj is not None else None
        return obj


def _validar_impresora(imp: Impresora) -> None:
    from ..services.impresion import validar_destino

    try:
        imp.destino = validar_destino(imp.tipo, imp.destino)
    except ValueError as e:
        raise ReglaNegocioError(str(e)) from None
    if not 24 <= imp.columnas <= 64:
        raise ReglaNegocioError("Las columnas van de 24 a 64 (80 mm ≈ 42 o 48).")


def _validar_producto(p: Producto) -> None:
    if p.area2_id is not None and p.area2_id == p.area1_id:
        p.area2_id = None
    if p.precio is None or p.precio <= 0:
        raise ReglaNegocioError("El precio debe ser mayor que 0.")


def _validar_cliente(c: Cliente) -> None:
    if c.tipo in ("natural", "juridico") and not (c.dv or "").isdigit():
        raise ReglaNegocioError(
            "El DV es obligatorio para contribuyentes (1 a 3 dígitos)."
        )
    if c.tipo_pago in ("credito", "autorizado") and (c.limite_credito or 0) <= 0:
        raise ReglaNegocioError("Indica el límite de crédito.")


TASAS = [
    (0, "Exento (0 %)"),
    (7, "7 % (general)"),
    (10, "10 % (bebidas alcohólicas)"),
    (15, "15 % (tabaco)"),
]
NOMBRE_TIPO_PRODUCTO = {
    "directo": "Producto directo",
    "menu": "Menú / orden",
    "combo": "Combo",
}
NOMBRE_CONDICION = {
    "activo_sinv": "Activo sin inventario",
    "activo_cinv": "Activo con inventario (receta)",
    "inactivo": "Inactivo",
}

CATALOGOS = {
    c.clave: c
    for c in [
        Catalogo(
            "productos",
            "Productos del menú",
            "producto",
            Producto,
            campos=[
                Campo("codigo", "Código", "entero", minimo=1, maximo=999999),
                Campo("descripcion", "Descripción larga", maximo=120),
                Campo(
                    "descripcion_corta",
                    "Descripción corta (botón y comanda)",
                    maximo=30,
                    mayusculas=True,
                ),
                Campo("seccion_id", "Sección", "relacion", modelo=Seccion),
                Campo(
                    "area1_id",
                    "Área de producción",
                    "relacion",
                    modelo=AreaProduccion,
                    texto_relacion="descripcion",
                ),
                Campo(
                    "area2_id",
                    "Segunda área (opcional)",
                    "relacion",
                    requerido=False,
                    modelo=AreaProduccion,
                    texto_relacion="descripcion",
                ),
                Campo(
                    "tipo",
                    "Tipo",
                    "opcion",
                    opciones=[(t, NOMBRE_TIPO_PRODUCTO[t]) for t in TIPOS_PRODUCTO],
                ),
                Campo("precio", "Precio (B/.)", "dinero", minimo=1),
                Campo(
                    "tasa_itbms",
                    "ITBMS",
                    "opcion",
                    opciones=TASAS,
                    opcion_entera=True,
                    ayuda="La confirma el contador. Cada cambio queda en la auditoría.",
                ),
                Campo("es_alcoholica", "Bebida alcohólica", "si_no"),
                Campo("aplica_jubilado", "Aplica descuento de jubilado", "si_no"),
                Campo("con_acompanamiento", "Lleva acompañamiento", "si_no"),
                Campo(
                    "condicion",
                    "Condición",
                    "opcion",
                    opciones=[(c, NOMBRE_CONDICION[c]) for c in CONDICIONES],
                ),
                Campo("agotado", "Agotado", "si_no"),
                Campo("codigo_barras", "Código de barras", requerido=False, maximo=32),
            ],
            columnas=[
                ("codigo", "Código"),
                ("descripcion_corta", "Botón"),
                ("seccion.nombre", "Sección"),
                ("area1.descripcion", "Área"),
                ("precio", "Precio"),
                ("tasa_itbms", "ITBMS %"),
                ("condicion", "Condición"),
                ("agotado", "Agotado"),
            ],
            orden=Producto.codigo,
            busqueda=("descripcion", "descripcion_corta"),
            validar=_validar_producto,
        ),
        Catalogo(
            "secciones",
            "Secciones del menú",
            "sección",
            Seccion,
            campos=[
                Campo("nombre", "Nombre", maximo=40),
                Campo("orden", "Orden", "entero", maximo=999),
                Campo("color", "Color del botón", "color", maximo=7),
                Campo("activa", "Activa", "si_no"),
            ],
            columnas=[
                ("orden", "Orden"),
                ("nombre", "Nombre"),
                ("color", "Color"),
                ("activa", "Activa"),
            ],
            orden=Seccion.orden,
            busqueda=("nombre",),
            activo="activa",
        ),
        Catalogo(
            "acompanamientos",
            "Acompañamientos",
            "acompañamiento",
            Acompanamiento,
            campos=[
                Campo("codigo", "Código", "entero", minimo=1, maximo=999999),
                Campo("descripcion", "Descripción", maximo=40),
                Campo("precio", "Precio adicional (B/.)", "dinero"),
                Campo("activo", "Activo", "si_no"),
            ],
            columnas=[
                ("codigo", "Código"),
                ("descripcion", "Descripción"),
                ("precio", "Adicional"),
                ("activo", "Activo"),
            ],
            orden=Acompanamiento.codigo,
            busqueda=("descripcion",),
            activo="activo",
        ),
        Catalogo(
            "areas",
            "Áreas de producción",
            "área",
            AreaProduccion,
            campos=[
                Campo("codigo", "Código", "entero", minimo=1, maximo=99),
                Campo("descripcion", "Descripción", maximo=40),
                Campo(
                    "impresora_id",
                    "Impresora",
                    "relacion",
                    requerido=False,
                    modelo=Impresora,
                ),
                Campo("activa", "Activa", "si_no"),
            ],
            columnas=[
                ("codigo", "Código"),
                ("descripcion", "Descripción"),
                ("impresora_obj.nombre", "Impresora"),
                ("activa", "Activa"),
            ],
            orden=AreaProduccion.codigo,
            activo="activa",
        ),
        Catalogo(
            "salas",
            "Salas de venta",
            "sala",
            Sala,
            campos=[
                Campo("nombre", "Nombre", maximo=40),
                Campo("orden", "Orden", "entero", maximo=99),
                Campo(
                    "tipo",
                    "Tipo",
                    "opcion",
                    opciones=[
                        ("salon", "Mesa · salón"),
                        ("rapido", "Servicio rápido"),
                        ("llevar", "Para llevar"),
                    ],
                ),
                Campo("activa", "Activa", "si_no"),
            ],
            columnas=[
                ("orden", "Orden"),
                ("nombre", "Nombre"),
                ("tipo", "Tipo"),
                ("activa", "Activa"),
            ],
            orden=Sala.orden,
            activo="activa",
        ),
        Catalogo(
            "mesas",
            "Configurar mesas",
            "mesa",
            Mesa,
            campos=[
                Campo("numero", "Número", "entero", minimo=1, maximo=999),
                Campo("sala_id", "Sala", "relacion", modelo=Sala),
                Campo("nombre_especial", "Nombre especial", requerido=False, maximo=40),
                Campo("puestos", "Puestos", "entero", minimo=1, maximo=40),
            ],
            columnas=[
                ("numero", "Mesa"),
                ("sala.nombre", "Sala"),
                ("nombre_especial", "Nombre"),
                ("puestos", "Puestos"),
                ("estado", "Estado"),
            ],
            orden=Mesa.numero,
            ayuda="Para ponerla fuera de servicio, tócala en el mapa de mesas.",
        ),
        Catalogo(
            "impresoras",
            "Impresoras",
            "impresora",
            Impresora,
            campos=[
                Campo("nombre", "Nombre", maximo=40),
                Campo("tipo", "Tipo", "opcion", opciones=list(TIPOS_IMPRESORA.items())),
                Campo(
                    "destino",
                    "Destino",
                    maximo=200,
                    ayuda="Red: IP:puerto (192.168.1.50:9100). Windows: nombre exacto. Archivo: nombre corto.",
                ),
                Campo(
                    "columnas",
                    "Columnas (80 mm ≈ 42 o 48)",
                    "entero",
                    minimo=24,
                    maximo=64,
                ),
                Campo("activa", "Activa", "si_no"),
            ],
            columnas=[
                ("nombre", "Nombre"),
                ("tipo", "Tipo"),
                ("destino", "Destino"),
                ("columnas", "Col."),
                ("activa", "Activa"),
            ],
            orden=Impresora.nombre,
            activo="activa",
            validar=_validar_impresora,
        ),
        Catalogo(
            "insumos",
            "Insumos",
            "insumo",
            Insumo,
            campos=[
                Campo("codigo", "Código", "entero", minimo=1, maximo=999999),
                Campo("nombre", "Nombre", maximo=60),
                Campo(
                    "unidad",
                    "Unidad",
                    "opcion",
                    opciones=[
                        (u, u) for u in ("unid", "lb", "kg", "g", "l", "ml", "oz")
                    ],
                ),
                Campo("minimo", "Existencia mínima (alerta)", "cantidad"),
                Campo("activo", "Activo", "si_no"),
            ],
            columnas=[
                ("codigo", "Código"),
                ("nombre", "Nombre"),
                ("existencia", "Existencia"),
                ("unidad", "Unidad"),
                ("minimo", "Mínimo"),
                ("activo", "Activo"),
            ],
            orden=Insumo.codigo,
            busqueda=("nombre",),
            activo="activo",
            ayuda="La existencia cambia con entradas y ajustes (Inventario) y con las ventas.",
        ),
        Catalogo(
            "clientes",
            "Clientes",
            "cliente",
            Cliente,
            campos=[
                Campo("ruc", "Cédula / RUC / pasaporte", maximo=30, mayusculas=True),
                Campo("dv", "DV", requerido=False, maximo=3),
                Campo(
                    "tipo",
                    "Tipo",
                    "opcion",
                    opciones=[
                        (t, t.replace("_", " ").capitalize()) for t in TIPOS_CLIENTE
                    ],
                ),
                Campo("nombre", "Nombre o razón social", maximo=120, mayusculas=True),
                Campo("correo", "Correo", requerido=False, maximo=120),
                Campo(
                    "tipo_pago",
                    "Tipo de pago",
                    "opcion",
                    opciones=[(t, t.capitalize()) for t in TIPOS_PAGO_CLIENTE],
                ),
                Campo(
                    "limite_credito",
                    "Límite de crédito (B/.)",
                    "dinero",
                    requerido=False,
                ),
                Campo("activo", "Activo", "si_no"),
            ],
            columnas=[
                ("ruc", "RUC"),
                ("dv", "DV"),
                ("nombre", "Nombre"),
                ("tipo_pago", "Pago"),
                ("limite_credito", "Límite"),
                ("activo", "Activo"),
            ],
            orden=Cliente.nombre,
            busqueda=("nombre", "ruc"),
            activo="activo",
            validar=_validar_cliente,
        ),
    ]
}


def aplicar(cat: Catalogo, obj, formulario) -> list:
    """Asigna los campos validados; devuelve los cambios («campo: antes → después»)."""
    cambios = []
    for campo in cat.campos:
        nuevo = campo.convertir(formulario.get(campo.nombre))
        if campo.tipo == "dinero" and nuevo is None:
            nuevo = Decimal("0.00")
        anterior = getattr(obj, campo.nombre, None)
        if anterior != nuevo:
            cambios.append(f"{campo.nombre}: {anterior} → {nuevo}")
            setattr(obj, campo.nombre, nuevo)
    if cat.validar is not None:
        cat.validar(obj)
    return cambios


def lista(cat: Catalogo, q: str):
    consulta = cat.modelo.query
    if q and cat.busqueda:
        patron = f"%{q}%"
        consulta = consulta.filter(
            db.or_(*[getattr(cat.modelo, c).ilike(patron) for c in cat.busqueda])
        )
    return consulta.order_by(cat.orden).limit(500).all()
