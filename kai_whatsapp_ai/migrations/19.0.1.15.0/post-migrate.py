# -*- coding: utf-8 -*-
"""Hide the activity guide from the IA Agent bar. The records stay."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_menu
           SET active = FALSE
         WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'kai_whatsapp_ai'
               AND name = 'menu_kai_whatsapp_ai_advisory'
               AND model = 'ir.ui.menu'
         )
        """
    )
