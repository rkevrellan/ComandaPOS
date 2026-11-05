# ComandaPOS 1.1
**«Del pedido a la factura, sin perder una comanda.»**

Punto de venta para restaurantes de servicio a la mesa en Panamá: **mesa → comanda → cocina → cobro →
factura electrónica (CAFE) → cierre de turno**. Monolito en Python/Flask que se instala en Windows como
programa de escritorio (`ComandaPOS.exe` + instalador) y atiende terminales y pantallas de cocina en la red local.

Programación: **Kevin Rellán** · Especificación: [`docs/PROMPT_ComandaPOS.md`](docs/PROMPT_ComandaPOS.md) ·
Manual de uso: [`docs/MANUAL.md`](docs/MANUAL.md) · Novedades de la 1.1: [`docs/CAMBIOS.md`](docs/CAMBIOS.md)
(corrige los 24 hallazgos del diagnóstico de la 1.0)

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
| **Seguridad** | 5 niveles de acceso, PIN/contraseñas con scrypt, **verificación en dos pasos** (obligatoria para administración fuera de la demo), auditoría encadenada con HMAC, CSRF, CSP estricta, **HTTPS en la red local** con certificado propio, lista de terminales permitidas, carpeta de datos solo para el grupo «ComandaPOS». Ver [`docs/SEGURIDAD.md`](docs/SEGURIDAD.md). |

## Instalar en Windows (usuario final)
1. Ejecuta `ComandaPOS-1.1.0-instalador.exe` (lo genera `build.bat`, ver abajo). El instalador pregunta
   **Producción** o **Demostración**.
2. Abre **ComandaPOS**. En producción, la primera vez pide crear el **primer administrador** (solo desde esa
   PC) y luego activar su verificación en dos pasos. Los datos viven en `C:\ProgramData\ComandaPOS`, que solo
   pueden abrir los Administradores y el grupo de Windows «ComandaPOS».
3. Sigue [`docs/PRIMEROS_PASOS.txt`](docs/PRIMEROS_PASOS.txt): emisor, PAC, impresoras, usuarios, respaldo.

| Acceso directo / comando | Qué hace |
|---|---|
| **ComandaPOS** | Ventana propia en este equipo (servidor solo local). |
| **ComandaPOS (servidor de red local)** | `--red`: servidor **HTTPS** para terminales y cocina en otras PC. |
| **Confiar en el certificado (este equipo)** | `--confiar`: instala la CA de ComandaPOS en este usuario de Windows. |
| `ComandaPOS.exe --servidor https://IP:5000` | Terminal de otra PC (antes, instalar `ca.crt` en ella). |
| `ComandaPOS.exe --cocina` | Pantalla de cocina. |
| **Empezar con una base nueva** | `--nueva-base`: aparta la base actual en un respaldo (no borra nada). |
| `ComandaPOS-servidor.exe --modo produccion` | Cambia el modo del equipo (o `demostracion`). |
| **Cambiar credenciales de prueba** | `--nuevas-claves`. |
| `ComandaPOS-servidor.exe --verificar` | Comprueba que el paquete trae todas sus dependencias. |

## Construir el .exe y el instalador (en tu PC con Windows)
Requisitos: **Python 3.12+** (python.org, «Add python.exe to PATH») e **Inno Setup 6** (jrsoftware.org).
```bat
build.bat
```
Hace todo y se detiene si algo falla: entorno limpio → dependencias → **pruebas** → **pip-audit** →
**bandit** → PyInstaller (`dist\ComandaPOS\ComandaPOS.exe`) → `--verificar` → Inno Setup (`dist\ComandaPOS-1.1.0-instalador.exe`)
→ `dist\SHA256SUMS.txt`. Sin Inno Setup queda la versión portable en `dist\ComandaPOS\`.
Recomendado antes de distribuir: firmar los `.exe` con un certificado de firma de código (`signtool`).

## Desarrollo (sin instalar)
**Windows:** doble clic en `iniciar.bat` → http://127.0.0.1:5000. **Mac/Linux:** `./iniciar.sh`. En VS Code: **F5**.
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py                 &rem solo este equipo
python run.py --red           &rem red local con HTTPS (configura «Terminales permitidas»)
python escritorio.py          &rem como el .exe (ventana propia si está pywebview)
python -m pytest              &rem 224 pruebas
```
Opciones de `run.py`: `--puerto 8080` · `--no-abrir` · `--dev` (solo 127.0.0.1) · `--red` · `--sin-tls` · `--confiar` · `--modo` · `--nueva-base` · `--nuevas-claves` · `--verificar`.
Reiniciar los datos de prueba: `python seed.py --reiniciar`.

## Cuentas de demostración
| Usuario | Nivel | Credencial |
|---|---|---|
| `ana`, `luis` | Operador (mesero) | PIN `246810` |
| `marta` | Cajero | PIN `246810` |
| `jose` | Supervisor | `comandapos123` |
| `admin` | Administrador | `comandapos123` |
| `dev` | Programador (Kevin Rellán) | `comandapos123` |

Solo existen en la demostración y solo se muestran en la PC donde corre el servidor (nunca a las terminales de
la red). La demostración usa un PAC **simulado**: sus documentos dicen «SIN VALIDEZ FISCAL». Una base de
demostración no arranca en producción.

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
| `COMANDAPOS_PRODUCCION` | `1` producción · `0` demostración. Si no existe, manda `modo.txt` de la carpeta de datos (lo escribe el instalador). |
| `COMANDAPOS_DATA` | Carpeta de datos (base, clave secreta, ancla de auditoría, PDF, impresiones). |
| `COMANDAPOS_DB` | Otra base (por ejemplo, PostgreSQL). |
| `COMANDAPOS_SECRET` | Clave secreta fija (si no, se genera una por instalación). |
| `COMANDAPOS_PAC_TOKEN` | Credencial del PAC (si no, la que se guarda desde Configuración, cifrada para el equipo). |
| `COMANDAPOS_HTTPS=1` | Cookies `Secure` y HSTS (automático con `--red`; manual si hay un proxy con TLS delante). |

## Estructura
```
app/
  __init__.py        factory, CSRF, cabeceras, inactividad, 2FA obligatoria, terminales permitidas
  config.py          nombre, versión, roles, tiempos de inactividad, carpeta de datos
  models.py          modelo de datos (dinero en centavos enteros)   migracion.py  columnas nuevas
  seguridad.py       @publica / @rol_requerido, limitadores, PIN y contraseñas
  services/          calculos (RN-01..06) · secuencias · pedidos · caja · fiscal (PAC) · impresion (ESC/POS)
                     inventario · reportes · dos_pasos (TOTP) · tls (HTTPS) · secretos · pdf · auditoria · configuracion
  auth/ mesas/ salon/ cocina/ caja/ catalogos/ admin/ reportes/ cuenta/ dev/     pantallas
  templates/ static/ interfaz táctil (sin JavaScript en línea)
escritorio.py        ComandaPOS.exe: ventana propia, una sola instancia, modo terminal y cocina
run.py               ComandaPOS-servidor.exe: servidor local o de red, cambio de credenciales
comandapos.spec      PyInstaller        instalador/  Inno Setup, icono, versión de Windows
build.bat            construcción completa con pruebas y análisis de seguridad
tests/               224 pruebas automáticas
docs/                MANUAL, FISCAL, SEGURIDAD, CAMBIOS, SUPOSICIONES, PENDIENTES, PRIMEROS_PASOS, capturas y PDF
```
