# Prompt maestro — ComandaPOS
**«Del pedido a la factura, sin perder una comanda.»**

> Copia este documento completo en la IA (Claude Code u otra) o entrégaselo a tu equipo. Si puedes, adjunta también las
> fotos de referencia del punto de venta actual. Describe el producto, la lógica, las reglas y los criterios de aceptación
> con suficiente detalle para construir **ComandaPOS** desde cero y entregarlo como **instalador .exe para Windows** dentro
> de **un zip completo**. El nombre «ComandaPOS» es provisional: cámbialo en un solo lugar (`app/config.py → NOMBRE`).

---

## 0. Cómo trabajar este prompt
- Trabaja **por fases** (sección 19). No pases a la siguiente fase hasta que las pruebas de la actual estén en verde.
- Ante una duda de negocio, **no inventes**: deja la regla configurable, documenta la suposición en `docs/SUPOSICIONES.md`
  y sigue. Esto aplica sobre todo a los temas fiscales (sección 11).
- Si puedes, adjunta también el código de **Manda2 v3** como referencia de estilo: estructura de carpetas, `seguridad.py`
  (`@publica`, `@rol_requerido`, `destino_seguro`, limitadores), `services/` y la forma de escribir pruebas y `docs/SEGURIDAD.md`.
  Sigue esas mismas convenciones.
- Todo el código, los comentarios, la interfaz y la documentación van en **español**.
- Nunca dejes `TODO` sin resolver en el entregable final; si algo queda pendiente, va en `docs/PENDIENTES.md` con su motivo.

## 1. Rol y objetivo
Actúa como un equipo senior de producto, desarrollo de sistemas de punto de venta (POS) para restaurantes, seguridad de
aplicaciones (OWASP) y facturación electrónica de Panamá. Construye **ComandaPOS**: un sistema de punto de venta para
**restaurantes de servicio a la mesa** en Panamá que cubre todo el ciclo:

**mesa → comanda → cocina → entrega → pre-cuenta → cobro → factura electrónica (CAFE en PDF / impresa) → cierre de turno.**

Toma como referencia funcional el POS que hoy usa un restaurante de David, Chiriquí (un sistema de escritorio de pantallas
táctiles con mapa de mesas, comandas por área de producción, pantalla de cocina y administración de archivos). **Replica el
flujo de trabajo y la lógica** que se describen en la sección 6, pero con **identidad, nombre, ilustraciones y código propios**:
no copies logos, mascotas, textos de marca ni código de ese producto.

Entregable: una **aplicación monolítica en Python 3.11+ / Flask** empaquetada como **programa de escritorio para Windows 10/11**
(`ComandaPOS.exe` + instalador), lista para correr en la caja y en las demás terminales del local, con datos de demostración,
pruebas automáticas, documentos PDF fiscales y documentación en español. Todo dentro de **`ComandaPOS_v1.0.zip`** (sección 18).

## 2. Público y tono
- Meseros y meseras que toman pedidos en pantalla táctil, muchas veces con prisa y con las manos ocupadas.
- Cajeros que cobran, emiten facturas y cuadran la caja al final del turno.
- Cocina y área del frente, que preparan los pedidos y los marcan como listos.
- Supervisores y administradores que autorizan anulaciones y descuentos, configuran el menú y revisan reportes.
- Tono de la interfaz: directo y claro («Enviar a cocina», «Cobrar», «Mesa 12 ocupada»). Moneda: **balboas / dólares**, se muestra
  **B/.** en documentos fiscales y en reportes.

## 3. Arquitectura (monolito, el mismo estilo de mis proyectos)
- **Una sola app Flask** con factory `create_app()` y blueprints: `auth`, `mesas`, `pedidos`, `caja`, `cocina`, `admin`,
  `reportes`, `fiscal`, `dev`, `api`.
- **Servicios separados de las rutas** (`app/services/`): `calculos.py` (dinero e impuestos, sin Flask ni BD), `pedidos.py`,
  `mesas.py`, `caja.py`, `turnos.py`, `inventario.py`, `impresion.py`, `fiscal/` (sección 11), `reportes.py`, `auditoria.py`,
  `respaldo.py`. Las rutas solo validan la entrada, llaman al servicio y muestran el resultado.
- **Reglas de negocio numeradas** (`RN-01`, `RN-02`…) en el docstring del módulo que las aplica, y cada una con al menos una prueba
  que la nombra. Lista mínima en la sección 9.
- **SQLite** con SQLAlchemy en modo **WAL** y `foreign_keys=ON` (un solo local). Debe poder cambiarse a PostgreSQL con la
  variable `COMANDAPOS_DB` sin tocar el código.
- Interfaz: **plantillas Jinja2, CSS propio y JavaScript sin frameworks**, con las librerías de terceros incluidas localmente y
  verificadas con SRI (sin CDN: el local puede quedarse sin internet).
- Tiempo real (mapa de mesas, cocina, «pedidos listos»): **Server-Sent Events** con respaldo de consulta cada 5 s.
- Servidor: **Waitress**. Ventana de escritorio: **pywebview** (WebView2 de Windows) a pantalla completa, sin barra de direcciones.
- `seed.py` con datos de prueba realistas de un restaurante panameño (sección 15).
- `run.py` con opciones: `--modo servidor|terminal|cocina`, `--dev`, `--puerto`, `--nuevas-claves`, `--respaldar`.

### 3.1 Despliegue en el local (varias pantallas)
| Equipo | Modo | Qué muestra |
|---|---|---|
| PC de caja (servidor) | `servidor` | Todo. Aquí viven la base de datos, la impresora fiscal o térmica de caja y la gaveta de dinero. |
| Terminales de meseros | `terminal` | Mapa de mesas y toma de pedidos. Se conectan al servidor por la red local. |
| Pantalla de cocina (KDS) | `cocina` | Tablero de comandas de su área de producción (sección 6.12). |
| Administración | (cualquier modo, con rol) | Configuración, reportes y consola del programador. |

