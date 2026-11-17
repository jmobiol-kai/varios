from odoo import models
from odoo.addons.mail.tools.discuss import Store

from .time_utils import business_tz


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def _lf_uses_business_clock(self):
        self.ensure_one()
        return bool((self.model or '').startswith('lafija.') or (
            self.model == 'res.partner' and self.res_id
            and self.env['res.partner'].sudo().browse(self.res_id).exists().lf_corporate_account))

    def _to_store_defaults(self, target):
        values = super()._to_store_defaults(target)
        if target.is_internal(self.env):
            values.append(Store.Attr('lfBusinessTimezone',
                value=lambda m: business_tz(m.env),
                predicate=lambda m: m._lf_uses_business_clock()))
        return values
