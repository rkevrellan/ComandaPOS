# Seguridad de ComandaPOS 1.0

Cómo ComandaPOS aplica el **OWASP Top 10 (2021)** y qué queda en manos de quien lo instala.

## 1. Actores y permisos
| Nivel | Puede | Credencial |
|---|---|---|
| Operador (mesero) | Sus mesas y comandas, pre-cuenta, cocina | PIN de 6 dígitos |
| Cajero | + cobrar, caja (corte X/Z, abonos, gaveta), clientes, notas de crédito (con supervisor) | PIN de 6 dígitos |
| Supervisor | + autorizar anulaciones y descuentos, notas fijas, mesas fuera de servicio, **reportes** | Contraseña |
| Administrador | + **administración** (catálogos, operadores, configuración, inventario, impresiones) | Contraseña + **2FA** |
| Programador | + consola técnica y verificación de la auditoría | Contraseña + **2FA** |

Un administrador no crea ni edita programadores, no puede bajarse de nivel a sí mismo y no puede dejar el
sistema sin administradores activos. Cambiar el nivel o la credencial de alguien **cierra sus sesiones**.

## 2. OWASP Top 10 (2021)
| Riesgo | Control | Dónde |
|---|---|---|
| A01 Control de acceso | Cada vista declara `@publica`, `@con_sesion` o `@rol_requerido(...)`; una prueba falla si alguna ruta queda sin marcar. Por comanda: un mesero solo ve y opera lo suyo (sin IDOR). Autorización de supervisor en el momento para anulaciones, descuentos sobre el tope y notas de crédito. Accesos denegados auditados. `destino_seguro()` impide redirecciones abiertas. **Red local:** solo entran este equipo y las IP/redes de «Terminales permitidas» (se verifica en cada petición, antes que todo). | `app/seguridad.py`, `app/__init__.py`, `tests/test_web.py`, `tests/test_final_admin.py` |
| A02 Criptografía | PIN y contraseñas con **scrypt**. Clave secreta aleatoria por instalación. Auditoría con HMAC-SHA256. Secreto TOTP de 160 bits. **La credencial del PAC nunca va a la base**: Administrador de credenciales de Windows (DPAPI, vía `keyring`) o variable de entorno. Solo `https://` hacia el PAC. Con HTTPS: cookie `__Host-`, `Secure` y HSTS. | `app/models.py`, `app/services/fiscal.py`, `app/services/dos_pasos.py` |
| A03 Inyección | Solo ORM con parámetros (la consola cuenta filas con `select(func.count())`, sin concatenar). Jinja con escape automático; los campos ocultos usan `Markup.format` (escapa). **CSP sin JavaScript ni estilos en línea**. **ESC/POS:** todo texto de personas se limpia de bytes de control antes de mezclarse con comandos de impresora (un nombre no corta papel ni abre la gaveta). **CSV:** celdas que empiezan con `= + - @` se neutralizan (inyección de fórmulas en Excel). | `app/__init__.py`, `app/services/impresion.py`, `app/services/reportes.py` |
| A04 Diseño inseguro | Dinero en centavos enteros y `Decimal`; montos inválidos se rechazan (RN-03). Secuencias atómicas sin huecos (RN-04). **Idempotencia** en agregar, enviar y cobrar (RN-05). Totales recalculados en el servidor. Crédito con límite (RN-10). La llamada al PAC ocurre **fuera** de la transacción de la venta. Nota de crédito solo sobre comprobantes autorizados y nunca por más de lo vendido. Inventario por receta en la misma transacción que el envío o la anulación. | `app/services/*` |
| A05 Configuración | CSP, `frame-ancestors 'none'`, `nosniff`, `no-referrer`, `Permissions-Policy`, COOP/CORP, sin cabecera `Server`, `no-store`. Errores genéricos con referencia. **Producción no arranca con credenciales de prueba.** Escucha en `127.0.0.1` salvo `--red`. El depurador de Flask (`--dev`) solo en `127.0.0.1`. El PAC simulado no se puede elegir fuera de la demo. | `app/__init__.py`, `run.py` |
| A06 Componentes | Dependencias mínimas, nada desde CDN. `build.bat` corre **pip-audit** y se detiene si hay vulnerabilidades conocidas. | `requirements.txt`, `build.bat` |
| A07 Autenticación | Límite de fallos por usuario+terminal y por terminal, revisado **antes** del hash; mismo mensaje y costo exista o no el usuario. PIN sin secuencias ni repeticiones; contraseñas de 10+ caracteres sin valores comunes. Sesión nueva al entrar, `SameSite=Strict`, versión de sesión, inactividad por rol, duración máxima. **2FA (TOTP, RFC 6238)**: obligatoria para administrador y programador fuera de la demo, ventana de ±30 s, **anti-repetición** (un código no sirve dos veces), 8 códigos de recuperación de un solo uso guardados con hash, intentos limitados; el administrador no puede quitársela. Cambiar la propia contraseña exige la actual. | `app/auth/routes.py`, `app/cuenta/routes.py`, `app/services/dos_pasos.py` |
| A08 Integridad | CSRF en todo POST. **Auditoría encadenada con HMAC + ancla externa** (detecta ediciones, borrados y truncados). Quedan en la cadena: precios y catálogos (antes → después), configuración, operadores, 2FA, cobros, notas de crédito, anulaciones, gaveta sin venta, cortes, exportaciones, autorizaciones fiscales y contingencias. `build.bat` publica huellas **SHA-256** de los ejecutables. | `app/services/auditoria.py`, `build.bat` |
| A09 Registro | Accesos, fallos, bloqueos, denegaciones, CSRF rechazados, terminales rechazadas, cambios de credenciales y 2FA. Sin caracteres de control. Eventos agrupados para no inundar. El `.exe` sin consola escribe en `escritorio.log`. | `app/seguridad.py` |
| A10 SSRF | El servidor solo se conecta a: la URL del PAC que configura el administrador (validada: `https://`, sin credenciales en la URL) y las impresoras de red configuradas (IP privada y puerto). El modo terminal solo acepta `http(s)://host:puerto`. | `app/services/fiscal.py`, `app/services/impresion.py`, `escritorio.py` |

