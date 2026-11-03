# ComandaPOS — Fase 2 (salón, cocina y caja)
**«Del pedido a la factura, sin perder una comanda.»**

Punto de venta para restaurantes de servicio a la mesa en Panamá: mesa → comanda → cocina → cobro →
factura electrónica (CAFE) → cierre de turno. Es un **monolito en Python/Flask** que en la fase 7 se
empaqueta como programa de escritorio para Windows (`ComandaPOS.exe` + instalador).

Programación: **Kevin Rellán** · Especificación completa: [`docs/PROMPT_ComandaPOS.md`](docs/PROMPT_ComandaPOS.md)

## Qué funciona: el ciclo completo
**mesa → comanda → cocina → pre-cuenta → cobro → comprobante → liberar mesa → cierre de turno**

| Pantalla | Qué hace |
|---|---|
| **Mapa de mesas** | Las mesas se tocan. Cada mesa ocupada muestra el mesero, los minutos y el total. Panel «Pedidos listos» con botón «Entregado». Barra: Caja, Notas fijas, Clientes, Cocina y Pedidos directos (cobro rápido). |
| **Abrir mesa** | Se elige el número de personas (1 a 12). El supervisor puede poner una mesa fuera de servicio y habilitarla. |
| **Comanda** | Secciones del menú, productos con precio, acompañamiento obligatorio cuando aplica, cuentas separadas (1..n), cantidad +/−, notas fijas y libres, para llevar, borrar (solo lo no enviado), descuento %, anular con autorización de supervisor y motivo, pasar una línea a otra cuenta, «Enviar pedidos», jubilado %, pre-cuenta, mover mesa, otro mesero. Totales SB-TOT, DES-PRD, DES-JUB, ITBMS y TOTAL. |
| **Cocina (KDS)** | Una pantalla por área (Cocina, Frente): tarjetas por mesa con tiempo (verde → amarillo → rojo) y botones **P** (en proceso), **L** (listo, avisa al mesero) y **E** (entregado). Se actualiza sola. |
| **Pre-cuenta** | PDF de ticket de 80 mm con «PRE-CUENTA — NO ES FACTURA». |
| **Cobro** | Multipago (efectivo, Visa, Mastercard, Clave, Yappy y crédito), billetes rápidos, vuelto en vivo, cliente contribuyente o consumidor final con nombre, crédito con límite. |
| **Comprobante** | PDF de 80 mm con estructura de CAFE: emisor, receptor, detalle con ITBMS por línea, bases por tasa, formas de pago, vuelto, código y **QR**. Marcado «SIN VALIDEZ FISCAL» hasta la fase 5 (PAC). |
| **Caja** | Abrir turno con fondo, ventas por forma de pago, comprobantes del turno con reimpresión, corte Z con arqueo y justificación de diferencias. |
| **Notas fijas y clientes** | Listado y alta (las notas las crea un supervisor; el crédito lo asigna un supervisor). |

La demostración arranca con el **turno 1 abierto** (cajera Marta, fondo B/. 50) para poder cobrar de inmediato.

### Recorrido de prueba
1. Entra como `ana` (PIN `246810`), toca la mesa 12, elige 3 personas.
2. Toca productos (Bebidas, Almuerzo…). Al tasajo ponle una nota. Pulsa **Enviar pedidos**.
3. En otra ventana entra como `luis`, ve a **Cocina** y pulsa **L** (listo). A Ana le aparece en «Pedidos listos».
4. Ana pulsa **Pre-cuenta** e imprime el PDF.
5. Entra como `marta` (cajera), toca la mesa 12 → **Cobrar** → mezcla Visa y efectivo → **EXE**. Imprime el comprobante.
6. **Liberar mesa**. En **Caja** verás la venta y podrás cerrar el turno.

## Base (fase 1)
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
| **Pruebas** | 128 pruebas automáticas (`pytest`), incluido el ciclo completo de una mesa. |

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
  services/          calculos (RN-01..06), secuencias (RN-04), pedidos (salón), caja (cobro y turnos),
                     autorizacion, pdf (pre-cuenta y comprobante), auditoria, configuracion
  auth/ mesas/ salon/ cocina/ caja/ catalogos/ dev/   pantallas
  templates/ static/ interfaz táctil (sin JavaScript en línea)
tests/               128 pruebas
docs/                SEGURIDAD, SUPOSICIONES, PENDIENTES y el prompt maestro
```

## Próximas fases
3 Impresión térmica ESC/POS · 4 Corte X y reportes de caja · 5 Facturación electrónica real (PAC, CUFE, contingencia,
notas de crédito) · 6 Administración del menú, inventario y reportes · 7 Escritorio (.exe e instalador) ·
8 Revisión de seguridad independiente.
Detalle en `docs/PENDIENTES.md`.
