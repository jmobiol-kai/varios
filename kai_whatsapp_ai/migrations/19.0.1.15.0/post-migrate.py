# -*- coding: utf-8 -*-
"""Hide the activity guide and the FAQ from the IA Agent bar. The records stay."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_menu
           SET active = FALSE
         WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'kai_whatsapp_ai'
               AND name IN ('menu_kai_whatsapp_ai_advisory', 'menu_kai_whatsapp_ai_faq')
               AND model = 'ir.ui.menu'
         )
        """
    )
