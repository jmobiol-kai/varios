import logging

from odoo import models
from odoo.tools import str2bool

from .portal_wizard import PARAM

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _notify_security_setting_update(self, subject, content, mail_values=None, **kwargs):
        """No enviar avisos de seguridad (p.ej. "Contraseña cambiada") a usuarios de portal
        cuando el parámetro de 'sin correos' está activo, ni cuando lo pide el asistente."""
        skip_ctx = self.env.context.get('kai_no_security_mail')
        disabled = str2bool(self.env['ir.config_parameter'].sudo().get_param(PARAM, 'True'), True)
        to_skip = self.filtered(lambda u: u.share) if (disabled or skip_ctx) else self.browse()
        if to_skip:
            _logger.info('Security notification "%s" skipped for portal users %s', subject, to_skip.ids)
        rest = self - to_skip
        if rest:
            return super(ResUsers, rest)._notify_security_setting_update(subject, content, mail_values=mail_values, **kwargs)
        return True
