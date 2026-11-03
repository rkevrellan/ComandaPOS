# Pendientes por fase

| Fase | Estado | Qué falta |
|---|---|---|
| 1 · Base | ✔ Completa | Verificación en dos pasos (TOTP) para administración: va en la fase 6 con la pantalla de operadores. |
| 2 · Salón | ✔ Completa | Unir dos mesas ocupadas (hoy «Mover mesa» solo va a mesas disponibles). |
| 3 · Cocina e impresión | ◐ Parcial | Hecho: pantalla de cocina por área con P/L/E, tiempos y «Pedidos listos». Falta: impresión térmica ESC/POS de comandas por área (con saneamiento de bytes de control), avisos de anulación impresos y apertura de gaveta. |
| 4 · Caja | ◐ Casi completa | Hecho: turnos con fondo, cobro con multipago, vuelto, crédito con límite, jubilado con cédula, corte Z con arqueo. Falta: corte X impreso, abonos a crédito con recibo, gaveta sin venta con motivo. |
| 5 · Facturación electrónica | ◐ Base lista | Hecho: comprobante PDF 80 mm con estructura de CAFE y QR, numeración atómica. Falta: adaptador PAC (CUFE real, XML autorizado), contingencia, folios, notas de crédito, formato carta. |
| 6 · Administración | Pendiente | Catálogos del menú (productos, secciones, mesas, operadores) con 2FA, inventario por receta (RN-14), reportes con gráficos. |
| 7 · Escritorio | Pendiente | pywebview, modos servidor/terminal/cocina, emparejamiento con TLS, DPAPI, PyInstaller, Inno Setup, `build.bat`, dependencias con hash. |
| 8 · Revisión | Pendiente | Revisión de seguridad independiente y zip final. |

## Notas de diseño
- **Pantalla de cocina:** cualquier usuario con sesión puede marcar P/L/E (las pantallas de cocina usan una cuenta de
  operador). Se recarga cada 15 s, así que no se bloquea por inactividad; conviene una cuenta dedicada por pantalla.
- **Bases de datos de la fase 1:** al arrancar se crean solas las tablas nuevas. Como esa base ya tenía datos, no se abre
  el turno de demostración: ábrelo en **Caja**.
