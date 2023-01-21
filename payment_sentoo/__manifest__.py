# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': "Payment Provider: Sentoo Payment",
    'version': '16.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'summary': "Sentoo payment provider covering Aruba region.",
    'author': "Mainframe Monkey",
    'website': "https://www.mainframemonkey.com",
    'depends': ['account_payment'],
    'data': [
        'data/payment_cron.xml',
        'views/payment_sentoo_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
        'views/account_move_views.xml',
    ],
    'application': False,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'license': 'LGPL-3',
}
