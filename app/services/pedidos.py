"""Salón: mesas, comandas, cuentas y líneas de pedido.

RN-03  El servidor recalcula todo: la pantalla solo manda producto, cantidad y cuenta.
RN-05  Idempotencia: «Enviar pedidos», «Agregar» y «Cobrar» llevan una clave única.
RN-07  Un descuento de producto por encima del tope requiere supervisor.
RN-08  Anular una línea enviada requiere supervisor y motivo; una línea cobrada no se anula.
RN-11  No se pide pre-cuenta ni se cobra una cuenta con líneas sin enviar.
RN-12  Una cuenta pagada no admite más líneas.
RN-15  Un producto agotado o inactivo no se puede pedir.
A01    Un mesero solo opera sus comandas; cajero, supervisor y superiores operan todas.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    Acompanamiento,
    Anulacion,
    Comanda,
    Cuenta,
    Idempotencia,
    LineaPedido,
    Mesa,
    NotaFija,
    Operador,
    Producto,
    ahora,
)
from . import configuracion, secuencias
from .auditoria import auditar
from .calculos import LineaCalculo, ReglaNegocioError, totalizar, validar_cantidad

MAX_CUENTAS = 12
MAX_LINEAS_POR_CUENTA = 150
MAX_PUESTOS = 40


# --------------------------------------------------------------------------- acceso
def puede_operar(op: Operador, comanda: Comanda) -> bool:
    return op.puede("cajero") or comanda.mesero_id == op.id


def tomar_idempotencia(clave: str, accion: str) -> bool:
    """Registra la clave en la transacción actual. False si ya se usó (acción repetida)."""
    clave = (clave or "").strip()[:64]
    if len(clave) < 16:
        raise ReglaNegocioError(
            "La pantalla estaba desactualizada. Vuelve a intentarlo."
        )
    if db.session.get(Idempotencia, clave) is not None:
        return False
    db.session.add(Idempotencia(clave=clave, accion=accion))
    try:
        db.session.flush()
    except IntegrityError:  # otro hilo la registró al mismo tiempo
        db.session.rollback()
        return False
    return True


# --------------------------------------------------------------------------- mesas
def abrir_mesa(mesa: Mesa, mesero: Operador, puestos) -> Comanda:
    if mesa.estado != "disponible":
        raise ReglaNegocioError(f"La mesa {mesa.numero} no está disponible.")
    try:
        puestos = int(puestos)
    except (TypeError, ValueError):
        raise ReglaNegocioError("Indica cuántas personas hay en la mesa.") from None
    if not 1 <= puestos <= MAX_PUESTOS:
        raise ReglaNegocioError(f"Los puestos deben estar entre 1 y {MAX_PUESTOS}.")
    comanda = Comanda(
        numero=secuencias.siguiente("comanda"),
        tipo="mesa",
        mesa=mesa,
        mesero_id=mesero.id,
        puestos=puestos,
    )
    comanda.cuentas.append(Cuenta(numero=1))
    db.session.add(comanda)
    mesa.estado = "ocupada"
    auditar(
        "mesa_abierta",
        f"mesa {mesa.numero}, comanda {comanda.numero}, {puestos} puestos",
    )
    return comanda


def abrir_rapida(mesero: Operador) -> Comanda:
    """Pedido directo de mostrador (sin mesa): se cobra al momento."""
    comanda = Comanda(
        numero=secuencias.siguiente("comanda"), tipo="rapido", mesero_id=mesero.id
    )
    comanda.cuentas.append(Cuenta(numero=1))
    db.session.add(comanda)
    auditar("cobro_rapido", f"comanda {comanda.numero}")
    return comanda


def comanda_abierta_de(mesa: Mesa) -> Comanda | None:
    return Comanda.query.filter_by(mesa_id=mesa.id, estado="abierta").first()


def actualizar_mesa(comanda: Comanda) -> None:
    """El estado de la mesa sale del estado de sus cuentas."""
    if comanda.mesa is None:
        return
    if comanda.estado == "cerrada":
        comanda.mesa.estado = "pagada"
        return
    con_consumo = [c for c in comanda.cuentas if c.activas and c.estado != "pagada"]
    if con_consumo and all(c.estado == "precuenta" for c in con_consumo):
        comanda.mesa.estado = "precuenta"
    else:
        comanda.mesa.estado = "ocupada"


def liberar_mesa(mesa: Mesa) -> None:
    if mesa.estado != "pagada":
        raise ReglaNegocioError("Solo se libera una mesa pagada.")
    mesa.estado = "disponible"
    auditar("mesa_liberada", f"mesa {mesa.numero}")


def fuera_de_servicio(mesa: Mesa, fuera: bool) -> None:
    if fuera and mesa.estado != "disponible":
        raise ReglaNegocioError(
            "Solo una mesa disponible puede quedar fuera de servicio."
        )
    if not fuera and mesa.estado != "fuera":
        raise ReglaNegocioError("La mesa no está fuera de servicio.")
    mesa.estado = "fuera" if fuera else "disponible"
    auditar("mesa_fuera" if fuera else "mesa_habilitada", f"mesa {mesa.numero}")


def mover_mesa(comanda: Comanda, destino: Mesa) -> None:
    if comanda.tipo != "mesa" or comanda.estado != "abierta":
        raise ReglaNegocioError("Solo se mueve una comanda de mesa abierta.")
    if destino.estado != "disponible":
        raise ReglaNegocioError(f"La mesa {destino.numero} no está disponible.")
    origen = comanda.mesa
    origen.estado = "disponible"
    comanda.mesa = destino
    actualizar_mesa(comanda)
    auditar(
        "mesa_movida",
        f"comanda {comanda.numero}: mesa {origen.numero} → {destino.numero}",
    )


def cambiar_mesero(comanda: Comanda, nuevo: Operador, autorizador: Operador) -> None:
    if not nuevo.activo:
        raise ReglaNegocioError("Ese mesero no está activo.")
    anterior = comanda.mesero
    comanda.mesero_id = nuevo.id
    auditar(
        "otro_mesero",
        f"comanda {comanda.numero}: {anterior.usuario} → {nuevo.usuario}",
        autorizador=autorizador,
    )


# --------------------------------------------------------------------------- cuentas y líneas
def cuenta_de(comanda: Comanda, numero) -> Cuenta:
    for c in comanda.cuentas:
        if str(c.numero) == str(numero):
            return c
    return comanda.cuentas[0]


def nueva_cuenta(comanda: Comanda) -> Cuenta:
    if len(comanda.cuentas) >= MAX_CUENTAS:
        raise ReglaNegocioError(f"Máximo {MAX_CUENTAS} cuentas por mesa.")
    cuenta = Cuenta(numero=max(c.numero for c in comanda.cuentas) + 1)
    comanda.cuentas.append(cuenta)
    return cuenta


def _cuenta_editable(cuenta: Cuenta) -> None:
    if cuenta.estado == "pagada":
        raise ReglaNegocioError("Esa cuenta ya está pagada; usa otra cuenta.")  # RN-12
    if cuenta.comanda.estado != "abierta":
        raise ReglaNegocioError("La comanda ya está cerrada.")


def _reabrir_si_precuenta(cuenta: Cuenta) -> None:
    if cuenta.estado == "precuenta":
        cuenta.estado = "abierta"
        actualizar_mesa(cuenta.comanda)


def agregar(
    cuenta: Cuenta,
    producto: Producto,
    mesero: Operador,
    cantidad=1,
    acompanamiento: Acompanamiento | None = None,
) -> LineaPedido:
    _cuenta_editable(cuenta)
    if not producto.disponible:
        raise ReglaNegocioError(
            f"«{producto.descripcion}» no está disponible."
        )  # RN-15
    if producto.con_acompanamiento and acompanamiento is None:
        raise ReglaNegocioError("Elige el acompañamiento.")
    if acompanamiento is not None and not acompanamiento.activo:
        raise ReglaNegocioError("Ese acompañamiento no está disponible.")
    if len(cuenta.lineas) >= MAX_LINEAS_POR_CUENTA:
        raise ReglaNegocioError("La cuenta tiene demasiadas líneas; abre otra cuenta.")
    precio = producto.precio + (
        acompanamiento.precio if acompanamiento else Decimal("0.00")
    )
    linea = LineaPedido(
        cuenta=cuenta,
        producto_id=producto.id,
        mesero_id=mesero.id,
        area_id=producto.area1_id,
        descripcion=producto.descripcion_corta,
        cantidad=validar_cantidad(cantidad),
        precio=precio,
        tasa_itbms=producto.tasa_itbms,
        aplica_jubilado=producto.aplica_jubilado,
        acompanamiento=acompanamiento.descripcion if acompanamiento else None,
    )
    db.session.add(linea)
    # H-13: lo pendiente de enviar en TODA la mesa más esta línea debe alcanzar.
    from . import inventario

    inventario.revisar_existencia(
        [
            ln
            for c in cuenta.comanda.cuentas
            for ln in c.lineas
            if ln is not linea and ln.estado == "PED"
        ]
        + [linea]  # aún sin guardar: su estado «PED» se asigna al insertarla
    )
    _reabrir_si_precuenta(cuenta)
    return linea


def _linea_pendiente(linea: LineaPedido) -> None:
    if linea.estado != "PED":
        raise ReglaNegocioError(
            "Esa línea ya se envió; para quitarla hay que anularla."
        )
    _cuenta_editable(linea.cuenta)


def cambiar_cantidad(linea: LineaPedido, delta: int) -> None:
    _linea_pendiente(linea)
    nueva = linea.cantidad + Decimal(delta)
    if nueva <= 0:
        db.session.delete(linea)
        return
    linea.cantidad = validar_cantidad(nueva)


def borrar(linea: LineaPedido) -> None:
    _linea_pendiente(linea)
    db.session.delete(linea)


def fijar_notas(linea: LineaPedido, ids_fijas, libre: str) -> None:
    _linea_pendiente(linea)
    textos = []
    for nota in NotaFija.query.filter(
        NotaFija.id.in_([int(i) for i in ids_fijas if str(i).isdigit()]),
        NotaFija.activa.is_(True),
    ).order_by(NotaFija.codigo):
        textos.append(nota.descripcion)
    libre = " ".join((libre or "").split())[:140]
    if libre:
        textos.append(libre)
    linea.notas = "; ".join(textos)[:200]


def alternar_llevar(linea: LineaPedido) -> None:
    _linea_pendiente(linea)
    linea.para_llevar = not linea.para_llevar


def descontar(linea: LineaPedido, pct, autorizador: Operador) -> None:
    """RN-07: el tope sin supervisor sale de la configuración."""
    _cuenta_editable(linea.cuenta)
    if linea.estado == "ANU":
        raise ReglaNegocioError("Esa línea está anulada.")
    try:
        pct = int(str(pct).strip())
    except ValueError:
        raise ReglaNegocioError(
            "El descuento debe ser un número entero de 0 a 100."
        ) from None
    if not 0 <= pct <= 100:
        raise ReglaNegocioError("El descuento debe estar entre 0 y 100 %.")
    tope = int(configuracion.obtener("descuento.tope_sin_supervisor") or 10)
    if pct > tope and not autorizador.puede("supervisor"):
        raise ReglaNegocioError(f"Un descuento mayor de {tope} % requiere supervisor.")
    linea.descuento_pct = pct
    auditar(
        "descuento",
        f"línea {linea.id} ({linea.descripcion}): {pct} %",
        autorizador=autorizador,
    )


def mover_linea(linea: LineaPedido, destino: Cuenta) -> None:
    """Separar cuenta: pasa una línea a otra cuenta de la misma comanda."""
    # Se comparan los objetos: una cuenta recién creada todavía no tiene comanda_id asignado.
    if linea.cuenta.comanda is not destino.comanda:
        raise ReglaNegocioError("Solo se mueve entre cuentas de la misma mesa.")
    _cuenta_editable(linea.cuenta)
    _cuenta_editable(destino)
    origen = linea.cuenta
    linea.cuenta = destino
    _reabrir_si_precuenta(origen)
    _reabrir_si_precuenta(destino)


def enviar(comanda: Comanda, operador: Operador | None = None) -> int:
    """Manda a cada área de producción las líneas en PED: pantalla de cocina, comanda impresa
    por área y salida de inventario (RN-14). Devuelve cuántas líneas envió."""
    from . import impresion, inventario

    if comanda.estado != "abierta":
        raise ReglaNegocioError("La comanda ya está cerrada.")
    momento = ahora()
    enviadas = []
    for cuenta in comanda.cuentas:
        for linea in cuenta.lineas:
            if linea.estado == "PED":
                linea.estado = "ORD"
                linea.enviado = True
                linea.enviado_en = momento
                enviadas.append(linea)
    if enviadas:
        inventario.revisar_existencia(
            enviadas
        )  # H-13: otra mesa pudo gastarlo mientras tanto
        db.session.flush()
        inventario.consumir(enviadas, operador or comanda.mesero)
        impresion.encolar_comandas(comanda, enviadas)
        auditar("pedido_enviado", f"comanda {comanda.numero}: {len(enviadas)} línea(s)")
    return len(enviadas)


def anular(
    linea: LineaPedido, solicitante: Operador, autorizador: Operador, motivo: str
) -> None:
    """RN-08."""
    if linea.estado == "ANU":
        raise ReglaNegocioError("Esa línea ya está anulada.")
    if linea.cuenta.estado == "pagada":
        raise ReglaNegocioError(
            "Esa línea ya se cobró: se corrige con una nota de crédito."
        )
    if linea.estado == "PED":
        raise ReglaNegocioError("Esa línea no se ha enviado: bórrala sin autorización.")
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 10:
        raise ReglaNegocioError(
            "Explica el motivo de la anulación (mínimo 10 caracteres)."
        )
    from . import impresion, inventario

    estado_previo = linea.estado
    linea.estado = "ANU"
    if estado_previo in (
        "ORD",
        "PRO",
    ):  # RN-14: todavía no se preparó → vuelve al inventario
        inventario.reversar(linea, autorizador)
    if (
        linea.area is not None
        and linea.area.impresora_obj is not None
        and estado_previo != "ENT"
    ):
        impresion.encolar(
            linea.area.impresora_obj,
            f"Anulación comanda {linea.cuenta.comanda.numero}",
            impresion.aviso_anulacion(
                linea, autorizador, motivo, linea.area.impresora_obj.columnas
            ),
        )
    db.session.add(
        Anulacion(
            linea=linea,
            solicitante_id=solicitante.id,
            autorizador_id=autorizador.id,
            motivo=motivo[:200],
        )
    )
    auditar(
        "anulacion",
        f"comanda {linea.cuenta.comanda.numero}, {linea.cantidad.normalize()} × "
        f"{linea.descripcion}: {motivo}",
        operador=solicitante,
        autorizador=autorizador,
    )
    actualizar_mesa(linea.cuenta.comanda)


def fijar_jubilado(cuenta: Cuenta, cedula: str, nombre: str) -> None:
    """RN-06: una persona por cuenta, con cédula o carné registrado."""
    _cuenta_editable(cuenta)
    cedula = "".join(ch for ch in (cedula or "") if ch.isalnum() or ch == "-")[:20]
    if not cedula:
        cuenta.jubilado_cedula = cuenta.jubilado_nombre = None
        auditar(
            "jubilado_quitado",
            f"cuenta {cuenta.numero} de la comanda {cuenta.comanda.numero}",
        )
        return
    if len(cedula) < 5:
        raise ReglaNegocioError("Escribe la cédula o el carné del jubilado.")
    cuenta.jubilado_cedula = cedula
    cuenta.jubilado_nombre = " ".join((nombre or "").split())[:80] or None
    auditar(
        "jubilado",
        f"cuenta {cuenta.numero} de la comanda {cuenta.comanda.numero}: {cedula}",
    )


def precuenta(cuenta: Cuenta) -> None:
    _cuenta_editable(cuenta)
    if not cuenta.activas:
        raise ReglaNegocioError("La cuenta no tiene consumo.")
    if any(ln.estado == "PED" for ln in cuenta.lineas):
        raise ReglaNegocioError(
            "Hay pedidos sin enviar: envíalos o bórralos primero."
        )  # RN-11
    cuenta.estado = "precuenta"
    actualizar_mesa(cuenta.comanda)
    auditar("precuenta", f"comanda {cuenta.comanda.numero}, cuenta {cuenta.numero}")


# --------------------------------------------------------------------------- totales
def lineas_calculo(cuenta: Cuenta) -> list:
    return [
        LineaCalculo.crear(
            ln.cantidad, ln.precio, ln.tasa_itbms, ln.descuento_pct, ln.aplica_jubilado
        )
        for ln in cuenta.activas
    ]


def totales(cuenta: Cuenta):
    pct = configuracion.porcentaje_jubilado() if cuenta.jubilado_cedula else 0
    return totalizar(lineas_calculo(cuenta), pct)


def total_comanda(comanda: Comanda) -> Decimal:
    return sum((totales(c).total for c in comanda.cuentas), Decimal("0.00"))


# --------------------------------------------------------------------------- cocina
def marcar_cocina(comanda: Comanda, area_id: int, accion: str) -> int:
    """P: en proceso · L: listo · E: entregado (para las líneas de esa área)."""
    transiciones = {
        "P": ({"ORD"}, "PRO"),
        "L": ({"ORD", "PRO"}, "PRE"),
        "E": ({"PRE"}, "ENT"),
    }
    if accion not in transiciones:
        raise ReglaNegocioError("Acción de cocina desconocida.")
    origen, destino = transiciones[accion]
    momento = ahora()
    n = 0
    for cuenta in comanda.cuentas:
        for ln in cuenta.lineas:
            if ln.area_id == area_id and ln.estado in origen:
                ln.estado = destino
                if destino == "PRE":
                    ln.listo_en = momento
                if destino == "ENT":
                    ln.entregado_en = momento
                n += 1
    return n


def entregar(linea: LineaPedido) -> None:
    if linea.estado != "PRE":
        raise ReglaNegocioError("Esa línea no está lista.")
    linea.estado = "ENT"
    linea.entregado_en = ahora()
