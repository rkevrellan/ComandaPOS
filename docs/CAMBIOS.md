# Cambios de la versión 1.2.0 — suscripción mensual y diseño «Brasa»

## Suscripción mensual (SaaS)

ComandaPOS pasa a cobrarse por mes con dos planes. Todo lo de la suscripción se configura y se
explica en [SUSCRIPCION.md](SUSCRIPCION.md).

| Plan | Qué incluye |
|---|---|
| **Básico** (B/. 29.00/mes, precio de ejemplo) | El punto de venta: mapa de mesas, comandas, servicio rápido, cobro, factura electrónica DGI, notas de crédito, caja (X/Z), jubilado, catálogos, operadores, 2FA y auditoría. Solo en la PC donde está instalado. |
| **Pro** (B/. 59.00/mes, precio de ejemplo) | Todo lo anterior + pantalla de cocina, reportes avanzados, inventario y recetas, crédito a clientes y terminales en red. |

- **Códigos mensuales firmados (Ed25519).** El restaurante paga, envía su ID de instalación y pega
  el código `CPOS-…` en Administración → Suscripción. ComandaPOS solo tiene la llave pública: no se
  puede falsificar un código, usarlo en otra PC ni activarlo dos veces.
- **Fases:** prueba de 14 días (Pro) → al día → por vencer (aviso 5 días antes) → gracia (7 días)
  → **modo limitado**: se terminan, cobran y facturan las cuentas abiertas y se cierra caja, pero no
  se abren mesas ni pedidos nuevos. Retroceder el reloj de Windows no alarga nada.
- **Herramienta del proveedor:** `proveedor/emitir_codigo.py` (crear-llave, emitir, historial).
- `build.bat` se niega a empaquetar con la llave de pruebas (`run.py --verificar-llave`).
- En la demostración no se cobra: todo funciona como Pro.

## Diseño «Brasa»

- Hoja de estilos nueva: fondo carbón con brillos cálidos, paneles de vidrio, degradados
  ámbar → brasa → rojo, sombras con profundidad y estados con brillo propio.
- Tipografía **Inter / Inter Display** incluida en el programa (SIL OFL, funciona sin internet).
- **59 íconos propios** (`static/img/iconos.svg`) en cabecera, menús, botones y tarjetas.
- Logo renovado e ícono `.ico` del instalador regenerado.
- Acceso con panel de presentación; mesas con degradado, brillo y pre-cuenta que late; productos
  del color de su sección; la comanda y la cocina como «papel» legible; cobro con ícono por forma de
  pago; administración en mosaico con íconos y candado en lo que es Pro.
- Ilustraciones propias para errores (404, 403, 429, 5xx, 400) y estados vacíos.

## Servidor apagado

- **Causa del problema reportado:** ComandaPOS y otra app de prueba usaban `127.0.0.1:5000`; el
  navegador guardó el «modo sin conexión» de la otra app y lo mostraba cuando ComandaPOS se apagaba.
- ComandaPOS registra su propio service worker en `/sw.js`: reemplaza al ajeno, borra sus cachés y,
  si el servidor no responde, muestra «El servidor de ComandaPOS no responde», que vuelve sola.
  Si se había enviado un formulario, avisa que la acción pudo no guardarse.
- Barra roja de «Sin conexión con el servidor» mientras se trabaja; la pantalla de cocina no recarga
  a ciegas y el bloqueo por inactividad no lleva a una pantalla de error.

## Pruebas

`tests/test_suscripcion.py` (19) y `tests/test_sin_servidor.py` (7). Total: 250, todas pasan.

---

# Cambios de la versión 1.1.0 — correcciones del diagnóstico

La 1.1.0 corrige los 24 hallazgos del «Diagnóstico — ComandaPOS 1.0» (H-01 a H-24). Cada corrección
tiene al menos una prueba automática (`tests/test_produccion.py`, `tests/test_correcciones_fiscal.py`,
`tests/test_correcciones_operacion.py` y ampliaciones en `test_web.py` y `test_final_admin.py`).
Total: 224 pruebas, todas pasan.

