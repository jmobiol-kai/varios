"""Pulida local: avisos, títulos, mosaico, orientación y anexo vacío."""
import base64
import copy
import json
from io import BytesIO

from freezegun import freeze_time
from lxml import html
from PIL import Image

from odoo import Command
from odoo.tests import tagged

from .test_pages import PagesCommon
from .test_preparation import PreparationCommon
from .test_release_160 import TestRelease160
from .test_release_180 import TestQuotation180
from .test_release_181 import TestQuotation181
from .test_release_182 import TestBrowser182


@tagged('post_install', '-at_install')
class TestPresentation191(PreparationCommon):
    _summary = TestQuotation180._summary
    _pdf = TestQuotation181._pdf

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-10-01 15:00:00'))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.cut = self._take()
        self.model = self.env['lafija.quotation.preparation'].with_user(self.operator)

    def test_refresh_feedback_only_after_success_and_not_for_changed_summary(self):
        batch = self._summary()
        before = copy.deepcopy(batch.snapshot)
        for _ in range(2):
            action = batch.action_refresh()
            self.assertEqual(action['tag'], 'lf_quotation_reload')
            self.assertEqual(action['params']['form']['res_id'], batch.id)
            self.assertEqual(action['params']['feedback'], 'Resumen actualizado.')
            self.assertEqual(batch.snapshot, before)
        self.reservation._request_correction('Consulta posterior al resumen')
        changed = batch.action_prepare()
        self.assertFalse(changed['params']['feedback'])
        self.assertIn('El resumen cambió', batch.notice)
        self.assertFalse(batch.order_id)

    def test_action_titles_keep_ids_domains_and_today_context(self):
        model = self.env['ir.actions.act_window'].with_user(self.operator)
        for xmlid, title in [('cut_action', 'Listas de preparación'), ('reservation_action', 'Consultar reservas')]:
            action = model._for_xml_id('kai_viandas.' + xmlid)
            self.assertEqual(action['name'], title)
            self.assertEqual(action['display_name'], title)
            self.assertEqual(action['id'], self.env.ref('kai_viandas.' + xmlid).id)
        action = self.env['lafija.menu.day'].with_user(self.operator).action_workday()
        self.assertEqual(action['name'], action['display_name'])
        self.assertTrue(action['name'].startswith('Hoy · '))
        self.assertEqual(action['context'], {'search_default_today': 1})
        self.assertIn('otras fechas', action['help'])

    def test_empty_annex_has_count_without_orphan_heading_and_keeps_issued_pdf(self):
        batch = self._summary(date_from='2026-08-01', date_to='2026-08-31')
        snapshot, token = copy.deepcopy(batch.snapshot), batch.snapshot_token
        values = self.env['report.kai_viandas.quotation_annex'].with_user(self.operator)._get_report_values(batch.ids)
        doc = html.fromstring(self.env['ir.qweb']._render('kai_viandas.quotation_annex', values))
        self.assertFalse(doc.xpath('//table|//h2'))
        pdf, text = self._pdf(batch, 'lf191_anexo_vacio_')
        self.assertIn('0 viandas disponibles.', text)
        self.assertIn('No hay viandas disponibles en esta consulta.', text)
        self.assertIn('Resumen sin cotización preparada', text)
        self.assertNotIn('Detalle por empleado', text)
        attachment = self.env['ir.attachment'].create({'name': 'Consulta emitida 191.pdf', 'raw': pdf,
            'res_model': batch._name, 'res_id': batch.id})
        batch.action_refresh()
        self.assertEqual(attachment.raw, pdf)
        self.assertEqual((batch.snapshot, batch.snapshot_token), (snapshot, token))
        other = self._summary()
        _, text = self._pdf(other, 'lf191_anexo_con_vianda_')
        self.assertIn('Detalle por empleado y fecha', text)
        self.assertIn(self.reservation.name, text)


