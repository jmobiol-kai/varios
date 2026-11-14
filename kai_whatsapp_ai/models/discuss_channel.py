import logging

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.kai_whatsapp_ai.models.whatsapp_delete import assert_can_delete

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post_after_hook(self, message, msg_vals):
        result = super()._message_post_after_hook(message, msg_vals)
        try:
            self.env['kai.whatsapp.ai.training']._on_discuss_message(self, message, msg_vals)
        except Exception:
            _logger.exception("WhatsApp AI: trainer chat not stored for channel %s", self.id)
        return result

    def action_om_whatsapp_delete_conversation(self):
        """Remove the conversation in Odoo. The contact, the account and the phone stay."""
        for channel in self:
            if channel.channel_type != 'om_whatsapp':
                raise UserError(_("Only a WhatsApp conversation can be deleted this way."))
            assert_can_delete(self.env, channel.om_whatsapp_account_id)
            partner_id = channel.om_whatsapp_partner_id.id
            account_id = channel.om_whatsapp_account_id.id
            self.env['kai.whatsapp.ai.suggestion'].sudo().search([
                ('channel_id', '=', channel.id),
            ]).unlink()
            self.env['mail.message'].sudo().search([
                ('model', '=', 'discuss.channel'),
                ('res_id', '=', channel.id),
            ]).unlink()
            channel.sudo().unlink()
            if partner_id and not self.env['res.partner'].sudo().browse(partner_id).exists():
                raise UserError(_("The contact stays."))
            if account_id and not self.env['om.whatsapp.account'].sudo().browse(account_id).exists():
                raise UserError(_("The WhatsApp account stays."))
        return True
