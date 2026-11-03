"""Seguridad transversal de ComandaPOS (OWASP Top 10), con las mismas convenciones de Manda2.

- RBAC: cada vista declara `@publica` o `@rol_requerido(...)` (A01). `desde("cajero")` devuelve
  ese rol y todos los superiores, porque los niveles del sistema son jerárquicos.
- Fuerza bruta: `Limitador` en memoria acotada (LRU), por usuario+terminal y por terminal (A07).
- PIN y contraseñas: política con listas de valores triviales o comunes (A07).
- Navegación: `destino_seguro` evita redirecciones abiertas (A01).
- Entrada JSON: `json_objeto` (A04).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from functools import wraps
from urllib.parse import urlparse

from flask import abort, request
from flask_login import current_user, login_required

from .config import ROLES

#: Credenciales de la demostración (se rechazan fuera del modo demostración, ver run.py).
PIN_DEMO = "246810"
CLAVE_DEMO = "comandapos123"
#: (usuario, nombre, rol) de las cuentas que crea seed.py; se muestran solo en la demostración.
CUENTAS_DEMO = (
    ("ana", "Ana Pinzón", "operador"),
    ("luis", "Luis Caballero", "operador"),
    ("marta", "Marta Quintero", "cajero"),
    ("jose", "José Samudio", "supervisor"),
    ("admin", "Administración El Fogón", "administrador"),
    ("dev", "Kevin Rellán", "programador"),
)


# --------------------------------------------------------------------------- RBAC
def desde(rol_minimo: str) -> tuple:
    """`desde("supervisor")` → ("supervisor", "administrador", "programador")."""
    return ROLES[ROLES.index(rol_minimo) :]


def rol_requerido(*roles):
    """Exige sesión y un rol de la lista (si no, 403 y evento de seguridad).

    Deja la marca `_roles` en la vista: una prueba recorre todas las rutas y exige que cada una
    sea pública a propósito (`@publica`) o tenga roles declarados (A01).
    """
    for rol in roles:
        if rol not in ROLES:
            raise ValueError(f"Rol desconocido: {rol}")

    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(*args, **kwargs):
            if current_user.rol not in roles:
                evento_seguridad(
                    "acceso_denegado",
                    f"{current_user.usuario} ({current_user.rol}) pidió {request.path[:120]}",
                )
                abort(403)
            return vista(*args, **kwargs)

        envoltura._roles = roles
        return envoltura

    return decorador


def con_sesion(vista):
    """Cualquier operador con sesión iniciada."""
    envuelta = login_required(vista)
    envuelta._roles = ROLES
    return envuelta


def publica(vista):
    """Marca explícita de ruta pública. Sin esta marca, la prueba de RBAC falla."""
    vista._publica = True
    return vista


def destino_seguro(siguiente, respaldo: str) -> str:
    """Solo rutas internas del mismo sitio (nada de `//otro.com`, `https://…` ni `\\`)."""
    if not siguiente:
        return respaldo
    p = urlparse(siguiente)
    if (
        p.scheme
        or p.netloc
        or not siguiente.startswith("/")
        or siguiente.startswith("//")
        or "\\" in siguiente
    ):
        return respaldo
    return siguiente


def json_objeto() -> dict:
    """Cuerpo JSON solo si es un objeto; «[1]» o basura → {} (A04: nunca un 500)."""
    datos = request.get_json(silent=True)
    return datos if isinstance(datos, dict) else {}


def ip_cliente() -> str:
    return (request.remote_addr or "")[:45]


_HASH_RELLENO: list = []


def hash_relleno() -> str:
    """Hash scrypt de relleno: si el usuario no existe se verifica contra este (mismo costo, A07)."""
    if not _HASH_RELLENO:
        from werkzeug.security import generate_password_hash

        _HASH_RELLENO.append(
            generate_password_hash("relleno-" + str(time.time()), method="scrypt")
        )
    return _HASH_RELLENO[0]


# --------------------------------------------------------------------------- eventos
_ULTIMO_EVENTO: dict = {}
_LOCK_EVENTO = threading.Lock()
EVENTOS: dict = {}


def evento_seguridad(tipo: str, detalle: str = "") -> None:
    """Cuenta el evento para el panel y lo audita como máximo una vez por minuto por terminal."""
    from .services.auditoria import auditar_ya

    clave = (tipo, ip_cliente())
    ahora = time.monotonic()
    with _LOCK_EVENTO:
        EVENTOS[tipo] = EVENTOS.get(tipo, 0) + 1
        if ahora - _ULTIMO_EVENTO.get(clave, -999.0) < 60:
            return
        _ULTIMO_EVENTO[clave] = ahora
        if len(_ULTIMO_EVENTO) > 5000:
            _ULTIMO_EVENTO.clear()
    auditar_ya(tipo, detalle)


# --------------------------------------------------------------------------- fuerza bruta
class Limitador:
    """Ventana deslizante en memoria, segura entre hilos y con memoria acotada (LRU)."""

    MAX_CLAVES = 20000

    def __init__(self, maximo: int, ventana_seg: int):
        self.maximo, self.ventana = maximo, ventana_seg
        self._hits: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def _limpiar(self, clave, ahora):
        q = self._hits.get(clave)
        if q is None:
            return deque()
        while q and ahora - q[0] > self.ventana:
            q.popleft()
        if not q:
            del self._hits[clave]
        return q

    def fallo(self, clave: str) -> None:
        with self._lock:
            ahora = time.monotonic()
            q = self._limpiar(clave, ahora)
            q.append(ahora)
            self._hits[clave] = q
            self._hits.move_to_end(clave)
            while len(self._hits) > self.MAX_CLAVES:
                self._hits.popitem(last=False)

    def espera(self, clave: str) -> int:
        with self._lock:
            ahora = time.monotonic()
            q = self._limpiar(clave, ahora)
            if len(q) < self.maximo:
                return 0
            return max(1, int(self.ventana - (ahora - q[0])))

    def limpiar(self, clave: str) -> None:
        with self._lock:
            self._hits.pop(clave, None)

    def reiniciar(self) -> None:
        with self._lock:
            self._hits.clear()


#: 5 intentos fallidos por usuario+terminal cada 10 minutos.
ACCESO = Limitador(5, 600)
#: 30 intentos por terminal cada 10 minutos, sin importar el usuario (se revisa ANTES del hash).
ACCESO_TERMINAL = Limitador(30, 600)
#: 5 autorizaciones de supervisor fallidas por terminal cada 10 minutos (fase 2: anulaciones).
AUTORIZACION = Limitador(5, 600)


# --------------------------------------------------------------------------- PIN y contraseñas
PINES_TRIVIALES = {
    "000000",
    "111111",
    "222222",
    "333333",
    "444444",
    "555555",
    "666666",
    "777777",
    "888888",
    "999999",
    "123456",
    "654321",
    "123123",
    "121212",
    "112233",
    "123321",
    "000001",
    "101010",
    "696969",
    "159753",
    "147258",
    "258369",
    "987654",
    "456789",
    "012345",
    "098765",
}

CLAVES_COMUNES = set("""
12345678 123456789 1234567890 87654321 11111111 00000000 password password1 password123 passw0rd
contraseña contrasena qwerty123 qwertyuiop abc12345 abcd1234 a1234567 1q2w3e4r 1qaz2wsx admin123
administrador admin1234 root1234 letmein1 welcome1 iloveyou1 panama123 panama2025 panama2026
chiriqui1 chiriqui123 david1234 restaurante1 restaurante123 comanda123 comandapos comandapos1
comandapos123 cajero123 mesero123 cocina123 supervisor1 clave1234 miclave123 hola1234
""".split())


def validar_pin(pin: str) -> list:
    """PIN de exactamente 6 dígitos, sin secuencias ni repeticiones triviales."""
    pin = pin or ""
    if len(pin) != 6 or not pin.isdigit():
        return ["El PIN debe tener exactamente 6 dígitos."]
    if pin in PINES_TRIVIALES or len(set(pin)) <= 2:
        return ["Ese PIN es demasiado fácil de adivinar."]
    pasos = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if len(pasos) == 1 and pasos.pop() in (-1, 1):
        return ["Ese PIN es una secuencia; elige otro."]
    return []


def validar_clave(clave: str, usuario: str = "", nombre: str = "") -> list:
    """Política de contraseñas (OWASP ASVS 2.1): 10 a 128 caracteres, no comunes ni derivadas."""
    errores = []
    clave = clave or ""
    if len(clave) < 10:
        errores.append("La contraseña debe tener al menos 10 caracteres.")
    if len(clave) > 128:
        errores.append("La contraseña no puede pasar de 128 caracteres.")
    if clave.lower() in CLAVES_COMUNES:
        errores.append("Esa contraseña es demasiado común.")
    if clave and not any(c.isdigit() for c in clave):
        errores.append("Incluye al menos un número.")
    if clave and not any(c.isalpha() for c in clave):
        errores.append("Incluye al menos una letra.")
    if usuario and len(usuario) > 3 and usuario.lower() in clave.lower():
        errores.append("La contraseña no debe contener tu usuario.")
    for parte in (nombre or "").lower().split():
        if len(parte) > 3 and parte in clave.lower():
            errores.append("La contraseña no debe contener tu nombre.")
            break
    return errores


def validar_credencial(operador, valor: str) -> list:
    """PIN para operadores y cajeros; contraseña para el resto."""
    if operador.usa_pin:
        return validar_pin(valor)
    return validar_clave(valor, operador.usuario, operador.nombre)
