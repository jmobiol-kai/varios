from odoo import _
from odoo.exceptions import AccessError


def assert_can_delete(env, account):
    """Settings, or a WhatsApp administrator who belongs to the account."""
    user = env.user
    if user.has_group('base.group_system'):
        return
    if not user.has_group('om_whatsapp_base.group_om_whatsapp_manager'):
        raise AccessError(_("Only a WhatsApp administrator can delete this in Odoo."))
    if account and user not in account.user_ids:
        raise AccessError(_("Only a WhatsApp administrator of this account can delete this in Odoo."))
