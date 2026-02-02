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

    def button_confirm(self):
        """
        Por qué: Informar tasa de cambio al confirmar orden de compra
        Patrón: Observer Pattern - notificar evento de confirmación
        """
        res = super().button_confirm()

        for order in self:
            if order.currency_id != order.company_id.currency_id:
                order._post_currency_rate_message('confirm')

        return res

    def write(self, vals):
        """
        Por qué: Detectar cambio en modo de impresión
        """
        old_print_flags = {rec.id: rec.print_in_company_currency for rec in self}

        res = super().write(vals)

        if 'print_in_company_currency' in vals:
            for order in self:
                old_value = old_print_flags.get(order.id)
                if old_value != order.print_in_company_currency:
                    order._post_print_mode_message()

        return res

    def _post_currency_rate_message(self, action_type='confirm'):
        """
        Por qué: Mensaje en chatter con información de tasa
        Tip: Mismo formato que sale.order para consistencia
        """
        self.ensure_one()

        rate = self._get_effective_rate()
        rate_source = 'manual' if self.manual_currency_rate else 'sistema'

        if action_type == 'confirm':
            icon = '✅'
            title = 'Orden de Compra Confirmada'
            action_text = 'confirmada'
        else:
            icon = 'ℹ️'
            title = 'Tipo de Cambio'
            action_text = 'registrado'

        message = f"""
        <div style="padding: 10px; border-left: 4px solid #875a7b; background-color: #fef5ff; margin: 5px 0;">
            <h4 style="margin: 0 0 10px 0; color: #875a7b;">
                {icon} {title} - Tipo de Cambio Aplicado
            </h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 5px; font-weight: bold; width: 40%;">Moneda del documento:</td>
                    <td style="padding: 5px;">{self.currency_id.name} ({self.currency_id.symbol})</td>
                </tr>
                <tr>
                    <td style="padding: 5px; font-weight: bold;">Moneda de la compañía:</td>
                    <td style="padding: 5px;">{self.company_id.currency_id.name} ({self.company_id.currency_id.symbol})</td>
                </tr>
                <tr style="background-color: #f5e6ff;">
                    <td style="padding: 5px; font-weight: bold;">Tipo de cambio aplicado:</td>
                    <td style="padding: 5px; font-size: 16px; font-weight: bold; color: #875a7b;">
                        1 {self.currency_id.name} = {rate:,.6f} {self.company_id.currency_id.name}
                    </td>
                </tr>
                <tr>
                    <td style="padding: 5px; font-weight: bold;">Origen de la tasa:</td>
                    <td style="padding: 5px;">
                        <span style="background-color: {'#ffd700' if rate_source == 'manual' else '#90ee90'};
                                     padding: 2px 8px; border-radius: 3px; font-weight: bold;">
                            {rate_source.upper()}
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 5px; font-weight: bold;">Total convertido:</td>
                    <td style="padding: 5px;">
                        {self.amount_total:,.2f} {self.currency_id.symbol} =
                        <strong>{self.amount_total * rate:,.2f} {self.company_id.currency_id.symbol}</strong>
                    </td>
                </tr>
            </table>
            <p style="margin: 10px 0 0 0; font-size: 12px; color: #666; font-style: italic;">
                Este tipo de cambio se aplicará en las facturas generadas desde esta orden de compra.
            </p>
        </div>
        """

        self.message_post(
            body=message,
            subject=f'Tipo de Cambio {action_text.capitalize()}',
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

    def _post_print_mode_message(self):
        """
        Por qué: Notificar cambio en modo de impresión
        """
        self.ensure_one()

        if self.print_in_company_currency:
            icon = '🖨️'
            mode = f'<strong style="color: #875a7b;">Moneda de la Compañía ({self.company_id.currency_id.name})</strong>'
            explanation = f'Los reportes se imprimirán en {self.company_id.currency_id.name}, ' \
                         f'aplicando la tasa de cambio configurada.'
        else:
            icon = '📄'
            mode = f'<strong style="color: #875a7b;">Moneda Original ({self.currency_id.name})</strong>'
            explanation = f'Los reportes se imprimirán en {self.currency_id.name}, ' \
                         f'la moneda original del documento.'

        message = f"""
        <div style="padding: 10px; border-left: 4px solid #875a7b; background-color: #fef5ff; margin: 5px 0;">
            <h4 style="margin: 0 0 10px 0; color: #875a7b;">
                {icon} Modo de Impresión Modificado
            </h4>
            <p style="margin: 5px 0;">
                <strong>Nuevo modo:</strong> {mode}
            </p>
            <p style="margin: 5px 0; font-size: 12px; color: #666; font-style: italic;">
                {explanation}
            </p>
        </div>
        """

        self.message_post(
            body=message,
            subject='Modo de Impresión Modificado',
            message_type='notification',
            subtype_xmlid='mail.mt_note'
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
