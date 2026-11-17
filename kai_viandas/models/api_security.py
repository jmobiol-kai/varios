from odoo import models
from odoo.exceptions import AccessDenied
from odoo.http import request


class Users(models.Model):
    _inherit = "res.users"

    def _check_credentials(self, credential, env):
        if self._lf_is_corporate_subject():
            # 'interactive' puede venir de un cliente RPC: no acredita un login web.
            is_login = (request and request.db and request.httprequest.path == "/web/login"
                        and request.httprequest.method == "POST")
            if not is_login:
                raise AccessDenied()
            site_id, corporate = self.env["website"]._lf_host_site(request.httprequest.host)
            if not corporate or not self._lf_can_use_site(self.env["website"].sudo().browse(site_id)):
                raise AccessDenied()
        return super()._check_credentials(credential, env)


class APIKeys(models.Model):
    _inherit = "res.users.apikeys"

    def _generate(self, scope, name, expiration_date):
        if self.env.user._lf_is_corporate_subject():
            raise AccessDenied()
        return super()._generate(scope, name, expiration_date)

    def _check_credentials(self, *, scope, key):
        uid = super()._check_credentials(scope=scope, key=key)
        if uid and self.env["res.users"].sudo().browse(uid)._lf_is_corporate_subject():
            raise AccessDenied()
        return uid
