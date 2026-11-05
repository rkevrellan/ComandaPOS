# Seguridad de ComandaPOS 1.1

Cómo ComandaPOS aplica el **OWASP Top 10 (2021)** y qué queda en manos de quien lo instala.
La 1.1 corrige los 24 hallazgos del diagnóstico de la 1.0 (detalle en [`CAMBIOS.md`](CAMBIOS.md)).

## 1. Actores y permisos
| Nivel | Puede | Credencial |
|---|---|---|
| Operador (mesero) | Sus mesas y comandas, pre-cuenta, cocina | PIN de 6 dígitos |
| Cajero | + cobrar, caja (corte X/Z, abonos, gaveta), clientes, corregir rechazados, notas de crédito (con supervisor) | PIN de 6 dígitos |
| Supervisor | + autorizar anulaciones, descuentos sobre el tope, notas de crédito y cierres con pendientes; notas fijas; **reportes** | Contraseña |
| Administrador | + **administración** (catálogos, operadores, configuración, inventario, impresiones), cédula completa en el CSV de jubilados | Contraseña + **2FA** |
| Programador | + consola técnica y verificación de la auditoría | Contraseña + **2FA** |

Un administrador no crea ni edita programadores, no puede bajarse de nivel a sí mismo y no puede dejar el
sistema sin administradores activos. Cambiar el nivel o la credencial de alguien **cierra sus sesiones**.
El **primer administrador** de una instalación nueva solo se crea desde el propio equipo (127.0.0.1).

## 2. OWASP Top 10 (2021)
| Riesgo | Control | Dónde |
|---|---|---|
| A01 Control de acceso | Cada vista declara `@publica`, `@con_sesion` o `@rol_requerido(...)`; una prueba falla si alguna ruta queda sin marcar. Por comanda: un mesero solo ve y opera lo suyo (sin IDOR). Autorización de supervisor en el momento para anulaciones, descuentos, notas de crédito y cierres con pendientes. **Red local:** solo este equipo y las IP/redes de «Terminales permitidas». **Primer inicio** solo desde 127.0.0.1. | `seguridad.py`, `__init__.py`, `auth/routes.py` |
| A02 Criptografía | scrypt para PIN y contraseñas. Clave secreta aleatoria por instalación. Auditoría con HMAC-SHA256. Secreto TOTP de 160 bits. **HTTPS en la red local** (CA propia, ECDSA P-256, TLS 1.2+), cookies `__Host-`, `Secure` y HSTS. **Credencial del PAC** cifrada con DPAPI de máquina en la carpeta de datos (nunca en la base). Solo `https://` hacia el PAC. | `services/tls.py`, `services/secretos.py`, `services/fiscal.py` |
| A03 Inyección | Solo ORM con parámetros. Jinja con escape automático; `Markup.format` escapa. **CSP sin JavaScript ni estilos en línea**. ESC/POS: texto de personas sin bytes de control. CSV: celdas `= + - @` neutralizadas. | `__init__.py`, `impresion.py`, `reportes.py` |
| A04 Diseño inseguro | Dinero en centavos y `Decimal`. Secuencias sin huecos. Idempotencia. Totales en el servidor. La llamada al PAC va **fuera** de la transacción. Rechazados se corrigen y reenvían (auditado). Folios agotados → contingencia. Corte Z con pendientes → supervisor. El inventario no queda negativo. Producción nunca usa una base de demostración ni factura sin datos del emisor. | `services/*`, `run.py` |
| A05 Configuración | Cabeceras de seguridad, errores genéricos con referencia, sin versión en `/salud`. El modo (producción/demostración) se elige al instalar. Producción no arranca con credenciales de prueba ni con una base de demostración. `--dev` solo en 127.0.0.1. El PAC simulado no existe fuera de la demo. | `__init__.py`, `run.py`, `comandapos.iss` |
| A06 Componentes | Dependencias mínimas, nada desde CDN. `build.bat` corre **pip-audit** y **bandit**, y `--verificar` comprueba el paquete. | `requirements.txt`, `build.bat` |
| A07 Autenticación | Limitadores **atómicos y persistentes** (sobreviven a un reinicio) por usuario+terminal y por terminal de red; en el propio equipo un empleado no bloquea a los demás y un administrador puede desbloquear. Mismo mensaje y costo exista o no el usuario. PIN sin secuencias; contraseñas de 10+ caracteres. Sesión nueva al entrar, `SameSite=Strict`, versión de sesión, inactividad por rol. **2FA (TOTP)** obligatoria para administración, anti-repetición, códigos de recuperación de un uso; activarla, renovar códigos o quitarla **exige la contraseña actual** y tiene límite de intentos. | `seguridad.py`, `auth/`, `cuenta/` |
| A08 Integridad | CSRF en todo POST. Auditoría encadenada con HMAC + ancla externa. Quedan en la cadena: precios y catálogos, configuración, operadores, 2FA, cobros, correcciones de comprobantes, notas de crédito, anulaciones, gaveta, cortes (con pendientes y quién autorizó), exportaciones (y si llevan cédula completa), desbloqueos. `build.bat` publica huellas SHA-256. | `services/auditoria.py` |
| A09 Registro | Accesos, fallos, bloqueos, denegaciones, CSRF rechazados, terminales rechazadas, intentos de primer inicio desde la red. Sin caracteres de control. El `.exe` sin consola escribe en `escritorio.log`. | `seguridad.py` |
| A10 SSRF | El servidor solo se conecta a: la URL del PAC (`https://`, **sin seguir redirecciones**) y las impresoras de red (IP privada de otro equipo, puertos 9100–9109). El modo terminal solo acepta `http(s)://host:puerto`. | `fiscal.py`, `impresion.py`, `escritorio.py` |