- Un solo `ComandaPOS.exe`; el modo se elige en el asistente de primera ejecución y se guarda en la configuración local.
- Emparejamiento de terminales: el servidor muestra un **código de emparejamiento de un solo uso** (y QR) que caduca en
  10 minutos; la terminal lo ingresa y recibe un **token de dispositivo** propio, revocable desde Administración → Dispositivos.
  Una terminal sin token válido no ve nada.
- Tráfico en la red local con **TLS**: en la instalación del servidor se genera una CA local propia y un certificado; las
  terminales emparejadas confían solo en esa CA (anclaje). Nada de HTTP plano con contraseñas en la red.

## 4. Roles y permisos
Los cinco niveles del sistema de referencia, con permisos explícitos (decorador `@rol_requerido(...)` en **cada** ruta;
una prueba falla si alguna ruta queda sin marcar como `@publica` o con rol):

| Rol | Puede |
|---|---|
| **Operador (mesero)** | Abrir mesa, tomar pedidos, notas, enviar a cocina, pedir pre-cuenta, mover **sus** mesas, aplicar descuento de jubilado (registrando cédula). Solo ve sus mesas, salvo que el supervisor le asigne otra. |
| **Cajero** | Todo lo del operador + cobrar, emitir factura, multipago, reimprimir CAFE, abrir y cerrar turno de caja, arqueo, abrir gaveta con motivo. |
| **Supervisor** | Todo lo anterior + **autorizar anulaciones**, descuentos por porcentaje, «otro mesero» (pasar mesas), reabrir una cuenta cobrada antes de facturar, marcar productos agotados. |
| **Administrador** | Todo lo anterior + administración de archivos (sección 6.13), reportes, operadores, clientes, dispositivos, configuración fiscal y de impresoras. |
| **Programador (superusuario)** | Todo lo anterior + consola del programador (`/dev`): estado del sistema, base de datos en **solo lectura**, auditoría, eventos de seguridad, respaldos y diagnóstico de impresoras y del proveedor fiscal. |

- **Autorización de supervisor en el momento**: cuando un operador intenta algo que no puede (anular, descuento %), aparece una
  ventana para que un supervisor escriba **su** usuario y clave **sin cerrar la sesión del operador**. Queda en la auditoría
  quién pidió, quién autorizó, qué y por qué.

## 5. Identidad visual y experiencia táctil
- Pantallas táctiles de 20–24″ (resoluciones 1366×768 y 1920×1080). Botones de **mínimo 56 px** de alto, separación de 8 px,
  sin depender del pasar el ratón por encima (no hay hover en táctil).
- **Teclado en pantalla** (números y QWERTY con tecla «CLR») en el inicio de sesión y en todos los campos de texto.
- Colores de estado **consistentes en todo el sistema** (mapa de mesas, líneas de pedido y cocina), siempre acompañados de un
  texto o ícono (no solo color, por accesibilidad):

| Estado de mesa | Color |
|---|---|
| Disponible | verde |
| Ocupada | azul |
| Pre-cuenta impresa | rojo |
| Pagada (por liberar) | magenta |
| Fuera de servicio | gris |
| Para llevar / pagada por adelantado | amarillo |

| Estado de línea de pedido | Sigla | Color |
|---|---|---|
| Pedido (en pantalla, sin enviar) | PED | amarillo |
| Ordenado (enviado a su área) | ORD | verde |
| En proceso (cocina lo tomó) | PRO | azul |
| Preparado / listo | PRE | rojo |
| Entregado a la mesa | ENT | magenta |
| Anulado | ANU | negro, texto tachado |

- Identidad propia: diseña un logotipo e ilustraciones originales (SVG generado por código, como en mis otros proyectos),
  tema oscuro por defecto para el salón y tema claro opcional. Contraste AA, foco visible.
- Fecha, hora, turno, mesero y número de comanda siempre visibles en la cabecera de la pantalla de pedidos.

## 6. Pantallas y flujo (réplica funcional del sistema de referencia)

### 6.1 Control de acceso
- Fondo: el mapa de mesas atenuado. Al centro, la tarjeta de acceso con el nombre del sistema, versión, **usuario**
  (lista con foto opcional para tocar) y **contraseña/PIN** con teclado en pantalla y botones «Aceptar» y «Salir».
- Operadores y cajeros usan **PIN de 6 dígitos** (no 4); supervisores, administradores y programador usan contraseña y,
  fuera del modo demostración, **verificación en dos pasos (TOTP)**.
- Bloqueo tras 5 intentos fallidos por usuario+terminal y 30 por terminal (revisado **antes** de calcular el hash),
  respuestas de igual duración exista o no el usuario.
- **Bloqueo automático por inactividad** de la terminal (configurable, 90 s por defecto en terminales de mesero) y opción
  «cerrar sesión al enviar pedido». Volver a entrar no pierde la comanda abierta.

### 6.2 Control — ocupación de mesas (pantalla principal)
- Cuadrícula de mesas por **sala de venta** (Salón, Servicio rápido, Reservado, Terraza…; configurables). Cada mesa muestra su
  número, color de estado, mesero, número de puestos ocupados y tiempo abierta.
- Panel izquierdo: fecha, hora, **turno #**, salas de venta, «última mesa» y «último mesero» atendidos.
- Leyenda de colores a la derecha y panel **«Pedidos listos»** que parpadea cuando cocina marca algo como listo para una mesa
  del mesero que está en la sesión.
- Barra inferior: **Caja**, **Notas fijas**, **Clientes**, **Pedidos directos (cobro rápido)** y **Salir**.
- Tocar una mesa disponible la abre (pide número de puestos); tocar una ocupada abre su comanda.

### 6.3 Comanda (toma de pedidos)
Distribución de referencia (respétala, porque el personal ya la conoce):
- **Cabecera:** ícono y número de mesa, número de cuentas (`Ctas`), flechas para cambiar de cuenta, «Hora/Reg», fecha y hora,
  **Mesero**, **Turno #**, **# Comanda** (secuencia global, nunca se repite), y botón «Reimprimir facturas emitidas».
