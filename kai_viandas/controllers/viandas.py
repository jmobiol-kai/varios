import base64
import json
from hmac import compare_digest
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.tools.mimetypes import guess_mimetype
from odoo.tools.misc import hmac
from werkzeug.exceptions import abort

from ..models.ir_http import private_response
from ..models.time_utils import business_today, business_tz, day_label
from ..models.reservation import DAYS_PER_WEEK, SelectionConflict, PastDayConflict


class CorporateLogin(AuthSignupHome):
    def _login_redirect(self, uid, redirect=None):
        user = request.env['res.users'].sudo().browse(uid)
        # Website ya pudo completar /odoo en su rama del controlador. Solo un
        # destino pedido por el visitante prevalece sobre el inicio de La Fija.
        if not request.params.get('redirect') and user.has_group('kai_viandas.group_operator'):
            redirect = '/odoo/action-kai_viandas.orders_action'
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def web_login(self, redirect=None, **kw):
        if request.env.context.get("lf_corporate_route"):
            # Los parámetros existen aquí, después del predespacho HTTP nativo.
            redirect = "/my/viandas"
            request.params["redirect"] = redirect
        response = super().web_login(redirect=redirect, **kw)
        if getattr(response, 'qcontext', None) is not None and not request.env.context.get('lf_corporate_route'):
            from ..models.ir_http import safe_site_url
            site = request.env['website'].sudo().search([('lf_corporate_site', '=', True)], limit=1)
            response.qcontext['lf_corporate_login_url'] = safe_site_url(site, '/web/login') if site else False
            if site and response.qcontext.get('error'):
                response.qcontext['error'] = 'No se pudo iniciar sesión. Revisá tu usuario y contraseña.'
        return response


