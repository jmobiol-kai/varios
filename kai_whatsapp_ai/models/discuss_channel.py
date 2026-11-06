import logging

from odoo import models

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
