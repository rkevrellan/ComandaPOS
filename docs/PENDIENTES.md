# Pendientes por fase

| Fase | Qué falta | Nota |
|---|---|---|
| 1 | — | Completa. Verificación en dos pasos (TOTP) para administración: se implementa en la fase 6, junto con la pantalla de operadores. |
| 2 · Salón | Abrir mesa, comanda completa (secciones, productos, cuentas separadas), notas, acompañamientos, anulación con autorización de supervisor, mover mesa, otro mesero, pre-cuenta, idempotencia de «Enviar pedidos» (RN-05), RN-08, RN-11, RN-12, RN-15. | Los botones de la barra inferior están desactivados hasta esta fase. |
| 3 · Cocina e impresión | Pantalla de cocina por área (P/L/E, tiempos), «Pedidos listos», cola de impresión ESC/POS con saneamiento de bytes de control, avisos de anulación. | |
| 4 · Caja | Cobro, multipago, vuelto, crédito con límite (RN-09, RN-10), jubilado con cédula, turnos, cortes X y Z, arqueo (RN-13), gaveta. | |
| 5 · Facturación electrónica | Adaptador PAC (simulado + HTTP), CAFE en PDF 80 mm y carta con CUFE y QR, contingencia, folios, notas de crédito. | Según la ficha técnica vigente de la DGI y la API del PAC contratado. |
| 6 · Administración | Catálogos completos, operadores con 2FA, inventario por receta (RN-14), reportes, PDF por sección. | |
| 7 · Escritorio | pywebview, modos servidor/terminal/cocina, emparejamiento con TLS, DPAPI, PyInstaller, Inno Setup, `build.bat`, dependencias con hash. | |
| 8 · Revisión | Revisión de seguridad independiente y zip final. | |