| ID | Severidad | Qué cambió | Dónde | Prueba |
|---|---|---|---|---|
| H-01 | Alta | Primer arranque en producción: asistente para crear el primer administrador (solo desde el propio equipo), opción de cargar salas, mesas y menú de ejemplo sin ventas ni usuarios de prueba. Una base de demostración se niega a arrancar en producción; `--nueva-base` la aparta en un respaldo. En producción el emisor arranca vacío y no se factura sin sus datos. | `auth/routes.py`, `run.py`, `seed.py`, `configuracion.py`, `caja.py` | `test_produccion.py` |
| H-02 | Alta | «Corregir y reenviar» para comprobantes rechazados (mismo número, cambio auditado) y «Reenviar sin cambios»; aviso en Caja con enlace. | `fiscal.corregir_receptor`, `salon/routes.py` | `test_rechazado_*` |
| H-03 | Media | El instalador pregunta Producción o Demostración (`modo.txt`); `--modo` lo cambia. Las credenciales de prueba solo se muestran en el propio equipo, nunca en la red. | `config.modo_demo`, `comandapos.iss`, `auth/routes.py` | `test_modo_*`, `test_credenciales_*` |
| H-04 | Media | El cliente del PAC no sigue redirecciones: un 3xx deja el documento en contingencia y la credencial no sale. | `fiscal._SinRedirecciones` | `test_pac_que_redirige_*` |
| H-05 | Media | La carpeta de datos queda solo para Administradores, SYSTEM y el grupo local «ComandaPOS» (antes: todos los usuarios). | `comandapos.iss` (`net localgroup`, `icacls`) | Verificar en Windows |
| H-06 | Media | Modo red con **HTTPS**: CA local propia, certificado del servidor por IP (se renueva solo), TLS 1.2+, cookies `Secure`/`__Host-`. `--confiar` instala la CA; `--sin-tls` solo si se pide. | `services/tls.py`, `run.py`, `escritorio.py` | `test_certificados_*` + prueba con `curl` |
| H-07 | Media | La impresión va en un hilo aparte: «Enviar pedidos» ya no espera a la impresora (antes 4/8/12 s, ahora < 1 s). Una impresora caída se salta en el resto de la pasada y la base no queda bloqueada mientras se espera. | `impresion.despertar`, `procesar_pendientes` | `test_impresora_*` |
| H-08 | Media | `pywin32` en las dependencias de Windows y en el paquete; `ComandaPOS-servidor.exe --verificar` comprueba los módulos y `build.bat` lo usa. | `requirements.txt`, `comandapos.spec`, `run.verificar` | `test_verificar_dependencias` |
| H-09 | Media | La credencial del PAC se guarda cifrada **para el equipo** (DPAPI de máquina) en la carpeta de datos protegida: sirve con cualquier cuenta del grupo. Avisos en Caja y en el cobro si falta. | `services/secretos.py`, `fiscal.avisos` | `test_credencial_*`, `test_aviso_*` |
| H-10 | Media | El corte Z lista mesas sin cobrar y documentos sin autorizar; para cerrar igual hace falta un supervisor y queda auditado. | `caja.pendientes_de_cierre`, `cerrar_turno` | `test_corte_z_*` |
| H-11 | Media | Con los folios agotados el comprobante queda en contingencia («Folios agotados») en vez de mandarse al PAC; aviso en el cobro desde el 10 %. | `fiscal.autorizar`, `fiscal.avisos` | `test_folios_*` |
| H-12 | Media | Ventas, ticket promedio e ITBMS excluyen los rechazados; se muestran aparte. | `reportes.ESTADOS_VENTA` | `test_reportes_no_cuentan_rechazados` |
| H-13 | Baja | No se agrega ni se envía lo que el inventario no cubre (configurable); la existencia ya no queda negativa. | `inventario.revisar_existencia` | `test_no_se_envia_*`, `test_otra_mesa_*` |
| H-14 | Baja | Activar 2FA, generar códigos nuevos y quitarla exigen la contraseña actual y tienen límite de intentos. | `cuenta/routes.py` | `test_activar_2fa_exige_*`, `test_nuevos_codigos_*` |
| H-15 | Baja | El descuento decide si hace falta supervisor con el número ya limpio. | `salon/routes.py` | `test_descuento_con_espacios_*` |
| H-16 | Baja | Limitadores atómicos (`tomar`) y persistentes en la carpeta de datos: ni hilos simultáneos ni un reinicio saltan el límite. | `seguridad.Limitador` | `test_limitador_atomico_y_persistente` |
| H-17 | Baja | Impresoras de red: solo IP privada (no el propio equipo, ni enlace local) y puertos 9100–9109. | `impresion.validar_destino` | `test_impresora_de_red_*` |
| H-18 | Baja | Los mensajes conservan «B/.» en mayúscula. | `catalogos.Campo.convertir` | `test_mensajes_conservan_la_moneda` |
| H-19 | Baja | Reportes leen solo las columnas necesarias y agrupan en SQL: un año (36 000 comprobantes) pasó de 4.0 s a 0.2 s. | `reportes.calcular` | medido con `sondeo7.py` |
| H-20 | Info | `/salud` ya no dice la versión. | `__init__.py` | `test_salud_no_dice_la_version` |
| H-21 | Info | Cédulas de jubilados enmascaradas en pantalla y CSV; la completa solo la baja un administrador y queda auditado. | `reportes.enmascarar_cedula` | `test_cedula_*` |
| H-22 | Info | Desactivar a un mesero con mesas abiertas exige elegir a quién pasarlas. | `admin/routes.py` | `test_desactivar_mesero_*` |
| H-23 | Info | Los manuales se instalan en `.txt` (se abren con el Bloc de notas). | `comandapos.iss` | — |
| H-24 | Info | En el propio equipo no se aplica el límite por IP (un empleado no bloquea a los demás); un administrador puede «Desbloquear acceso» de un usuario. | `auth/routes.py`, `admin/routes.py` | `test_en_este_equipo_*`, `test_bloqueo_por_usuario_*` |

## Lo que solo se puede comprobar en Windows
- H-05 (grupo y permisos de la carpeta), H-08 (impresión con pywin32), H-09 (DPAPI de máquina) y la
  instalación de la CA con `--confiar`. El código está escrito y el resto del flujo probado en Linux;
  hacer una instalación de prueba en una PC con Windows antes de llevarlo a un restaurante.
