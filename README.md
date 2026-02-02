# L10n AR Custom Currency - Análisis Técnico Odoo 17.0

## Índice
1. [Funcionamiento Nativo de Monedas en Odoo 17](#funcionamiento-nativo)
2. [Sistema de Tasas de Cambio](#sistema-tasas)
3. [Proceso de Conversión](#proceso-conversion)
4. [Impacto Contable en Facturación](#impacto-contable)
5. [Diferencias de Cambio Automáticas](#diferencias-cambio)
6. [Reconciliación Multi-moneda](#reconciliacion)
7. [Configuración Requerida](#configuracion)

---

## 1. Funcionamiento Nativo de Monedas en Odoo 17 {#funcionamiento-nativo}

### Arquitectura del Sistema

Odoo 17 maneja las monedas a través de tres modelos principales:

```python
# Modelo: res.currency
- name: Código ISO 4217 (ej: USD, ARS, EUR)
- symbol: Símbolo ($, €, etc)
- rounding: Factor de redondeo (default: 0.01)
- rate_ids: One2many a res.currency.rate
- rate: Campo computado (tasa actual)
- inverse_rate: Campo computado (inversa de rate)

# Modelo: res.currency.rate
- name: fields.Date (fecha de la tasa)
- rate: Float (tasa técnica - INVERSA)
- currency_id: Many2one('res.currency')
- company_id: Many2one('res.company')

# Constraint SQL:
CHECK (rate > 0) - La tasa debe ser estrictamente positiva
```

### Por qué usa Tasa Inversa

**Concepto clave:** Odoo almacena la tasa como **1/tasa_real**

**Ejemplo:**
```python
# Tasa real del mercado: 1 USD = 1000 ARS
# Odoo almacena: rate = 0.001 (1/1000)

# Por qué:
# - La moneda de la compañía siempre tiene ratio = 1.0
# - Todas las demás monedas se expresan relativas a ella
# - Facilita cálculos bidireccionales
```

**Código fuente:**
```python
# odoo/addons/base/models/res_currency.py - líneas 145-160
@api.depends('rate_ids.rate')
@api.depends_context('to_currency', 'date', 'company')
def _compute_current_rate(self):
    date = self._context.get('date') or fields.Date.context_today(self)
    company = self.env.company
    to_currency = self.browse(self.env.context.get('to_currency')) or company.currency_id

    currency_rates = (self + to_currency)._get_rates(company, date)

    for currency in self:
        # Cálculo: rate_moneda / rate_moneda_destino
        currency.rate = (currency_rates.get(currency.id) or 1.0) / currency_rates.get(to_currency.id)
        currency.inverse_rate = 1 / currency.rate
```

---

## 2. Sistema de Tasas de Cambio {#sistema-tasas}

### Obtención de Tasa para una Fecha

**Query SQL ejecutada:**
```python
# res_currency.py - método _get_rates (líneas 135-175)
def _get_rates(self, company, date):
    query = """
        SELECT c.id,
               COALESCE(
                   (  -- Primera opción: tasa antes/igual a la fecha
                       SELECT r.rate
                         FROM res_currency_rate r
                        WHERE r.currency_id = c.id
                          AND r.name <= %(date)s
                          AND (r.company_id IS NULL OR r.company_id = %(company_id)s)
                     ORDER BY r.company_id, r.name DESC
                        LIMIT 1
                   ),
                   (  -- Segunda opción: primera tasa disponible
                       SELECT r.rate
                         FROM res_currency_rate r
                        WHERE r.currency_id = c.id
                          AND (r.company_id IS NULL OR r.company_id = %(company_id)s)
                     ORDER BY r.company_id, r.name ASC
                        LIMIT 1
                   ),
                   1.0  -- Fallback: sin tasa definida
               ) AS rate
          FROM res_currency c
         WHERE c.id IN %(currency_ids)s
    """
```

**Lógica de prioridad:**
1. Busca tasa con `date <= fecha_solicitada` (más reciente)
2. Si no existe, toma la primera tasa disponible (histórica futura)
3. Si no hay tasas, usa 1.0
4. Prioriza tasas con `company_id` específica sobre `NULL`

**Por qué:**
- Permite usar la última tasa conocida
- Evita errores si no hay tasa exacta para una fecha
- Soporta multi-compañía

---

## 3. Proceso de Conversión {#proceso-conversion}

### Método de Conversión

```python
# res_currency.py
def _get_conversion_rate(from_currency, to_currency, company, date):
    """
    Calcula la tasa de conversión entre dos monedas

    Por qué: Necesita contexto (fecha, compañía) para obtener la tasa correcta
    Patrón: Template Method - delega en _get_rates para obtener datos
    """
    if from_currency == to_currency:
        return 1  # Optimización: misma moneda

    # Obtiene inverse_rate con contexto
    return from_currency.with_context(
        to_currency=to_currency.id,
        date=str(date)
    ).inverse_rate

# Ejemplo de uso en account.move.line:
amount_in_currency = amount_company_currency * conversion_rate
```

### Conversión en Facturas

```python
# account.move (facturas/asientos)
# Campo: amount_currency vs balance

# Estructura de líneas contables:
{
    'balance': 100.00,           # Siempre en moneda compañía (ARS)
    'amount_currency': 0.10,     # En moneda de la línea (USD)
    'currency_id': USD.id,       # Moneda de la línea
    'company_currency_id': ARS.id  # Moneda de la compañía
}

# Por qué dos campos:
# - balance: para reportes en moneda local (legal)
# - amount_currency: para tracking del monto original (comercial)
# Tip: Siempre usar balance para cálculos contables
```

---

## 4. Impacto Contable en Facturación {#impacto-contable}

### Caso Real: Factura USD cobrada en ARS

**Escenario:**
- Factura: USD $100 a tasa 900 → ARS $90,000
- Pago (45 días después): USD $100 a tasa 1000 → ARS $100,000
- Diferencia: +ARS $10,000 (ganancia por diferencia de cambio)

**Asientos Contables Generados:**

#### A) Emisión de Factura (tasa: 1 USD = 900 ARS)
```python
# account.move (type='out_invoice')
Cuentas por Cobrar (11010201)    90,000 ARS | 100 USD
    Ventas (41010101)                         90,000 ARS | 100 USD

# Por qué se usa la tasa de invoice_date:
# account_move_line.py - get_odoo_rate()
if aml.move_id.is_invoice(include_receipts=True):
    exchange_rate_date = aml.move_id.invoice_date  # ← Tasa de emisión
```

#### B) Registro de Pago (tasa: 1 USD = 1000 ARS)
```python
# account.payment
Banco (11020101)                 100,000 ARS | 100 USD
    Cuenta Tránsito (Outstanding)            100,000 ARS | 100 USD

# Por qué se usa la tasa de payment_date:
exchange_rate_date = counterpart_line.date  # ← Tasa del pago
```

#### C) Diferencia de Cambio (automática al reconciliar)
```python
# account.move (exchange_move_id)
# Generado por: _prepare_exchange_difference_move_vals

Cuentas por Cobrar (11010201)    10,000 ARS | 0 USD
    Ganancia Dif. Cambio (51020201)          10,000 ARS | 0 USD

# Por qué se genera:
# - Residual en USD: 0 (factura pagada completa)
# - Residual en ARS: -10,000 (cobrado de más)
# - Odoo ajusta automáticamente al reconciliar
```

### Flujo de Montos

```
Factura:     100 USD × 900 = 90,000 ARS    [balance en Ctas x Cobrar]
Pago:        100 USD × 1000 = 100,000 ARS  [balance en Banco]
                                  --------
Diferencia:                       +10,000 ARS ← Debe ajustarse
```

---

## 5. Diferencias de Cambio Automáticas {#diferencias-cambio}

### Detección de Diferencias

**Código fuente:**
```python
# account_move_line.py - _prepare_reconciliation_single_partial
# Líneas 2100-2180

def _prepare_reconciliation_single_partial(debit_values, credit_values):
    """
    Por qué: Al reconciliar, verifica si hay diferencias de cambio
    Patrón: Strategy Pattern - diferentes estrategias según monedas
    """

    # 1. Calcula monto a reconciliar en moneda compañía
    partial_amount = min(remaining_debit_amount, remaining_credit_amount)

    # 2. Calcula en monedas originales
    partial_debit_amount_currency = ...
    partial_credit_amount_currency = ...

    # 3. Detecta diferencia de cambio
    if not self._context.get('no_exchange_difference'):
        exchange_lines_to_fix = self.env['account.move.line']
        amounts_list = []

        if debit_fully_matched:
            # Diferencia en moneda compañía
            debit_exchange_amount = remaining_debit_amount - partial_amount

            if not company_currency.is_zero(debit_exchange_amount):
                exchange_lines_to_fix += debit_aml
                amounts_list.append({'amount_residual': debit_exchange_amount})

        if exchange_lines_to_fix:
            # Prepara asiento de diferencia
            res['exchange_values'] = exchange_lines_to_fix\
                ._prepare_exchange_difference_move_vals(amounts_list)

    return res
```

### Creación del Asiento de Diferencia

```python
# account_move_line.py - _prepare_exchange_difference_move_vals
# Líneas 1800-1920

def _prepare_exchange_difference_move_vals(self, amounts_list, exchange_date):
    """
    Por qué: Genera el asiento que ajusta las diferencias de cambio
    Patrón: Builder Pattern - construye move_vals paso a paso
    Tip: Siempre usa la fecha mayor entre las líneas reconciliadas
    """

    company = self.company_id
    journal = self._get_exchange_journal(company)

    move_vals = {
        'move_type': 'entry',
        'date': exchange_date,  # max(fecha_factura, fecha_pago)
        'journal_id': journal.id,
        'line_ids': [],
    }

    for line, amounts in zip(self, amounts_list):
        amount_residual = amounts['amount_residual']

        # Determina cuenta de ganancia/pérdida
        if amount_residual > 0.0:
            exchange_account = company.expense_currency_exchange_account_id  # Pérdida
        else:
            exchange_account = company.income_currency_exchange_account_id  # Ganancia

        # Línea 1: Ajuste en cuenta original
        line_vals = [
            {
                'name': 'Currency exchange rate difference',
                'account_id': line.account_id.id,  # Ej: Cuentas x Cobrar
                'debit': -amount_residual if amount_residual < 0.0 else 0.0,
                'credit': amount_residual if amount_residual > 0.0 else 0.0,
                'partner_id': line.partner_id.id,
            },
            # Línea 2: Contrapartida en cuenta de diferencia
            {
                'name': 'Currency exchange rate difference',
                'account_id': exchange_account.id,  # Ganancia/Pérdida
                'debit': amount_residual if amount_residual > 0.0 else 0.0,
                'credit': -amount_residual if amount_residual < 0.0 else 0.0,
                'partner_id': line.partner_id.id,
            },
        ]

        move_vals['line_ids'] += [Command.create(vals) for vals in line_vals]

    return {'move_values': move_vals, 'to_reconcile': to_reconcile}
```

### Tipos de Diferencias

| Tipo | Causa | Cuenta | Ejemplo |
|------|-------|--------|---------|
| **Ganancia** | Tasa subió entre factura y cobro | `income_currency_exchange_account_id` | Venta USD, tasa subió de 900 a 1000 |
| **Pérdida** | Tasa bajó entre factura y cobro | `expense_currency_exchange_account_id` | Venta USD, tasa bajó de 1000 a 900 |

---

## 6. Reconciliación Multi-moneda {#reconciliacion}

### Modelo: account.partial.reconcile

```python
# account_partial_reconcile.py
# Representa la reconciliación parcial/total entre dos líneas

class AccountPartialReconcile(models.Model):
    _name = 'account.partial.reconcile'

    # Líneas reconciliadas
    debit_move_id = fields.Many2one('account.move.line')
    credit_move_id = fields.Many2one('account.move.line')

    # Montos reconciliados
    amount = fields.Monetary(currency_field='company_currency_id')
    debit_amount_currency = fields.Monetary(currency_field='debit_currency_id')
    credit_amount_currency = fields.Monetary(currency_field='credit_currency_id')

    # Asiento de diferencia de cambio generado
    exchange_move_id = fields.Many2one('account.move')

    # Reconciliación completa
    full_reconcile_id = fields.Many2one('account.full.reconcile')
```

### Proceso de Reconciliación

```python
# account_move_line.py - reconcile()
# Flujo completo:

def reconcile(self):
    """
    Por qué: Método principal para reconciliar líneas contables
    Patrón: Facade Pattern - orquesta múltiples operaciones complejas
    Tip: Siempre verificar que las líneas sean de cuentas reconciliables
    """

    # 1. Preparar planes de reconciliación
    plan_list = self._prepare_reconciliation_plans()

    # 2. Procesar cada plan
    for plan in plan_list:
        # 2.1 Preparar partials
        plan_results = self._prepare_reconciliation_plan(plan)

        for results in plan_results:
            partials_values_list.append(results['partial_values'])

            # 2.2 Si hay diferencia de cambio
            if results.get('exchange_values'):
                exchange_diff_values_list.append(results['exchange_values'])

    # 3. Crear partials
    partials = self.env['account.partial.reconcile'].create(partials_values_list)

    # 4. Crear asientos de diferencia de cambio
    exchange_moves = self._create_exchange_difference_moves(exchange_diff_values_list)

    # 5. Vincular exchange_move_id a partials
    for index, exchange_move in enumerate(exchange_moves):
        partials[index].exchange_move_id = exchange_move

    # 6. Crear full reconcile si están completamente reconciliadas
    if is_fully_reconciled(amls):
        self.env['account.full.reconcile'].create({
            'partial_reconcile_ids': [(6, 0, partials.ids)],
            'reconciled_line_ids': [(6, 0, amls.ids)],
        })

    return True
```

### Ejemplo Paso a Paso

**Datos:**
- Factura: Ctas x Cobrar +90,000 ARS / +100 USD
- Pago: Cta Tránsito -100,000 ARS / -100 USD

**Reconciliación:**
```python
# 1. Se llama: invoice_line_ids.reconcile()

# 2. _prepare_reconciliation_single_partial detecta:
remaining_debit_amount = 90,000 ARS
remaining_credit_amount = 100,000 ARS
partial_amount = 90,000 ARS  # min()

remaining_debit_amount_curr = 100 USD
remaining_credit_amount_curr = 100 USD
partial_debit_amount_currency = 100 USD
partial_credit_amount_currency = 100 USD

# 3. Línea débito fully_matched (100 USD reconciliados)
#    Pero queda residual en ARS:
debit_exchange_amount = 0 ARS (fully matched en USD)
# Sin embargo, hay diferencia implícita por tasas

# 4. Detecta: amount_residual = -10,000 ARS en cuenta crédito
exchange_lines_to_fix = credit_line
amounts_list = [{'amount_residual': -10,000}]

# 5. Crea partial:
{
    'amount': 90,000,
    'debit_amount_currency': 100,
    'credit_amount_currency': 100,
    'debit_move_id': factura_line.id,
    'credit_move_id': pago_line.id,
}

# 6. Crea exchange_move:
Cuentas x Cobrar    10,000
    Ganancia Dif       10,000

# 7. Vincula: partial.exchange_move_id = exchange_move

# 8. Crea full_reconcile (todas las líneas en 0)
```

---

## 7. Configuración Requerida {#configuracion}

### Cuentas de Diferencia de Cambio

**Ruta:** Contabilidad > Configuración > Ajustes > Cuentas por Defecto

```python
# res.company
class Company(models.Model):
    # Cuenta de pérdida por diferencia de cambio
    expense_currency_exchange_account_id = fields.Many2one(
        'account.account',
        string='Loss Exchange Rate Account',
        domain="[('account_type', '=', 'expense'), ('deprecated', '=', False)]"
    )

    # Cuenta de ganancia por diferencia de cambio
    income_currency_exchange_account_id = fields.Many2one(
        'account.account',
        string='Gain Exchange Rate Account',
        domain="[('account_type', '=', 'income_other'), ('deprecated', '=', False)]"
    )

    # Diario para asientos de diferencia
    currency_exchange_journal_id = fields.Many2one(
        'account.journal',
        string='Exchange Gain or Loss Journal',
        domain="[('type', '=', 'general')]"
    )
```

### Plan de Cuentas Argentina (Típico)

```
51020101 - Ganancia por Diferencia de Cambio    [income_other]
61020101 - Pérdida por Diferencia de Cambio     [expense]

# Diario recomendado:
EXCH - Diferencias de Cambio [general]
```

### Validaciones del Sistema

```python
# account_move_line.py - _create_exchange_difference_moves
# Líneas 3500-3530

if not journal.company_id.expense_currency_exchange_account_id:
    raise UserError(_(
        "You should configure the 'Loss Exchange Rate Account' in your company settings"
    ))

if not journal.company_id.income_currency_exchange_account_id:
    raise UserError(_(
        "You should configure the 'Gain Exchange Rate Account' in your company settings"
    ))

if not journal:
    raise UserError(_(
        "You have to configure the 'Exchange Gain or Loss Journal' in your company settings"
    ))
```

---

## Diagrama de Flujo Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                    EMISIÓN DE FACTURA USD                       │
├─────────────────────────────────────────────────────────────────┤
│ invoice_date: 2024-01-01                                        │
│ currency_id: USD                                                │
│ Tasa: 1 USD = 900 ARS (rate = 0.001111)                       │
│                                                                 │
│ Asiento:                                                        │
│   Ctas x Cobrar    90,000 ARS / 100 USD                        │
│       Ventas                      90,000 ARS / 100 USD         │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ 45 días después
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     REGISTRO DE PAGO                            │
├─────────────────────────────────────────────────────────────────┤
│ payment_date: 2024-02-15                                        │
│ currency_id: USD                                                │
│ Tasa: 1 USD = 1000 ARS (rate = 0.001)                         │
│                                                                 │
│ Asiento:                                                        │
│   Banco            100,000 ARS / 100 USD                       │
│       Cta Tránsito                  100,000 ARS / 100 USD      │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ Reconciliación automática
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              PROCESO DE RECONCILIACIÓN                          │
├─────────────────────────────────────────────────────────────────┤
│ 1. reconcile() llamado en líneas de Ctas x Cobrar             │
│ 2. _prepare_reconciliation_single_partial()                    │
│    - Detecta: 100 USD reconciliados en ambas líneas            │
│    - Detecta: +10,000 ARS de diferencia                        │
│ 3. _prepare_exchange_difference_move_vals()                    │
│    - Crea vals del asiento de ajuste                           │
│ 4. create(account.partial.reconcile)                           │
│ 5. _create_exchange_difference_moves()                         │
│ 6. Vincula exchange_move_id al partial                         │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│           ASIENTO DIFERENCIA DE CAMBIO (Automático)            │
├─────────────────────────────────────────────────────────────────┤
│ date: 2024-02-15 (max de fechas reconciliadas)                │
│ journal_id: EXCH - Diferencias de Cambio                       │
│                                                                 │
│ Asiento:                                                        │
│   Ctas x Cobrar         10,000 ARS / 0 USD                     │
│       Ganancia Dif. Cambio            10,000 ARS / 0 USD       │
│                                                                 │
│ Vinculado: partial.exchange_move_id = move.id                  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FULL RECONCILE                                │
├─────────────────────────────────────────────────────────────────┤
│ Todas las líneas en 0:                                          │
│   - Ctas x Cobrar: 0 ARS / 0 USD                               │
│   - Cta Tránsito: 0 ARS / 0 USD                                │
│                                                                 │
│ full_reconcile creado con:                                      │
│   - partial_reconcile_ids: [partial.id]                        │
│   - exchange_move_id: exchange_move.id                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Conclusiones Técnicas

### Buenas Prácticas de Odoo

1. **Tasa Inversa**
   - Por qué: Mantiene la moneda de la compañía como referencia (ratio 1.0)
   - Facilita conversiones bidireccionales
   - Evita divisiones por cero

2. **Dos Campos de Monto**
   - `balance`: Siempre en moneda compañía (legal/reportes)
   - `amount_currency`: En moneda original (comercial/tracking)
   - Por qué: Cumplimiento legal + información comercial

3. **Diferencias Automáticas**
   - Se generan al reconciliar, no al pagar
   - Por qué: Hasta la reconciliación no se sabe si hay diferencia
   - Fecha: max(fecha_documento, fecha_pago)

4. **Query Optimizado**
   - Una sola query SQL para obtener todas las tasas
   - Usa COALESCE para fallbacks
   - Por qué: Performance en multi-moneda

### Patrones de Diseño Utilizados

```python
# 1. Template Method Pattern
# _get_conversion_rate → delega en _get_rates
# Por qué: Separar algoritmo de obtención de datos

# 2. Strategy Pattern
# Diferentes estrategias según tipo de reconciliación
# Por qué: Flexibilidad en cálculo de diferencias

# 3. Builder Pattern
# _prepare_exchange_difference_move_vals construye move_vals
# Por qué: Construcción compleja paso a paso

# 4. Facade Pattern
# reconcile() orquesta múltiples operaciones
# Por qué: Simplifica interfaz compleja
```

### Alternativas No Implementadas

```python
# Odoo NO implementa:
# 1. Diferencias de cambio en cada línea de factura
#    Por qué: Solo al reconciliar se conoce la diferencia real

# 2. Re-valorización automática de saldos
#    Por qué: Requiere configuración específica por país

# 3. Múltiples tasas por moneda en un día
#    Por qué: Complejidad vs beneficio limitado
```

---

## Referencias

### Archivos Clave del Código Fuente

```bash
# Monedas base
odoo/addons/base/models/res_currency.py          # Líneas 1-300
odoo/addons/base/models/res_currency_rate.py     # Modelo de tasas

# Contabilidad
addons/account/models/account_move.py             # Líneas 1-5000
addons/account/models/account_move_line.py        # Líneas 1800-3600
addons/account/models/account_partial_reconcile.py # Líneas 1-400
addons/account/models/account_payment.py          # Líneas 1-1500

# Métodos críticos:
# - res_currency._get_rates()                      Línea 135
# - res_currency._get_conversion_rate()            Línea 88
# - account_move_line.reconcile()                  Línea 1000
# - account_move_line._prepare_reconciliation_single_partial()  Línea 2100
# - account_move_line._prepare_exchange_difference_move_vals()  Línea 1800
# - account_move_line._create_exchange_difference_moves()       Línea 3500
```

### Issues de GitHub Relacionados

- [#218904](https://github.com/odoo/odoo/issues/218904) - Unable to register payment with currency gain/loss (v17.0)
- [#21888](https://github.com/odoo/odoo/issues/21888) - Payment wrongly generated entries with exchange difference
- [#188372](https://github.com/odoo/odoo/issues/188372) - Amount currency not correct in payment receipt

### Documentación Oficial

- [Multi-currency system - Odoo 17.0](https://www.odoo.com/documentation/17.0/applications/finance/accounting/get_started/multi_currency.html)
- [Manage a bank account in a foreign currency](https://www.odoo.com/documentation/17.0/applications/finance/accounting/bank/foreign_currency.html)

---

## Solución Implementada - Tasa Manual

### Funcionalidad Principal

**Problema:** Odoo nativo usa siempre la última tasa configurada en `res.currency.rate`, sin permitir especificar una tasa diferente por transacción.

**Solución:** Agregar campo `manual_currency_rate` en presupuestos (ventas/compras) y facturas, que permite:
- Cargar tasa manual cuando `currency_id != company_currency_id`
- Aplicar esa tasa en todo el ciclo de vida del documento
- Propagar la tasa desde orden → factura

### Modelos Modificados

#### 1. sale.order (Presupuestos de Venta)

```python
# models/sale_order.py

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Campo principal
    manual_currency_rate = fields.Float('Tasa de Cambio Manual', digits=(12, 6))

    # Por qué: Visibilidad condicional
    show_manual_rate = fields.Boolean(compute='_compute_show_manual_rate')

    @api.depends('currency_id', 'company_id')
    def _compute_show_manual_rate(self):
        # Muestra campo solo si moneda diferente
        order.show_manual_rate = order.currency_id != order.company_id.currency_id

    def _prepare_invoice(self):
        # Propagar tasa manual a factura
        invoice_vals = super()._prepare_invoice()
        if self.manual_currency_rate:
            invoice_vals['manual_currency_rate'] = self.manual_currency_rate
        return invoice_vals

    def _compute_amounts(self):
        # Inyectar tasa en contexto
        if order.manual_currency_rate:
            order = order.with_context(
                manual_currency_rate=order.manual_currency_rate
            )
        return super()._compute_amounts()
```

**Flujo:**
1. Usuario selecciona moneda USD (diferente a ARS)
2. Campo `manual_currency_rate` se vuelve visible
3. Usuario ingresa tasa: 1050.00
4. Al calcular totales, usa tasa 1050 (no la del sistema)
5. Al crear factura, hereda `manual_currency_rate = 1050.00`

#### 2. purchase.order (Órdenes de Compra)

```python
# models/purchase_order.py

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Misma lógica que sale.order
    manual_currency_rate = fields.Float('Tasa de Cambio Manual', digits=(12, 6))
    show_manual_rate = fields.Boolean(compute='_compute_show_manual_rate')

    def _prepare_invoice(self):
        # Propagar a factura de proveedor
        invoice_vals = super()._prepare_invoice()
        if self.manual_currency_rate:
            invoice_vals['manual_currency_rate'] = self.manual_currency_rate
        return invoice_vals
```

**Consistencia:** Mismo comportamiento en compras y ventas

#### 3. account.move (Facturas)

```python
# models/account_move.py

class AccountMove(models.Model):
    _inherit = 'account.move'

    # Heredar tasa de orden o permitir edición manual
    manual_currency_rate = fields.Float('Tasa de Cambio Manual', digits=(12, 6))
    show_manual_rate = fields.Boolean(compute='_compute_show_manual_rate')

    def _recompute_dynamic_lines(self, ...):
        # Inyectar tasa en recálculo de líneas
        if move.manual_currency_rate:
            move = move.with_context(
                manual_currency_rate=move.manual_currency_rate
            )
        return super()._recompute_dynamic_lines(...)
```

**Por qué:** Facturas pueden:
- Heredar tasa de orden de compra/venta
- Tener tasa manual si se crean directamente

#### 4. account.move.line (Líneas de Factura)

```python
# models/account_move.py

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _get_fields_onchange_balance_model(self, ...):
        # Interceptar conversión de moneda
        manual_rate = self._context.get('manual_currency_rate')
        if manual_rate:
            self = self.with_context(
                manual_currency_conversion_rate=manual_rate
            )
        return super()._get_fields_onchange_balance_model(...)
```

**Por qué:** Es en las líneas donde Odoo hace la conversión real de montos

### Vistas XML

#### Sale Order
```xml
<!-- views/sale_order_views.xml -->
<xpath expr="//field[@name='currency_id']" position="after">
    <field name="show_manual_rate" invisible="1"/>
    <field name="manual_currency_rate"
           invisible="not show_manual_rate"
           placeholder="Ingrese tasa manual (ej: 1000.00)"/>
</xpath>
```

**Comportamiento UI:**
- Campo oculto si `currency_id == company_currency_id`
- Visible automáticamente al cambiar moneda
- Placeholder con ejemplo

#### Purchase Order
```xml
<!-- views/purchase_order_views.xml -->
<!-- Misma estructura que sale.order -->
```

#### Account Move
```xml
<!-- views/account_move_views.xml -->
<xpath expr="//field[@name='currency_id']" position="after">
    <field name="manual_currency_rate"
           invisible="not show_manual_rate"
           readonly="state != 'draft'"/>
</xpath>
```

**Diferencia:** Campo readonly si factura confirmada

### Ejemplo Completo de Uso

**Caso: Venta USD con Tasa Manual**

```
1. Crear Presupuesto de Venta
   - Cliente: Cliente Argentina
   - Moneda: USD
   - manual_currency_rate: 1050.00 (visible automáticamente)
   - Producto: Notebook $100 USD

2. Cálculos en Presupuesto
   Subtotal USD: 100.00
   Subtotal ARS: 100.00 × 1050 = 105,000 ARS  ← Usa tasa manual

3. Confirmar Presupuesto → Orden de Venta

4. Crear Factura
   - manual_currency_rate: 1050.00 (heredado)
   - Líneas calculan con tasa 1050

5. Factura Generada
   Ctas x Cobrar    105,000 ARS / 100 USD
       Ventas                   105,000 ARS / 100 USD

   ✓ Usó tasa 1050, no la del sistema (ej: 1000)
```

**Diferencia vs Nativo:**
```python
# Odoo Nativo:
# Busca en res.currency.rate la última tasa disponible
rate = currency._get_rates(company, date)  # → 1000.00

# Con módulo:
# Si existe manual_currency_rate, usa esa
rate = manual_currency_rate or currency._get_rates(company, date)  # → 1050.00
```

### Ventajas de la Solución

1. **No modifica datos nativos**
   - No altera `res.currency.rate`
   - No requiere crear tasas ficticias

2. **Propagación automática**
   - Orden → Factura
   - Mantiene trazabilidad

3. **Flexible**
   - Puede dejarse vacío (usa tasa sistema)
   - O especificarse por transacción

4. **Auditable**
   - Campo visible en todos los documentos
   - Se sabe qué tasa se usó

### Patrones Implementados

```python
# 1. Template Method Pattern
# Override de métodos de cálculo sin cambiar algoritmo base
def _compute_amounts(self):
    if self.manual_currency_rate:
        self = self.with_context(manual_currency_rate=...)
    return super()._compute_amounts()

# 2. Context Injection Pattern
# Pasar parámetros vía contexto en lugar de modificar métodos
self.with_context(manual_currency_rate=1050.00)

# 3. Propagation Pattern
# Heredar valores de documento origen
def _prepare_invoice(self):
    vals = super()._prepare_invoice()
    vals['manual_currency_rate'] = self.manual_currency_rate
    return vals

# 4. Conditional Visibility Pattern
# Mostrar campos según estado
show_manual_rate = compute based on currency_id
```

### Alternativas Descartadas

```python
# Alternativa 1: Crear res.currency.rate temporal
# Por qué NO:
# - Contamina tabla de tasas
# - Puede afectar otros documentos
# - Difícil de limpiar

# Alternativa 2: Modificar _get_conversion_rate
# Por qué NO:
# - Muy invasivo
# - Afecta todo el sistema
# - Dificulta upgrades

# Alternativa 3: Calcular montos manualmente
# Por qué NO:
# - Duplica lógica nativa
# - Propenso a errores
# - No mantiene consistencia con Odoo
```

---

## Impresión en Moneda de la Compañía

### Problema

**Caso:** Presupuesto/Factura en USD, pero necesidad de imprimir en ARS.

**Odoo Nativo:** Solo imprime en la moneda del documento (`currency_id`).

### Solución Implementada

Campo `print_in_company_currency` (boolean) que permite:
- Mantener documento en moneda original (USD)
- Imprimir reporte en moneda compañía (ARS)
- Aplicar tasa manual o del sistema

### Campos Computados Agregados

#### En sale.order y purchase.order

```python
# models/sale_order.py

print_in_company_currency = fields.Boolean('Imprimir en Moneda Compañía')

# Por qué: Campos para mostrar en reportes
amount_untaxed_company = fields.Monetary(
    compute='_compute_amounts_company_currency',
    currency_field='company_currency_id'
)
amount_tax_company = fields.Monetary(
    compute='_compute_amounts_company_currency'
)
amount_total_company = fields.Monetary(
    compute='_compute_amounts_company_currency'
)

@api.depends('amount_untaxed', 'currency_id', 'manual_currency_rate')
def _compute_amounts_company_currency(self):
    for order in self:
        rate = order._get_effective_rate()  # Manual o sistema

        if order.currency_id == order.company_id.currency_id:
            # Sin conversión
            order.amount_untaxed_company = order.amount_untaxed
            ...
        else:
            # Convertir con tasa efectiva
            order.amount_untaxed_company = order.amount_untaxed * rate
            order.amount_tax_company = order.amount_tax * rate
            order.amount_total_company = order.amount_total * rate

def _get_effective_rate(self):
    # Prioridad: manual_currency_rate > tasa sistema
    if self.manual_currency_rate:
        return self.manual_currency_rate

    return self.currency_id._get_conversion_rate(
        self.currency_id,
        self.company_id.currency_id,
        self.company_id,
        self.date_order
    )
```

**Por qué separar en campos:**
- Computed fields actualizan automáticamente
- Disponibles en formulario y reportes
- No modifican montos originales

#### En sale.order.line y purchase.order.line

```python
# models/sale_order_line.py

# Por qué: Necesario para mostrar detalle en reportes
price_unit_company = fields.Monetary(
    compute='_compute_price_company_currency',
    currency_field='company_currency_id'
)
price_subtotal_company = fields.Monetary(
    compute='_compute_price_company_currency'
)

@api.depends('price_unit', 'order_id.manual_currency_rate')
def _compute_price_company_currency(self):
    for line in self:
        rate = line.order_id._get_effective_rate()

        if line.order_id.currency_id == line.company_currency_id:
            line.price_unit_company = line.price_unit
            line.price_subtotal_company = line.price_subtotal
        else:
            line.price_unit_company = line.price_unit * rate
            line.price_subtotal_company = line.price_subtotal * rate
```

**Por qué en líneas:**
- Reportes muestran detalle por producto
- Cada línea necesita su precio convertido

#### En account.move

```python
# models/account_move.py

print_in_company_currency = fields.Boolean('Imprimir en Moneda Compañía')

# Por qué: Usa campos *_signed para respetar tipo (invoice/refund)
amount_untaxed_signed_company = fields.Monetary(
    compute='_compute_amounts_company_currency'
)
amount_tax_signed_company = fields.Monetary(...)
amount_total_signed_company = fields.Monetary(...)

def _get_effective_rate(self):
    # Usa invoice_date en lugar de date_order
    if self.manual_currency_rate:
        return self.manual_currency_rate

    return self.currency_id._get_conversion_rate(
        self.currency_id,
        self.company_id.currency_id,
        self.company_id,
        self.invoice_date or fields.Date.today()
    )
```

**Diferencia con orders:**
- Usa `*_signed` (respeta signo de refunds)
- Fecha de referencia: `invoice_date`

### Reportes QWeb Modificados

#### Estructura de Herencia

```xml
<!-- reports/sale_order_report.xml -->
<template id="report_saleorder_document_inherit"
          inherit_id="sale.report_saleorder_document">

    <!-- 1. Determinar moneda a mostrar -->
    <xpath expr="//t[@t-set='display_discount']" position="before">
        <t t-set="doc_currency"
           t-value="doc.company_currency_id if doc.print_in_company_currency
                    else doc.currency_id"/>
    </xpath>

    <!-- 2. Precio unitario por línea -->
    <xpath expr="//td[@name='td_priceunit']/span" position="replace">
        <span t-if="doc.print_in_company_currency"
              t-field="line.price_unit_company"
              t-options='{"widget": "monetary",
                          "display_currency": doc.company_currency_id}'/>
        <span t-else=""
              t-field="line.price_unit"
              t-options='{"widget": "monetary",
                          "display_currency": doc.currency_id}'/>
    </xpath>

    <!-- 3. Subtotal por línea -->
    <xpath expr="//td[@name='td_subtotal']/span" position="replace">
        <span t-if="doc.print_in_company_currency"
              t-field="line.price_subtotal_company"
              t-options='{"widget": "monetary",
                          "display_currency": doc.company_currency_id}'/>
        <span t-else=""
              t-field="line.price_subtotal"
              t-options='{"widget": "monetary",
                          "display_currency": doc.currency_id}'/>
    </xpath>

    <!-- 4. Totales del documento -->
    <xpath expr="//span[@id='amount_total']" position="replace">
        <span id="amount_total">
            <span t-if="doc.print_in_company_currency"
                  t-field="doc.amount_total_company"
                  t-options='{"widget": "monetary",
                              "display_currency": doc.company_currency_id}'/>
            <span t-else=""
                  t-field="doc.amount_total"
                  t-options='{"widget": "monetary",
                              "display_currency": doc.currency_id}'/>
        </span>
    </xpath>

    <!-- 5. Nota aclaratoria -->
    <xpath expr="//div[@id='informations']" position="after">
        <div t-if="doc.print_in_company_currency and
                   doc.currency_id != doc.company_currency_id"
             class="alert alert-info mt-3">
            <strong>Nota:</strong>
            Montos expresados en
            <span t-field="doc.company_currency_id.name"/>
            <span t-if="doc.manual_currency_rate">
                aplicando tasa manual de
                <span t-field="doc.manual_currency_rate"/>
                por <span t-field="doc.currency_id.name"/>.
            </span>
            <span t-else="">
                aplicando tasa del sistema.
            </span>
        </div>
    </xpath>

</template>
```

**Por qué usar herencia:**
- No reescribir template completo
- Mantener compatibilidad con updates
- Solo modificar elementos específicos

**Patrón aplicado:**
```python
# Patrón: Template Method + Strategy
# - Template: estructura del reporte (nativo)
# - Strategy: selección de moneda según flag
t-value="campo_company if flag else campo_normal"
```

### Ejemplo Completo de Uso

**Caso: Presupuesto USD → Imprimir ARS**

```
1. Crear Presupuesto
   - Moneda: USD
   - manual_currency_rate: 1050
   - Producto: Notebook $100 USD

2. Activar impresión compañía
   - print_in_company_currency: True ✓

3. Vista en formulario
   Tab "Montos en Moneda Compañía":
   - Base Imponible: ARS 105,000
   - Impuestos: ARS 22,050
   - Total: ARS 127,050
   - Tasa aplicada: 1050.00

4. Al imprimir PDF
   Producto         Cant  Precio Unit    Subtotal
   Notebook           1    105,000.00   105,000.00

   Base Imponible:                      105,000.00
   Impuestos (21%):                      22,050.00
   Total:                               127,050.00

   [Nota informativa]
   Montos expresados en ARS aplicando tasa manual
   de 1050.00 por USD.

5. Documento sigue en USD
   - currency_id: USD
   - amount_total: 127.05 USD
   - Cálculos internos usan USD
```

**Diferencia vs Nativo:**
```
Odoo Nativo:
- Documento USD → Imprime USD
- No permite cambiar moneda en reporte

Con Módulo:
- Documento USD → Puede imprimir ARS
- Documento mantiene moneda original
- Conversión solo visual (reportes)
```

### Flujo de Datos

```
                        ┌─────────────────────────┐
                        │   sale.order (USD)      │
                        ├─────────────────────────┤
                        │ currency_id: USD        │
                        │ amount_total: 127.05    │
                        │ manual_currency_rate:   │
                        │   1050.00               │
                        │ print_in_company_curr:  │
                        │   True                  │
                        └─────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
            ┌───────▼──────────┐      ┌──────────▼─────────┐
            │ Campos Nativos   │      │ Campos Computed    │
            ├──────────────────┤      ├────────────────────┤
            │ amount_untaxed   │      │ amount_untaxed_    │
            │   = 105.00 USD   │      │   company          │
            ├──────────────────┤      │   = 105,000 ARS    │
            │ amount_tax       │      ├────────────────────┤
            │   = 22.05 USD    │      │ _get_effective_    │
            ├──────────────────┤      │   rate()           │
            │ amount_total     │      │   → 1050.00        │
            │   = 127.05 USD   │      └────────────────────┘
            └──────────────────┘                │
                    │                            │
                    │                            │
            ┌───────▼────────────────────────────▼────────┐
            │         Reporte QWeb                        │
            ├─────────────────────────────────────────────┤
            │ if print_in_company_currency:               │
            │   mostrar: amount_total_company (105k ARS)  │
            │ else:                                        │
            │   mostrar: amount_total (127.05 USD)        │
            └─────────────────────────────────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │    PDF Generado     │
                        ├─────────────────────┤
                        │ Total: 127,050 ARS  │
                        │                     │
                        │ [Nota: Tasa 1050]   │
                        └─────────────────────┘
```

### Ventajas del Enfoque

1. **Separación de Responsabilidades**
   - Modelo: mantiene moneda original
   - Computed fields: conversión
   - Reportes: visualización

2. **No destructivo**
   - `currency_id` no cambia
   - `amount_total` mantiene valor USD
   - Solo campos *_company agregados

3. **Flexible**
   - Flag activable/desactivable
   - Mismo documento → múltiples impresiones
   - Puede imprimir en ambas monedas

4. **Consistente**
   - Misma tasa en todo el documento
   - Propaga de orden → factura
   - Trazabilidad completa

### Casos de Uso

```python
# Caso 1: Presupuesto cliente Argentina, moneda USD
# - Necesita ver precio en ARS para aprobar
sale_order.print_in_company_currency = True
# Imprime en ARS, mantiene contrato en USD

# Caso 2: Orden de compra importación
# - Proveedor cobra USD
# - Contabilidad necesita ver ARS
purchase_order.print_in_company_currency = True
# Factura proveedor en USD, reporte interno en ARS

# Caso 3: Factura exportación
# - Cliente paga USD
# - Auditoría requiere ver equivalente ARS
invoice.print_in_company_currency = True
# Factura legal USD, reporte auditoría ARS

# Caso 4: Cotización alternativa
# - Mostrar al cliente ambas opciones
# Imprimir 2 veces:
#   - print_in_company_currency = False → USD
#   - print_in_company_currency = True → ARS
```

### Patrones de Diseño

```python
# 1. Decorator Pattern
# Agregar funcionalidad (conversión) sin modificar original
amount_untaxed_company = amount_untaxed * rate

# 2. Strategy Pattern
# Selección de estrategia de display según flag
display_amount = company_amount if flag else original_amount

# 3. Adapter Pattern
# Adaptar montos de una moneda a otra
rate = _get_effective_rate()
adapted_amount = original_amount * rate

# 4. Template Method Pattern (QWeb)
# Template base con puntos de extensión
<span t-if="condition" t-field="field_a"/>
<span t-else="" t-field="field_b"/>
```

---

## Próximas Mejoras

1. **Automatización de Cotizaciones**
   - Integración con APIs de BCRA
   - Actualización automática diaria
   - Tipos de cambio: Oficial, MEP, CCL, Blue

2. **Reportes Específicos**
   - Diferencias de cambio por período
   - Exposición al riesgo cambiario
   - Conciliación de tipos de cambio

3. **Validaciones Adicionales**
   - Alertas de variaciones significativas
   - Límites de diferencias de cambio
   - Auditoría de tasas aplicadas

4. **Configuración por Tipo de Operación**
   - Tasa para ventas vs compras
   - Tasa para cobros vs pagos
   - Tasa específica por cliente/proveedor
