# -*- coding: utf-8 -*-
"""Copy om_whatsapp.inbound_allowlist onto each WhatsApp account that has no receive list.

Does not delete the parameter and does not turn on blocked numbers or auto-reply.
"""
import re

INBOUND_PARAM = "om_whatsapp.inbound_allowlist"


def _e164(number):
    digits = re.sub(r"\D", "", str(number or ""))
    return f"+{digits}" if digits else ""


def inbound_numbers_from_parameter(value):
    parts = re.split(r"[\n,;]+", str(value or ""))
    return sorted({_e164(part) for part in parts if _e164(part)})


def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (INBOUND_PARAM,))
    row = cr.fetchone()
    numbers = inbound_numbers_from_parameter(row[0] if row else "")
    if not numbers:
        return
    cr.execute("SELECT id, company_id FROM om_whatsapp_account")
    for account_id, company_id in cr.fetchall():
        cr.execute(
            "SELECT id FROM kai_whatsapp_ai_inbound WHERE account_id = %s LIMIT 1",
            (account_id,),
        )
        if cr.fetchone():
            continue
        for phone in numbers:
            cr.execute(
                """
                INSERT INTO kai_whatsapp_ai_inbound
                    (account_id, company_id, phone, phone_e164, create_uid, write_uid, create_date, write_date)
                VALUES (%s, %s, %s, %s, 1, 1, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                """,
                (account_id, company_id, phone, phone),
            )
