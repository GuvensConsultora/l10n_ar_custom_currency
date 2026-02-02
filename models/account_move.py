# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Por qué: Mantener tasa manual en factura generada desde orden
    # Patrón: Propagation Pattern - propagar dato del origen
    manual_currency_rate = fields.Float(
        string='Tasa de Cambio Manual',
        digits=(12, 6),
        help='Tasa de cambio manual heredada de la orden de compra/venta.'
    )

    # Por qué: Visibilidad condicional
    show_manual_rate = fields.Boolean(
        compute='_compute_show_manual_rate',
        string='Mostrar Tasa Manual'
    )

    @api.depends('currency_id', 'company_id')
    def _compute_show_manual_rate(self):
        """
        Por qué: Controlar visibilidad en facturas
        Tip: Consistente con órdenes
        """
        for move in self:
            move.show_manual_rate = (
                move.currency_id
                and move.company_id.currency_id
                and move.currency_id != move.company_id.currency_id
            )

    @api.onchange('currency_id')
    def _onchange_currency_id(self):
        """
        Por qué: Limpiar tasa manual si se cambia a moneda de la compañía
        Tip: Evitar inconsistencias
        """
        res = super()._onchange_currency_id()
        if self.currency_id == self.company_id.currency_id:
            self.manual_currency_rate = 0.0
        return res

    # Por qué: Permitir impresión en moneda compañía
    print_in_company_currency = fields.Boolean(
        string='Imprimir en Moneda Compañía',
        default=False,
        help='Si está marcado, el reporte se imprime en la moneda de la compañía.'
    )

    # Por qué: Montos convertidos para reportes
    amount_untaxed_signed_company = fields.Monetary(
        string='Base Imponible (Moneda Compañía)',
        compute='_compute_amounts_company_currency',
        currency_field='company_currency_id'
    )
    amount_tax_signed_company = fields.Monetary(
        string='Impuestos (Moneda Compañía)',
        compute='_compute_amounts_company_currency',
        currency_field='company_currency_id'
    )
    amount_total_signed_company = fields.Monetary(
        string='Total (Moneda Compañía)',
        compute='_compute_amounts_company_currency',
        currency_field='company_currency_id'
    )

    @api.depends('amount_untaxed_signed', 'amount_tax_signed', 'amount_total_signed', 'currency_id', 'manual_currency_rate')
    def _compute_amounts_company_currency(self):
        """
        Por qué: Calcular montos en moneda compañía para facturas
        Tip: Usa campos *_signed para respetar signo (invoice/refund)
        """
        for move in self:
            rate = move._get_effective_rate()

            if move.currency_id == move.company_id.currency_id:
                move.amount_untaxed_signed_company = move.amount_untaxed_signed
                move.amount_tax_signed_company = move.amount_tax_signed
                move.amount_total_signed_company = move.amount_total_signed
            else:
                move.amount_untaxed_signed_company = move.amount_untaxed_signed * rate
                move.amount_tax_signed_company = move.amount_tax_signed * rate
                move.amount_total_signed_company = move.amount_total_signed * rate

    def _get_effective_rate(self):
        """
        Por qué: Obtener tasa efectiva (manual o sistema)
        Tip: Si viene de orden, usa su tasa; sino usa invoice_date
        """
        self.ensure_one()

        if self.manual_currency_rate:
            return self.manual_currency_rate

        return self.currency_id._get_conversion_rate(
            self.currency_id,
            self.company_id.currency_id,
            self.company_id,
            self.invoice_date or fields.Date.today()
        )

    def action_post(self):
        """
        Por qué: Informar tasa de cambio al validar factura
        Patrón: Observer Pattern - notificar validación
        """
        res = super().action_post()

        for move in self:
            if move.currency_id != move.company_id.currency_id:
                move._post_currency_rate_message('post')

        return res

    def write(self, vals):
        """
        Por qué: Detectar cambio en modo de impresión
        """
        old_print_flags = {rec.id: rec.print_in_company_currency for rec in self}

        res = super().write(vals)

        if 'print_in_company_currency' in vals:
            for move in self:
                old_value = old_print_flags.get(move.id)
                if old_value != move.print_in_company_currency:
                    move._post_print_mode_message()

        return res

    def _post_currency_rate_message(self, action_type='post'):
        """
        Por qué: Mensaje en chatter con información de tasa en facturas
        Tip: Diferencia visual según tipo de factura
        """
        self.ensure_one()

        rate = self._get_effective_rate()
        rate_source = 'manual' if self.manual_currency_rate else 'sistema'

        # Por qué: Diferentes iconos y colores según tipo de documento
        if self.move_type == 'out_invoice':
            icon = '📄'
            title = 'Factura de Cliente Validada'
            color = '#00a09d'
            bg_color = '#f0f9ff'
        elif self.move_type == 'in_invoice':
            icon = '📥'
            title = 'Factura de Proveedor Validada'
            color = '#875a7b'
            bg_color = '#fef5ff'
        elif self.move_type == 'out_refund':
            icon = '🔄'
            title = 'Nota de Crédito Cliente Validada'
            color = '#f06050'
            bg_color = '#fff0f0'
        elif self.move_type == 'in_refund':
            icon = '↩️'
            title = 'Nota de Crédito Proveedor Validada'
            color = '#f06050'
            bg_color = '#fff0f0'
        else:
            icon = '📋'
            title = 'Asiento Validado'
            color = '#6c757d'
            bg_color = '#f8f9fa'

        message = f"""
        <div style="padding: 10px; border-left: 4px solid {color}; background-color: {bg_color}; margin: 5px 0;">
            <h4 style="margin: 0 0 10px 0; color: {color};">
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
                <tr style="background-color: {bg_color};">
                    <td style="padding: 5px; font-weight: bold;">Tipo de cambio aplicado:</td>
                    <td style="padding: 5px; font-size: 16px; font-weight: bold; color: {color};">
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
                    <td style="padding: 5px; font-weight: bold;">Fecha de referencia:</td>
                    <td style="padding: 5px;">{self.invoice_date or 'N/A'}</td>
                </tr>
                <tr>
                    <td style="padding: 5px; font-weight: bold;">Total convertido:</td>
                    <td style="padding: 5px;">
                        {abs(self.amount_total_signed):,.2f} {self.currency_id.symbol} =
                        <strong>{abs(self.amount_total_signed) * rate:,.2f} {self.company_id.currency_id.symbol}</strong>
                    </td>
                </tr>
            </table>
            <p style="margin: 10px 0 0 0; font-size: 12px; color: #666; font-style: italic;">
                Esta tasa se ha aplicado en los asientos contables generados.
            </p>
        </div>
        """

        self.message_post(
            body=message,
            subject=f'Tipo de Cambio Aplicado',
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

    def _post_print_mode_message(self):
        """
        Por qué: Notificar cambio en modo de impresión para facturas
        """
        self.ensure_one()

        if self.print_in_company_currency:
            icon = '🖨️'
            mode = f'<strong style="color: #00a09d;">Moneda de la Compañía ({self.company_id.currency_id.name})</strong>'
            explanation = f'El reporte de factura se imprimirá en {self.company_id.currency_id.name}, ' \
                         f'aplicando la tasa de cambio configurada.'
        else:
            icon = '📄'
            mode = f'<strong style="color: #875a7b;">Moneda Original ({self.currency_id.name})</strong>'
            explanation = f'El reporte de factura se imprimirá en {self.currency_id.name}, ' \
                         f'la moneda original del documento.'

        message = f"""
        <div style="padding: 10px; border-left: 4px solid #6c757d; background-color: #f8f9fa; margin: 5px 0;">
            <h4 style="margin: 0 0 10px 0; color: #6c757d;">
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

    def _recompute_dynamic_lines(self, recompute_all_taxes=False, recompute_tax_base_amount=False):
        """
        Por qué: Inyectar tasa manual en recálculo de líneas
        Patrón: Context Injection - pasar parámetros vía contexto
        Tip: Todas las líneas usan la misma tasa manual
        """
        for move in self:
            if move.manual_currency_rate:
                move = move.with_context(
                    manual_currency_rate=move.manual_currency_rate,
                    manual_currency_rate_move_id=move.id
                )

        return super(AccountMove, self)._recompute_dynamic_lines(
            recompute_all_taxes=recompute_all_taxes,
            recompute_tax_base_amount=recompute_tax_base_amount
        )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _get_fields_onchange_balance_model(
        self, quantity, discount, amount_currency, move_type, currency, taxes, price_subtotal, force_computation=False
    ):
        """
        Por qué: Interceptar cálculo de conversión de moneda
        Patrón: Hook Method - punto de extensión del framework
        Tip: Aquí se aplica la tasa manual si existe
        """
        # Obtener tasa manual del contexto si existe
        manual_rate = self._context.get('manual_currency_rate')

        if manual_rate:
            # Forzar tasa manual en contexto para conversión
            self = self.with_context(manual_currency_conversion_rate=manual_rate)

        return super()._get_fields_onchange_balance_model(
            quantity=quantity,
            discount=discount,
            amount_currency=amount_currency,
            move_type=move_type,
            currency=currency,
            taxes=taxes,
            price_subtotal=price_subtotal,
            force_computation=force_computation
        )

    @api.model
    def _get_fields_onchange_subtotal_model(
        self, price_subtotal, move_type, currency, company, date
    ):
        """
        Por qué: Aplicar tasa manual en conversión de subtotal
        Patrón: Template Method - override punto de conversión
        Tip: Interceptar antes de la conversión nativa
        """
        manual_rate = self._context.get('manual_currency_rate')

        if manual_rate:
            self = self.with_context(manual_currency_conversion_rate=manual_rate)

        return super()._get_fields_onchange_subtotal_model(
            price_subtotal=price_subtotal,
            move_type=move_type,
            currency=currency,
            company=company,
            date=date
        )
