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

## Próximos Pasos - Customización

Este módulo `l10n_ar_custom_currency` permitirá:

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
