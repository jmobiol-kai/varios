from odoo import api, http, models, tools
from odoo.http import request
from werkzeug.exceptions import BadRequest, HTTPException, abort
from urllib.parse import urlsplit


def safe_site_url(site, path=''):
    domain = (site.domain or '').rstrip('/')
    parsed = urlsplit(domain)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        return False
    return domain + path


def private_response(message, status=403):
    content_type = 'text/plain; charset=utf-8'
    if request and request.httprequest.method == 'GET':
        public_site = request.env['website'].sudo().search([('lf_corporate_site', '=', False)], limit=1)
        public_url = safe_site_url(public_site) if public_site else False
        uid = request.session.uid
        user = request.env['res.users'].sudo().browse(uid) if uid else request.env['res.users']
        site_id, corporate_site = request.env['website']._lf_host_site(request.httprequest.host)
        own_url = '/my/viandas' if uid and corporate_site and user._lf_can_use_site(request.env['website'].sudo().browse(site_id)) else False
        links = [('/web/session/logout?redirect=/web/login', 'Salir y entrar con otra cuenta')] if uid else [('/web/login', 'Ir al acceso de viandas')]
        if own_url:
            links.insert(0, (own_url, 'Volver a mis viandas'))
        if public_url:
            links.append((public_url, 'Ir al sitio público'))
        # La denegación ocurre antes del predespacho de website. QWeb requiere
        # el sitio resuelto aunque no se llegue a ejecutar la página solicitada.
        request.website = request.env['website'].sudo().browse(site_id)
        message = request.env['ir.qweb']._render('kai_viandas.access_denied', {
            'message': message, 'links': links, 'lf_authenticated': bool(own_url),
            'lf_identity': False,
        })
        content_type = 'text/html; charset=utf-8'
    return http.Response(
        message, status=status, content_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


class Website(models.Model):
    _inherit = "website"

    @api.model
    @tools.ormcache("host")
    def _lf_host_site(self, host):
        site = self.sudo().browse(self.sudo()._get_current_website_id(host))
        return site.id, bool(site.lf_corporate_site)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_bearer(cls):
        result = super()._auth_method_bearer()
        # La autenticación nativa ya comprobó la clave. Conservar al solicitante
        # antes de que un reporte use privilegios; no confiar en un uid del cliente.
        request._lf_bearer_uid = request.env.uid
        return result

    @classmethod
    def _lf_request_scope(cls):
        # Esta lectura precede a _frontend_pre_dispatch: session.context puede
        # contener un idioma del navegador que no existe activo en esta base.
        # Incluso leer un booleano precarga campos traducibles del sitio.
        # El entorno local sin traducción evita usarlo antes de conocer el ámbito.
        env = request.env(context=dict(request.env.context, lang=None))
        website_id, corporate_site = env["website"]._lf_host_site(request.httprequest.host)
        uid = request.session.uid or env.uid
        user = env["res.users"].sudo().browse(uid) if uid else env["res.users"]
        corporate_user = bool(user and user._lf_is_corporate_subject())
        return website_id, corporate_site, user, corporate_user

    @classmethod
    def _lf_normalize_language(cls, site_id):
        """Solo contexto de esta petición corporativa; no sesión ni configuración."""
        env = request.env(context=dict(request.env.context, lang=None))
        active = env['res.lang']._get_active_by('code')
        current = request.env.context.get('lang')
        if current in active:
            return
        matched = getattr(getattr(request, 'lang', None), 'code', None)
        default = env['website'].sudo().browse(site_id).default_lang_id.code
        chosen = next((code for code in (matched, default) if code in active), None)
        chosen = chosen or next(iter(active), None)
        request.update_context(lang=chosen)

    @classmethod
    def _lf_guard(cls, rule=None):
        site_id, corporate_site, user, corporate_user = cls._lf_request_scope()
        if not corporate_site and not corporate_user:
            return  # NO-OP: no sesión/contexto/respuesta modificados en B2C o backend.
        cls._lf_normalize_language(site_id)
        path = rule.rule if rule else request.httprequest.path
        method = request.httprequest.method
        if path == "/web/session/logout" and method == "GET":
            return
        if corporate_user and not corporate_site:
            abort(private_response("Esta cuenta solo puede usarse en el sitio corporativo de La Fija."))
        if corporate_site:
            catalogue = (
                path.startswith("/shop") or path.startswith("/website/search")
                or path.startswith("/web/image") or path.startswith("/web/content")
            )
            if catalogue:
                abort(private_response("Esta página no está disponible aquí. Para elegir o consultar tus viandas, usá Mis viandas."))
            site = request.env["website"].sudo().browse(site_id)
            public_help = path == '/viandas/ayuda-acceso' and method == 'GET'
            brand_logo = path == '/viandas/marca/<string:fingerprint>/logo' and method == 'GET'
            if public_help or brand_logo or (path == "/web/login" and method in ("GET", "POST")):
                request.update_context(lf_corporate_route=True, website_id=site_id)
                request.website = site
                request.session.pop("force_website_id", None)
                return
            if path in ("/web/signup", "/web/reset_password", "/.well-known/change-password", "/my/security"):
                abort(private_response("Para recuperar tu acceso, pedí a tu empresa que contacte a La Fija por el canal acordado."))
            if not corporate_user:
                # Los usuarios internos mantienen el backend, sujeto a sus permisos.
                # Las entradas de catálogo anteriores se rechazan también para ellos.
                if user and user.has_group("base.group_user") and rule and not rule.endpoint.routing.get("website"):
                    return
                if path in ("/", "/my") and method == "GET":
                    abort(request.redirect("/web/login", code=303))
                abort(private_response("Este sitio requiere una cuenta corporativa habilitada por La Fija."))
            if not user._lf_can_use_site(site):
                abort(private_response("Tu acceso necesita una revisión de La Fija. Pedí ayuda a tu empresa por el canal acordado."))
            # La raíz es también la entrada de un marcador con sesión abierta;
            # llega aquí solo después de validar la cuenta y este sitio.
            if path in ("/", "/my", "/my/account") and method == "GET":
                abort(request.redirect("/my/viandas", code=303))
            allowed = {
                ("/my/viandas", "GET"),
                ("/my/viandas/ayuda", "GET"),
                ("/my/viandas/reservar", "POST"),
                ("/my/viandas/<int:reservation_id>", "GET"),
                ("/my/viandas/<int:reservation_id>/correccion", "POST"),
                ("/my/viandas/opcion/<int:product_id>/imagen", "GET"),
            }
            if (path, method) not in allowed:
                abort(private_response("Esta cuenta solo permite consultar y gestionar tus viandas."))
            request.update_context(lf_corporate_route=True, website_id=site_id)
            request.website = site
            request.session.pop("force_website_id", None)

    @classmethod
    def _pre_dispatch(cls, rule, args):
        cls._lf_guard(rule)
        return super()._pre_dispatch(rule, args)

    @classmethod
    def _serve_fallback(cls):
        # Las páginas y adjuntos servidos sin ruta no pasan por _pre_dispatch.
        cls._lf_guard()
        return super()._serve_fallback()

    @classmethod
    def _handle_error(cls, exception):
        site_id, corporate_site, _, corporate_user = cls._lf_request_scope()
        if corporate_site or corporate_user:
            cls._lf_normalize_language(site_id)
            if (corporate_site and request.httprequest.path == '/web/login'
                    and request.httprequest.method == 'POST' and isinstance(exception, BadRequest)
                    and exception.description == 'Session expired (invalid CSRF token)'):
                # El POST fue rechazado por Odoo; no se autentica ni reutiliza la
                # contraseña. Se ofrece un formulario con el token de la sesión actual.
                content = request.render('kai_viandas.corporate_login', {
                    'lf_authenticated': False, 'lf_identity': False,
                    'login': '', 'error': False, 'form_expired': True,
                }, lazy=False)
                return request.make_response(content, status=400,
                    headers=[('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'private, no-store')])
            if isinstance(exception, http.SessionExpiredException):
                # Primero conserva logout/rotación nativos. La explicación no
                # confirma si existió una cuenta ni cuál fue la causa del cierre.
                response = request.dispatcher.handle_error(exception)
                if (corporate_site and request.httprequest.path.startswith('/my/viandas')
                        and response.status_code in (302, 303)):
                    response.headers['Location'] = '/web/login?lf_login_required=1'
                    response.headers['Cache-Control'] = 'private, no-store'
                return response
            if isinstance(exception, HTTPException) and exception.response is not None:
                return exception.response
            status = exception.code if isinstance(exception, HTTPException) else getattr(exception, "http_status", 500)
            return private_response("No se pudo completar la solicitud. Volvé a tus viandas o contactá a La Fija.", status=status)
        return super()._handle_error(exception)
