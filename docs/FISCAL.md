# Facturación electrónica en ComandaPOS

> No soy contador ni abogado: esta guía describe cómo está construido el sistema. Las reglas fiscales concretas
> (tasas, plazos de contingencia, obligación de usar PAC) las confirma el contador del restaurante con la DGI y el PAC.

## 1. Cómo fluye un comprobante
```
Cobrar (EXE) ──► venta guardada (transacción) ──► llamada al PAC (fuera de la transacción)
                                                     │
                     ┌───────────────────────────────┼─────────────────────────────┐
              autorizado                         rechazado                 sin respuesta / sin PAC
     CUFE, protocolo y QR del PAC        mensaje del PAC, «NO ENTREGAR»     «contingencia»: la venta sigue,
     PDF ticket o carta con QR           se corrige y se emite de nuevo      reenvío automático y desde Caja
```
- **El sistema nunca inventa un CUFE.** Solo muestra el que devuelve el PAC.
- La venta **no se detiene** si el PAC o internet fallan: el documento queda en contingencia con su leyenda
  («EMITIDO EN CONTINGENCIA — PENDIENTE DE AUTORIZACIÓN»), y se reenvía al cobrar otras ventas o con
  **Caja → Reenviar al PAC**. Cada intento queda en la auditoría.
- Numeración atómica por punto de facturación: sin duplicados ni huecos aunque cobren varias terminales.

## 2. Documentos
| Tipo | Código | Cuándo |
|---|---|---|
| Factura de operación interna | `01` | Cada cobro. Consumidor final o contribuyente (RUC + DV). |
| Nota de crédito | `04` | Devolución total o parcial de un comprobante **ya autorizado**. Pide motivo (10+ caracteres) y autorización de supervisor; nunca acredita más de lo vendido; la devolución sale de caja en la forma elegida o como crédito del cliente. |

## 3. Proveedores
| Proveedor | Para qué |
|---|---|
| **Simulado** | Solo demostración y pruebas. Documentos con «DOCUMENTO DE PRUEBA — SIN VALIDEZ FISCAL». No se puede elegir en producción. |
| **PAC por HTTP** | Producción. Envía cada documento al PAC contratado. |
| **Ninguno** | Todo queda en contingencia hasta configurar el PAC. |

## 4. Conectar el PAC contratado
`PACHttp` (en `app/services/fiscal.py`) hace `POST` JSON a la URL configurada con `Authorization: Bearer <credencial>`
y espera esta respuesta:
```json
{"estado": "autorizado", "cufe": "FE01…", "protocolo": "…", "qr": "https://…", "mensaje": ""}
```
Cuerpo que envía ComandaPOS:
```json
{"tipo": "01", "numero": 1, "punto": "001", "sucursal": "0000", "fecha": "2026-11-04T21:30:00Z",
 "emisor": {"ruc": "…", "dv": "…", "razon_social": "…", "direccion": "…"},
 "receptor": {"ruc": "00-00-00", "dv": "", "nombre": "CONSUMIDOR FINAL"},
 "items": [{"codigo": 201, "descripcion": "BISTEC PICADO", "acompanamiento": "Arroz con guandú",
            "cantidad": "1", "precio": "8.95", "bruto": "8.95", "descuento": "0.00", "descuento_pct": "0",
            "es_jubilado": false, "base": "8.95", "tasa": 7, "itbms": "0.63", "total": "9.58"}],
 "totales": {"subtotal": "…", "descuento": "…", "itbms": "…", "total": "…"},
 "impuestos": {"7": ["17.20", "1.21"]},
 "pagos": [{"forma": "visa", "monto": "10.00", "recibido": "10.00", "vuelto": "0.00", "referencia": "123456"}],
 "referencia": {"numero": 1, "cufe": "…", "motivo": "…"}}
```
(`referencia` solo en notas de crédito.) Cada PAC tiene su propia API: lo normal es **una función de traducción**
entre este cuerpo y el formato del PAC (o un pequeño servicio intermedio). Pasos:
1. Pide al PAC su documentación técnica y un ambiente de pruebas.
2. Adapta `PACHttp.emitir()` o crea una clase hija que traduzca el cuerpo y la respuesta. No cambies nada más:
   contingencia, reintentos, auditoría, PDF y QR ya funcionan con `ResultadoFiscal`.
3. **Administración → Configuración → Facturación electrónica**: «PAC por HTTP» y la URL `https://`.
4. La credencial: en Windows se guarda en el Administrador de credenciales (pantalla de Configuración);
   si no, variable de entorno `COMANDAPOS_PAC_TOKEN`. **Nunca** en la base de datos.
5. Prueba en el ambiente del PAC: un consumidor final, un contribuyente, una nota de crédito y una caída
   (desconecta el cable) para ver la contingencia y el reenvío.

## 5. Folios
**Configuración → Folios comprados.** La caja muestra disponibles y usados, y alerta cuando queda menos del 10 %.

## 6. ITBMS
Por línea, half-up a 2 decimales; el total es la suma de las líneas (cuadra con el detalle). Tasas 0/7/10/15 % por
producto. **Reportes → ITBMS por tasa** da base e impuesto netos de notas de crédito, para la declaración.
Ver S-01 en `SUPOSICIONES.md` sobre bebidas alcohólicas.

## 7. PDF
- **Ticket 80 mm** (y copia impresa ESC/POS en la impresora de caja).
- **Carta** para quien pide factura a nombre de empresa.
Ambos llevan emisor, receptor, detalle con ITBMS por línea, bases por tasa, formas de pago, vuelto, CUFE y **QR**.
