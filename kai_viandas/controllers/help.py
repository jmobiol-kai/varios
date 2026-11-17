from datetime import timedelta

from odoo import fields, http
from odoo.http import request
from werkzeug.exceptions import NotFound

from .viandas import Viandas


class CorporateHelp(http.Controller):
    @http.route('/my/viandas/ayuda', type='http', auth='user', website=True, methods=['GET'], sitemap=False)
    def employee_help(self, week=None, reservation=None, **kwargs):
        site = Viandas()._site()
        back = '/my/viandas'
        if reservation and str(reservation).isdigit():
            own = request.env['lafija.reservation'].search([('id', '=', int(reservation))], limit=1)
            if own and own.sudo().website_id == site:
                back += '/' + str(own.id)
        elif week:
            try:
                start = fields.Date.to_date(week)
                start -= timedelta(days=start.weekday())
                back += '?week=' + str(start)
            except (ValueError, TypeError, AttributeError):
                pass
        # Nunca aceptar un return_url libre ni consultar una referencia ajena.
        return request.render('kai_viandas.help_employee', {'lf_authenticated': True, 'lf_help_back': back},
                              headers={'Cache-Control': 'private, no-store'})

    @http.route('/viandas/ayuda-acceso', type='http', auth='public', website=True, methods=['GET'], sitemap=False)
    def access_help(self, **kwargs):
        _, corporate = request.env['website']._lf_host_site(request.httprequest.host)
        if not corporate:
            raise NotFound()
        return request.render('kai_viandas.help_access', {'lf_authenticated': False},
                              headers={'Cache-Control': 'private, no-store'})

    @http.route('/viandas/marca/<string:fingerprint>/logo', type='http', auth='public', website=True, methods=['GET'], sitemap=False)
    def logo(self, fingerprint, **kwargs):
        site_id, corporate = request.env['website']._lf_host_site(request.httprequest.host)
        payload = request.env['website'].sudo().browse(site_id)._lf_logo() if corporate else None
        if not payload or payload[2] != fingerprint:
            raise NotFound()
        response = request.make_response(payload[0], headers=[
            ('Content-Type', payload[1]), ('Cache-Control', 'public, max-age=86400, immutable'),
            ('X-Content-Type-Options', 'nosniff'),
            ('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; sandbox"),
        ])
        response.set_etag(payload[2])
        response.make_conditional(request.httprequest)
        return response
