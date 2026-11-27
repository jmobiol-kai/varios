import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.kai_whatsapp_ai.services import engine

_logger = logging.getLogger(__name__)


class OmWhatsappAccount(models.Model):
    _inherit = 'om.whatsapp.account'

    inbound_ids = fields.One2many(
        'kai.whatsapp.ai.inbound', 'account_id', string='Receive only these numbers',
        groups='om_whatsapp_base.group_om_whatsapp_manager',
        help="Empty: inbound chats are kept as usual. With numbers: any other inbound number is dropped "
             "before Odoo creates a conversation or a contact. Messages sent from this phone are still kept.")

    def _kai_inbound_numbers(self):
        self.ensure_one()
        return self.sudo().inbound_ids.mapped('phone_e164')

    def _om_whatsapp_receive(self, number, body='', whatsapp_id=False, attachments=None, quoted_id=False, from_me=False,
                             profile_name=False, voice=False):
        """Drop a non-listed inbound number before the conversation exists, then file a suggestion.

        A failure of the suggestion must not roll back the inbound message, and this method
        does not send a reply.
        """
        if not from_me and not engine.inbound_kept(number, self._kai_inbound_numbers()):
            _logger.info("WhatsApp AI: inbound dropped by the receive list of account %s", self.id)
            return False
        message = super()._om_whatsapp_receive(
            number, body=body, whatsapp_id=whatsapp_id, attachments=attachments, quoted_id=quoted_id,
            from_me=from_me, profile_name=profile_name, voice=voice)
        try:
            self.env['kai.whatsapp.ai.suggestion']._register_inbound(
                self, message, body, from_me=from_me)
        except Exception:
            _logger.exception("WhatsApp AI: suggestion not stored for account %s", self.id)
        return message


class KaiWhatsappAiInbound(models.Model):
    """Numbers this WhatsApp account may store. Not the AI allowlist and not the trainer list."""
    _name = 'kai.whatsapp.ai.inbound'
    _description = 'WhatsApp inbound numbers'
    _order = 'id'

    account_id = fields.Many2one('om.whatsapp.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True, index=True)
    phone = fields.Char(required=True)
    phone_e164 = fields.Char(string='E.164', readonly=True, index=True)

    _inbound_phone_unique = models.UniqueIndex("(account_id, phone_e164) WHERE phone_e164 IS NOT NULL")

    @api.onchange('phone')
    def _onchange_phone(self):
        self.phone_e164 = engine.normalize_e164(self.phone)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['phone_e164'] = engine.normalize_e164(vals.get('phone'))
            if not vals['phone_e164']:
                raise ValidationError(_("The receive list needs a phone number."))
        return super().create(vals_list)

    def write(self, vals):
        if 'phone' in vals:
            vals = dict(vals, phone_e164=engine.normalize_e164(vals.get('phone')))
            if not vals['phone_e164']:
                raise ValidationError(_("The receive list needs a phone number."))
        return super().write(vals)
