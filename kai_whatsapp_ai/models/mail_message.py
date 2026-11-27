from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.kai_whatsapp_ai.models.whatsapp_delete import assert_can_delete


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def action_om_whatsapp_delete_in_odoo(self):
        """Drop the WhatsApp message in Odoo. It stays on the customer's phone.

        ``update_content`` refuses a message that is not a comment, so this
        unlinks the row after the same people who may administer the account
        have been checked.
        """
        for message in self:
            if message.message_type != 'om_whatsapp':
                raise UserError(_("Only a WhatsApp message can be deleted this way."))
            assert_can_delete(self.env, message.om_whatsapp_account_id)
        self.sudo().unlink()
        return True