- **Secciones del menú** (botones grandes con scroll): Bebidas, Desayunos, Almuerzo, Sopas, Carnes (porción), Porciones,
  Picadas, Postres, Pastas, Cortes de carne, Hamburguesas, Mariscos, Órdenes de arroz, Entradas, Órdenes de pollo…
- **Productos de la sección**: cuadrícula de botones con foto opcional, nombre y precio en la esquina. Los agotados se ven
  grises y no se pueden tocar.
- **Detalle de la comanda** (tabla): Producto, Cant, Precio, Sub-total, Enviado (SÍ/NO), Estado (PED/ORD/PRO/PRE/ENT/ANU),
  Cuenta #. Debajo, la leyenda de estados con sus colores.
- **Botonera de acciones** (columna central): borrar línea no enviada, agregar cantidad, **Jubilado %**, **Descuento %**,
  **Error** (anular línea enviada → pide autorización), **Separar cuenta**, **Notas especiales**, **Para llevar**,
  **Pedidos directos / cobro rápido**.
- **Botonera derecha:** **Enviar pedidos** (manda a cada área de producción solo las líneas en PED), **Pre-cuentas**,
  **Estado de cuenta**, **Mover mesa**, **Otro mesero**, **Cerrar**.
- **Zona de cobro:** campo «Pre/Cant» con teclado numérico (0–9, punto, CLR), montos rápidos 0.25 / 0.75 / 1.00, billetes
  5 / 10 / 20 / 50, **CTA/TOT** (cobrar la cuenta seleccionada o el total), totales **SB-TOT, DES-PRD, DES-JUB, ITBMS, TOTAL**,
  tipo de pedido («Pedido regular», «Para llevar», «Servicio rápido»), **Cliente/Compañía** con RUC y DV
  («CONSUMIDOR FINAL / 00-00-00» por defecto), **formas de pago** (Efectivo, Visa, Mastercard, Clave, Yappy, Crédito a cliente
  autorizado, Otro) y botón **EXE** (ejecutar el cobro) y **Multi-pago**.
- **Contador de folios** fiscales: total, usados y disponibles (sección 11), en rojo cuando quedan menos del 10 %.
- **Cuentas separadas:** una mesa tiene 1..n cuentas; las líneas se asignan a una cuenta y se pueden mover entre cuentas
  («Separar cuenta») antes del cobro. Cada cuenta se cobra y se factura por separado.

### 6.4 Notas del producto
- Al tocar «Notas especiales» con una línea seleccionada: lista de **notas predefinidas** (búsqueda), botón **Anotar** (las
  agrega), **Borrar**, cuadro de **notas libres** (máx. 140 caracteres) y **Grabar notas**. Las notas salen impresas en la comanda
  de cocina debajo del producto.

### 6.5 Acompañamientos
- Un producto «con acompañamiento» abre un selector obligatorio de acompañamientos (p. ej., papas salteadas, vegetales
  hervidos, arroz blanco, ensalada verde, patacones, «sin acompañamiento»). Algunos tienen precio adicional; se suman a la
  línea y se imprimen en la comanda.

### 6.6 Anulación de productos
- Ventana «Anulación de productos»: **usuario y contraseña de un supervisor**, **explicación obligatoria** (mín. 10 caracteres)
  y botón **Aplicar/Anular**. La línea pasa a **ANU**, no se borra; si ya estaba en cocina, se imprime un aviso de anulación en esa área.
- Una línea ya **facturada** no se anula desde aquí: requiere nota de crédito (sección 11.5).

### 6.7 Mover mesa y otro mesero
- **Mover mesa:** cuadrícula de mesas disponibles; muestra comanda, mesa actual y mesa nueva; botón «Mover». Se mueve la comanda
  completa (todas sus cuentas). Permite **unir** mesas si el destino está ocupada (con confirmación).
- **Otro mesero:** pasa la mesa a otro mesero activo (supervisor). Ambos cambios quedan en la auditoría.

### 6.8 Pre-cuenta y estado de cuenta
- **Pre-cuenta:** imprime y genera PDF del consumo por cuenta, con la leyenda grande **«PRE-CUENTA — NO ES FACTURA»**, subtotal,
  descuentos, ITBMS estimado y total. La mesa pasa a «Pre-cuenta». Agregar algo después la regresa a «Ocupada».
- **Estado de cuenta:** vista en pantalla de todas las cuentas de la mesa, lo enviado, lo pendiente y lo cobrado.

### 6.9 Clientes en el cobro
- Ventana «Consulta y creación de registros de clientes»: buscar por nombre o RUC, lista (cédula/RUC, nombre o compañía, DV),
  «Seleccionar para la factura actual».
- **Consumidor final con nombre:** permite poner el nombre solo para imprimirlo, sin guardar el registro.
- **Contribuyente:** crear registro permanente (persona natural o jurídica) con validación de formato de cédula/RUC y DV
  (sección 11.3). Doble toque para eliminar solo si no tiene facturas.

### 6.10 Cobro
- Efectivo con cálculo de **vuelto**; tarjetas y Yappy con número de referencia o autorización (últimos 4 dígitos, nunca el
  número completo de la tarjeta); **multipago** (varias formas en una cuenta hasta cubrir el total exacto); **crédito** solo para
  clientes con tipo de pago «Crédito» o «Autorizado» y límite disponible.
- Al ejecutar el cobro: se emite el documento fiscal (sección 11), se imprime el CAFE, se abre la gaveta si hubo efectivo y la
  cuenta queda pagada. Cuando todas las cuentas de una mesa están pagadas, la mesa pasa a «Pagada» y luego a «Disponible» al
  liberarla (o automáticamente a los N minutos, configurable).
- **Pedidos directos / cobro rápido:** venta sin mesa (mostrador), se cobra al momento y se envía a cocina con un número de turno.

### 6.11 Para llevar
- Marca la cuenta o la línea como «para llevar»: imprime «PARA LLEVAR» en la comanda y sugiere cargos configurables de envase
  (envase de sopa, envase para llevar, cubiertos desechables, cuchara plástica…).

