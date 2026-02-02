# Ejemplos de Mensajes en Chatter

## Funcionalidad de Logging Automático

El módulo registra automáticamente en el chatter (historial de comunicación) dos eventos importantes:

1. **Confirmación de documentos** con tipo de cambio aplicado
2. **Cambio en modo de impresión**

---

## 1. Confirmación de Presupuesto de Venta

### Trigger
- Método: `sale.order.action_confirm()`
- Evento: Usuario presiona botón "Confirmar Presupuesto"

### Mensaje en Chatter

```
✅ Presupuesto Confirmado - Tipo de Cambio Aplicado

┌─────────────────────────────────────────────────────────────┐
│ Moneda del documento:        USD ($)                        │
│ Moneda de la compañía:       ARS ($)                        │
│ Tipo de cambio aplicado:    1 USD = 1050.000000 ARS        │
│ Origen de la tasa:           [MANUAL] o [SISTEMA]          │
│ Total convertido:            100.00 $ = 105,000.00 $        │
└─────────────────────────────────────────────────────────────┘

Este tipo de cambio se aplicará en toda la documentación
generada desde este presupuesto.
```

### Visual
- **Color:** Azul turquesa (#00a09d)
- **Icono:** ✅
- **Badge origen:** Dorado (manual) / Verde (sistema)

---

## 2. Confirmación de Orden de Compra

### Trigger
- Método: `purchase.order.button_confirm()`
- Evento: Usuario presiona botón "Confirmar Orden"

### Mensaje en Chatter

```
✅ Orden de Compra Confirmada - Tipo de Cambio Aplicado

┌─────────────────────────────────────────────────────────────┐
│ Moneda del documento:        USD ($)                        │
│ Moneda de la compañía:       ARS ($)                        │
│ Tipo de cambio aplicado:    1 USD = 1050.000000 ARS        │
│ Origen de la tasa:           [MANUAL]                       │
│ Total convertido:            500.00 $ = 525,000.00 $        │
└─────────────────────────────────────────────────────────────┘

Este tipo de cambio se aplicará en las facturas generadas
desde esta orden de compra.
```

### Visual
- **Color:** Púrpura (#875a7b)
- **Icono:** ✅
- **Badge origen:** Dorado (manual) / Verde (sistema)

---

## 3. Validación de Factura de Cliente

### Trigger
- Método: `account.move.action_post()`
- Evento: Usuario presiona botón "Validar" en factura
- Tipo: `out_invoice`

### Mensaje en Chatter

```
📄 Factura de Cliente Validada - Tipo de Cambio Aplicado

┌─────────────────────────────────────────────────────────────┐
│ Moneda del documento:        USD ($)                        │
│ Moneda de la compañía:       ARS ($)                        │
│ Tipo de cambio aplicado:    1 USD = 1050.000000 ARS        │
│ Origen de la tasa:           [MANUAL]                       │
│ Fecha de referencia:         2026-02-02                     │
│ Total convertido:            100.00 $ = 105,000.00 $        │
└─────────────────────────────────────────────────────────────┘

Esta tasa se ha aplicado en los asientos contables generados.
```

### Visual
- **Color:** Azul turquesa (#00a09d)
- **Icono:** 📄
- **Badge origen:** Dorado (manual) / Verde (sistema)

---

## 4. Validación de Factura de Proveedor

### Trigger
- Método: `account.move.action_post()`
- Tipo: `in_invoice`

### Mensaje en Chatter

```
📥 Factura de Proveedor Validada - Tipo de Cambio Aplicado

┌─────────────────────────────────────────────────────────────┐
│ Moneda del documento:        USD ($)                        │
│ Moneda de la compañía:       ARS ($)                        │
│ Tipo de cambio aplicado:    1 USD = 1050.000000 ARS        │
│ Origen de la tasa:           [MANUAL]                       │
│ Fecha de referencia:         2026-02-02                     │
│ Total convertido:            500.00 $ = 525,000.00 $        │
└─────────────────────────────────────────────────────────────┘

Esta tasa se ha aplicado en los asientos contables generados.
```

### Visual
- **Color:** Púrpura (#875a7b)
- **Icono:** 📥

---

## 5. Validación de Nota de Crédito

### Trigger
- Tipos: `out_refund` / `in_refund`

### Mensaje en Chatter

```
🔄 Nota de Crédito Cliente Validada - Tipo de Cambio Aplicado

[Mismo formato que factura, con icono diferente]
```

### Visual
- **Color:** Rojo (#f06050)
- **Icono:** 🔄 (cliente) / ↩️ (proveedor)

---

## 6. Cambio a Impresión en Moneda Compañía

### Trigger
- Método: `write({'print_in_company_currency': True})`
- Evento: Usuario activa toggle "Imprimir en Moneda Compañía"

### Mensaje en Chatter (Sale Order)

```
🖨️ Modo de Impresión Modificado

Nuevo modo: Moneda de la Compañía (ARS)

Los reportes se imprimirán en ARS, aplicando la tasa
de cambio configurada.
```

### Visual
- **Color:** Púrpura (#875a7b)
- **Icono:** 🖨️
- **Badge:** Azul con nombre de moneda

---

## 7. Cambio a Impresión en Moneda Original

### Trigger
- Método: `write({'print_in_company_currency': False})`
- Evento: Usuario desactiva toggle

### Mensaje en Chatter

```
📄 Modo de Impresión Modificado

Nuevo modo: Moneda Original (USD)

Los reportes se imprimirán en USD, la moneda original
del documento.
```

### Visual
- **Color:** Púrpura (#875a7b)
- **Icono:** 📄

---

## Implementación Técnica

### Métodos Agregados

```python
# En sale.order, purchase.order, account.move

def action_confirm(self):  # o button_confirm() o action_post()
    res = super().action_confirm()
    for record in self:
        if record.currency_id != record.company_id.currency_id:
            record._post_currency_rate_message('confirm')
    return res

def write(self, vals):
    old_print_flags = {rec.id: rec.print_in_company_currency for rec in self}
    res = super().write(vals)

    if 'print_in_company_currency' in vals:
        for record in self:
            old_value = old_print_flags.get(record.id)
            if old_value != record.print_in_company_currency:
                record._post_print_mode_message()

    return res

def _post_currency_rate_message(self, action_type='confirm'):
    """Genera mensaje HTML estético con información de tasa"""
    rate = self._get_effective_rate()
    rate_source = 'manual' if self.manual_currency_rate else 'sistema'

    message = f"""
    <div style="padding: 10px; border-left: 4px solid {color}; ...">
        <h4>{icon} {title} - Tipo de Cambio Aplicado</h4>
        <table>
            <tr><td>Moneda del documento:</td><td>{self.currency_id.name}</td></tr>
            <tr><td>Tipo de cambio:</td><td>1 {cur} = {rate} {company_cur}</td></tr>
            <tr><td>Origen:</td><td><span style="...">{rate_source}</span></td></tr>
            <tr><td>Total:</td><td>{total} = {converted}</td></tr>
        </table>
    </div>
    """

    self.message_post(
        body=message,
        subject='Tipo de Cambio Aplicado',
        message_type='notification',
        subtype_xmlid='mail.mt_note'
    )

def _post_print_mode_message(self):
    """Genera mensaje sobre cambio de modo impresión"""
    # Similar estructura HTML
```

### Características

**Formato HTML Estético:**
- Bordes coloreados según tipo de documento
- Tablas organizadas
- Badges para resaltar origen de tasa
- Iconos emoji para identificación rápida
- Colores corporativos de Odoo

**Información Incluida:**
- Monedas involucradas (documento y compañía)
- Tasa aplicada (con 6 decimales)
- Origen de la tasa (visual con badge)
- Total convertido
- Nota explicativa contextual

**No Intrusivo:**
- `message_type='notification'`
- `subtype_xmlid='mail.mt_note'` (no envía email)
- Solo visible en chatter del documento

---

## Casos de Uso

### Caso 1: Presupuesto USD con Tasa Manual

**Usuario:**
1. Crea presupuesto USD
2. Ingresa `manual_currency_rate: 1050`
3. Presiona "Confirmar Presupuesto"

**Sistema:**
- ✅ Registra en chatter: tasa 1050, origen MANUAL
- Badge dorado indica tasa manual
- Total convertido visible

**Auditoría:**
- Queda trazado qué tasa se usó
- Visible para aprobadores
- Histórico permanente

---

### Caso 2: Cambio de Modo de Impresión

**Usuario:**
1. Tiene presupuesto USD confirmado
2. Cliente pide cotización en ARS
3. Activa toggle "Imprimir en Moneda Compañía"

**Sistema:**
- 🖨️ Registra cambio en chatter
- Indica nuevo modo: ARS
- Explica que reportes usarán conversión

**Beneficio:**
- Trazabilidad de cambios
- Usuario puede volver atrás revisando historial
- Equipo sabe qué versión se imprimió

---

## Ventajas

1. **Auditoría Completa**
   - Todo cambio registrado
   - Timestamp automático
   - Usuario que hizo el cambio

2. **Transparencia**
   - Tasa aplicada visible
   - Origen claro (manual vs sistema)
   - Total convertido calculado

3. **Trazabilidad**
   - Historial inmutable
   - Orden cronológico
   - Buscar en comunicaciones

4. **Sin Emails**
   - Solo visible en chatter
   - No genera spam
   - Acceso bajo demanda

5. **Formato Profesional**
   - Estética consistente
   - Fácil lectura
   - Información estructurada
