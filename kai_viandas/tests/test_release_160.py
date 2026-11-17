"""Navegación sin pérdidas inadvertidas, límite calendario y operación legible."""
import json
import time
from datetime import date
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree, html

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser
from odoo.tools.safe_eval import safe_eval

from ..models.reservation import OrderWindowClosed, PastDayConflict, operation_context
from .test_pages import PagesCommon
from .test_ux_round2 import TestUXRound2


@tagged('post_install', '-at_install')
class TestRelease160(PagesCommon):
    _pointer_browser = TestUXRound2._pointer_browser

    def setUp(self):
        super().setUp()
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.enterContext(freeze_time('2026-09-11 16:00:00', tick=True))

    def _employee(self):
        user, _ = self._create_employee()
        self._real_login(user.login, 'employee-password-123')
        return user, self.env['lafija.reservation'].with_user(user)

    def _week(self, week='2026-09-14'):
        return html.fromstring(self.url_open('/my/viandas?week=' + week).content)

    def _submission(self, page, choices, week='2026-09-14'):
        return {'csrf_token': page.xpath('//input[@name="csrf_token"]/@value')[0],
                'form_choices': page.xpath('//input[@name="form_choices"]/@value')[0], 'week': week,
                **{f'menu_{menu}': str(product or '') for menu, product in choices}}

    def test_past_date_rejects_new_and_substitution_but_not_today_late_or_operator(self):
        user, service = self._employee()
        menu = self.menus[0]
        other = self.env['product.product'].create({'name': 'Cerdo permitido', 'sale_ok': True})
        menu.with_user(self.operator).write({'product_ids': [Command.link(other.id)]})
        with freeze_time('2026-09-14 13:20:00'):
            record = service._submit_selections(self.website, [(menu.id, self.product.id)])
            self.assertFalse(record.sudo().after_reference_time)
            self.assertEqual(record.sudo().current_product_id, self.product)
            menu.with_user(self.operator).action_take_list()
            service._submit_selections(self.website, [(menu.id, other.id)])
            self.assertEqual(record.sudo().current_product_id, other)
            self.assertFalse(record.sudo().pending_product_id)
        with freeze_time('2026-09-14 13:31:00'):
            with self.assertRaises(OrderWindowClosed):
                service._submit_selections(self.website, [(menu.id, self.product.id)])
            self.assertEqual(record.sudo().current_product_id, other)
        revision = menu.cut_ids.current_revision_id
        with freeze_time('2026-09-15 03:00:00'):
            page = self._week()
            cards = page.xpath(f'//details[@data-menu="{menu.id}"]//input[@type="radio"]/@value')
            self.assertCountEqual(cards, [str(self.product.id), str(other.id)])
            self.assertIn('Día pasado · para corregir', page.text_content())
            events = record.sudo().event_ids.ids
            service._submit_selections(self.website, [(menu.id, other.id)])
            self.assertEqual(record.sudo().event_ids.ids, events)  # Reenvío inocuo.
            record._request_correction('Consulta sobre ayer')
            service._submit_selections(self.website, [(menu.id, self.product.id)])
            self.assertFalse(record.sudo().pending_product_id)
            self.assertTrue(record.sudo().attention_pending)
            self.assertEqual(menu.cut_ids.current_revision_id, revision)
            with self.assertRaises(PastDayConflict), self.cr.savepoint():
                service._submit_selections(self.website, [(menu.id, other.id)])
            another, _ = self._create_employee('otro-160')
            with self.assertRaises(PastDayConflict), self.cr.savepoint():
                service.with_user(another)._submit_selections(self.website, [(menu.id, self.product.id)])
            self.env['lafija.reservation.correction'].with_user(self.operator).create({
                'reservation_id': record.id, 'operation': 'replace', 'product_id': other.id,
                'reason': 'Corrección operativa de un día pasado',
            }).action_apply()
            self.assertEqual(record.sudo().current_product_id, other)

    def test_midnight_atomic_draft_can_drop_past_day_and_save_other_dates(self):
        user, service = self._employee()
        choices = [(self.menus[i].id, self.product.id) for i in (0, 1, 3)]
        with freeze_time('2026-09-14 13:29:59'):
            page = self._week()
            data = self._submission(page, choices)
            self.assertFalse(page.xpath('//details[@data-menu="%s"]//p[contains(.,"Día pasado")]' % self.menus[0].id))
        with freeze_time('2026-09-15 03:00:00'):
            response = self.url_open('/my/viandas/reservar', data=data, allow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            self.env.invalidate_all()
            self.assertFalse(service.search([]))
            for _ in range(2):
                draft = self._week()
                self.assertIn('No se guardó ningún día', draft.text_content())
                self.assertIn('3 días sin guardar', draft.text_content())
                self.assertIn('Este día ya pasó mientras elegías', draft.text_content())
                self.assertEqual(draft.xpath('//details[@open]/@data-menu'), [str(self.menus[0].id)])
            old = draft.xpath('//input[@data-unavailable="1"]/parent::label')[0]
            self.assertIn('Pollo con arroz', old.text_content())
            self.assertFalse(old.xpath('.//img'))
            retry = self._submission(draft, [(self.menus[0].id, 0), *choices[1:]])
            response = self.url_open('/my/viandas/reservar', data=retry)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('No se guardó ningún día', response.text)
            self.env.invalidate_all()
            self.assertCountEqual(service.search([]).mapped('date'), [date(2026, 9, 15), date(2026, 9, 17)])

    def test_manipulated_past_or_foreign_choice_never_creates_draft_or_record(self):
        user, service = self._employee()
        with freeze_time('2026-09-15 03:00:00'):
            page = self._week()
            self.assertFalse(page.xpath('//details[@data-menu="%s"]//input[@type="radio"]' % self.menus[0].id))
            data = self._submission(page, [(self.menus[0].id, self.product.id)])
            result = self.url_open('/my/viandas/reservar', data=data)
            self.assertEqual(result.status_code, 400)
            self.assertNotIn('Descartar este borrador', result.text)
        with freeze_time('2026-09-15 02:59:59'):
            page = self._week()
            data = self._submission(page, [(self.menus[0].id, self.product.id)])
        foreign = self.env['product.product'].create({'name': 'AJENO-SECRETO-160'})
        data[f'menu_{self.menus[1].id}'] = str(foreign.id)
        with freeze_time('2026-09-15 03:00:00'):
            result = self.url_open('/my/viandas/reservar', data=data)
            self.assertEqual(result.status_code, 400)
            self.assertNotIn(foreign.name, result.text)
            self.assertNotIn('Descartar este borrador', result.text)
        self.env.invalidate_all()
        self.assertFalse(service.search([]))

    def test_help_origin_is_local_validated_and_own_only(self):
        user, service = self._employee()
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        self.assertIn('/my/viandas/ayuda?week=2026-09-14', self.url_open('/my/viandas?week=2026-09-14').text)
        self.assertIn(f'/my/viandas/ayuda?reservation={record.id}', self.url_open(f'/my/viandas/{record.id}').text)
        other, _ = self._create_employee('ajeno-160')
        foreign = service.with_user(other)._submit_selections(self.website, [(self.menus[1].id, self.product.id)])
        for suffix, target in [('', '/my/viandas'), ('?week=2026-09-17', '/my/viandas?week=2026-09-14'),
                               (f'?reservation={record.id}', f'/my/viandas/{record.id}'),
                               (f'?reservation={foreign.id}', '/my/viandas'),
                               ('?week=https://example.test&return_url=//example.test', '/my/viandas')]:
            response = self.url_open('/my/viandas/ayuda' + suffix)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(html.fromstring(response.content).xpath('//a[@class="back-link"]/@href'), [target])
        self._anonymous()
        redirect = self.url_open('/my/viandas/ayuda', allow_redirects=False)
        self.assertIn('lf_login_required', redirect.headers.get('Location', ''))
        self.assertNotIn('Tu sesión terminó', self.url_open(redirect.headers['Location']).text)

    def test_week_groups_chronological_in_sql_with_pagination(self):
        user, service = self._employee()
        menus = self.menus[:1] | self.env['lafija.menu.day'].with_user(self.operator).create([
            {'date': day, 'website_id': self.website.id, 'published': True, 'product_ids': [Command.set(self.product.ids)]}
            for day in ('2026-10-05', '2027-01-04')])
        records = service._submit_selections(self.website, [(m.id, self.product.id) for m in menus])
        scope = [('id', 'in', records.ids)]
        model = self.env['lafija.reservation'].with_user(self.operator)
        groups = model._read_group(scope, ['week_label'], ['__count'])
        self.assertEqual([g[0] for g in groups], ['14/09/2026 al 20/09/2026', '05/10/2026 al 11/10/2026', '04/01/2027 al 10/01/2027'])
        self.assertEqual(model._read_group(scope, ['week_label'], ['__count'], offset=1, limit=1), groups[1:2])
        self.assertEqual(model._read_group(scope, ['week_label'], ['__count'], order='week_label DESC'), list(reversed(groups)))
        web = model.web_read_group(scope, groupby=['week_label'], aggregates=['__count'], limit=1, offset=1)
        self.assertEqual(web['groups'][0]['week_label'], groups[1][0])

    def test_label_previous_domain_and_validation_share_chronological_rule(self):
        cuts = []
        for menu in self.menus[:2]:
            result = menu.with_user(self.operator).action_take_list()
            cuts.append(self.env['lafija.preparation.cut'].browse(result['res_id']))
        prints = self.env['lafija.label.print'].with_context(**operation_context()).create([
            {'revision_id': cut.current_revision_id.id, 'actor_id': self.operator.id, 'generated_at': stamp}
            for cut, stamp in [(cuts[0], '2026-09-14 13:00:00'), (cuts[0], '2026-09-14 13:00:00'),
                               (cuts[0], '2026-09-14 14:00:00'), (cuts[1], '2026-09-14 12:00:00')]])
        wizard = self.env['lafija.label.replacement'].with_user(self.operator).create({
            'new_print_id': prints[1].id, 'old_print_id': prints[0].id, 'note': 'Coordinado con cocina'})
        arch = etree.fromstring(wizard.get_view(self.env.ref('kai_viandas.label_replacement_form').id, 'form')['arch'].encode())
        domain = safe_eval(arch.xpath('//field[@name="old_print_id"]/@domain')[0], {
            'cut_id': cuts[0].id, 'new_generated_at': fields.Datetime.to_string(prints[1].generated_at),
            'new_print_id': prints[1].id})
        self.assertEqual(self.env['lafija.label.print'].search(domain), prints[0])
        for wrong in prints[1:]:
            wizard.old_print_id = wrong
            with self.assertRaises(ValidationError), self.cr.savepoint():
                wizard.action_apply()
        wizard.old_print_id = prints[0]
        wizard.action_apply()
        self.assertEqual(prints[1].handling_ids.old_print_id, prints[0])

    def test_sale_link_tags_and_reverse_view_have_no_new_commercial_logic(self):
        user, service = self._employee()
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        order = self.env['sale.order'].with_user(self.operator).create({
            'partner_id': self.customer.id, 'lf_reservation_ids': [Command.set(record.ids)]})
        self.assertFalse(order.order_line)
        self.assertTrue(order.lf_protected)
        self.assertEqual(record.with_user(self.operator).lf_sale_order_ids, order)
        label = record.with_user(self.operator).with_context(lf_origin_display=True).display_name
        for item in (record.name, 'Juan de prueba', 'Lunes 14/09'):
            self.assertIn(item, label)
        self.assertEqual(record.with_user(user).with_context(lf_origin_display=True).display_name, record.name)
        with self.assertRaises(AccessError):
            record.with_user(user).read(['lf_sale_order_ids'])
        arch = etree.fromstring(order.get_view(self.env.ref('sale.view_order_form').id, 'form')['arch'].encode())
        options = safe_eval(arch.xpath('//field[@name="lf_reservation_ids"]/@options')[0])
        self.assertTrue(options['no_create'])
        self.assertTrue(options['no_create_edit'])

    def test_own_views_labels_and_access_feedback_are_ephemeral(self):
        user, _ = self._employee()
        result = self._manage(user, 'update', customer_company_id=self.customer.id,
                              website_id=self.website.id).with_context(lf_access_feedback=True).action_apply()
        self.assertEqual(result['tag'], 'lf_operation_feedback')
        self.assertNotIn('lf_access_result', str(result))
        self.assertEqual(result['params']['next']['res_id'], user.partner_id.id)
        arch = self.env['res.partner'].with_user(self.operator).get_view(self.env.ref('kai_viandas.employee_form').id, 'form')['arch']
        self.assertNotIn('Operación de acceso completada', arch)
        refresh = self.menus[0].with_user(self.operator).action_refresh_options()
        self.assertIn('Descripciones copiadas', refresh['params']['message'])
        self.assertEqual(self.env['lafija.label.print']._fields['name'].string, 'Archivo')
        self.assertEqual(self.env['lafija.preparation.cut']._fields['name'].string, 'Lista de preparación')
        menu_view = self.menus[0].with_user(self.operator).get_view(self.env.ref('kai_viandas.menu_day_form').id, 'form')['arch']
        self.assertIn('lf_menu_form', menu_view)
        self.assertTrue(self.menus[0].take_list_future)
        public = self.url_open('/web/login', headers={'Host': 'public.test'})
        self.assertIn('Acceso para clientes y personal de La Fija', public.text)
        self.assertIn('Usuario o correo electrónico', public.text)

    def _employee_pointer_journey(self, path, journey, width=360, login=None):
        """Puntero y teclado del Chrome privado, también entre documentos completos."""
        cookies = None if login else {'session_id': next(
            c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')}
        original = ChromeBrowser._wait_code_ok
        def drive(browser, code, timeout, **kwargs):
            browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                'width': width, 'height': 800 if width == 360 else 844, 'deviceScaleFactor': 1, 'mobile': False})
            def evaluate(expression):
                return browser._websocket_request('Runtime.evaluate', params={
                    'expression': expression, 'returnByValue': True}).get('result', {}).get('value')
            def wait(expression):
                for _ in range(240):
                    if evaluate('Boolean(' + expression + ')'):
                        return
                    time.sleep(.05)
                self.fail(expression)
            def pointer(selector):
                target = 'document.querySelector(' + json.dumps(selector) + ')'
                wait(target)
                evaluate(target + '.scrollIntoView({block:"center"})')
                time.sleep(.18)
                point = evaluate('(()=>{const e=' + target + ';const r=e.getBoundingClientRect();'
                    'const x=r.x+r.width/2,y=r.y+r.height/2;return {x,y,clear:e.contains(document.elementFromPoint(x,y))};})()')
                self.assertTrue(point['clear'], selector)
                for kind in ('mousePressed', 'mouseReleased'):
                    browser._websocket_request('Input.dispatchMouseEvent', params={
                        'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})
                time.sleep(.15)
            def type_keys(text):
                for char in text:
                    browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyDown', 'key': char, 'text': char})
                    browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyUp', 'key': char})
            journey(browser, evaluate, wait, pointer, type_keys)
            return original(browser, code, timeout, **kwargs)
        with patch.object(ChromeBrowser, '_wait_code_ok', drive):
            self.browser_js(path, "console.log('test successful');", login=login,
                            cookies=cookies, timeout=120)

    def test_pointer_dirty_week_warning_and_help_returns_origin_at_390(self):
        user, service = self._employee()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector("#lf-week-form")')
            for menu in self.menus[:2]:
                if not evaluate(f'document.querySelector("[data-menu=\\"{menu.id}\\"]").open'):
                    pointer(f'[data-menu="{menu.id}"] summary')
                pointer(f'[data-menu="{menu.id}"] label:has(input[value="{self.product.id}"])')
            pointer('.header-actions a[href*="ayuda"]')
            wait('document.querySelector("#lf-leave-dialog").open')
            self.assertEqual(evaluate('document.querySelector("#lf-leave-title").textContent'), 'Tenés 2 días sin guardar')
            browser.take_screenshot(prefix='lf160_salida_390_').result(timeout=10)
            pointer('[data-keep-choosing]')
            self.assertIn('2 días sin guardar', evaluate('document.querySelector("[data-save-state]").textContent'))
            self.assertTrue(evaluate('document.activeElement === document.querySelector(".header-actions a[href*=ayuda]")'))
            pointer('a.this-week')
            wait('document.querySelector("#lf-leave-dialog").open')
            pointer('[data-keep-choosing]')
            self.assertTrue(evaluate('document.activeElement === document.querySelector("a.this-week")'))
            pointer('.header-actions a[href*="ayuda"]')
            wait('document.querySelector("#lf-leave-dialog").open')
            pointer('[data-leave-unsaved]')
            wait('location.pathname.endsWith("/ayuda") && document.querySelector(".back-link")')
            self.assertEqual(evaluate('document.querySelector(".back-link").getAttribute("href")'), '/my/viandas?week=2026-09-14')
            pointer('a.back-link')
            wait('document.querySelector("#lf-week-form")')
            self.assertFalse(evaluate('!!document.querySelector(".draft-choice:not([hidden])")'))
            self.assertFalse(evaluate('document.documentElement.scrollWidth > innerWidth'))
            self.assertFalse(evaluate('document.querySelector("a.this-week").hasAttribute("aria-current")'))
        self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey, width=390)
        self.env.invalidate_all()
        self.assertFalse(service.search([]))

    def test_pointer_unsent_consultation_and_help_returns_own_detail(self):
        user, service = self._employee()
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector(".lf-correction-form")')
            pointer('#message')
            type_keys('Necesito consultar mi vianda')
            pointer('.header-actions a[href*="ayuda"]')
            wait('document.querySelector("#lf-leave-dialog").open')
            self.assertIn('consulta sin enviar', evaluate('document.querySelector("#lf-leave-title").textContent'))
            browser.take_screenshot(prefix='lf160_consulta_360_').result(timeout=10)
            pointer('[data-keep-choosing]')
            self.assertEqual(evaluate('document.querySelector("#message").value'), 'Necesito consultar mi vianda')
            pointer('.header-actions a[href*="ayuda"]')
            pointer('[data-leave-unsaved]')
            wait('location.pathname.endsWith("/ayuda") && document.querySelector(".back-link")')
            self.assertEqual(evaluate('document.querySelector(".back-link").getAttribute("href")'), f'/my/viandas/{record.id}')
            pointer('a.back-link')
            wait('document.querySelector(".lf-correction-form")')
            self.assertEqual(evaluate('document.querySelector("#message").value'), '')
            self.assertGreaterEqual(evaluate('document.querySelector(".history summary").getBoundingClientRect().height'), 44)
            self.assertNotIn('America/Argentina', evaluate('document.body.textContent'))
        self._employee_pointer_journey(f'/my/viandas/{record.id}', journey)
        self.env.invalidate_all()
        self.assertFalse(record.sudo().attention_pending)

    def test_pointer_midnight_preserves_draft_then_leaves_past_day_unchanged(self):
        user, service = self._employee()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector("#lf-week-form")')
            for menu in (self.menus[0], self.menus[1], self.menus[3]):
                if not evaluate(f'document.querySelector("[data-menu=\\"{menu.id}\\"]").open'):
                    pointer(f'[data-menu="{menu.id}"] summary')
                pointer(f'[data-menu="{menu.id}"] label:has(input[value="{self.product.id}"])')
            with freeze_time('2026-09-15 03:00:01', tick=True):
                pointer('.save-bar button')
                wait('document.querySelector(".day-conflict")?.textContent.includes("Este día ya pasó")')
                self.assertIn('3 días sin guardar', evaluate('document.querySelector("[data-save-state]").textContent'))
                browser.take_screenshot(prefix='lf160_medianoche_360_').result(timeout=10)
                self.env.invalidate_all()
                self.assertFalse(service.search([]))
                history = browser._websocket_request('Page.getNavigationHistory')
                before = history['entries'][history['currentIndex'] - 1]['id']
                browser._websocket_request('Page.navigateToHistoryEntry', params={'entryId': before})
                wait('document.querySelector(".day-conflict") && !document.querySelector(".save-bar button").disabled')
                browser._websocket_request('Page.reload')
                wait('document.querySelector(".day-conflict") && document.readyState === "complete"')
                self.assertIn('3 días sin guardar', evaluate('document.querySelector("[data-save-state]").textContent'))
                pointer(f'[data-menu="{self.menus[0].id}"] label:has(input[value=""])')
                self.assertIn('2 días sin guardar', evaluate('document.querySelector("[data-save-state]").textContent'))
                pointer('.save-bar button')
                wait('document.querySelector(".success") && !document.querySelector(".day-conflict")')
                self.assertFalse(evaluate('document.querySelector("[data-menu=\\"%s\\"] input[type=radio]")' % self.menus[0].id))
        with freeze_time('2026-09-15 02:59:00', tick=True):
            self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey)
        self.env.invalidate_all()
        self.assertCountEqual(service.search([]).mapped('date'), [date(2026, 9, 15), date(2026, 9, 17)])

    def test_pointer_preparation_confirmation_cancel_and_accept_future_menu(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        menu = self.menus[0]
        self._pointer_browser(f'/odoo/action-kai_viandas.menu_day_action/{menu.id}', r'''
            await wait(()=>document.querySelector('.o_form_view'),'Falta ficha del menú');
            const take=await wait(()=>[...document.querySelectorAll('button[name="action_take_list"]')].find(visible),'Falta Tomar lista');
            if(take.classList.contains('btn-primary')) throw new Error('Un corte futuro se destaca como principal');
            await pointer(take);
            let dialog=await wait(()=>document.querySelector('.o_dialog .modal'),'Falta confirmación');
            if(!dialog.textContent.includes('14/09/2026') || !(dialog.textContent.includes('10:30') || dialog.textContent.includes('queda para revisión'))) throw new Error('No explica fecha y consecuencia');
            await pointer([...dialog.querySelectorAll('button')].find(e=>e.textContent.trim()==='Volver'));
            await wait(()=>!document.querySelector('.o_dialog .modal'),'No cerró al cancelar');
            if(![...document.querySelectorAll('button[name="action_take_list"]')].some(visible)) throw new Error('Cancelar tomó la lista');
            await pointer([...document.querySelectorAll('button[name="action_take_list"]')].find(visible));
            dialog=await wait(()=>document.querySelector('.o_dialog .modal'),'Falta segunda confirmación');
            await pointer([...dialog.querySelectorAll('button')].find(e=>e.textContent.trim()==='Tomar lista'));
            await wait(()=>document.querySelector('.o_field_widget[name="current_revision_id"]'),'No abrió la lista tomada');
        ''', login=self.operator.login, min_clicks=4, viewport=(1366, 900))
        self.env.invalidate_all()
        self.assertEqual(len(menu.cut_ids), 1)
        self.assertEqual(menu.cut_ids.current_revision_id.number, 1)

    def test_pointer_desktop_footer_help_pager_and_refresh_feedback(self):
        self._employee()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector("#lf-week-form")')
            browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                'width': 1366, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
            pointer(f'[data-menu="{self.menus[3].id}"] summary')
            box = evaluate('(()=>{const e=document.querySelector(".save-bar"),r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,position:getComputedStyle(e).position};})()')
            self.assertLessEqual(box['bottom'], 900)
            self.assertNotIn(box['position'], ('fixed', 'sticky'))
            browser.take_screenshot(prefix='lf160_guardar_escritorio_').result(timeout=10)
            pointer(f'[data-menu="{self.menus[3].id}"] label:has(input[value="{self.product.id}"])')
            pointer('.save-bar button')
            wait('document.querySelector(".success")')
        self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey)
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.menu_day_action/{self.menus[1].id}', r'''
            await pointer(await wait(()=>[...document.querySelectorAll('button[name="action_refresh_options"]')].find(visible),'Falta copiar'));
            await wait(()=>[...document.querySelectorAll('.o_notification')].some(e=>e.textContent.includes('Descripciones copiadas')),'No hay aviso después de copiar');
            await pointer(await wait(()=>[...document.querySelectorAll('a')].find(e=>visible(e)&&e.textContent.trim()==='Ayuda'),'Falta menú Ayuda'));
            await wait(()=>document.querySelector('.o_field_widget[name="content"]'),'No abrió la ayuda');
            if([...document.querySelectorAll('.o_pager')].some(visible)) throw new Error('Ayuda tiene paginador');
        ''', login=self.operator.login, min_clicks=2, viewport=(1366, 900))
