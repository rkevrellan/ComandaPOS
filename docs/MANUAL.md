# Manual de ComandaPOS

Guía corta por puesto de trabajo. Todo se maneja con el dedo: cada botón es grande y la pantalla se bloquea
sola si nadie la toca (90 s en terminales de mesero).

## Entrar
Escribe tu usuario y tu PIN (meseros y cajeros) o tu contraseña (supervisores y administración) con el teclado
en pantalla. Tras varios intentos fallidos el usuario se bloquea unos minutos. Si tienes **verificación en dos
pasos**, después te pide el código de 6 dígitos de tu aplicación (o uno de tus códigos de recuperación).

## Mesero
1. **Mapa de mesas:** verde = libre, ocupada muestra mesero, minutos y total. Cambia de sala arriba.
2. Toca una mesa libre → elige **cuántas personas**.
3. **Comanda:** toca una sección y luego los productos. Si el plato lleva acompañamiento, te lo pide.
   - **Cantidad + / −**, **Notas** (fijas como «SIN CEBOLLA» o libres), **Para llevar**.
   - **Cuentas:** «Nueva cuenta» para dividir; «Pasar a cuenta» mueve la línea seleccionada a otra cuenta.
   - **Borrar** solo funciona con lo que aún no se envió. Lo enviado se **anula** con autorización de supervisor.
4. **Enviar pedidos:** sale a la pantalla de cocina y se imprime en la impresora de su área.
5. Cuando cocina marca «listo», aparece en **Pedidos listos** del mapa: entrégalo y toca **Entregado**.
6. **Pre-cuenta:** PDF o ticket para el cliente (dice «NO ES FACTURA»).
7. **Jubilado:** cédula y nombre; el descuento se aplica solo a lo que corresponde por ley.

## Cocina
Pantalla por área (Cocina, Frente…). Cada tarjeta es una mesa con su tiempo (verde → amarillo → rojo).
**P** = en preparación, **L** = listo (avisa al mesero), **E** = entregado. Se actualiza sola.
Las anulaciones salen impresas para que no se prepare algo cancelado.

## Cajero
1. **Caja → Abrir turno** con el fondo de caja.
2. Toca la mesa → **Cobrar**. Elige cuenta, cliente (consumidor final o contribuyente con RUC) y formas de pago.
   Los billetes rápidos llenan el efectivo; el vuelto se calcula solo. **EXE** cobra.
3. El comprobante se autoriza con el PAC y se imprime en la impresora de caja (o **PDF ticket / PDF carta**).
   Si no hay internet, sale **en contingencia**: entrégalo igual; se reenvía solo (o **Caja → Reenviar al PAC**).
4. **Liberar mesa** cuando el cliente se va.
5. **Nota de crédito:** desde el comprobante, marca qué productos y cuántos se devuelven, el motivo y cómo se
   devuelve el dinero. Pide la clave de un supervisor.
6. **Clientes y abonos:** abonos a cuentas de crédito con recibo PDF.
7. **Gaveta sin venta:** escribe el motivo (queda en la auditoría).
8. **Corte X:** PDF del turno sin cerrarlo. **Corte Z:** cuenta el efectivo, escríbelo y cierra; si la diferencia
   pasa de B/. 1.00 te pide una justificación.

## Supervisor
- Autoriza en la misma pantalla del mesero o cajero: anulaciones, descuentos sobre el tope, notas de crédito,
  «Otro mesero».
- **Notas fijas**, mesas **fuera de servicio** (desde el mapa).
- **Reportes:** elige el rango de fechas. Cada bloque tiene su **CSV** para Excel.

## Administración
- **Catálogos:** productos (precio, ITBMS, áreas de impresión, jubilado, acompañamiento, receta de insumos),
  secciones con color, acompañamientos, áreas de producción, salas, mesas, clientes, impresoras, insumos, notas fijas.
  Desactivar en vez de borrar: lo vendido nunca se pierde. Cada cambio de precio queda en la auditoría.
- **Operadores:** crear usuarios, cambiar nivel, restablecer PIN o contraseña, desactivar.
- **Configuración:** datos del emisor, descuentos de jubilado, tiempos de cocina, PAC y folios, impresión,
  inventario y **Terminales permitidas** (red local).
- **Inventario:** existencias, entradas y ajustes con motivo. Las ventas descuentan según la receta y, si un
  insumo llega a 0, el producto se marca agotado.
- **Impresiones:** cola de trabajos con vista previa, reintento y página de prueba por impresora.
- **Mi cuenta (⚙):** cambiar contraseña y activar la verificación en dos pasos (obligatoria para administración).

## Impresoras
| Tipo | Destino | Ejemplo |
|---|---|---|
| Red | IP:puerto de la impresora térmica | `192.168.1.50:9100` |
| Windows | Nombre de la impresora instalada | `EPSON TM-T20III` |
| Archivo | Carpeta de datos (demostración) | — |
Cada área de producción tiene su impresora; la de caja se elige en Configuración.

## Varias PC (red local)
1. En la PC de caja abre **ComandaPOS (servidor de red local)**. Te muestra su dirección (ej. `http://192.168.1.10:5000`).
2. En **Configuración → Terminales permitidas** escribe las IP de las otras PC o la red (`192.168.1.0/24`).
3. En cada terminal: acceso directo a `ComandaPOS.exe --servidor http://192.168.1.10:5000`
   (cocina: agrega `--cocina`). También sirve cualquier navegador.

## Respaldo
Copia diaria de `C:\ProgramData\ComandaPOS` (base, `secret_key` y `auditoria.ancla`) a un USB o a la nube.
Para restaurar: cierra ComandaPOS, reemplaza la carpeta y vuelve a abrir. El programador verifica en su consola
que la auditoría diga «Cadena íntegra».