### Datos de pago
- De las tarjetas solo se guarda el **código de autorización** (4 a 12 caracteres). Un número de más de 12 dígitos
  se rechaza con «No escribas el número de la tarjeta».
- Los PDF se generan en memoria y se sirven con `no-store`.

## 3. Diseño de la auditoría
1. La operación y su registro se confirman en **la misma transacción**.
2. Al terminar la petición, `sellar_pendientes()` asigna `sello`, `hash_previo` y `hash = HMAC(campos + hash_previo)`.
3. Se escribe `auditoria.ancla` (último sello y hash, firmados) con reemplazo atómico.
4. `verificar()` recorre la cadena y la compara con el ancla (consola del programador).

**Límite conocido:** quien tenga a la vez la base **y** la clave secreta podría rehacer la cadena. Por eso conviene
respaldar el ancla aparte (USB o nube) y restringir quién entra a Windows en la PC de caja.

## 4. Análisis automático
| Herramienta | Resultado en 1.0.0 |
|---|---|
| `pytest` | 187 pruebas, todas pasan (incluye permisos por nivel, 2FA, CSV, terminales, ESC/POS, idempotencia, auditoría). |
| `pip-audit -r requirements.txt` | Sin vulnerabilidades conocidas. |
| `bandit -ll` (media y alta) | Sin hallazgos. Excepciones justificadas en línea: escuchar en `0.0.0.0` con `--red` (filtrado por la lista de terminales) y `urlopen` hacia URL ya validadas. |
| Recorrido en navegador (Playwright) | Todas las pantallas sin errores de consola, sin violaciones de CSP y sin errores 500. |

## 5. Responsabilidad de quien instala
1. `ComandaPOS-servidor.exe --nuevas-claves` y anotar las credenciales nuevas.
2. `COMANDAPOS_PRODUCCION=1` (variable de entorno del sistema) y activar la 2FA de cada administrador.
3. Red: la PC de caja y las terminales en la **red del local**, nunca en la Wi-Fi de clientes. Llenar
   «Terminales permitidas» con IP fijas o la red exacta (`192.168.1.0/24`). Sin TLS, el tráfico en la red local va
   sin cifrar: si la red no es de confianza, pon un proxy con HTTPS delante y `COMANDAPOS_HTTPS=1`.
4. La carpeta `C:\ProgramData\ComandaPOS` es escribible por los usuarios de Windows del equipo (el cajero necesita
   escribir la base). Usa cuentas de Windows separadas y sin privilegios para el personal, y cifrado de disco (BitLocker).
5. Respaldo diario de la carpeta de datos (`comandapos.db`, `secret_key`, `auditoria.ancla`) fuera del equipo.
6. Firmar los `.exe` con un certificado de firma de código antes de distribuirlos.