class Viandas(http.Controller):
    def _form_choices(self, website, choices):
        # Firma solo de presentación: acredita el nombre de la vigente propia
        # que pudo dejar de estar en el menú. Nunca autoriza a reservarla.
        body = base64.urlsafe_b64encode(json.dumps(
            [request.env.uid, website.id, choices], ensure_ascii=False).encode()).decode()
        signature = hmac(request.env(su=True), 'lafija.form.choices', body)
        return body + '.' + signature

    def _read_form_choices(self, website, token):
        if not token or len(token) > 65536:
            return {}
        try:
            body, signature = token.rsplit('.', 1)
            expected = hmac(request.env(su=True), 'lafija.form.choices', body)
            if not compare_digest(signature, expected):
                return {}
            uid, site_id, choices = json.loads(base64.urlsafe_b64decode(body))
            return choices if uid == request.env.uid and site_id == website.id and isinstance(choices, dict) else {}
        except (ValueError, TypeError, UnicodeError):
            return {}

    def _draft_key(self, website, week):
        return f'{request.env.uid}:{website.id}:{week}'

    def _discard_draft(self, website, week):
        drafts = dict(request.session.get('lf_week_drafts', {}))
        drafts.pop(self._draft_key(website, week), None)
        request.session['lf_week_drafts'] = drafts


    def _choice_from_draft(self, raw):
        if isinstance(raw, dict):
            return int(raw.get('product') or 0), int(raw.get('dessert') or 0), int(raw.get('drink') or 0)
        return int(raw or 0), 0, 0

    def _group_options(self, products, snapshot, retained, past):
        options = []
        for product in products.filtered(lambda p: p.active and p.sale_ok):
            item = (snapshot or {}).get(str(product.id))
            if item:
                options.append({"id": product.id, "name": item["description"], "description": item["description"],
                                "image": bool(product.image_1024)})
        for product, description in retained:
            if not product:
                continue
            option = next((o for o in options if o['id'] == product.id), None)
            if option:
                option.update(name=description, description=description)
            else:
                options.insert(0, {'id': product.id, 'name': description,
                                   'description': description, 'image': False})
        if past:
            allowed = {product.id for product, _description in retained if product}
            options = [o for o in options if o['id'] in allowed]
        return options

    def _restore_draft(self, website, values):
        draft = request.session.get('lf_week_drafts', {}).get(self._draft_key(website, values['week']))
        if not draft:
            return values
        values['has_draft'] = True
        values['error'] = ('No se guardó ningún día de este envío. Conservamos tus elecciones como borrador. '
                           'Revisá el día señalado y volvé a guardar.')
        first_conflict = None
        for day in values['days']:
            key = str(day['id'])
            if key not in draft['selections']:
                continue
            choice, dessert, drink = self._choice_from_draft(draft['selections'][key])
            option = next((o for o in day['options'] if o['id'] == choice), None)
            day['conflict'] = day['id'] in draft['conflicts']
            day['conflict_message'] = (
                'Este día ya pasó mientras elegías. Dejalo sin cambios y guardá los demás días; para corregirlo, escribile a La Fija.'
                if draft.get('past_conflicts', {}).get(key) else
                'La Fija cambió esta vianda mientras elegías. Revisala y volvé a guardar.')
            day['unavailable'] = bool(choice and not option) or (not choice and bool(day['selected_id']))
            if day['unavailable']:
                previous = draft['labels'].get(key)
                name = (previous[1] if previous and previous[0] == choice else
                        previous[2].get(str(choice), 'Tu elección anterior') if previous and len(previous) > 2
                        else 'Tu elección anterior')
                option = {'id': choice, 'name': name, 'description': name, 'image': False, 'unavailable': True}
                day['options'].insert(0, option)
                day['conflict'] = True
            day['initial_id'] = choice
            day['initial_dessert_id'] = dessert
            day['initial_drink_id'] = drink
            day['show_options'] = day['show_options'] or day['conflict']
            day['dirty'] = (choice != (day['selected_id'] or 0)
                            or dessert != (day['selected_dessert_id'] or 0)
                            or drink != (day['selected_drink_id'] or 0)
                            or day['conflict'])
            if day['dirty']:
                from ..models.reservation import choice_label
                name = option['name'] if option else 'No reservar este día'
                label = choice_label(name if choice else '', next((o['name'] for o in day['desserts'] if o['id'] == dessert), '') if dessert else '',
                                     next((o['name'] for o in day['drinks'] if o['id'] == drink), '') if drink else '')
                current = day['reservation']['current_label'] if day['reservation'] else day['reservation'] and day['reservation']['current']
                annulling = bool(day['pending_id'] or day['pending_dessert_id'] or day['pending_drink_id']) and (
                    choice == day['current_id'] and dessert == day['current_dessert_id'] and drink == day['current_drink_id'])
                day['draft_text'] = (f"Sin guardar: anular el cambio pedido. Sigue {day['reservation']['current_label'] or day['reservation']['current']}."
                                     if annulling else f'Sin guardar: {label or name}')
            if day['conflict'] and first_conflict is None:
                first_conflict = day['id']
        if first_conflict is not None:
            for day in values['days']:
                day['open'] = day['id'] == first_conflict
        values['draft_count'] = sum(day['dirty'] for day in values['days'])
        return values

    def _site(self):
        site_id, corporate = request.env["website"]._lf_host_site(request.httprequest.host)
        site = request.env["website"].sudo().browse(site_id)
        if not corporate or not request.env.user._lf_can_use_site(site):
            abort(private_response("Esta página requiere una cuenta corporativa habilitada."))
        return site

    def _page_values(self, website, week=None):
        # Una fecha de referencia por respuesta, también al cruzar medianoche.
        today = business_today(request.env)
        Menu = request.env["lafija.menu.day"].sudo()
        if week:
            start = fields.Date.to_date(week)
        else:
            scope = [("website_id", "=", website.id), ("published", "=", True), ("date", ">=", today)]
            moment = fields.Datetime.now()
            candidates = Menu.search(scope + [('cut_ids', '=', False)])
            first = candidates.filtered(lambda m: m._employee_window_open(moment) and any(
                str(p.id) in (m.option_snapshot or {}) for p in m.product_ids if p.active and p.sale_ok))[:1]
            # La ventana de pedido orienta el aterrizaje; se puede consultar
            # una semana explícita aunque ya esté cerrada. Si ya no hay días
            # abiertos, se conserva acceso a lo publicado y a la historia.
            first = first or Menu.search(scope, limit=1)
            start = first.date or today
        start -= timedelta(days=start.weekday())
        own = request.env["lafija.reservation"].search([
            ('date', '>=', start), ('date', '<', start + timedelta(days=7))], order='date, id')
        menus = Menu.search([("website_id", "=", website.id), ("published", "=", True),
                             ("date", ">=", start), ("date", "<", start + timedelta(days=7))])
        days = []
        empty = request.env['product.product']
        for menu in menus:
            reservation = own.sudo().filtered(lambda r: r.menu_id == menu)[:1]
            current = reservation.current_product_id if reservation.state == 'active' else empty
            current_dessert = reservation.current_dessert_id if reservation.state == 'active' else empty
            current_drink = reservation.current_drink_id if reservation.state == 'active' else empty
            pending = reservation.pending_product_id if reservation else empty
            pending_dessert = reservation.pending_dessert_id if reservation else empty
            pending_drink = reservation.pending_drink_id if reservation else empty
            selected = pending or current
            selected_dessert = pending_dessert if (pending or pending_dessert or pending_drink) else current_dessert
            selected_drink = pending_drink if (pending or pending_dessert or pending_drink) else current_drink
            past = menu.date < today
            window_closed = not menu._employee_window_open()
            window_message = menu._employee_window_message() if window_closed else ""
            options = self._group_options(menu.product_ids, menu.option_snapshot, (
                (current, reservation.current_description),
                (pending, reservation.pending_description),
            ), past)
            desserts = self._group_options(menu.dessert_ids, menu.dessert_snapshot, (
                (current_dessert, reservation.current_dessert_description),
                (pending_dessert, reservation.pending_dessert_description),
            ), past)
            drinks = self._group_options(menu.drink_ids, menu.drink_snapshot, (
                (current_drink, reservation.current_drink_description),
                (pending_drink, reservation.pending_drink_description),
            ), past)
            offered = {str(o['id']): o['name'] for o in options}
            days.append({"id": menu.id, "date": str(menu.date), "date_label": day_label(menu.date), "options": options,
                         "desserts": desserts, "drinks": drinks,
                         "reservation": reservation.with_user(request.env.user)._employee_values() if reservation else False,
                         "after_cut": bool(menu.cut_ids),
                         "current_id": current.id,
                         "current_dessert_id": current_dessert.id,
                         "current_drink_id": current_drink.id,
                         "pending_id": pending.id,
                         "pending_dessert_id": pending_dessert.id,
                         "pending_drink_id": pending_drink.id,
                         "past": past, "window_closed": window_closed,
                         "window_message": window_message, "offered": offered,
                         "offered_desserts": {str(o['id']): o['name'] for o in desserts},
                         "offered_drinks": {str(o['id']): o['name'] for o in drinks},
                         "show_options": not window_closed})
            days[-1]['selected_id'] = selected.id
            days[-1]['selected_dessert_id'] = selected_dessert.id
            days[-1]['selected_drink_id'] = selected_drink.id
            days[-1].update(initial_id=selected.id, initial_dessert_id=selected_dessert.id,
                            initial_drink_id=selected_drink.id, dirty=False, conflict=False,
                            unavailable=False, draft_text='', conflict_message='')
        open_ids = set(request.session.pop('lf_open_menu_ids', [])) & {d['id'] for d in days}
        preferred = next((d['id'] for d in days if d['id'] in open_ids), None)
        if not preferred:
            preferred = next((d['id'] for d in days if not d.get('window_closed')), None)
        for day in days:
            day['open'] = day['id'] == preferred
        partner = request.env.user.sudo().partner_id
        return {"lf_authenticated": True, "lf_identity": f'{partner.name} · {partner.lf_customer_company_id.name}',
                'has_draft': False, 'draft_count': 0,
                'form_choices': self._form_choices(website, {
                    str(d['id']): [d['current_id'], d['reservation']['current'] if d['reservation'] else '',
                                   d['offered'], d['date'], not d.get('window_closed'),
                                   d['current_dessert_id'], d['current_drink_id'],
                                   d['offered_desserts'], d['offered_drinks']]
                    for d in days}),
                "week": str(start), "week_label": f'{start:%d/%m} al {start + timedelta(days=6):%d/%m/%Y}',
                "timezone": business_tz(request.env), "days": days,
                "past_week": start + timedelta(days=7) <= today,
                "this_week": str(today - timedelta(days=today.weekday())),
                "previous_week": str(start - timedelta(days=7)), "next_week": str(start + timedelta(days=7)),
                "reservations": [r._employee_values() for r in own],
                "orphan_reservations": [r._employee_values() for r in own if r.sudo().menu_id not in menus]}

    @http.route("/my/viandas", type="http", auth="user", website=True, methods=["GET"])
    def index(self, week=None, discard_draft=None, **kwargs):
        site = self._site()
        try:
            values = self._page_values(site, week)
        except (ValueError, TypeError):
            values = self._page_values(site)
            values["error"] = "La fecha indicada no es válida."
        if discard_draft:
            self._discard_draft(site, values['week'])
            return request.redirect('/my/viandas?week=' + values['week'], code=303)
        self._restore_draft(site, values)
        values['feedback'] = request.session.pop('lf_feedback', [])
        return request.render("kai_viandas.week", values, headers={"Cache-Control": "private, no-store"})

    @http.route("/my/viandas/reservar", type="http", auth="user", website=True, methods=["POST"])
    def reserve(self, **post):
        site = self._site()
        submitted = {}
        desserts = {}
        drinks = {}
        selections = []
        withdraw_current = {}
        try:
            def posted(prefix):
                entries = [(int(key[len(prefix):]), int(value) if value else 0)
                           for key, value in post.items() if key.startswith(prefix)]
                mapping = dict(entries)
                if len(entries) != len(mapping):
                    raise ValidationError('Elegí los días sin repetirlos, hasta una semana por envío.')
                return mapping
            submitted = posted('menu_')
            if len(submitted) > DAYS_PER_WEEK:
                raise ValidationError('Elegí los días sin repetirlos, hasta una semana por envío.')
            desserts = posted('dessert_')
            drinks = posted('drink_')
            selections = [(menu, choice, desserts.get(menu, 0), drinks.get(menu, 0))
                          for menu, choice in submitted.items() if choice]
            withdraw_plates = {int(key[9:]): int(value) for key, value in post.items()
                               if key.startswith("withdraw_") and not key.startswith("withdraw_dessert_")
                               and not key.startswith("withdraw_drink_") and value}
            withdraw_desserts = posted('withdraw_dessert_')
            withdraw_drinks = posted('withdraw_drink_')
            withdraw_current = {menu: (plate, withdraw_desserts.get(menu, 0), withdraw_drinks.get(menu, 0))
                                for menu, plate in withdraw_plates.items()}
            with request.env.cr.savepoint():
                service = request.env["lafija.reservation"]
                before = service._last_events_for_submission(site, selections)
                records = service._submit_selections(site, selections, withdraw_current=withdraw_current) if selections else service
                changed = records.filtered(lambda r: r.sudo().event_ids[-1:].id != before.get(r.id))
                feedback = []
                for record in changed:
                    payload = record._employee_values()
                    if record.sudo().event_ids[-1:].kind == 'withdrawal':
                        feedback.append(f"{payload['date_label']}: anulaste el cambio pedido. Sigue vigente {payload.get('current_label') or payload['current']}.")
                        continue
                    received = 'cambio recibido' if payload['current'] else 'reserva recibida'
                    feedback.append(f"{payload['date_label']}: {received} para revisión; todavía no se aplicó."
                                    if payload['pending'] else f"{payload['date_label']}: elección guardada · {payload.get('current_label') or payload['current']}.")
                request.session['lf_feedback'] = feedback or ['No hiciste cambios. Tus reservas y solicitudes se mantienen.']
                request.session['lf_open_menu_ids'] = (changed.sudo().menu_id.ids if changed else
                    [int(v) for v in str(post.get('open_days', '')).split(',') if v.isdigit()][:7])
        except (AccessError, ValidationError, ValueError, TypeError) as error:
            try:
                values = self._page_values(site, post.get("week"))
            except (ValueError, TypeError):
                values = self._page_values(site)
            if isinstance(error, SelectionConflict):
                labels = self._read_form_choices(site, post.get('form_choices'))
                days = {d['id']: d for d in values['days']}
                conflicts = []
                past_conflicts = {}
                valid = error.menu_id in days
                for menu, choice in submitted.items():
                    day = days.get(menu)
                    if not day:
                        valid = False
                        break
                    dessert = desserts.get(menu, 0)
                    drink = drinks.get(menu, 0)
                    submitted_triple = (choice, dessert, drink)
                    current_triple = (day['current_id'], day['current_dessert_id'], day['current_drink_id'])
                    selected_triple = (day['selected_id'] or 0, day['selected_dessert_id'] or 0, day['selected_drink_id'] or 0)
                    previous = labels.get(str(menu))
                    withdrawn = withdraw_current.get(menu)
                    stale = (previous and previous[0] == choice and withdrawn in (choice, submitted_triple)
                             and current_triple != submitted_triple)
                    expired = (isinstance(error, PastDayConflict) and day['past'] and previous
                               and len(previous) >= 5 and previous[4] is True
                               and previous[3] == day['date'] and str(choice) in previous[2]
                               and submitted_triple != selected_triple)
                    if stale:
                        conflicts.append(menu)
                    if expired:
                        conflicts.append(menu)
                        past_conflicts[str(menu)] = True
                    allowed = choice in [o['id'] for o in day['options']] or (not choice and not day['selected_id'])
                    allowed = allowed and (not dessert or dessert in [o['id'] for o in day['desserts']])
                    allowed = allowed and (not drink or drink in [o['id'] for o in day['drinks']])
                    if not allowed and not stale and not expired:
                        valid = False
                if valid and error.menu_id in conflicts:
                    drafts = dict(request.session.get('lf_week_drafts', {}))
                    drafts[self._draft_key(site, values['week'])] = {
                        'selections': {str(k): {'product': v, 'dessert': desserts.get(k, 0), 'drink': drinks.get(k, 0)}
                                       for k, v in submitted.items()},
                        'labels': labels, 'conflicts': conflicts, 'past_conflicts': past_conflicts,
                    }
                    request.session['lf_week_drafts'] = drafts
                    # POST → GET también en el conflicto: Recargar/Atrás nunca
                    # repiten la escritura. El GET recompone estado y borrador.
                    return request.redirect('/my/viandas?week=' + values['week'], code=303)
            self._restore_draft(site, values)
            values["error"] = str(error) if isinstance(error, ValidationError) else "No se pudo guardar esa selección."
            return request.render("kai_viandas.week", values, status=400, headers={"Cache-Control": "private, no-store"})
        try:
            week = fields.Date.to_date(post.get('week'))
        except (ValueError, TypeError):
            week = None
        if week:
            self._discard_draft(site, str(week - timedelta(days=week.weekday())))
        return request.redirect('/my/viandas' + (f'?week={week}' if week else '') + '#resultado', code=303)

    @http.route("/my/viandas/<int:reservation_id>", type="http", auth="user", website=True, methods=["GET"])
    def detail(self, reservation_id, **kwargs):
        self._site()
        record = request.env["lafija.reservation"].search([("id", "=", reservation_id)], limit=1)
        if not record:
            abort(private_response("La reserva no está disponible.", status=404))
        return request.render("kai_viandas.detail", {"lf_authenticated": True, "reservation": record._employee_values(),
                              "feedback": request.session.pop('lf_feedback', [])},
                              headers={"Cache-Control": "private, no-store"})

    @http.route("/my/viandas/<int:reservation_id>/correccion", type="http", auth="user", website=True, methods=["POST"])
    def correction(self, reservation_id, message=None, **kwargs):
        self._site()
        record = request.env["lafija.reservation"].search([("id", "=", reservation_id)], limit=1)
        if not record:
            abort(private_response("La reserva no está disponible.", status=404))
        try:
            with request.env.cr.savepoint():
                record._request_correction(message)
        except ValidationError:
            return request.render('kai_viandas.detail', {'lf_authenticated': True, 'reservation': record._employee_values(),
                'correction_text': (message or '')[:4000], 'error': 'Escribí la corrección que necesitás, hasta 4000 caracteres.'},
                status=400, headers={'Cache-Control': 'private, no-store'})
        request.session['lf_feedback'] = ['Solicitud enviada a La Fija. Sigue pendiente hasta que la atiendan. La respuesta se verá acá.']
        return request.redirect(f"/my/viandas/{record.id}", code=303)

    @http.route("/my/viandas/opcion/<int:product_id>/imagen", type="http", auth="user", website=True, methods=["GET"])
    def image(self, product_id, menu_id=None, **kwargs):
        site = self._site()
        try:
            menu_id = int(menu_id)
        except (TypeError, ValueError):
            abort(private_response("Opción no disponible.", status=404))
        menu = request.env["lafija.menu.day"].sudo().search([
            ("id", "=", menu_id), ("website_id", "=", site.id), ("published", "=", True),
            "|", "|", ("product_ids", "in", [product_id]),
            ("dessert_ids", "in", [product_id]), ("drink_ids", "in", [product_id]),
        ], limit=1)
        product = (menu.product_ids | menu.dessert_ids | menu.drink_ids).filtered(
            lambda p: p.id == product_id and p.active and p.sale_ok)
        if not product or not product.image_1024:
            abort(private_response("Imagen no disponible.", status=404))
        data = base64.b64decode(product.image_1024)
        return http.Response(data, content_type=guess_mimetype(data),
                             headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
