# ComandaPOS — Fase 1 (base)
**«Del pedido a la factura, sin perder una comanda.»**

Punto de venta para restaurantes de servicio a la mesa en Panamá: mesa → comanda → cocina → cobro →
factura electrónica (CAFE) → cierre de turno. Es un **monolito en Python/Flask** que en la fase 7 se
empaqueta como programa de escritorio para Windows (`ComandaPOS.exe` + instalador).

Programación: **Kevin Rellán** · Especificación completa: [`docs/PROMPT_ComandaPOS.md`](docs/PROMPT_ComandaPOS.md)

## Qué trae la fase 1
| Parte | Detalle |
|---|---|
| **Núcleo** | `create_app()`, carpeta de datos fuera del programa (`%PROGRAMDATA%\ComandaPOS` en Windows), SQLite en modo WAL, clave secreta por instalación. |
| **Modelo de datos** | Operadores, salas, mesas, secciones, productos, acompañamientos, notas fijas, áreas de producción, clientes, configuración, secuencias y auditoría. El dinero se guarda en **centavos enteros** (nunca float). |
| **Cálculos (RN-01 a RN-06)** | `app/services/calculos.py`: redondeo half-up, ITBMS por línea (0/7/10/15 %), totales = suma de líneas, descuentos antes del impuesto, descuento de jubilado (Ley 6 de 1987) sin combinarse con otro, validación de montos, vuelto. |
| **Secuencias (RN-04)** | Números de comanda y de factura atómicos: sin duplicados ni huecos aunque cobren varias terminales a la vez. |
| **Acceso** | Pantalla táctil con teclado en pantalla, PIN de 6 dígitos para meseros y cajeros, contraseña para el resto, bloqueo por intentos, bloqueo por inactividad según el rol. |
| **Roles** | Operador, cajero, supervisor, administrador y programador (los 5 niveles del sistema de referencia). Cada ruta declara su rol. |
| **Auditoría encadenada** | Cada registro queda sellado con HMAC y encadenado al anterior, más un ancla fuera de la base: editar, borrar o truncar la bitácora se detecta. |
| **Pantallas** | Control de acceso, control de ocupación de mesas por sala, consola del programador (estado, secuencias, verificación de la auditoría). |
| **Datos de prueba** | «Restaurante El Fogón (demo)»: 38 mesas en 3 salas, 70 productos panameños, acompañamientos, notas fijas y clientes ficticios. |
| **Pruebas** | 95 pruebas automáticas (`pytest`). |

## Requisitos
- **Python 3.11 a 3.13** (en Windows, desde python.org marcando «Add python.exe to PATH»).
- Dependencias en `requirements.txt` (sin vulnerabilidades conocidas según `pip-audit`).
- No necesita internet: todo lo de la interfaz viene incluido.

## Inicio rápido
**Windows:** doble clic en `iniciar.bat`. La primera vez crea el entorno e instala todo; luego abre
http://127.0.0.1:5000. **Mac/Linux:** `./iniciar.sh`.

Manual:
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```
Opciones: `--puerto 8080` · `--no-abrir` · `--dev` · `--nuevas-claves`. Reiniciar los datos de prueba: `python seed.py --reiniciar`.

## Cuentas de demostración
| Usuario | Nivel | Credencial |
|---|---|---|
| `ana`, `luis` | Operador (mesero) | PIN `246810` |
| `marta` | Cajero | PIN `246810` |
| `jose` | Supervisor | `comandapos123` |
| `admin` | Administrador | `comandapos123` |
| `dev` | Programador (Kevin Rellán) | `comandapos123` |

Estas credenciales **solo sirven en la demostración**. Con `COMANDAPOS_PRODUCCION=1` el sistema se niega a
arrancar mientras alguna cuenta las use; cámbialas con `python run.py --nuevas-claves`.

## Variables de entorno
| Variable | Para qué |
|---|---|
| `COMANDAPOS_PRODUCCION=1` | Apaga la demostración (exige credenciales propias). |
| `COMANDAPOS_DATA` | Carpeta de datos (base, clave secreta, ancla de auditoría, bitácoras). |
| `COMANDAPOS_DB` | Otra base (por ejemplo, PostgreSQL). |
| `COMANDAPOS_SECRET` | Clave secreta fija (si no, se genera una por instalación). |
| `COMANDAPOS_HTTPS=1` | Cookies `Secure` y HSTS (cuando haya TLS delante). |

## Pruebas
```bat
python -m pytest
```

## Estructura
```
app/
  __init__.py        factory, CSRF, cabeceras, inactividad, sellado de auditoría, errores
  config.py          nombre, versión, roles, tiempos de inactividad, carpeta de datos
  models.py          modelo de datos (Dinero y Cantidad en enteros)
  seguridad.py       @publica / @rol_requerido, limitadores, PIN y contraseñas, destino_seguro
  services/          calculos (RN-01..06), secuencias (RN-04), auditoria, configuracion
  auth/ mesas/ dev/  pantallas
  templates/ static/ interfaz táctil (sin JavaScript en línea)
tests/               95 pruebas
docs/                SEGURIDAD, SUPOSICIONES, PENDIENTES y el prompt maestro
```

## Próximas fases
2 Salón (comanda completa) · 3 Cocina e impresión · 4 Caja · 5 Facturación electrónica (PAC y CAFE en PDF) ·
6 Administración, inventario y reportes · 7 Escritorio (.exe e instalador) · 8 Revisión de seguridad independiente.
Detalle en `docs/PENDIENTES.md`.