### Datos personales y de pago
- De las tarjetas solo se guarda el **código de autorización**; un número largo se rechaza.
- Cédulas de jubilados **enmascaradas** (`8-***-4567`) en pantalla y CSV; la completa solo para administración y auditada.
- Los PDF se generan en memoria y se sirven con `no-store`.

## 3. Diseño de la auditoría
1. La operación y su registro se confirman en **la misma transacción**.
2. Al terminar la petición, `sellar_pendientes()` asigna `sello`, `hash_previo` y `hash = HMAC(campos + hash_previo)`.
3. Se escribe `auditoria.ancla` (último sello y hash, firmados) con reemplazo atómico.
4. `verificar()` recorre la cadena y la compara con el ancla (consola del programador).

**Límite conocido:** quien tenga a la vez la base **y** la clave secreta podría rehacer la cadena. Por eso la
carpeta de datos queda solo para Administradores, SYSTEM y el grupo «ComandaPOS» (1.1), y conviene respaldar el
ancla aparte (USB o nube).

## 4. Análisis automático (1.1.0)
| Herramienta | Resultado |
|---|---|
| `pytest` | 224 pruebas, todas pasan (incluye una o más por cada hallazgo del diagnóstico). |
| `pip-audit -r requirements.txt` | Sin vulnerabilidades conocidas. |
| `bandit -ll` (media y alta) | Sin hallazgos. Excepciones justificadas en línea: `0.0.0.0` con `--red`, `urlopen` a URL validadas, `debug=True` solo con `--dev` en 127.0.0.1, `certutil` con ruta y argumentos fijos. |
| HTTPS en modo red | Probado con `curl`: válido con la CA, rechazado sin ella, TLS 1.1 rechazado, cookie `__Host-…; Secure`. |
| Recorrido en navegador (Playwright) | Todas las pantallas sin errores de consola, sin violaciones de CSP ni errores 500. |

## 5. Responsabilidad de quien instala
1. Elegir **Producción** en el instalador y crear el primer administrador en la PC de caja; activar su 2FA.
2. Agregar al grupo de Windows «ComandaPOS» solo las cuentas que usan el sistema; cuentas separadas y sin
   privilegios para el personal, y cifrado de disco (BitLocker).
3. Red: la PC de caja y las terminales en la **red del local**, nunca en la Wi-Fi de clientes; IP fija para la
   PC de caja; «Terminales permitidas» con las IP exactas o la red (`192.168.1.0/24`); instalar `ca.crt` en cada
   terminal comprobando la huella.
4. Respaldo diario de la carpeta de datos (`comandapos.db`, `secret_key`, `auditoria.ancla`, `tls/`) fuera del equipo.
5. Firmar los `.exe` con un certificado de firma de código antes de distribuirlos.
6. Una revisión de seguridad independiente antes de venderlo a terceros.
