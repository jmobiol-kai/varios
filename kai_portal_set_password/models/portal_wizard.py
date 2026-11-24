import logging

from odoo import models
from odoo.tools import str2bool

_logger = logging.getLogger(__name__)

PARAM = 'kai_portal_set_password.disable_portal_invite_email'


class PortalWizardUser(models.TransientModel):
    _inherit = 'portal.wizard.user'

    def _send_email(self):
        """No enviar el correo de invitación del portal si el parámetro está activo."""
        disabled = str2bool(self.env['ir.config_parameter'].sudo().get_param(PARAM, 'True'), True)
        if disabled:
            _logger.info('Portal invitation email skipped (%s) for partners %s', PARAM, self.partner_id.ids)
            return True
        return super()._send_email()
