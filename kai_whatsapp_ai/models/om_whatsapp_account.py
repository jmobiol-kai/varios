import logging

from odoo import models

_logger = logging.getLogger(__name__)


class OmWhatsappAccount(models.Model):
    _inherit = 'om.whatsapp.account'

    def _om_whatsapp_receive(self, number, body='', whatsapp_id=False, attachments=None, quoted_id=False, from_me=False,
                             profile_name=False, voice=False):
        """Keep the upstream message, then optionally file a suggestion.

        A failure here must not roll back the inbound message, and this method
        does not send a reply.
        """
        message = super()._om_whatsapp_receive(
            number, body=body, whatsapp_id=whatsapp_id, attachments=attachments, quoted_id=quoted_id,
            from_me=from_me, profile_name=profile_name, voice=voice)
        try:
            self.env['kai.whatsapp.ai.suggestion']._register_inbound(
                self, message, body, from_me=from_me)
        except Exception:
            _logger.exception("WhatsApp AI: suggestion not stored for account %s", self.id)
        return message