### 6.12 Pantalla de cocina (KDS) por área de producción
- Tablero de tarjetas (6 por página, paginado): **Mesa #**, **Mesero**, tabla Cant/Pedido con notas y acompañamientos,
  **Rec #** (número de comanda), **Tp** (tiempo transcurrido con barra verde → amarilla → roja según umbrales configurables).
- Botones por tarjeta: **P** (en proceso), **L** (listo), **E** (entregado). Al marcar **L**, avisa en el mapa de mesas
  («Pedidos listos») a ese mesero.
- Barra lateral: página, **Refrescar**, **Servir/entregar todo**, **Limpiar entregados**, configuración del área y **Cerrar**.
- Cada área ve solo los productos asignados a ella (Cocina, Frente/Bar, Parrilla…). Un producto puede tener **dos áreas**.
- Si la pantalla de cocina no está disponible, la comanda **igual se imprime** en la impresora del área.

### 6.13 Administración de archivos (menú del administrador)
Pantalla con íconos grandes hacia cada catálogo, cada uno con lista + buscador a la izquierda, formulario «Datos – registro»
a la derecha y botones **Nuevo, Grabar, Borrar, Cancelar, Salir**. Borrar es lógico (inactivar) si el registro tiene historial.

1. **Productos del menú:** código, código de barras, descripción larga, descripción corta (para el botón y la comanda),
   sección, familia, subfamilia, **área de producción 1 y 2**, ubicación del botón, tipo (**producto directo** /
   **menú-orden** / **combo**), **receta** (insumo, cantidad, unidad) o detalle del **combo** (producto, cantidad, precio),
   estado de venta (con existencia / agotado temporal), **tasa de ITBMS** (exento, 7 %, 10 %, 15 %), si **aplica descuento de
   jubilado**, si lleva **acompañamiento**, condición (activo sin inventario / activo con inventario / inactivo), imagen
   (re-codificada, sección 12) y fecha de inicio. Reporte imprimible **por sección**.
2. **Secciones del menú:** nombre, orden, color, activa.
3. **Acompañamientos:** código, código de inventario, descripción rápida, cantidad, precio adicional, activo.
4. **Áreas de producción:** código, descripción (Cocina, Frente…), impresora asignada, activa.
5. **Salas de venta:** nombre, orden, tipo (mesa-salón, para llevar, servicio rápido).
6. **Configuración de mesas:** número, sala, nombre especial, puestos, tipo, estado (libre, ocupada, pagada, fuera de servicio),
   y vista de control con comanda activa, hora de apertura y estado de los pedidos (disponible, pedido, proceso, listo, entregado).
7. **Notas fijas:** código, descripción, activa.
8. **Clientes:** cédula/RUC, DV, tipo (natural/jurídico/extranjero/consumidor final), nombre o compañía, apellido, nombre,
   correo (opcional, para enviar el CAFE), tipo de pago (**contado, autorizado, personal, crédito**), límite de crédito, activo.
9. **Operadores:** código, nombre, cargo, usuario, PIN o contraseña, **nivel de seguridad** (programador, administrador,
   supervisor, cajero, operador), foto opcional, activo/inactivo.
10. **Inventario:** insumos, unidades, existencia, mínimo, entradas (compras) y salidas automáticas por receta o producto directo;
    alerta de existencia baja; al llegar a cero, el producto se marca agotado si así se configura.
11. **Formas de pago, impresoras, dispositivos, datos fiscales del emisor y folios** (secciones 10 y 11).

### 6.14 Caja y turnos
- **Apertura de turno** con fondo inicial por cajero. Número de turno visible en todo el sistema.
- **Corte X** (parcial, no cierra) y **Corte Z** (cierre del turno): ventas por forma de pago, descuentos, anulaciones,
  ITBMS por tasa, propinas si se habilitan, efectivo esperado contra **arqueo** contado por denominación, diferencia
  (sobrante/faltante) con justificación obligatoria si supera un umbral.
- No se puede cerrar el turno con mesas abiertas sin pasarlas al siguiente turno o al siguiente cajero (queda registrado).
- Apertura de gaveta sin venta: solo cajero o superior, con motivo; queda en la auditoría.

## 7. Modelo de datos (mínimo)
`Operador`, `Dispositivo`, `Sala`, `Mesa`, `Seccion`, `Familia`, `Producto`, `Receta`, `ComboDetalle`, `Acompanamiento`,
`AreaProduccion`, `NotaFija`, `Cliente`, `Turno`, `Comanda` (mesa, mesero, turno, número global, apertura, cierre),
`Cuenta` (comanda, número, cliente, jubilado_cedula), `LineaPedido` (cuenta, producto, cantidad, precio_unitario **congelado**,
descuentos, tasa ITBMS **congelada**, estado, enviado, área, notas, acompañamientos, para_llevar, idempotencia),
`Anulacion` (línea, solicitante, autorizador, motivo, fecha), `Pago` (cuenta, forma, monto, referencia, vuelto),
`DocumentoFiscal` (tipo, número, punto de facturación, CUFE, protocolo de autorización, QR, XML, PDF, estado, intentos),
`Folio` (paquetes comprados, usados), `Insumo`, `MovimientoInventario`, `Impresora`, `Auditoria`, `EventoSeguridad`, `Config`.
- **Dinero siempre en `Decimal`**, columnas numéricas con 2 decimales (cantidades con 3). Nunca `float`.
- El precio y la tasa de impuesto **se congelan en la línea** al momento del pedido: cambiar el menú no altera cuentas abiertas
  ni facturas emitidas.

## 8. Lógica de estados
- **Mesa:** Disponible → Ocupada → Pre-cuenta → (Ocupada si se agrega algo) → Pagada → Disponible. Fuera de servicio se fija
  manualmente. Transiciones inválidas → error de regla de negocio, nunca un 500.
- **Línea:** PED → ORD → PRO → PRE → ENT; cualquier estado anterior a facturada → ANU (con autorización si ya fue enviada).
  Una línea en PED se borra sin autorización (todavía no salió de la terminal).
