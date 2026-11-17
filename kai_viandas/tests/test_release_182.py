"""Idioma de entrada, navegación del operador y opciones con imagen."""
import logging
import base64
import copy
import json
from io import BytesIO

from freezegun import freeze_time
from lxml import html
from PIL import Image
from unittest.mock import patch

from odoo import Command, http
from odoo.tests import tagged

from .test_pages import PagesCommon
from .test_preparation import PreparationCommon
from .test_release_160 import TestRelease160
from .test_release_180 import TestQuotation180
from .test_release_181 import TestQuotation181
from ..models.quotation import digest

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestLanguage182(PagesCommon):
    def setUp(self):
        super().setUp()
        lang = self.env['res.lang']._activate_lang('es_AR')
        (self.website | self.public_site).write({
            'language_ids': [Command.set(lang.ids)], 'default_lang_id': lang.id})
        self.env['res.partner'].with_context(active_test=False).search([]).write({'lang': 'es_AR'})
        self.env['res.lang'].search([('code', '!=', 'es_AR')]).write({'active': False})

    def test_fresh_headers_and_existing_invalid_session(self):
        self.authenticate(None, None)
        self.session.context['lang'] = 'es_ES'
        http.root.session_store.save(self.session)
        self.env.registry.clear_cache()
        self.env.invalidate_all()
        self.assertEqual(self.url_open('/web/login').status_code, 200)
        for language in ('es-ES', 'es-419,es;q=0.9', 'zh-CN', 'es-AR', 'en-US'):
            self.opener.cookies.clear()
            response = self.url_open('/web/login', headers={'Accept-Language': language})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Entrá a tus viandas', response.text)
            self.assertEqual(response.cookies.get('frontend_lang'), 'es_AR')
            _logger.info('LAFIJA_182_FRESH_HEADER %s %s', language, response.status_code)

    def test_anonymous_languages_cold_and_warm_routes(self):
        results = []
        for language in ('es-419', 'es-ES', 'zh-CN', 'es-419,es;q=0.9', 'es-AR', 'en-US'):
            for route in ('/web/login', '/viandas/ayuda-acceso', '/my/viandas', '/shop'):
                for cold in (True, False):
                    self.authenticate(None, None)
                    # Reproduce una sesión cuyo contexto procede del navegador.
                    self.session.context['lang'] = language.split(',')[0].replace('-', '_')
                    http.root.session_store.save(self.session)
                    if cold:
                        self.env.registry.clear_cache()
                        self.env.invalidate_all()
                    response = self.url_open(route, headers={'Accept-Language': language}, allow_redirects=False)
                    results.append((language, route, cold, response.status_code))
                    _logger.info('LAFIJA_182_LANGUAGE %s', results[-1])
        for language, route, cold, status in results:
            self.assertEqual(status, {'/web/login': 200, '/viandas/ayuda-acceso': 200, '/my/viandas': 303, '/shop': 403}[route], (language, route, cold))
        self.assertEqual(self.env['res.lang'].search([]).mapped('code'), ['es_AR'])

    def test_login_post_authenticated_week_and_denials_with_invalid_session_language(self):
        employee, _ = self._create_employee()
        for language in ('es_ES', 'es_419', 'zh_CN'):
            self.authenticate(None, None)
            self.session.context['lang'] = language
            http.root.session_store.save(self.session)
            page = self.url_open('/web/login')
            token = html.fromstring(page.content).xpath('//input[@name="csrf_token"]/@value')[0]
            response = self.url_open('/web/login', data={'csrf_token': token,
                'login': employee.login, 'password': 'employee-password-123', 'type': 'password'}, allow_redirects=False)
            self.assertEqual(response.status_code, 303)
            # Una sesión anterior puede conservar un idioma inactivo.
            session = http.root.session_store.get(self.opener.cookies.get('session_id'))
            session.context['lang'] = language
            http.root.session_store.save(session)
            for route, status in (('/my/viandas', 200), ('/my/viandas/ayuda', 200), ('/shop', 403), ('/web/reset_password', 403)):
                response = self.url_open(route)
                self.assertEqual(response.status_code, status, (language, route, response.text[:100]))
                self.assertNotIn('Invalid language code', response.text)
            crossed = self.url_open('/shop', headers={'Host': 'public.test'}, cookies={'session_id': session.sid})
            self.assertEqual(crossed.status_code, 403)

    def test_public_language_and_scope_are_native_without_request_or_session_changes(self):
        for language in ('es_ES', 'es_419', 'zh_CN', 'es_AR', 'en_US'):
            self.authenticate(None, None)
            self.session.context['lang'] = language
            http.root.session_store.save(self.session)
            for route in ('/web/login', '/shop'):
                headers = {'Host': 'public.test', 'Accept-Language': language.replace('_', '-')}
                self.env.registry.clear_cache()
                self.env.invalidate_all()
                guarded = self.url_open(route, headers=headers)
                with patch.object(type(self.env['ir.http']), '_lf_guard', return_value=None):
                    native = self.url_open(route, headers=headers)
                self.assertEqual(guarded.status_code, native.status_code)
                self.assertEqual(guarded.status_code, 200, guarded.text[:200])
                for response in (guarded, native):
                    self.assertNotIn('Invalid language code', response.text)
                    self.assertEqual(html.fromstring(response.content).get('lang'), 'es-AR')
            saved = http.root.session_store.get(self.session.sid)
            self.assertEqual(saved.context['lang'], language)
        self.assertEqual(self.env['res.lang'].search([]).mapped('code'), ['es_AR'])