@tagged('post_install', '-at_install')
class TestBrowser191(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey
    _backend = TestBrowser182._backend

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-09-13 16:00:00', tick=True))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.env['res.lang']._activate_lang('es_AR')
        self.operator.lang = 'es_AR'

    def _photos(self):
        pixels = BytesIO()
        Image.new('RGB', (1200, 900), (83, 126, 88)).save(pixels, 'PNG')
        return base64.b64encode(pixels.getvalue())

    def _mixed(self):
        self.product.image_1920 = self._photos()
        compact = self.env['product.product'].create([
            {'name': name, 'sale_ok': True, 'description_sale': name}
            for name in ['A · Tarta', 'B · Pescado', 'C · Verduras']])
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(p.id) for p in compact]})
        return compact

    @staticmethod
    def _key(browser, name, code):
        for kind in ('keyDown', 'keyUp'):
            browser._websocket_request('Input.dispatchKeyEvent', params={
                'type': kind, 'key': name, 'windowsVirtualKeyCode': code})

    def test_mixed_cards_fold_visible_and_save_same_product_at_360_390_1366(self):
        compact = self._mixed()
        day = f'[data-menu="{self.menus[0].id}"]'
        photo = day + ' .with-photo'
        for width in (360, 390, 1366):
            employee, _ = self._create_employee(f'lf191-{width}')
            self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(self.menus[0].id, compact[0].id)])
            self._real_login(employee.login, 'employee-password-123')
            # El agrupamiento es de presentación: IDs y orden estables en cada GET.
            orders = []
            for _ in range(2):
                doc = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
                orders.append(doc.xpath(f'//input[@name="menu_{self.menus[0].id}"]/@value'))
            self.assertEqual(orders[0], orders[1])
            self.assertEqual(orders[0], [str(p.id) for p in self.product + compact])
            def journey(browser, evaluate, wait, pointer, _type):
                wait('document.querySelector("#lf-week-form")')
                if not evaluate(f'document.querySelector({json.dumps(day)}).open'):
                    pointer(day + ' summary')
                wait(f'document.querySelector({json.dumps(photo + " img")})?.naturalWidth > 0')
                geometry = evaluate('''(()=>{const f=document.querySelector(%s),p=f.querySelector('.photo-options'),
                    c=f.querySelector('.compact-options'),a=p.getBoundingClientRect(),b=c.getBoundingClientRect();
                    return {px:a.x,pr:a.right,py:a.y,cy:b.y,cx:b.x,cb:b.bottom,cols:getComputedStyle(f).gridTemplateColumns.split(' ').length,
                    heights:[...c.querySelectorAll('label')].map(e=>e.getBoundingClientRect().height),
                    overflow:document.documentElement.scrollWidth>innerWidth};})()''' % json.dumps(day + ' .options'))
                self.assertFalse(geometry['overflow'], geometry)
                self.assertTrue(all(44 <= h <= 90 for h in geometry['heights']), geometry)
                if width == 1366:
                    self.assertAlmostEqual(geometry['py'], geometry['cy'], delta=2)
                    self.assertGreater(geometry['cx'], geometry['pr'])
                else:
                    self.assertEqual(geometry['cols'], 1)
                    self.assertGreater(geometry['cy'], geometry['py'])
                evaluate('document.querySelector(' + json.dumps(photo) + ').scrollIntoView({block:"center"})')
                browser.take_screenshot(prefix=f'lf191_mosaico_{width}_').result(timeout=10)
                pointer(photo + ' .option-copy')
                wait(f'!document.querySelector({json.dumps(day)}).open')
                visible = evaluate('''(()=>{const s=document.querySelector(%s),v=document.querySelector('.week-scroll').getBoundingClientRect(),
                    r=s.getBoundingClientRect(),d=s.querySelector('.draft-choice').getBoundingClientRect();
                    return {top:r.top,bottom:r.bottom,vt:v.top,vb:v.bottom,dt:d.top,db:d.bottom,focus:document.activeElement===s};})()''' % json.dumps(day + ' summary'))
                self.assertTrue(visible['focus'], visible)
                self.assertGreaterEqual(visible['top'], visible['vt'] - 1, visible)
                self.assertLessEqual(visible['bottom'], visible['vb'] + 1, visible)
                self.assertLessEqual(visible['db'], visible['vb'] + 1, visible)
                self.assertIn('Sin guardar:', evaluate('document.querySelector(' + json.dumps(day + ' .draft-choice') + ').textContent'))
                browser.take_screenshot(prefix=f'lf191_plegado_{width}_').result(timeout=10)
                pointer('.save-bar button')
                wait('document.querySelector(".success")')
            self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey, width=width)
            self.env.invalidate_all()
            record = self.env['lafija.reservation'].search([('employee_partner_id', '=', employee.partner_id.id), ('menu_id', '=', self.menus[0].id)])
            self.assertEqual(record.current_product_id, self.product)

    def test_keyboard_after_opening_header_keeps_options_open_and_follows_dom(self):
        compact = self._mixed()
        employee, _ = self._create_employee()
        self.env['lafija.reservation'].with_user(employee)._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        self._real_login(employee.login, 'employee-password-123')
        day = f'[data-menu="{self.menus[0].id}"]'
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector("#lf-week-form")')
            if evaluate(f'document.querySelector({json.dumps(day)}).open'):
                pointer(day + ' summary')
            pointer(day + ' summary')
            wait(f'document.querySelector({json.dumps(day)}).open')
            for _ in range(10):
                if evaluate('document.activeElement?.matches("input[type=radio]")'):
                    break
                self._key(browser, 'Tab', 9)
            self.assertTrue(evaluate('document.activeElement?.matches("input[type=radio]")'))
            self._key(browser, 'ArrowRight', 39)
            self.assertTrue(evaluate(f'document.querySelector({json.dumps(day)}).open'))
            self.assertEqual(evaluate('document.activeElement.value'), str(compact[0].id))
            self._key(browser, 'ArrowLeft', 37)
            self.assertTrue(evaluate(f'document.querySelector({json.dumps(day)}).open'))
            self.assertEqual(evaluate('document.activeElement.value'), str(self.product.id))
        self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey, width=390)

    def test_uniform_and_mixed_cards_use_available_columns(self):
        compact = self._mixed()
        products = self.product + compact
        employee, _ = self._create_employee()
        for photo_count in (4, 0, 2, 3):
            # Cada formulario de producto cambia una imagen: no depender de la
            # inversa de image_1920 sobre un recordset con varias plantillas.
            for index, product in enumerate(products):
                product.image_1920 = self._photos() if index < photo_count else False
            self.env.invalidate_all()
            self.assertEqual(sum(bool(p.image_1024) for p in products), photo_count)
            self._real_login(employee.login, 'employee-password-123')
            def journey(browser, evaluate, wait, pointer, _type):
                day = f'[data-menu="{self.menus[0].id}"]'
                wait(f'document.querySelector({json.dumps(day)})')
                if not evaluate(f'document.querySelector({json.dumps(day)}).open'):
                    pointer(day + ' summary')
                group = day + (' .photo-options' if photo_count else ' .compact-options')
                if photo_count:
                    wait(f'[...document.querySelectorAll({json.dumps(group + " img")})].every(i=>i.naturalWidth>0)')
                actual = evaluate('''(()=>{const g=document.querySelector(%s),r=[...g.querySelectorAll('label')].map(e=>e.getBoundingClientRect());
                    return {cols:getComputedStyle(g).gridTemplateColumns.split(' ').length,y:r.slice(0,%s).map(e=>e.y),
                    width:r.map(e=>e.width),overflow:document.documentElement.scrollWidth>innerWidth};})()''' % (json.dumps(group), 2 if photo_count == 2 else 3))
                self.assertEqual(actual['cols'], 2 if photo_count == 2 else 3, actual)
                self.assertLess(max(actual['y']) - min(actual['y']), 2)
                self.assertLess(max(actual['width']) - min(actual['width']), 2)
                self.assertFalse(actual['overflow'])
                evaluate('document.querySelector(' + json.dumps(group) + ').scrollIntoView({block:"start"})')
                browser.take_screenshot(prefix=f'lf191_mosaico_{photo_count}_fotos_').result(timeout=10)
            self._employee_pointer_journey('/my/viandas?week=2026-09-14', journey, width=1366)

    def test_two_refreshes_same_minute_replace_notice_after_reload_without_navigation(self):
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({
            'customer_company_id': self.customer.id, 'date_from': '2026-08-01', 'date_to': '2026-08-31'})
        batch.action_refresh()
        self._backend()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector(".lf-quotation-summary")')
            before = evaluate('({url:location.href,crumbs:document.querySelectorAll(".breadcrumb-item").length})')
            evaluate('''window.lf191Seen=new WeakSet();window.lf191Notices=0;
                window.lf191Observer=new MutationObserver(()=>document.querySelectorAll('.o_notification').forEach(e=>{
                    if(e.textContent.includes('Resumen actualizado.')&&!window.lf191Seen.has(e)){
                        window.lf191Seen.add(e);window.lf191Notices++;}}));
                window.lf191Observer.observe(document.body,{subtree:true,childList:true});''')
            for count in (1, 2):
                pointer('button[name=action_refresh]')
                wait(f'window.lf191Notices === {count}')
                wait('document.querySelector(".lf-quotation-summary")')
                self.assertEqual(evaluate('document.querySelectorAll(".o_notification").length'), 1)
                self.assertEqual(evaluate('getComputedStyle(document.querySelector(".lf-quotation-feedback")).pointerEvents'), 'none')
                self.assertEqual(evaluate('getComputedStyle(document.querySelector(".lf-quotation-feedback .o_notification_close")).display'), 'none')
                self.assertFalse(evaluate('Boolean(document.querySelector(".modal"))'))
                self.assertEqual(evaluate('({url:location.href,crumbs:document.querySelectorAll(".breadcrumb-item").length})'), before)
            browser.take_screenshot(prefix='lf191_resumen_confirmado_').result(timeout=10)
            wait('!document.querySelector(".o_notification")')
            evaluate('window.lf191Observer.disconnect()')
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertFalse(batch.order_id)

    def test_titles_are_the_ones_displayed_by_the_web_client(self):
        self._backend()
        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector(".o_list_view")')
            wait('document.querySelector(".o_breadcrumb")?.textContent.includes("Hoy ·")')
            pointer('[data-menu-xmlid="kai_viandas.menu_days"]')
            wait('document.querySelector(".o_breadcrumb")?.textContent.includes("Menús del día")')
            pointer('[data-menu-xmlid="kai_viandas.menu_employees_group"]')
            pointer('[data-menu-xmlid="kai_viandas.menu_employees"]')
            wait('document.querySelector(".o_breadcrumb")?.textContent.includes("Empleados")')
            browser.take_screenshot(prefix='lf191_titulos_').result(timeout=10)
        action = self.env.ref('kai_viandas.workday_action').id
        self._employee_pointer_journey(f'/odoo/action-{action}', journey, width=1366, login=self.operator.login)