- **Documento fiscal:** borrador → enviado → **autorizado** (con CUFE) | rechazado (con código y mensaje) | **contingencia**
  (pendiente de envío) → autorizado | anulado.

## 9. Reglas de negocio (numeradas, con prueba cada una)
- **RN-01** Dinero en `Decimal`, redondeo **half-up** a 2 decimales. El ITBMS se calcula **por línea** (base × tasa, redondeado)
  y los totales del documento son la **suma de las líneas**; así cuadra con el detalle del XML fiscal.
- **RN-02** Los descuentos reducen la **base gravable** antes del ITBMS.
- **RN-03** Precios, descuentos y totales se **recalculan en el servidor** en cada operación; lo que mande la pantalla es solo
  la intención (producto, cantidad). Montos y cantidades no finitos, negativos o cero → rechazo (422).
- **RN-04** El número de comanda y el número de documento fiscal son **secuencias atómicas** sin huecos ni duplicados, aunque
  dos terminales cobren al mismo tiempo.
- **RN-05** **Idempotencia** en «Enviar pedidos», «EXE/cobrar» y «Emitir factura»: un doble toque o un reintento de red no
  duplica comandas, pagos ni facturas (clave de idempotencia por acción).
- **RN-06** Descuento de **jubilado/pensionado/tercera edad** (Ley 6 de 1987): porcentaje configurable por tipo de
  establecimiento (**25 %** restaurante, **15 %** franquicia de comida rápida, 0 % fonda), sobre el **consumo individual de
  comida** (solo productos marcados «aplica jubilado»), **una persona por cuenta**, con cédula o carné registrado en la cuenta.
  No se combina con otros descuentos en la misma línea. Sale desglosado como **DES-JUB** en la cuenta y en el CAFE.
- **RN-07** Descuentos por porcentaje (DES-PRD) requieren supervisor por encima de un tope configurable (p. ej. 10 %).
- **RN-08** Anular una línea **enviada** requiere autorización de supervisor y motivo; una línea **facturada** solo se revierte
  con nota de crédito.
- **RN-09** Un pago no puede exceder el saldo de la cuenta salvo en efectivo (la diferencia es vuelto). El multipago debe cubrir
  el total **exacto** antes de emitir.
- **RN-10** Crédito solo a clientes con tipo de pago crédito/autorizado, activos y con límite disponible.
- **RN-11** No se factura una cuenta con líneas en PED (sin enviar); el sistema avisa y ofrece enviarlas o borrarlas.
- **RN-12** Una cuenta pagada no admite más líneas; lo nuevo va en una cuenta nueva de la misma mesa.
- **RN-13** El turno solo se cierra con todas las cuentas cobradas o transferidas; la diferencia del arqueo se justifica.
- **RN-14** La salida de inventario ocurre al **enviar** (no al tocar el producto) y se revierte si la línea se anula antes de
  prepararse.
- **RN-15** Un producto agotado no se puede pedir; si se agota con pedidos en PED, se avisa al mesero.

## 10. Impresión y periféricos
- **Comandas de cocina:** al enviar pedidos, una comanda **por área de producción** en su impresora térmica (ESC/POS, 80 mm,
  por red puerto 9100 o USB con la cola de Windows): mesa, mesero, # comanda, hora, cantidad y producto en letra grande, notas,
  acompañamientos, «PARA LLEVAR», y avisos de **ANULACIÓN** cuando corresponda.
- **CAFE / factura y pre-cuenta:** impresora de caja en formato **80 mm** y, opcionalmente, **carta** (sección 11.4).
- **Gaveta de dinero:** pulso ESC/POS por la impresora de caja.
- Cola de impresión con reintentos; si una impresora no responde, avisa en pantalla, guarda el PDF y permite reimprimir.
  Nunca se pierde una comanda: la cola persiste en la BD.
- Diagnóstico en `/dev/impresoras`: página de prueba por impresora.

## 11. Facturación electrónica de Panamá (DGI · SFEP)
> **Importante:** los requisitos fiscales cambian. Implementa contra la **Ficha Técnica de Factura Electrónica vigente de la
> DGI** y la documentación del **PAC** que contrate el restaurante. Donde este prompt y la ficha técnica difieran, **manda la
> ficha técnica**. Deja cada supuesto anotado en `docs/SUPOSICIONES.md` y valida con un contador.

### 11.1 Contexto que el sistema debe respetar
- En Panamá la factura electrónica es el **XML** autorizado dentro del Sistema de Factura Electrónica de Panamá (SFEP). Lo que se
  imprime o se envía en PDF es el **CAFE (Comprobante Auxiliar de Factura Electrónica)**, su representación gráfica.
- Cada factura autorizada tiene un **CUFE** (Código Único de Factura Electrónica) que la identifica y un **código QR** para
  verificarla en la DGI. **El sistema nunca inventa el CUFE ni el QR**: los recibe del PAC al autorizarse el documento.
- Desde el **1 de enero de 2026**, el facturador gratuito de la DGI queda limitado a contribuyentes de bajo volumen
  (ingresos anuales de hasta B/. 36,000 y no más de 100 documentos al mes). Un restaurante con el movimiento de la referencia
  necesita un **PAC** (Proveedor de Autorización Calificado), así que el sistema se integra con un PAC.

### 11.2 Integración con el PAC (adaptador)
- Interfaz `ProveedorFiscal` con métodos: `emitir(documento) → resultado`, `consultar(cufe)`, `anular(cufe, motivo)`,
  `folios_disponibles()`, `estado_servicio()`.
- Implementaciones:
  1. **`PACSimulado`** para demostración y pruebas: genera un identificador de prueba y un QR que apunta a una página local, y
     el CAFE lleva una marca de agua grande **«DOCUMENTO DE PRUEBA — SIN VALIDEZ FISCAL»**. Es el modo por defecto del modo
     demostración y **no puede activarse** fuera de él.
  2. **`PACHttp`** genérico y configurable (URL base, credenciales, ambiente de pruebas/producción, tiempo máximo), preparado
     para mapearse a la API del PAC que se contrate. Documenta en `docs/FISCAL.md` qué se debe completar con la documentación del PAC.
