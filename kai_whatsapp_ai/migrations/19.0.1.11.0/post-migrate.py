# -*- coding: utf-8 -*-
"""Name the app IA Agent, grant the cost group by login, and fill empty currencies with ARS."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    from odoo.addons.kai_whatsapp_ai.hooks import post_init_hook

    env = api.Environment(cr, SUPERUSER_ID, {})
    post_init_hook(env)
    cr.execute(
        """
        UPDATE kai_whatsapp_ai_consultation AS consultation
           SET billable_currency_id = currency.id
          FROM res_currency AS currency
         WHERE currency.name = 'ARS'
           AND consultation.billable_currency_id IS NULL
        """
    )
    cr.execute(
        """
        UPDATE kai_whatsapp_ai_consultation
           SET consultation_count = 1
         WHERE consultation_count IS NULL OR consultation_count = 0
        """
    )
