# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Por qué: Mostrar precios unitarios y subtotales en moneda compañía
    # Patrón: Decorator Pattern - agregar campos calculados
    price_unit_company = fields.Monetary(
        string='Precio Unitario (Moneda Compañía)',
        compute='_compute_price_company_currency',
        currency_field='company_currency_id'
    )
    price_subtotal_company = fields.Monetary(
        string='Subtotal (Moneda Compañía)',
        compute='_compute_price_company_currency',
        currency_field='company_currency_id'
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='order_id.company_id.currency_id',
        string='Moneda Compañía'
    )

    @api.depends('price_unit', 'price_subtotal', 'order_id.manual_currency_rate', 'order_id.currency_id')
    def _compute_price_company_currency(self):
        """
        Por qué: Calcular precios en moneda compañía para reportes
        Tip: Usa el método _get_effective_rate del order
        """
        for line in self:
            rate = line.order_id._get_effective_rate()

            if line.order_id.currency_id == line.company_currency_id:
                line.price_unit_company = line.price_unit
                line.price_subtotal_company = line.price_subtotal
            else:
                line.price_unit_company = line.price_unit * rate
                line.price_subtotal_company = line.price_subtotal * rate
