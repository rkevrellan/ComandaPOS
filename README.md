# ComandaPOS 1.0
**«Del pedido a la factura, sin perder una comanda.»**

Punto de venta para restaurantes de servicio a la mesa en Panamá: **mesa → comanda → cocina → cobro →
factura electrónica (CAFE) → cierre de turno**. Monolito en Python/Flask que se instala en Windows como
programa de escritorio (`ComandaPOS.exe` + instalador) y atiende terminales y pantallas de cocina en la red local.

Programación: **Kevin Rellán** · Especificación: [`docs/PROMPT_ComandaPOS.md`](docs/PROMPT_ComandaPOS.md) ·
Manual de uso: [`docs/MANUAL.md`](docs/MANUAL.md)

## Qué hace
| Área | Funciones |
|---|---|
| **Salón** | Mapa de mesas por sala (mesero, minutos, total), abrir mesa por número de personas, comanda táctil por secciones, acompañamientos obligatorios, notas fijas y libres, cuentas separadas, mover líneas entre cuentas, descuentos (sobre el tope pide supervisor), jubilado (Ley 6 de 1987) con cédula, anulación con autorización y motivo, mover mesa, cambiar mesero, pre-cuenta PDF, pedidos directos. |
| **Cocina** | Pantalla por área (KDS) con semáforo de tiempo y botones P/L/E; avisos «Pedido listo» al mesero; **comandas impresas por área** (ESC/POS 80 mm) y avisos de anulación impresos. |
| **Cobro** | Multipago (efectivo, Visa, Mastercard, Clave, Yappy, crédito), billetes rápidos, vuelto, contribuyente o consumidor final, crédito con límite, apertura de gaveta. |
| **Factura electrónica** | Comprobante (tipo 01) y **nota de crédito** (tipo 04) enviados al **PAC**; CUFE, protocolo y QR que devuelve el PAC; **contingencia** si el PAC o internet fallan (la venta no se detiene) y reenvío; control de **folios** con alerta; PDF ticket 80 mm y **carta**. Nunca se inventa un CUFE. Detalle en [`docs/FISCAL.md`](docs/FISCAL.md). |
| **Caja** | Turnos con fondo, **corte X** (PDF, sin cerrar), **corte Z** con arqueo y justificación, abonos a crédito con recibo, **gaveta sin venta con motivo**, comprobantes del turno con reimpresión, cola de impresión y reenvío fiscal. |
| **Administración** | Catálogos (productos, secciones con color, acompañamientos, áreas, salas, mesas, clientes, impresoras, insumos, notas fijas), operadores y niveles, configuración (emisor, descuentos, cocina, PAC, impresión, red), **inventario por receta** con entradas y ajustes (agota productos en cero), cola de impresiones con vista previa y página de prueba. |
| **Reportes** | Ventas, comprobantes, ticket promedio, notas de crédito, neto, ITBMS por tasa (para la declaración), mapa de calor día/hora, formas de pago, meseros, secciones, productos, tiempos de cocina, jubilados y anulaciones. Todo exportable a **CSV** (Excel en español). |
| **Seguridad** | 5 niveles de acceso, PIN/contraseñas con scrypt, **verificación en dos pasos** (obligatoria para administración fuera de la demo), auditoría encadenada con HMAC, CSRF, CSP estricta, lista de terminales permitidas en la red. Ver [`docs/SEGURIDAD.md`](docs/SEGURIDAD.md). |

## Instalar en Windows (usuario final)
1. Ejecuta `ComandaPOS-1.0.0-instalador.exe` (lo genera `build.bat`, ver abajo).
2. Abre **ComandaPOS** desde el escritorio. Los datos viven en `C:\ProgramData\ComandaPOS`.
3. Antes de vender de verdad sigue [`docs/PRIMEROS_PASOS.txt`](docs/PRIMEROS_PASOS.txt) (credenciales nuevas,
   modo producción, datos del emisor, PAC, impresoras, respaldo).

| Acceso directo | Qué abre |
|---|---|
| **ComandaPOS** | Ventana propia en este equipo (servidor solo local). |
| **ComandaPOS (servidor de red local)** | Servidor para terminales y cocina en otras PC (`--red`). |
| `ComandaPOS.exe --servidor http://IP:5000` | Terminal de otra PC (solo la ventana). |
| `ComandaPOS.exe --cocina` | Pantalla de cocina. |
| **Cambiar credenciales de prueba** | `--nuevas-claves`: reemplaza los PIN y contraseñas de la demostración. |