@tagged('post_install', '-at_install')
class TestPresentation182(PreparationCommon):
    _summary = TestQuotation180._summary
    _text = TestQuotation181._text
    _pdf = TestQuotation181._pdf

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-10-01 15:00:00'))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.cut = self._take()
        self.model = self.env['lafija.quotation.preparation'].with_user(self.operator)


    def test_four_menu_sections_keep_existing_leaf_actions_and_groups(self):
        root = self.env.ref('kai_viandas.menu_root')
        sections = self.env['ir.ui.menu'].search([('parent_id', '=', root.id)], order='sequence,id')
        self.assertEqual(sections.with_context(lang='en_US').mapped('name'),
                         ['Pedidos', 'Menús', 'Empleados', 'Ayuda'])
        menus = self.env.ref('kai_viandas.menu_days')
        self.assertEqual(menus.parent_id, root)
        self.assertEqual(menus.action, self.env.ref('kai_viandas.menu_day_action'))
        self.assertEqual(menus.group_ids, self.env.ref('kai_viandas.group_operator'))
        entry = self.env.ref('kai_viandas.menu_employees')
        self.assertEqual(entry.parent_id, self.env.ref('kai_viandas.menu_employees_group'))
        self.assertEqual(entry.action, self.env.ref('kai_viandas.employee_action'))
        self.assertFalse(self.env['ir.model.data'].sudo().search([
            ('module', '=', 'kai_viandas'), ('name', '=', 'menu_employee_create'),
        ]))
        self.assertTrue(self.env.ref('kai_viandas.employee_access_action'))

    def test_summary_dates_and_empty_pdf_only_change_presentation(self):
        batch = self._summary(date_from='2026-08-01', date_to='2026-08-31')
        original, token = copy.deepcopy(batch.snapshot), batch.snapshot_token
        self.assertIn('01/08/2026 al 31/08/2026', self._text(batch))
        values = self.env['report.kai_viandas.quotation_annex'].with_user(self.operator)._get_report_values(batch.ids)
        document = html.fromstring(self.env['ir.qweb']._render('kai_viandas.quotation_annex', values))
        self.assertFalse(document.xpath('//table'))
        _, text = self._pdf(batch, 'lf182_anexo_vacio_')
        self.assertIn('01/08/2026 al 31/08/2026', text)
        self.assertIn('No hay viandas disponibles en esta consulta.', text)
        self.assertIn('0 viandas', text)
        self.assertNotIn('Revisión de origen', text)
        self.assertEqual((batch.snapshot, batch.snapshot_token), (original, token))

    def test_nonempty_dates_and_prepared_snapshot_and_pdf_are_preserved(self):
        batch = self._summary()
        self.assertIn('14/09/2026', self._text(batch))
        self.assertNotIn('2026-09-14', self._text(batch))
        batch.action_prepare()
        original, token = copy.deepcopy(batch.prepared_snapshot), digest(batch.prepared_snapshot)
        pdf, text = self._pdf(batch, 'lf182_anexo_preparado_')
        attachment = self.env['ir.attachment'].create({'name': 'Emitido182.pdf', 'raw': pdf,
            'res_model': batch._name, 'res_id': batch.id})
        self.assertIn('14/09/2026', text)
        batch.action_refresh()
        self.assertEqual(batch.prepared_snapshot, original)
        self.assertEqual(digest(batch.prepared_snapshot), token)
        self.assertEqual(attachment.raw, pdf)
        self.assertEqual(batch.action_prepare()['res_id'], batch.order_id.id)

    def test_refresh_action_and_changed_summary_reuse_form(self):
        batch = self._summary()
        for _ in range(3):
            action = batch.action_refresh()
            self.assertEqual(action['tag'], 'lf_quotation_reload')
            self.assertEqual(action['params']['form']['res_id'], batch.id)
        stale = batch.snapshot_token
        self.reservation._request_correction('Aviso posterior a la consulta')
        action = batch.with_context(lf_seen_summary=stale).action_prepare()
        self.assertEqual(action['tag'], 'lf_quotation_reload')
        self.assertTrue(batch.notice)
        self.assertFalse(batch.order_id)


