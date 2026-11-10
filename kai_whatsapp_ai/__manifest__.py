{
    'name': 'WhatsApp AI Suggestions',
    'version': '19.0.1.6.0',
    'category': 'Marketing',
    'summary': 'Supervised reply and draft-quotation suggestions for Odoo Mates WhatsApp',
    'description': """
Suggestions for inbound WhatsApp messages. A person reviews the text and,
separately, confirms a draft quotation. The module does not send, confirm,
invoice or reserve stock by itself.
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
    ],
    'installable': True,
    'application': False,
}
