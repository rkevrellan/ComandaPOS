# Suscripción mensual — guía del proveedor

ComandaPOS se cobra por mes. Cada restaurante instala el programa en su PC; tú cobras la
mensualidad y le envías un **código** que activa el mes. El programa funciona sin internet.

## 1. Una sola vez: tu llave

En **tu** PC (no en la del restaurante), dentro de la carpeta del proyecto:

```
python proveedor\emitir_codigo.py crear-llave
```

- Crea tu llave privada en `%USERPROFILE%\.comandapos-proveedor\llave_privada.txt`.
  **Guárdala con respaldo y no la compartas:** quien la tenga puede emitir códigos.
- Escribe tu llave pública en `app\services\llave_proveedor.py`.
- Después compila el instalador con `build.bat`. Solo los instaladores compilados con tu llave
  aceptan tus códigos. `build.bat` se detiene si todavía está la llave de pruebas.

## 2. Precios

Están en `app\services\suscripcion.py`, en `PLANES` (los B/. 29.00 y B/. 59.00 son de ejemplo).
Cambia el número y vuelve a compilar.

| Plan | Incluye |
|---|---|
| Básico | Punto de venta completo en una PC: mesas, comandas, servicio rápido, cobro, factura electrónica DGI, notas de crédito, caja (X/Z), jubilado, catálogos, operadores, 2FA, auditoría. |
| Pro | Todo lo anterior + pantalla de cocina, reportes avanzados, inventario y recetas, crédito a clientes, terminales en red (varias PC o tabletas). |

## 3. Cada mes, cuando un restaurante paga

1. El restaurante te paga (Yappy, ACH o efectivo) y te manda su **ID de instalación**: lo ve en
   Administración → Suscripción (formato `ABCD-EFGH-IJKL-MNOP`, con botón «Copiar»).
2. Emites el código:

   ```
   python proveedor\emitir_codigo.py emitir --instalacion ABCD-EFGH-IJKL-MNOP --plan pro --cliente "Restaurante El Fogón"
   ```

   - `--meses 3` para cobrar varios meses juntos; `--hasta 2026-12-31` para una fecha exacta.
   - Si el cliente todavía tenía días pagados, el mes nuevo empieza al día siguiente de su
     vencimiento (no pierde días por pagar antes).
3. Le envías el código (`CPOS-…`) por WhatsApp o correo. Lo pega en Suscripción → «Activar código».
   Se aceptan minúsculas, espacios y saltos de línea.

`python proveedor\emitir_codigo.py historial` lista todo lo emitido (queda en
`emitidos.csv`, junto a tu llave).

## 4. Qué ve el restaurante

| Fase | Cuándo | Qué pasa |
|---|---|---|
| Prueba | 14 días desde el primer arranque en producción | Todo Pro, gratis. Aviso los últimos 5 días. |
| Al día | Código vigente | Normal. |
| Por vencer | 5 días antes | Barra azul con los días que faltan. |
| Gracia | Hasta 7 días después de vencer | Barra ámbar; todo sigue funcionando. |
| Modo limitado | Después de la gracia | Barra roja. Se pueden terminar, cobrar y facturar las cuentas abiertas, cerrar caja y ver todo; **no** se abren mesas ni pedidos nuevos. |

- Plan Básico: las pantallas Pro muestran «… es parte del plan Pro» con el botón para activar, y
  las terminales de la red reciben la misma explicación.
- La facturación de lo ya consumido nunca se bloquea (obligación fiscal del restaurante).
- Atrasar el reloj de Windows no alarga la suscripción: se guarda la fecha más alta vista.
- En la **demostración** no se cobra nada.

## 5. Seguridad del esquema

- Firma **Ed25519**: la app solo tiene la llave pública; un código alterado o de otra llave se
  rechaza.
- Cada código lleva el ID de instalación (no sirve en otra PC) y un número de serie (no se activa
  dos veces).
- El ID de instalación vive en `instalacion.id`, en la carpeta de datos: sobrevive a
  `--nueva-base`. Si el restaurante cambia de PC, tiene un ID nuevo y necesita un código nuevo.
- Cada activación queda en la auditoría encadenada.