@tagged('post_install', '-at_install')
class TestBrowser182(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-09-13 16:00:00', tick=True))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.env['res.lang']._activate_lang('es_AR')
        self.operator.lang = 'es_AR'

    def test_photo_cards_pointer_at_360_390_1366_and_normal_choice_submit(self):
        pixels = BytesIO()
        Image.new('RGB', (1200, 900), (100, 150, 90)).save(pixels, 'PNG')
        self.product.image_1920 = base64.b64encode(pixels.getvalue())
        self.product.is_published = False
        no_photo = self.env['product.product'].create({'name': 'Opción sin imagen', 'sale_ok': True})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(no_photo.id)]})
        employee, _ = self._create_employee()
        self._real_login(employee.login, 'employee-password-123')
        menu_id = self.menus[0].id
        for width, chosen in ((360, self.product), (390, no_photo), (1366, self.product)):
            self._real_login(employee.login, 'employee-password-123')
            def journey(browser, evaluate, wait, pointer, _type):
                wait('document.querySelector("#lf-week-form")')
                day = f'[data-menu="{menu_id}"]'
                if not evaluate(f'document.querySelector({json.dumps(day)}).open'):
                    pointer(day+' summary')
                photo = day+' label.with-photo'
                compact = day+f' label:has(input[value="{no_photo.id}"])'
                wait(f'document.querySelector({json.dumps(photo+" img")})?.naturalWidth > 0')
                data = evaluate('''(()=>{const a=document.querySelector(%s),b=document.querySelector(%s),
                    i=a.querySelector('img'), r=i.getBoundingClientRect(), ar=a.getBoundingClientRect();
                    return {image:r.width, ratio:r.width/r.height, card:ar.width, compact:b.getBoundingClientRect().height,
                    noImage:!b.querySelector('img,.option-symbol'), alt:i.alt,
                    radio:!!a.querySelector('input[type=radio]'), fit:getComputedStyle(i).objectFit,
                    overflow:document.documentElement.scrollWidth > innerWidth,
                    save:getComputedStyle(document.querySelector('.save-bar')).position,
                    columns:getComputedStyle(a.closest('.options')).gridTemplateColumns.split(' ').length};})()''' % (json.dumps(photo), json.dumps(compact)))
                self.assertGreater(data['image'], 200, data)
                self.assertAlmostEqual(data['ratio'], 16/9, places=2)
                self.assertLessEqual(data['card'] - data['image'], 5)
                self.assertTrue(data['noImage'] and data['radio'])
                self.assertGreaterEqual(data['compact'], 44)
                self.assertEqual(data['alt'], '')
                self.assertEqual(data['fit'], 'cover')
                self.assertFalse(data['overflow'])
                self.assertEqual(data['save'], 'static')
                self.assertEqual(data['columns'], 3 if width == 1366 else 1)
                self.assertNotIn('Sin foto', evaluate('document.querySelector("#lf-week-form").innerText'))
                evaluate('document.querySelector(' + json.dumps(photo) + ').scrollIntoView({block:"center"})')
                browser.take_screenshot(prefix=f'lf182_opciones_{width}_').result(timeout=10)
                pointer(day+f' label:has(input[value="{chosen.id}"])')
                wait(f'!document.querySelector({json.dumps(day)}).open')
                pointer('.save-bar button')
                wait('document.querySelector(".success")')
                self.assertFalse(evaluate('document.documentElement.scrollWidth > innerWidth'))
                _logger.info('LAFIJA_182_CARD %s %s', width, data)
            self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey, width=width)
            self.env.invalidate_all()
            record = self.env['lafija.reservation'].search([('employee_partner_id', '=', employee.partner_id.id), ('menu_id', '=', menu_id)])
            self.assertEqual(record.current_product_id, chosen)
        self._real_login(employee.login, 'employee-password-123')
        page = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
        self.assertIn('Vigente', page.text_content())

    def _backend(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self.operator.password = 'operator182-password'

    def test_changed_summary_refreshes_same_form_without_creating_order(self):
        employee, _ = self._create_employee()
        with freeze_time('2026-09-14 12:00:00'):
            record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(self.menus[0].id, self.product.id)])
        self.menus[0].with_user(self.operator).action_take_list()
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({
            'customer_company_id': self.customer.id, 'date_from': '2026-09-14', 'date_to': '2026-09-14'})
        batch.action_refresh()
        self._backend()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector("button[name=action_prepare]")')
            before = evaluate('location.href')
            record._request_correction('Consulta recibida después de mostrar el resumen')
            self.env.flush_all()
            self.assertNotEqual(digest(batch._collect()), batch.snapshot_token)
            pointer('button[name=action_prepare]')
            wait('document.querySelector("[name=notice]")?.textContent.includes("No se creó ninguna cotización")')
            self.assertEqual(evaluate('location.href'), before)
            self.assertIn('Consulta escrita abierta', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            browser.take_screenshot(prefix='lf182_resumen_cambiado_').result(timeout=10)
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertFalse(batch.order_id)

    def test_refresh_current_and_new_form_preserve_url_breadcrumbs_and_empty_state(self):
        self._backend()
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector("[name=customer_company_id] input")')
            pointer('[name=customer_company_id] input')
            type_keys(self.customer.name)
            wait('document.querySelector(".o-autocomplete--dropdown-item")')
            pointer('.o-autocomplete--dropdown-item')
            pointer('button[name=action_refresh]')
            wait('document.querySelector(".lf-quotation-summary")')
            first = evaluate('({url:location.href,crumbs:document.querySelectorAll(".o_breadcrumb .breadcrumb-item").length})')
            for _ in range(3):
                pointer('button[name=action_refresh]')
                wait('document.querySelector(".lf-quotation-summary")')
                now = evaluate('({url:location.href,crumbs:document.querySelectorAll(".o_breadcrumb .breadcrumb-item").length})')
                self.assertEqual(now, first)
            self.assertFalse(evaluate('Boolean(document.querySelector("button[name=action_prepare]"))'))
            browser.take_screenshot(prefix='lf182_consulta_sin_migas_').result(timeout=10)
        action = self.env.ref('kai_viandas.quotation_preparation_action').id
        self._employee_pointer_journey(f'/odoo/action-{action}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        batches = self.env['lafija.quotation.preparation'].search([('customer_company_id', '=', self.customer.id)])
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches.state, 'review')
        self.assertFalse(batches.order_id)

    def test_refresh_operation_opened_from_order_keeps_dialog_and_return_path(self):
        employee, _ = self._create_employee()
        with freeze_time('2026-09-14 12:00:00'):
            self.env['lafija.reservation'].with_user(employee)._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        self.menus[0].with_user(self.operator).action_take_list()
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({
            'customer_company_id': self.customer.id, 'date_from': '2026-09-14', 'date_to': '2026-09-14'})
        batch.action_refresh()
        batch.action_prepare()
        order = batch.order_id
        snapshot = copy.deepcopy(batch.prepared_snapshot)
        self._backend()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector("a[name=lf_protection]")')
            pointer('a[name=lf_protection]')
            pointer('[name=lf_quotation_preparation_ids] .o_data_row')
            wait('document.querySelector(".modal .lf-quotation-summary")')
            before = evaluate('location.href')
            for _ in range(3):
                pointer('.modal button[name=action_refresh]')
                wait('document.querySelector(".modal .lf-quotation-summary")?.textContent.includes("Ya incluidas en esa consulta")')
                self.assertEqual(evaluate('location.href'), before)
            browser.take_screenshot(prefix='lf182_consulta_desde_pedido_').result(timeout=10)
            pointer('.modal .btn-close')
            wait('!document.querySelector(".modal")')
            self.assertEqual(evaluate('location.href'), before)
        self._employee_pointer_journey(f'/odoo/sale.order/{order.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual(batch.prepared_snapshot, snapshot)
        self.assertEqual(batch.order_id, order)
        self.assertEqual(order.state, 'sale')


@tagged('post_install', '-at_install', 'lafija_menu_oca')
class TestMenuResponsive182(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def test_four_sections_from_apps_grid_without_reload_with_responsive(self):
        if not self.env['ir.module.module'].search_count([('name', '=', 'web_responsive'), ('state', '=', 'installed')]):
            self.skipTest('Se ejecuta además en la base aislada con web_responsive instalado')
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        root = self.env.ref('kai_viandas.menu_root')
        for width in (1366, 1100):
            def journey(browser, evaluate, wait, pointer, _type):
                wait('document.querySelector(".o_grid_apps_menu__button")')
                if not evaluate('document.body.classList.contains("o_apps_menu_opened")'):
                    pointer('.o_grid_apps_menu__button')
                wait('document.querySelector(".o-app-menu-list")')
                pointer(f'.o-app-menu-list [data-menu-xmlid="kai_viandas.menu_root"]')
                wait('!document.body.classList.contains("o_apps_menu_opened") && document.querySelector(".o_menu_sections")')
                for xmlid in ('menu_orders_group', 'menu_days', 'menu_employees_group', 'menu_help'):
                    selector = f'.o_menu_sections [data-menu-xmlid="kai_viandas.{xmlid}"]'
                    pointer(selector)
                    if xmlid.endswith('_group'):
                        self.assertTrue(evaluate('Boolean(document.querySelector(".o-dropdown--menu"))'))
                        # Cerrar el grupo mediante su botón; no abrir registros.
                        pointer(selector)
                browser.take_screenshot(prefix=f'lf182_menu_oca_{width}_').result(timeout=10)
            self._employee_pointer_journey('/odoo', journey, width=width, login=self.operator.login)