- Credenciales del PAC guardadas con **DPAPI de Windows** (paquete `keyring`), nunca en texto plano ni en la BD ni en el exe.
- El documento se arma desde los datos **congelados** de la cuenta: emisor (razón social, RUC, DV, sucursal, punto de
  facturación, dirección), receptor, ítems (código, descripción, cantidad, precio unitario, descuento, tasa y monto de ITBMS,
  total del ítem), totales por tasa, total, formas de pago y vuelto.
- Se guarda el **XML autorizado**, el CUFE, el protocolo o número de autorización con su fecha y hora, el contenido del QR
  y el PDF del CAFE. Conservación mínima configurable (por defecto, el plazo legal que indique el contador) con respaldo.
- **Contingencia:** si el PAC o internet no responden, la venta **no se detiene**: el documento queda en «contingencia» según
  el procedimiento que establezca la ficha técnica vigente y el PAC, se imprime el comprobante con esa condición indicada y una
  tarea en segundo plano lo reenvía con reintentos exponenciales. Panel de «Documentos pendientes» para el cajero y alerta si un
  documento lleva más de N horas sin autorizarse.
- **Folios:** contador de folios comprados, usados y disponibles (como en la referencia), con alerta al 10 %.

### 11.3 Receptor
- **Consumidor final** por defecto (RUC `00-00-00` o el valor que exija la ficha técnica), con nombre opcional.
- **Contribuyente** (natural o jurídico) con cédula/RUC y **DV** obligatorios; validar formato antes de enviar.
  Si el PAC ofrece consulta de RUC, usarla para autocompletar nombre y DV.
- **Extranjero** con pasaporte.

### 11.4 CAFE en PDF (imprimible) — `reportlab` + `segno`/`qrcode`
Dos formatos: **ticket de 80 mm** (impresora de caja) y **carta** (para enviar por correo o imprimir en oficina). Debe incluir
como mínimo:
- Título «COMPROBANTE AUXILIAR DE FACTURA ELECTRÓNICA» y tipo de documento (factura de operación interna, nota de crédito…).
- **Emisor:** razón social, nombre comercial, RUC y DV, dirección, sucursal y punto de facturación, teléfono.
- **Receptor:** nombre o razón social, cédula/RUC y DV (o «Consumidor final»), dirección si se tiene.
- Número del documento, serie/punto de facturación, **fecha y hora de emisión**, mesa, mesero y # comanda.
- **Detalle:** código, descripción, cantidad, precio unitario, descuento, ITBMS del ítem y total del ítem.
- **Totales:** subtotal, descuentos (desglosando **descuento de jubilado** con la cédula del beneficiario), base gravable e
  **ITBMS por tasa** (exento, 7 %, 10 %, 15 %), **total**, formas de pago con montos, **vuelto**.
- **CUFE** completo, **código QR** (del PAC), **protocolo/número de autorización con fecha y hora**, y la leyenda de consulta
  que indique la DGI/PAC.
- Espacio libre para un mensaje del restaurante.
- En contingencia o prueba, la leyenda correspondiente bien visible.
- Además, PDFs no fiscales: **pre-cuenta** («NO ES FACTURA»), **comanda**, **recibo de abono a crédito**, **corte X/Z**,
  **reporte por sección** y reportes de la sección 13.
- Pruebas que abran cada PDF generado y verifiquen que contiene el CUFE, los totales correctos y que el QR se decodifica.

### 11.5 Notas de crédito y anulación
- Un documento autorizado no se edita. Se corrige con **anulación** (si la ficha técnica lo permite dentro de su plazo) o con
  **nota de crédito electrónica** que referencia el CUFE original, total o parcial, con motivo y autorización de supervisor.
  La nota de crédito también tiene su CAFE.

### 11.6 ITBMS configurable
- Tasa por producto: **exento, 7 % (general), 10 % (bebidas alcohólicas), 15 % (tabaco)**.
- Hay criterios distintos sobre cómo tributan las bebidas alcohólicas servidas en un restaurante; por eso **la tasa de cada
  producto la confirma el contador del restaurante** en el asistente de configuración, y queda registrado quién la cambió y cuándo.
- Configuración del emisor: si es o no contribuyente de ITBMS. Los reportes desglosan bases e impuesto por tasa para preparar
  la declaración mensual.
- Propina o cargo por servicio: **apagado por defecto**; si se activa, es voluntaria, va separada y su tratamiento fiscal lo
  define el contador (dejarlo configurable, no asumir).

## 12. Seguridad (OWASP Top 10 2021 + buenas prácticas de escritorio)
Mismo nivel de rigor que en mis proyectos web, más lo propio de una app de escritorio con datos fiscales y dinero:
- **A01 Control de acceso:** `@publica` o `@rol_requerido` en cada ruta (prueba que lo verifica); un mesero solo opera sus
  mesas (sin IDOR: todas las consultas filtran por dueño o por permiso); las terminales solo ven datos con token de
  dispositivo válido; la pantalla de cocina solo lee su área y solo cambia estados de cocina; redirecciones solo internas.
- **A02 Criptografía:** contraseñas y PIN con **scrypt** (o Argon2id); clave secreta aleatoria por instalación guardada con
  DPAPI; TLS en la red local con CA propia; secretos del PAC en DPAPI; códigos de recuperación 2FA con hash.
- **A03 Inyección:** solo ORM con parámetros; consola de BD del programador **en solo lectura** (`query_only`, autorizador de
  SQLite que oculta columnas sensibles, tiempo máximo); CSV exportados **sin fórmulas** (prefijo para `=`, `+`, `-`, `@`);
  plantillas que escapan todo; **CSP sin JavaScript en línea**; los datos que van a impresoras ESC/POS se limpian de bytes de
  control (que un nombre de cliente no pueda mandar comandos a la impresora o abrir la gaveta).
