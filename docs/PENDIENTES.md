# Estado de ComandaPOS 1.0

| Fase | Estado |
|---|---|
| 1 · Base (núcleo, seguridad, auditoría, cálculos) | ✔ Completa |
| 2 · Salón (mesas, comanda, cuentas, pre-cuenta) | ✔ Completa |
| 3 · Cocina e impresión (KDS, ESC/POS por área, avisos de anulación, gaveta, cola persistente) | ✔ Completa |
| 4 · Caja (turnos, multipago, crédito, corte X y Z, abonos, gaveta sin venta) | ✔ Completa |
| 5 · Facturación electrónica (PAC, contingencia, folios, notas de crédito, PDF ticket y carta) | ✔ Completa con PAC simulado; falta la traducción a la API del PAC real |
| 6 · Administración (catálogos, operadores, 2FA, configuración, inventario por receta, reportes) | ✔ Completa |
| 7 · Escritorio (pywebview, una instancia, servidor/terminal/cocina, PyInstaller, Inno Setup, `build.bat`) | ✔ Completa; el `.exe` se compila en Windows con `build.bat` |
| 8 · Revisión (pruebas, pip-audit, bandit, recorrido en navegador, documentación) | ✔ Completa (revisión automática y propia) |

## Lo que falta para producción real (no se puede cerrar sin terceros)
1. **API del PAC contratado:** mapear `PACHttp` a su documentación y probar en su ambiente (ver `FISCAL.md`).
2. **Compilar el instalador en Windows** con `build.bat` (PyInstaller no genera `.exe` de Windows desde Linux;
   el paquete se verificó compilando y ejecutando la misma especificación en Linux).
3. **Firma de código** de los `.exe` (certificado comercial) para que Windows SmartScreen no los marque.
4. **TLS en la red local:** hoy el tráfico entre terminales va en HTTP dentro de la red del local, filtrado por
   la lista de terminales. Para redes no confiables: proxy HTTPS delante y `COMANDAPOS_HTTPS=1`.
5. **Revisión de seguridad independiente** (pentest) antes de vender a terceros: esta fue una revisión propia.
6. **Confirmar las suposiciones** de `SUPOSICIONES.md` con el contador.

## Mejoras posibles (no bloquean)
- Unir dos mesas ocupadas (hoy «Mover mesa» va a mesas libres).
- Fotos de productos en la comanda.
- Proteger la clave secreta de la instalación con DPAPI (hoy es un archivo en la carpeta de datos; ver SEGURIDAD §3).
- Respaldo automático programado a USB o nube.
