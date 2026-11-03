# Suposiciones por confirmar

Decisiones tomadas para avanzar sin inventar reglas. Cada una es configurable y debe confirmarla quien corresponda.

| # | Tema | Suposición | Confirma | Dónde se cambia |
|---|---|---|---|---|
| S-01 | ITBMS de bebidas alcohólicas servidas | Todos los productos arrancan en 7 %. Hay criterios distintos (7 % sobre todo el consumo cuando el local vende alcohol, o 10 % sobre las bebidas alcohólicas). Los productos alcohólicos quedan marcados (`es_alcoholica`) para revisarlos. | Contador del restaurante | Tasa por producto (0/7/10/15) |
| S-02 | Descuento de jubilado | 25 % (restaurante), 15 % (franquicia de comida rápida), 0 % (fonda). Aplica a comida y bebidas no alcohólicas; no a bebidas alcohólicas ni a envases. Una persona por cuenta. | Administración / ACODECO | `descuento.jubilado.*` y `aplica_jubilado` por producto |
| S-03 | Jubilado + otro descuento en la misma línea | No se combinan: se aplica el **mayor** (lo más favorable al cliente). | Administración | `app/services/calculos.py` (RN-06) |
| S-04 | Redondeo del ITBMS | Por línea, half-up a 2 decimales, y el total es la suma de las líneas (así cuadra con el detalle del XML). | Contador / ficha técnica de la DGI | `calculos.py` (RN-01) |
| S-05 | Hora | Se guarda en UTC y se muestra en hora de Panamá (UTC−5, sin horario de verano). | — | filtro `fecha` |
| S-06 | PIN | 6 dígitos para operadores y cajeros (el sistema de referencia usa 4). | Administración | `ROLES_CON_PIN`, `validar_pin` |
| S-07 | Inactividad | 90 s en terminales de mesero, 5 min cajero y supervisor, 15 min administración. | Administración | `INACTIVIDAD_SEG` en `app/config.py` |
| S-08 | Datos del emisor | RUC, DV y razón social de la demostración son ficticios. | Dueño del restaurante | Configuración (fase 6) |
