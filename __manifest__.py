# -*- coding: utf-8 -*-
{
    'name': 'Argentina - Custom Currency Management',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Personalización del manejo de monedas para Argentina',
    'description': """
        Módulo de personalización del sistema de monedas de Odoo para localización Argentina.

        Funcionalidades:
        - Tasa de cambio manual en presupuestos de venta
        - Tasa de cambio manual en órdenes de compra
        - Propagación de tasa manual a facturas
        - Aplicación en todo el ciclo de vida del documento
    """,
    'author': 'Tu Empresa',
    'website': 'https://www.tuempresa.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'sale_management',
        'purchase',
        'l10n_ar',
    ],
    'data': [
        # 'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/account_move_views.xml',
        'reports/sale_order_report.xml',
        'reports/purchase_order_report.xml',
        'reports/account_move_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
