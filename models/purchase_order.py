# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Por qué: Permitir tasa de cambio manual en órdenes de compra
    # Patrón: Template Method - mismo patrón que sale.order
    manual_currency_rate = fields.Float(
        string='Tasa de Cambio Manual',
        digits=(12, 6),
        help='Tasa de cambio manual a aplicar. Si se completa, '
             'se usa esta tasa en lugar de la configurada en el sistema.'
    )

    # Por qué: Mostrar la tasa solo cuando la moneda es diferente
    show_manual_rate = fields.Boolean(
        compute='_compute_show_manual_rate',
        string='Mostrar Tasa Manual'
    )

    @api.depends('currency_id', 'company_id')
    def _compute_show_manual_rate(self):
        """
        Por qué: Controlar visibilidad del campo de tasa manual
        Tip: Misma lógica que ventas
        """
        for order in self:
            order.show_manual_rate = (
                order.currency_id
                and order.company_id.currency_id
                and order.currency_id != order.company_id.currency_id
            )

    @api.onchange('currency_id')
    def _onchange_currency_id(self):
        """
        Por qué: Limpiar tasa manual al cambiar moneda
        Tip: Prevenir uso de tasa incorrecta
        """
        if self.currency_id == self.company_id.currency_id:
            self.manual_currency_rate = 0.0

    def _prepare_invoice(self):
        """
        Por qué: Heredar método nativo para pasar tasa manual a factura
        Patrón: Template Method - extender comportamiento base
        Tip: Facturas de proveedor usan misma tasa que orden de compra
        """
        invoice_vals = super()._prepare_invoice()

        # Pasar tasa manual a la factura si existe
        if self.manual_currency_rate:
            invoice_vals['manual_currency_rate'] = self.manual_currency_rate

        return invoice_vals

    # Por qué: Permitir impresión en moneda de la compañía
    print_in_company_currency = fields.Boolean(
        string='Imprimir en Moneda Compañía',
        default=False,
        help='Si está marcado, el reporte se imprime en la moneda de la compañía.'
    )

    # Por qué: Montos convertidos para reportes
    amount_untaxed_company = fields.Monetary(
        string='Base Imponible (Moneda Compañía)',
        compute='_compute_amounts_company_currency',
        currency_field='company_currency_id'
    )
    amount_tax_company = fields.Monetary(
        string='Impuestos (Moneda Compañía)',
        compute='_compute_amounts_company_currency',
        currency_field='company_currency_id'
    )
    amount_total_company = fields.Monetary(
        string='Total (Moneda Compañía)',
        compute='_compute_amounts_company_currency',
        currency_field='company_currency_id'
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Moneda Compañía'
    )

    @api.depends('amount_untaxed', 'amount_tax', 'amount_total', 'currency_id', 'manual_currency_rate')
    def _compute_amounts_company_currency(self):
        """
        Por qué: Calcular montos en moneda de compañía
        Tip: Misma lógica que sale.order
        """
        for order in self:
            rate = order._get_effective_rate()

            if order.currency_id == order.company_id.currency_id:
                order.amount_untaxed_company = order.amount_untaxed
                order.amount_tax_company = order.amount_tax
                order.amount_total_company = order.amount_total
            else:
                order.amount_untaxed_company = order.amount_untaxed * rate
                order.amount_tax_company = order.amount_tax * rate
                order.amount_total_company = order.amount_total * rate

    def _get_effective_rate(self):
        """
        Por qué: Obtener tasa efectiva (manual o sistema)
        Tip: Consistente con sale.order
        """
        self.ensure_one()

        if self.manual_currency_rate:
            return self.manual_currency_rate

        return self.currency_id._get_conversion_rate(
            self.currency_id,
            self.company_id.currency_id,
            self.company_id,
            self.date_order or fields.Date.today()
        )

    @api.depends('order_line.price_subtotal')
    def _compute_amount_all(self):
        """
        Por qué: Override para aplicar tasa manual en cálculos
        Patrón: Strategy Pattern - cambiar estrategia de conversión
        Tip: Inyectar tasa en contexto antes de calcular
        """
        for order in self:
            # Si hay tasa manual, inyectarla en contexto
            if order.manual_currency_rate:
                order = order.with_context(
                    manual_currency_rate=order.manual_currency_rate,
                    manual_currency_rate_order_id=order.id
                )

        # Ejecutar cálculo nativo con contexto modificado
        return super(PurchaseOrder, self)._compute_amount_all()
