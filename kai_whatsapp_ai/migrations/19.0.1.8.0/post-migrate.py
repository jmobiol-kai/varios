# -*- coding: utf-8 -*-
"""Point configs that still name the retired Flash-Lite model at the current one.

Does not turn on customer auto-reply and does not add allowlist numbers.
An empty allowlist keeps every customer on the review path.
"""

OLD_MODEL = "gemini-2.5-flash-lite"
NEW_MODEL = "gemini-3.5-flash-lite"


def migrate(cr, version):
    cr.execute(
        """
        UPDATE kai_whatsapp_ai_config
           SET api_model = %s
         WHERE api_model = %s
        """,
        (NEW_MODEL, OLD_MODEL),
    )
