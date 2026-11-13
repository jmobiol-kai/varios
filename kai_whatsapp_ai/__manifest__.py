{
    'name': 'WhatsApp AI Suggestions',
    'version': '19.0.1.10.0',
    'category': 'Marketing',
    'summary': 'Supervised reply and draft-quotation suggestions for Odoo Mates WhatsApp',
    'description': """
Suggestions for inbound WhatsApp messages. By default a person reviews the
text and sends it. An automatic reply exists only for numbers on the customer
allowlist, and only when that switch is on. The module does not confirm,
invoice or reserve stock.
    """,
    'author': 'jmobiol-kai',
    'license': 'LGPL-3',
    'depends': ['om_whatsapp_base', 'sale'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'data/ir_cron.xml',
        'data/ai_agent_user.xml',
        'views/ai_config_views.xml',
        'views/ai_training_views.xml',
        'views/ai_suggestion_views.xml',
        'views/ai_usage_views.xml',
        'views/ai_advice_views.xml',
        'views/menu.xml',
        'views/om_whatsapp_account_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kai_whatsapp_ai/static/src/discuss/delete_actions.js',
        ],
    },
    'installable': True,
    'application': False,
}
