# Suposiciones por confirmar

Decisiones tomadas para avanzar sin inventar reglas. Cada una es configurable y debe confirmarla quien corresponda.

| # | Tema | Suposición | Confirma | Dónde se cambia |
|---|---|---|---|---|
| S-01 | ITBMS de bebidas alcohólicas servidas | Todos los productos arrancan en 7 %. Hay criterios distintos (7 % sobre todo el consumo cuando el local vende alcohol, o 10 % sobre las bebidas alcohólicas). Los productos alcohólicos quedan marcados para revisarlos. | Contador del restaurante | Tasa por producto (0/7/10/15) |
| S-02 | Descuento de jubilado | 25 % (restaurante), 15 % (franquicia de comida rápida), 0 % (fonda). Aplica a comida y bebidas no alcohólicas; no a bebidas alcohólicas ni a envases. Una persona por cuenta. | Administración / ACODECO | Configuración → Descuentos y `aplica_jubilado` por producto |
| S-03 | Jubilado + otro descuento en la misma línea | No se combinan: se aplica el **mayor**. | Administración | `calculos.py` (RN-06) |
| S-04 | Redondeo del ITBMS | Por línea, half-up a 2 decimales; el total es la suma de las líneas. | Contador / ficha técnica de la DGI | `calculos.py` (RN-01) |
| S-05 | Hora | Se guarda en UTC y se muestra en hora de Panamá (UTC−5). | — | filtro `fecha` |
| S-06 | PIN | 6 dígitos para operadores y cajeros. | Administración | `ROLES_CON_PIN`, `validar_pin` |
| S-07 | Inactividad | 90 s mesero, 5 min cajero y supervisor, 15 min administración. | Administración | `INACTIVIDAD_SEG` |
| S-08 | Datos del emisor | RUC, DV y razón social de la demostración son ficticios. | Dueño del restaurante | Configuración → Emisor |
| S-09 | API del PAC | Se usa un contrato JSON genérico (`docs/FISCAL.md`); cada PAC necesita su traducción. | PAC contratado | `PACHttp.emitir()` |
| S-10 | Contingencia | El documento en contingencia se entrega con su leyenda y se reenvía automáticamente; el plazo máximo para regularizarlo lo define la DGI/PAC. | Contador / PAC | `fiscal.py` |
| S-11 | Nota de crédito | Solo sobre comprobantes autorizados, por ítems y cantidades, con autorización de supervisor y motivo de 10+ caracteres. | Contador | `caja.nota_credito()` (RN-16) |
| S-12 | Alerta de folios | Cuando quedan menos del 10 % de los folios comprados. | Administración | `fiscal.folios()` |
| S-13 | Diferencia de caja | Más de B/. 1.00 en el corte Z exige justificación. | Administración | `services/caja.py` |
| S-14 | Datos al desinstalar | No se borran (conservación de documentos fiscales). | Contador | `instalador/comandapos.iss` |
| S-15 | Permisos de la carpeta de datos | Solo Administradores, SYSTEM y el grupo local «ComandaPOS» (quien instala queda dentro; se agregan las cuentas del personal). | Quien instala | `instalador/comandapos.iss` |
| S-16 | Comprobante rechazado | Se corrige y se reenvía con el **mismo número**, porque el PAC no lo registró. | PAC contratado | `fiscal.corregir_receptor` |
| S-17 | Inventario insuficiente | Por defecto no se agrega ni se envía a cocina lo que la existencia no cubre (solo productos con control de inventario). | Administración | Configuración → «No enviar pedidos que el inventario no cubre» |
| S-18 | HTTPS en la red | Certificados propios de ComandaPOS (CA local), instalados una vez en cada terminal. | Quien instala | `services/tls.py` |
| S-19 | Cédula de jubilados | Enmascarada en pantalla y CSV; la completa solo para administración. | Administración / ACODECO | `reportes.enmascarar_cedula` |