- **A04 Diseño inseguro:** RN-03, RN-04, RN-05; límites de intentos; totales recalculados; autorización de supervisor
  para operaciones sensibles; cuerpos JSON que no sean objeto → 4xx, nunca 500.
- **A05 Configuración:** cabeceras CSP, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`,
  COOP/CORP; errores genéricos al usuario y detalle solo en la bitácora; **modo demostración apagado** en producción y el
  sistema **se niega a arrancar** si alguna cuenta conserva la clave de prueba (`--nuevas-claves` para cambiarlas); el
  servidor solo escucha en la red local y crea la regla del firewall de Windows **solo para redes privadas**.
- **A06 Componentes:** dependencias mínimas, versiones sin CVE conocidos, fijadas con hash (`pip-compile --generate-hashes`);
  `pip-audit` en el script de compilación; librerías de interfaz locales con SRI.
- **A07 Autenticación:** bloqueo por usuario+terminal y por terminal **antes** del hash; PIN de 6 dígitos con lista de PIN
  triviales prohibidos (000000, 123456…); 2FA TOTP para administración fuera de la demostración; sesiones versionadas
  («cerrar sesión en todas las terminales»); bloqueo por inactividad; expiración máxima de la sesión por rol.
- **A08 Integridad:** CSRF en formularios y API; imágenes del menú **re-codificadas** a WebP sin EXIF y con nombre aleatorio;
  **actualizaciones firmadas** (se verifica la firma o el hash publicado antes de instalar); **bitácora de auditoría encadenada
  con hash** (cada registro incluye el hash del anterior) para anulaciones, descuentos, cobros, cortes y cambios de precio o de
  tasa: si alguien edita la BD a mano, la verificación lo detecta.
- **A09 Registro y monitoreo:** auditoría de accesos, fallos, autorizaciones, anulaciones, descuentos, aperturas de gaveta,
  cambios de configuración, exportaciones y consultas del programador; bitácora rotativa sin caracteres de control; panel de
  eventos de seguridad en `/dev/seguridad`.
- **A10 SSRF:** el servidor solo se conecta a la URL del PAC configurada por el administrador (lista permitida); nunca descarga
  URLs que escriba un usuario.
- **Datos en reposo:** la BD, la clave secreta, los respaldos y las bitácoras viven en `%PROGRAMDATA%\ComandaPOS\` con permisos
  solo para el usuario del servicio y Administradores (no en `Program Files`). **Respaldo automático diario** (copia en caliente
  de SQLite) con rotación, opción de copia a una unidad externa y **restauración probada** desde la consola.
- **Datos personales:** cédula/RUC y correo del cliente solo los ven cajero o superior; nunca se guarda el número completo de
  una tarjeta (solo referencia y últimos 4).
- Documenta todo en `docs/SEGURIDAD.md` con la tabla «Riesgo → Control → Dónde» y la sección «Antes de poner en producción».

## 13. Reportes (pantalla, PDF y CSV)
- Ventas por día, por turno, por mesero, por sección, por producto (ranking), por forma de pago y por sala.
- **ITBMS por tasa** (bases e impuesto) por período, para la declaración mensual.
- **Descuentos de jubilado** con cédula, fecha, cuenta y monto (soporte ante ACODECO).
- **Anulaciones y notas de crédito** con motivo, solicitante y autorizador.
- **Tiempos de cocina** por área y por producto (de ORD a PRE y de PRE a ENT); mesas: ocupación y rotación por hora.
- Cortes X/Z históricos, diferencias de caja por cajero, documentos fiscales en contingencia o rechazados, folios usados.
- Gráficos (Chart.js local): ventas por hora (mapa de calor día × hora), ventas por sección, comparación contra el mismo día de
  la semana anterior.

## 14. Consola del programador (`/dev`)
- Estado del sistema (versión, modo, BD, espacio en disco, último respaldo, terminales conectadas, cola de impresión, estado del
  PAC), usuarios y roles, dispositivos, base de datos en solo lectura con exportación CSV, auditoría con **verificación de la
  cadena de hash**, eventos de seguridad, diagnóstico de impresoras, respaldo y restauración, configuración con secretos ocultos
  (cualquier clave que contenga SECRET, CLAVE, KEY, TOKEN, LLAVE, PASSWORD sale enmascarada).

## 15. Datos de demostración (`seed.py`)
- Restaurante ficticio «Restaurante El Fogón (demo)», David, Chiriquí, con RUC y DV **ficticios**. **No uses** nombres ni RUC de
  empresas o personas reales.
- Sala «Salón» con mesas 1–30, «Servicio rápido» y «Reservado»; áreas de producción **Cocina** y **Frente**.
- Menú panameño realista con precios en B/.: tasajo 3.75, almuerzo completo 5.50 y 8.00, concha a la criolla 8.95, pollo asado,
  chuleta fresca 8.95, bistec picado 8.95, pollo a la plancha 8.95, arroz con pollo 7.25, mondongo 7.95, carne ahumada de cerdo
  8.95, carne frita 8.75, torta 7.50, sopa de costilla grande 3.95, guacho pequeño 4.50; porciones (puré, patacones, tajadas,
  yuca, papas fritas 2.25, plátano en tentación, ensaladas); bebidas (té frío 2.00, batidos 4.50, licuados 3.50, chicha,
  limón y naranja con raspadura 2.00, refresco de nance, soda en lata 1.50, agua 1.00, jugo natural 2.00, sangría 5.50,
  jarra de ponche 18.00); cargos de envase (envase para llevar 0.25, envase de sopa 0.15, cubiertos desechables 0.25).
  Bebidas alcohólicas de ejemplo marcadas para que el contador revise su tasa.
- Acompañamientos: papas salteadas, vegetales hervidos, arroz blanco, sin acompañamiento, arroz con guandú, ensalada verde,
  ensalada blanca, papas fritas.
- Notas fijas: copita de salsa, doble ensalada, encuentro, ensalada sin mayonesa, ensalada verde, las dos ensaladas, muslo,
  muslo encuentro, patitas/alitas y pescuezo, sin cebolla, término medio, bien cocido.
- Operadores de prueba (uno por nivel) con PIN o contraseña de demostración documentados en el README, clientes contribuyentes
  ficticios y un historial de 60 días de ventas, anulaciones, descuentos de jubilado y cortes para que los reportes tengan datos.

## 16. Empaquetado como `.exe` para Windows
- **PyInstaller** en modo **carpeta** (`--onedir`: arranca más rápido y genera menos falsos positivos del antivirus que
  `--onefile`), con ícono propio, información de versión del ejecutable y sin consola en producción.
- **Instalador con Inno Setup** (`ComandaPOS_Setup_1.0.0.exe`): asistente en español, elige el modo (servidor, terminal,
  cocina), crea accesos directos, la carpeta de datos en `%PROGRAMDATA%`, la regla de firewall (solo red privada, solo en modo
  servidor) y, opcionalmente, inicio automático con Windows. Desinstalar **no borra** los datos ni los respaldos.
- Verificación de **WebView2** (instalarlo si falta) y de **una sola instancia** por equipo.
- Ventana a pantalla completa en modo quiosco para meseros y cocina; tecla o gesto protegido por PIN de supervisor para salir.
- Script `build.bat` reproducible: crea el entorno, instala dependencias con hashes, corre `pip-audit` y **todas las pruebas**,
  compila con PyInstaller, arma el instalador y calcula el **SHA-256** de cada archivo entregado. Si una prueba falla, no compila.
- Documenta cómo **firmar el ejecutable** con un certificado de firma de código (recomendado para producción).
- Funciona también sin empaquetar: `iniciar.bat` (doble clic) y `python run.py` para desarrollo.

## 17. Pruebas y aceptación
- `pytest` con pruebas de: cálculos (RN-01 a RN-03 con casos de redondeo en el límite), secuencias atómicas con hilos
  concurrentes (RN-04), idempotencia con doble envío (RN-05), jubilado (porcentajes, una persona por cuenta, solo productos que
  aplican, sin combinar), anulación con y sin autorización, separar cuentas y multipago, crédito con límite, mover y unir mesas,
  turnos y arqueo, inventario por receta, comandas por área, KDS por área, **PDF del CAFE** (contenido, totales, QR legible,
  marca de prueba en simulado), contingencia y reenvío, nota de crédito, IDOR entre meseros, terminal sin token, cada ruta con rol
  declarado, cabeceras de seguridad, CSRF, bloqueo de intentos, saneamiento ESC/POS, CSV sin fórmulas, cadena de auditoría
  (detecta una edición manual), respaldo y restauración.
- **Criterios de aceptación:**
  1. Un mesero abre una mesa, pide 3 productos con notas y acompañamiento y los envía a cocina en **menos de 30 segundos**.
  2. Cada área recibe **solo** sus productos, en pantalla y en papel.
  3. Un doble toque en «EXE» produce **un solo** pago y **una sola** factura.
  4. Con internet caído, se puede seguir cobrando; al volver la conexión, los documentos en contingencia se autorizan solos.
  5. El total del CAFE coincide al centavo con la suma de sus líneas y con lo cobrado, en todos los casos de prueba de redondeo.
  6. Un operador no puede anular, aplicar descuento % ni ver mesas ajenas sin autorización.
  7. Editar la tabla de auditoría a mano es detectado por la verificación de la cadena.
  8. El corte Z cuadra con la suma de los pagos del turno.
  9. El sistema no arranca en producción con contraseñas de prueba.

## 18. Entregables — `ComandaPOS_v1.0.zip`
```
ComandaPOS_v1.0.zip
├── instalador/ComandaPOS_Setup_1.0.0.exe     # instalador para Windows
├── dist/ComandaPOS/                            # versión portable (carpeta de PyInstaller)
├── fuente/                                     # código completo con .git e historial de commits por fase
│   ├── app/ (blueprints, services/, fiscal/, templates/, static/)
│   ├── tests/
│   ├── seed.py · run.py · build.bat · iniciar.bat · iniciar.sh
│   ├── requirements.in · requirements.txt (con hashes)
│   ├── instalador.iss                          # script de Inno Setup
│   └── README.md
├── docs/
│   ├── MANUAL_USUARIO.pdf      # mesero, cajero, cocina, supervisor (con capturas)
│   ├── MANUAL_ADMIN.pdf        # instalación, emparejar terminales, impresoras, PAC, respaldos
│   ├── SEGURIDAD.md · FISCAL.md · SUPOSICIONES.md · PENDIENTES.md
│   └── ejemplos_pdf/           # CAFE 80 mm y carta, pre-cuenta, comanda, corte X y Z (de demostración)
└── SHA256SUMS.txt
```
- El README explica en español: requisitos, instalación en el servidor y en las terminales, cuentas de prueba, cómo pasar a
  producción (sección 12) y cómo conectar el PAC.

## 19. Fases de construcción
1. **Base:** estructura, modelos, `calculos.py` con RN-01 a RN-03, autenticación, roles, auditoría encadenada, seed, pruebas.
2. **Salón:** mapa de mesas, comanda completa, notas, acompañamientos, cuentas separadas, mover mesa, otro mesero, anulaciones.
3. **Cocina e impresión:** áreas de producción, KDS, cola de impresión ESC/POS, comandas y avisos de anulación.
4. **Caja:** cobro, multipago, crédito, jubilado, pre-cuenta, turnos, cortes X/Z, gaveta.
5. **Fiscal:** adaptador PAC (simulado + HTTP), CAFE en PDF 80 mm y carta, contingencia, folios, notas de crédito.
6. **Administración, inventario y reportes.**
7. **Escritorio:** pywebview, modos, emparejamiento con TLS, PyInstaller, Inno Setup, `build.bat`.
8. **Revisión de seguridad independiente** (sin haber escrito el código): hallazgos con severidad, corrección y prueba de regresión
   por cada uno, documentados en `docs/SEGURIDAD.md`. Luego el zip final.