## Construir el .exe y el instalador (en tu PC con Windows)
Requisitos: **Python 3.12+** (python.org, «Add python.exe to PATH») e **Inno Setup 6** (jrsoftware.org).
```bat
build.bat
```
Hace todo y se detiene si algo falla: entorno limpio → dependencias → **pruebas** → **pip-audit** →
**bandit** → PyInstaller (`dist\ComandaPOS\ComandaPOS.exe`) → Inno Setup (`dist\ComandaPOS-1.0.0-instalador.exe`)
→ `dist\SHA256SUMS.txt`. Sin Inno Setup queda la versión portable en `dist\ComandaPOS\`.
Recomendado antes de distribuir: firmar los `.exe` con un certificado de firma de código (`signtool`).

## Desarrollo (sin instalar)
**Windows:** doble clic en `iniciar.bat` → http://127.0.0.1:5000. **Mac/Linux:** `./iniciar.sh`. En VS Code: **F5**.
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py                 &rem solo este equipo
python run.py --red           &rem red local (configura «Terminales permitidas»)
python escritorio.py          &rem como el .exe (ventana propia si está pywebview)
python -m pytest              &rem 187 pruebas
```
Opciones de `run.py`: `--puerto 8080` · `--no-abrir` · `--dev` (solo 127.0.0.1) · `--red` · `--nuevas-claves`.
Reiniciar los datos de prueba: `python seed.py --reiniciar`.

## Cuentas de demostración
| Usuario | Nivel | Credencial |
|---|---|---|
| `ana`, `luis` | Operador (mesero) | PIN `246810` |
| `marta` | Cajero | PIN `246810` |
| `jose` | Supervisor | `comandapos123` |
| `admin` | Administrador | `comandapos123` |
| `dev` | Programador (Kevin Rellán) | `comandapos123` |

Solo sirven en la demostración: con `COMANDAPOS_PRODUCCION=1` el sistema **no arranca** mientras alguna
cuenta las use. La demostración usa un PAC **simulado**: sus documentos dicen «SIN VALIDEZ FISCAL».

### Recorrido de prueba (5 minutos)
1. `ana` → mesa 12 → 3 personas → productos (al tasajo, una nota) → **Enviar pedidos**.
2. `luis` → **Cocina** → **L**. A Ana le aparece en «Pedidos listos». La comanda impresa queda en
   **Administración → Impresiones** (en la demo se «imprime» a archivo, con vista previa).
3. `marta` → mesa 12 → **Cobrar** → Visa + efectivo → **EXE** → ticket o **PDF carta** con CUFE y QR.
4. `marta` → **Nota de crédito** de un producto (pide supervisor: `jose`).
5. `marta` → **Caja** → **Corte X** → **Cerrar turno** (corte Z).
6. `jose` → **Reportes** → exporta «Productos» a CSV. `admin` → **Administración** → cambia un precio
   (queda en la auditoría). `dev` → **Consola** → «Cadena íntegra».

## Variables de entorno
| Variable | Para qué |
|---|---|
| `COMANDAPOS_PRODUCCION=1` | Apaga la demostración: exige credenciales propias, 2FA para administración y un PAC real o contingencia. |
| `COMANDAPOS_DATA` | Carpeta de datos (base, clave secreta, ancla de auditoría, PDF, impresiones). |
| `COMANDAPOS_DB` | Otra base (por ejemplo, PostgreSQL). |
| `COMANDAPOS_SECRET` | Clave secreta fija (si no, se genera una por instalación). |
| `COMANDAPOS_PAC_TOKEN` | Credencial del PAC si el equipo no tiene almacén seguro (en Windows va al Administrador de credenciales). |
| `COMANDAPOS_HTTPS=1` | Cookies `Secure` y HSTS (cuando haya TLS delante). |

## Estructura
```
app/
  __init__.py        factory, CSRF, cabeceras, inactividad, 2FA obligatoria, terminales permitidas
  config.py          nombre, versión, roles, tiempos de inactividad, carpeta de datos
  models.py          modelo de datos (dinero en centavos enteros)   migracion.py  columnas nuevas
  seguridad.py       @publica / @rol_requerido, limitadores, PIN y contraseñas
  services/          calculos (RN-01..06) · secuencias · pedidos · caja · fiscal (PAC) · impresion (ESC/POS)
                     inventario · reportes · dos_pasos (TOTP) · pdf · auditoria · autorizacion · configuracion
  auth/ mesas/ salon/ cocina/ caja/ catalogos/ admin/ reportes/ cuenta/ dev/     pantallas
  templates/ static/ interfaz táctil (sin JavaScript en línea)
escritorio.py        ComandaPOS.exe: ventana propia, una sola instancia, modo terminal y cocina
run.py               ComandaPOS-servidor.exe: servidor local o de red, cambio de credenciales
comandapos.spec      PyInstaller        instalador/  Inno Setup, icono, versión de Windows
build.bat            construcción completa con pruebas y análisis de seguridad
tests/               187 pruebas automáticas
docs/                MANUAL, FISCAL, SEGURIDAD, SUPOSICIONES, PENDIENTES, PRIMEROS_PASOS, capturas y PDF de ejemplo
```
