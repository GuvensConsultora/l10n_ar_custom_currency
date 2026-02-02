# Changelog - l10n_ar_custom_currency

## [1.1.0] - 2026-02-02

### Funcionalidades Agregadas

#### Logging Automático en Chatter

**Confirmación de Documentos:**
- Registro automático en chatter al confirmar presupuestos de venta
- Registro automático al confirmar órdenes de compra
- Registro automático al validar facturas (cliente/proveedor/notas de crédito)
- Información incluida:
  * Monedas involucradas (documento y compañía)
  * Tipo de cambio aplicado (6 decimales)
  * Origen de la tasa (badge visual: manual/sistema)
  * Total convertido
  * Nota explicativa contextual

**Cambio de Modo de Impresión:**
- Registro automático al activar/desactivar `print_in_company_currency`
- Indica modo nuevo (moneda compañía vs moneda original)
- Explica implicaciones del cambio

**Características:**
- Mensajes estéticos con HTML
- Iconos emoji identificativos
- Colores según tipo de documento
- Badges para origen de tasa (dorado=manual, verde=sistema)
- No genera emails (solo visible en chatter)
- Trazabilidad completa y auditable

### Modelos Modificados

**models/sale_order.py**
- `action_confirm()`: override para logging
- `write()`: detectar cambio en print_in_company_currency
- `_post_currency_rate_message()`: generar mensaje HTML estético
- `_post_print_mode_message()`: notificar cambio de modo

**models/purchase_order.py**
- `button_confirm()`: override para logging
- `write()`: detectar cambio en print_in_company_currency
- `_post_currency_rate_message()`: mensaje con color púrpura
- `_post_print_mode_message()`: notificar cambio

**models/account_move.py**
- `action_post()`: override para logging en facturas
- `write()`: detectar cambio en modo impresión
- `_post_currency_rate_message()`: colores según move_type
- `_post_print_mode_message()`: notificar cambio

### Documentación Agregada

**CHATTER_EXAMPLES.md**
- Ejemplos visuales de todos los mensajes
- Triggers de cada evento
- Estructura HTML de mensajes
- Casos de uso completos

---

## [1.0.0] - 2026-02-02

### Funcionalidades Agregadas

#### 1. Tasa de Cambio Manual
- Campo `manual_currency_rate` en presupuestos de venta
- Campo `manual_currency_rate` en órdenes de compra
- Campo `manual_currency_rate` en facturas (heredado)
- Visibilidad condicional (solo si moneda ≠ moneda compañía)
- Propagación automática: orden → factura
- Aplicación en todo el ciclo de vida del documento

#### 2. Impresión en Moneda de la Compañía
- Campo `print_in_company_currency` (boolean toggle)
- Campos computados: `amount_*_company` en orders
- Campos computados: `price_*_company` en lines
- Reportes QWeb heredados:
  * Sale Order Report
  * Purchase Order Report
  * Account Move (Invoice) Report
- Nota aclaratoria en PDFs indicando:
  * Moneda de impresión
  * Tasa aplicada (manual o sistema)
  * Moneda original del documento

### Modelos Modificados

**models/sale_order.py**
- `manual_currency_rate`: tasa manual
- `print_in_company_currency`: flag impresión
- `amount_untaxed_company`, `amount_tax_company`, `amount_total_company`
- `_compute_amounts_company_currency()`: conversión
- `_get_effective_rate()`: tasa efectiva (manual > sistema)

**models/sale_order_line.py**
- `price_unit_company`: precio unitario convertido
- `price_subtotal_company`: subtotal convertido
- `_compute_price_company_currency()`: conversión por línea

**models/purchase_order.py**
- Misma estructura que sale_order

**models/purchase_order_line.py**
- Misma estructura que sale_order_line

**models/account_move.py**
- `amount_untaxed_signed_company`: base imponible convertida
- `amount_tax_signed_company`: impuestos convertidos
- `amount_total_signed_company`: total convertido
- Usa campos `*_signed` para respetar tipo (invoice/refund)

### Vistas Agregadas

**views/sale_order_views.xml**
- Campo `manual_currency_rate` después de `currency_id`
- Toggle `print_in_company_currency`
- Notebook page "Montos en Moneda Compañía"

**views/purchase_order_views.xml**
- Estructura idéntica a sale_order

**views/account_move_views.xml**
- Campos con `readonly="state != 'draft'"`

### Reportes Modificados

**reports/sale_order_report.xml**
- Herencia de `sale.report_saleorder_document`
- XPath para precios unitarios, subtotales, totales
- Nota aclaratoria con tasa aplicada

**reports/purchase_order_report.xml**
- Herencia de `purchase.report_purchaseorder_document`

**reports/account_move_report.xml**
- Herencia de `account.report_invoice_document`

### Patrones Implementados

- **Template Method**: Override de métodos de cálculo
- **Context Injection**: Paso de tasa manual vía contexto
- **Propagation**: Heredar tasa de orden a factura
- **Conditional Visibility**: Mostrar campos según estado
- **Strategy**: Selección de tasa (manual vs sistema)
- **Adapter**: Conversión de montos entre monedas
- **Decorator**: Agregar campos sin modificar originales

### Tecnologías

- Odoo 17.0 Enterprise
- Python 3.10+
- QWeb Templates
- XML Views

### Dependencias

- `base`
- `account`
- `sale_management`
- `purchase`
- `l10n_ar`
