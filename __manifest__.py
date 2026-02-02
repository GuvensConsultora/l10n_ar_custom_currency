# -*- coding: utf-8 -*-
{
    'name': 'Argentina - Custom Currency Management',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Personalización del manejo de monedas para Argentina',
    'description': """
        Módulo de personalización del sistema de monedas de Odoo para localización Argentina.

        Funcionalidades:
        - Gestión personalizada de tasas de cambio
        - Automatización de diferencias de cambio
        - Integración con facturación multimoneda
        - Reportes específicos de cambio
    """,
    'author': 'Tu Empresa',
    'website': 'https://www.tuempresa.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'l10n_ar',
    ],
    'data': [
        # 'security/ir.model.access.csv',
        # 'views/res_currency_views.xml',
        # 'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
