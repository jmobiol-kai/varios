# -*- coding: utf-8 -*-
"""Hide Monthly usage from IA Agent > Configuration. The wizard stays."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_menu
           SET active = FALSE
         WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'kai_whatsapp_ai'
               AND name = 'menu_kai_whatsapp_ai_usage_wizard'
               AND model = 'ir.ui.menu'
         )
        """
    )
