# Seguridad de ComandaPOS — Fase 2

Cómo la base de ComandaPOS aplica el **OWASP Top 10 (2021)**. Cada fase agrega sus controles a esta tabla.

## 1. Actores
| Nivel | Acceso en la fase 1 | Credencial |
|---|---|---|
| Operador (mesero) | Mapa de mesas | PIN de 6 dígitos |
| Cajero | Mapa de mesas | PIN de 6 dígitos |
| Supervisor | Mapa de mesas | Contraseña |
| Administrador | Mapa de mesas | Contraseña |
| Programador | Todo + consola (`/dev`) y auditoría | Contraseña |

## 2. OWASP Top 10 (2021)
| Riesgo | Control | Dónde |
|---|---|---|
| A01 Control de acceso | Cada vista declara `@publica`, `@con_sesion` o `@rol_requerido(...)`; una prueba falla si alguna ruta queda sin marcar. La consola solo la ve el programador. **Por comanda:** un mesero solo ve y opera sus comandas, sus líneas, sus pre-cuentas y sus comprobantes (sin IDOR); cajero y superiores operan todas. Cobrar, Caja y Clientes exigen nivel cajero; anular, descuentos sobre el tope, otro mesero, notas fijas y mesas fuera de servicio exigen supervisor. Los accesos denegados se auditan. `destino_seguro()` impide redirecciones abiertas. | `app/seguridad.py`, `tests/test_web.py` |
| A02 Criptografía | PIN y contraseñas con **scrypt**. Clave secreta aleatoria por instalación (archivo 0600 en la carpeta de datos). La auditoría usa HMAC-SHA256 con una llave derivada de esa clave. Con HTTPS: cookie `__Host-` y `Secure`, y HSTS. | `app/models.py`, `app/__init__.py`, `app/services/auditoria.py` |
| A03 Inyección | Solo ORM con parámetros. Plantillas Jinja con escape automático. **CSP sin JavaScript en línea** (`script-src 'self'`). | `app/__init__.py`, `app/templates` |
| A04 Diseño inseguro | Dinero en centavos enteros y `Decimal`; montos no finitos, negativos, con más de 2 decimales o enormes se rechazan (RN-03). Tasas de ITBMS restringidas también en la base (`CHECK`). Secuencias atómicas (RN-04). **Idempotencia (RN-05):** agregar, enviar y cobrar llevan una clave única; un doble toque o un reintento no duplica pedidos, pagos ni comprobantes. Totales recalculados en el servidor en cada cobro; las formas que no son efectivo no pasan del total y el multipago cubre el total exacto (RN-09). Crédito solo con límite disponible (RN-10). Precio y tasa congelados en cada línea. `json_objeto()` para entradas JSON. | `app/services/calculos.py`, `app/models.py`, `app/services/secuencias.py` |
| A05 Configuración | CSP, `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, COOP/CORP, sin cabecera `Server`, `Cache-Control: no-store` en pantallas. Errores genéricos con referencia. **El servidor no arranca en producción si alguna cuenta usa credenciales de prueba.** Escucha solo en `127.0.0.1` hasta la fase 7. | `app/__init__.py`, `run.py` |
| A06 Componentes | Dependencias mínimas; `pip-audit` sin vulnerabilidades conocidas. Ninguna librería desde CDN. | `requirements.txt` |
| A07 Autenticación | Límite de 5 fallos por usuario+terminal y 30 por terminal cada 10 min, revisados **antes** del hash. Mismo mensaje y mismo costo exista o no el usuario. PIN de 6 dígitos sin secuencias ni repeticiones; contraseñas de 10+ caracteres sin valores comunes. Sesión nueva al entrar, cookie `SameSite=Strict`, versión de sesión (cambiar la clave cierra las sesiones abiertas), bloqueo por inactividad por rol (90 s en terminales de mesero) y duración máxima de 12 h. **Autorización de supervisor en el momento:** usuario y clave del supervisor en la misma pantalla, con el mismo costo exista o no, 5 fallos por terminal cada 10 min, y el autorizador queda registrado. | `app/auth/routes.py`, `app/seguridad.py`, `app/__init__.py` |
| A08 Integridad | CSRF en todo POST. **Auditoría encadenada con HMAC** + ancla externa: detecta registros editados, borrados del medio y truncados al final, incluso si alguien recalcula hashes sin la llave. Cada anulación, descuento, cobro, apertura y cierre de turno, cambio de mesa o de mesero queda en la cadena, con quien pidió y quien autorizó. | `app/services/auditoria.py`, `tests/test_integridad.py` |
| A09 Registro | Auditoría de accesos, fallos, bloqueos, accesos denegados, expiraciones, CSRF rechazados y cambios de credenciales. Sin caracteres de control (nadie falsifica líneas). Eventos agrupados (uno por minuto por terminal) para no inundar la bitácora. Bitácora técnica rotativa. | `app/seguridad.py`, `app/services/auditoria.py` |
| A10 SSRF | El servidor no descarga URLs de nadie. (La URL del PAC llegará en la fase 5 con lista permitida.) | — |

### Datos de pago
- De las tarjetas solo se guarda el **código de autorización** (4 a 12 caracteres). Si alguien escribe un número de más de 12 dígitos, el cobro se rechaza con «No escribas el número de la tarjeta».
- Los PDF se generan en memoria y se sirven con `no-store`: no quedan copias en disco ni en la caché del equipo.

## 3. Diseño de la auditoría
1. La operación y su registro de auditoría se confirman en **la misma transacción**: si la operación se revierte, el registro también.
2. Al terminar la petición, `sellar_pendientes()` asigna `sello` (1, 2, 3…), `hash_previo` y `hash = HMAC(campos + hash_previo)` bajo un candado.
3. Se escribe `auditoria.ancla` (último sello y hash, firmados) con reemplazo atómico.
4. `verificar()` recorre la cadena y la compara con el ancla. El resultado se ve en la consola del programador.

**Límite conocido:** quien tenga a la vez la base **y** la clave secreta de la instalación podría rehacer la cadena.
Por eso, en la fase 7 la clave secreta se protege con DPAPI de Windows y los respaldos guardan copias del ancla.

## 4. Antes de poner en producción (fase 1)
1. `python run.py --nuevas-claves` y anotar las credenciales nuevas.
2. `COMANDAPOS_PRODUCCION=1`.
3. Respaldar la carpeta de datos (`comandapos.db`, `secret_key`, `auditoria.ancla`).
4. Revisar la consola del programador: la auditoría debe decir «Cadena íntegra».
