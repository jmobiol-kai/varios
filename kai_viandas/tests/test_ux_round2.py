import json
import threading
import time
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from markupsafe import Markup

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser

from .test_pages import PagesCommon


@tagged('post_install', '-at_install')
class TestUXRound2(PagesCommon):
    def _json_call(self, url, params):
        response = self.url_open(url, headers={'Host': 'public.test'}, json={
            'jsonrpc': '2.0', 'id': 1, 'params': params})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('error', payload, payload)
        return payload['result']

    def test_operator_methods_and_web_action_execution_without_system(self):
        self.assertFalse(self.operator.has_group('base.group_system'))
        action = self.env['lafija.menu.day'].with_user(self.operator).action_workday()
        self.assertEqual(action['res_model'], 'lafija.reservation')
        alta = self.env['res.partner'].with_user(self.operator).action_lf_create_employee()
        self.assertEqual(alta['res_model'], 'lafija.employee.access')
        with self.assertRaises(AccessError):
            self.env['lafija.menu.day'].with_user(self.private).action_workday()
        self.authenticate(self.operator.login, 'fixture')
        self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
        loaded = self._json_call('/web/action/load', {'action_id': 'kai_viandas.workday_action'})
        result = self._json_call('/web/action/run', {'action_id': loaded['id']})
        self.assertEqual(result['res_model'], 'lafija.reservation')
        loaded = self._json_call('/web/action/load', {'action_id': 'kai_viandas.employee_access_action'})
        self.assertEqual(loaded['res_model'], 'lafija.employee.access')
        result = self._json_call('/web/dataset/call_button', {
            'model': 'res.partner', 'method': 'action_lf_create_employee', 'args': [[]], 'kwargs': {}})
        self.assertEqual(result['res_model'], 'lafija.employee.access')

    def test_expired_login_form_gets_new_csrf_without_authentication(self):
        employee, _ = self._create_employee()
        self._anonymous()
        response = self.url_open('/web/login', data={'csrf_token': 'stale-token',
            'login': employee.login, 'password': 'DO-NOT-REFLECT-ME', 'type': 'password'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('El formulario venció', response.text)
        self.assertNotIn('DO-NOT-REFLECT-ME', response.text)
        tree = html.fromstring(response.content)
        token = tree.xpath('//input[@name="csrf_token"]/@value')[0]
        self.assertNotEqual(token, 'stale-token')
        result = self.url_open('/web/login', data={'csrf_token': token, 'login': employee.login,
            'password': 'employee-password-123', 'type': 'password'}, allow_redirects=False)
        self.assertEqual(result.status_code, 303)
        self._manage(employee, 'disable').action_apply()
        self._anonymous()
        page = self.url_open('/web/login')
        token = html.fromstring(page.content).xpath('//input[@name="csrf_token"]/@value')[0]
        denied = self.url_open('/web/login', data={'csrf_token': token, 'login': employee.login,
            'password': 'employee-password-123', 'type': 'password'})
        self.assertEqual(denied.status_code, 200)
        self.assertIn('No se pudo iniciar sesión', denied.text)
        self.assertIn('recuperar el acceso', denied.text)

    def test_preselected_current_pending_and_manual_choice_survive_resave(self):
        employee, _ = self._create_employee()
        service = self.env['lafija.reservation'].with_user(employee)
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        record._request_correction('Consulta sin responder')
        self._real_login(employee.login, 'employee-password-123')
        def resave(expected):
            page = self.url_open('/my/viandas?week=2026-09-14')
            doc = html.fromstring(page.content)
            checked = doc.xpath(f'//input[@name="menu_{self.menus[0].id}" and @checked]/@value')
            self.assertEqual(checked, [str(expected.id)])
            self.assertNotIn('Mantener:', page.text)
            token = doc.xpath('//input[@name="csrf_token"]/@value')[0]
            self.env.invalidate_all()
            before = record.sudo().event_ids.ids
            result = self.url_open('/my/viandas/reservar', data={'csrf_token': token,
                'week': '2026-09-14', f'menu_{self.menus[0].id}': str(expected.id)})
            self.assertIn('No hiciste cambios', result.text)
            self.env.invalidate_all()
            self.assertEqual(record.sudo().event_ids.ids, before)
            self.assertTrue(record.sudo().attention_pending)
        resave(self.product)
        self.product.description_sale = 'Nueva descripción para elecciones futuras'
        self.menus[0].with_user(self.operator).action_refresh_options()
        page = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
        selected_card = page.xpath(f'//input[@name="menu_{self.menus[0].id}" and @checked]/parent::label')[0]
        self.assertIn(record.sudo().current_description, selected_card.text_content())
        self.assertNotIn('Nueva descripción para elecciones futuras', selected_card.text_content())
        alternate = self.env['product.product'].create({'name': 'Pescado', 'sale_ok': True})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(alternate.id)]})
        self.menus[0].with_user(self.operator).action_take_list()
        service._submit_selections(self.website, [(self.menus[0].id, alternate.id)])
        resave(alternate)
        self.assertEqual(record.sudo().pending_product_id, alternate)
        outside = self.env['product.product'].create({'name': 'Plan B', 'sale_ok': True})
        self.env['lafija.reservation.correction'].with_user(self.operator).create({
            'reservation_id': record.id, 'operation': 'replace', 'product_id': outside.id,
            'reason': 'Se agotó la opción'}).action_apply()
        resave(outside)
        with self.assertRaises(ValidationError):
            service._submit_selections(self.website, [(self.menus[1].id, outside.id)])

    def test_public_history_has_safe_resolutions_without_internal_reason(self):
        employee, _ = self._create_employee()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        for operation in ('note', 'close_request', 'replace'):
            self.env['lafija.reservation.correction'].with_user(self.operator).create({
                'reservation_id': record.id, 'operation': operation, 'product_id': self.product.id,
                'reason': 'SECRETO-INTERNO: importe 918273', 'employee_message': 'Atendido.'}).action_apply()
        values = record._employee_values()
        labels = [c['outcome'] for c in values['choices']]
        self.assertIn('Respuesta sin cierre', labels)
        self.assertIn('Solicitud cerrada', labels)
        self.assertIn('Opción corregida', labels)
        self.assertNotIn('SECRETO-INTERNO', json.dumps(values))
        self.assertNotIn('918273', json.dumps(values))

    def test_summary_keeps_distinct_products_and_counter_is_per_date(self):
        employee, _ = self._create_employee()
        other, _ = self._create_employee('abc-otro')
        p2 = self.env['product.product'].create({'name': 'Otro producto', 'description_sale': 'Pollo con arroz'})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(p2.id)]})
        records = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        records |= self.env['lafija.reservation'].with_user(other)._submit_selections(
            self.website, [(self.menus[0].id, p2.id)]).with_user(employee)
        cut_action = self.menus[0].with_user(self.operator).action_take_list()
        cut = self.env['lafija.preparation.cut'].browse(cut_action['res_id'])
        self.assertIn('Otro producto: 1', cut.option_summary)
        self.assertIn('Vianda prueba P1: 1', cut.option_summary)
        cls = type(records)
        original = cls.search_count
        calls = []
        def counted(rec, domain, *args, **kwargs):
            calls.append(domain)
            return original(rec, domain, *args, **kwargs)
        with patch.object(cls, 'search_count', counted):
            records.with_user(self.operator)._compute_local_display()
        self.assertEqual(len(calls), 1)
        self.assertEqual(records.sudo().mapped('week_label'), ['14/09/2026 al 20/09/2026'] * 2)

    def test_manual_invoice_inherits_reservation_provenance(self):
        employee, _ = self._create_employee()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        order = self.env['sale.order'].with_user(self.operator).create({
            'partner_id': self.customer.id, 'lf_reservation_ids': [Command.set(record.ids)],
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1})]})
        values = order._prepare_invoice()
        self.assertTrue(values['lf_protected'])
        self.assertEqual(values['lf_reservation_ids'], [Command.set(record.ids)])

    def test_week_and_upcoming_filters_use_business_day_at_utc_boundary(self):
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.operator.tz = 'UTC'
        employee, _ = self._create_employee()
        menus = self.env['lafija.menu.day'].with_user(self.operator).create([
            {'date': date, 'website_id': self.website.id, 'product_ids': [Command.set(self.product.ids)]}
            for date in ('2026-09-02', '2026-09-09', '2026-09-13')])
        menus.action_publish()
        # Historial legítimo: las elecciones se hicieron antes de esas fechas.
        with freeze_time('2026-09-01 15:00:00'):
            records = self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(m.id, self.product.id) for m in menus | self.menus[:1]])
        model = self.env['lafija.reservation'].with_user(self.operator)
        scope = [('id', 'in', records.ids)]
        with freeze_time('2026-09-14 02:30:00'):
            # UTC ya es lunes; en La Fija todavía es domingo 13.
            self.assertEqual(model.search(scope + [('is_today', '=', True)]).date.isoformat(), '2026-09-13')
            self.assertEqual(set(model.search(scope + [('business_week', '=', 0)]).mapped('date')),
                             set(menus[1:].mapped('date')))
            self.assertEqual(model.search(scope + [('business_week', '=', 1)]).date.isoformat(), '2026-09-14')
            self.assertEqual(model.search(scope + [('business_week', '=', -1)]).date.isoformat(), '2026-09-02')
            self.assertEqual(set(model.search(scope + [('is_upcoming', '=', True)]).mapped('date')),
                             {menus[-1].date, self.menus[0].date})
            self.assertEqual(menus.search([('id', 'in', menus.ids), ('is_upcoming', '=', True)]), menus[-1])

    def _pointer_browser(self, url, script, login, min_clicks=1, viewport=None, cookies=None):
        """El JS pide coordenadas; Chrome recibe eventos reales de puntero por CDP.

        No se invoca HTMLElement.click(). El objeto del navegador es el de esta
        base de pruebas, nunca el Chrome compartido del E2E.
        """
        original = ChromeBrowser._wait_code_ok
        counts = []
        def with_pointer(browser, code, timeout, **kwargs):
            browser._websocket_request('Emulation.setTimezoneOverride', params={'timezoneId': 'UTC'})
            if viewport:
                browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                    'width': viewport[0], 'height': viewport[1], 'deviceScaleFactor': 1, 'mobile': False})
            stop = threading.Event()
            def drive():
                while not stop.wait(.05):
                    try:
                        reply = browser._websocket_request('Runtime.evaluate', params={
                            'expression': 'window.lfPointer || null', 'returnByValue': True})
                        point = reply['result'].get('value')
                        if not point:
                            keys = browser._websocket_request('Runtime.evaluate', params={
                                'expression': 'window.lfKeys || null', 'returnByValue': True})['result'].get('value')
                            if keys:
                                for char in keys:
                                    browser._websocket_request('Input.dispatchKeyEvent', params={
                                        'type': 'keyDown', 'key': char, 'text': char})
                                    browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyUp', 'key': char})
                                browser._websocket_request('Runtime.evaluate', params={
                                    'expression': 'window.lfKeys=null; window.lfKeysDone=true;'})
                            continue
                        for kind in ('mousePressed', 'mouseReleased'):
                            browser._websocket_request('Input.dispatchMouseEvent', params={
                                'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})
                        counts.append(point)
                        browser._websocket_request('Runtime.evaluate', params={
                            'expression': 'window.lfPointer=null; window.lfPointerDone=true;'})
                    except Exception:
                        if stop.is_set():
                            break
            thread = threading.Thread(target=drive, daemon=True)
            thread.start()
            try:
                return original(browser, code, timeout, **kwargs)
            finally:
                stop.set()
                thread.join(timeout=5)
        helper = r'''
            const wait = async (fn, label) => {
                for (let n=0; n<200; n++) { const v=fn(); if(v) return v; await new Promise(r=>setTimeout(r,50)); }
                throw new Error(label);
            };
            const visible = e => e && e.getClientRects().length;
            const pointer = async el => {
                if (!visible(el)) throw new Error('Objetivo no visible');
                el.scrollIntoView({block:'center'});
                await new Promise(r=>setTimeout(r,120));
                const b=el.getBoundingClientRect(), x=b.x+b.width/2, y=b.y+b.height/2;
                if (!el.contains(document.elementFromPoint(x,y))) throw new Error('Otro elemento tapa el objetivo');
                window.lfPointerDone=false; window.lfPointer={x,y};
                await wait(()=>window.lfPointerDone,'No llegó el clic de puntero');
            };
            const typeKeys = async (el, text) => {
                await pointer(el);
                window.lfKeysDone=false; window.lfKeys=text;
                await wait(()=>window.lfKeysDone,'No llegó la escritura por teclado');
            };
        '''
        with patch.object(ChromeBrowser, '_wait_code_ok', with_pointer):
            self.browser_js(url, '(async()=>{' + helper + script + "console.log('test successful');})().catch(e=>console.error(e.message));",
                            login=login, timeout=120, cookies=cookies)
        self.assertGreaterEqual(len(counts), min_clicks)

    def test_pointer_operator_today_and_both_employee_creation_entries(self):
        self.website.domain = 'http://corporate.test'
        # Liberar primero la URL de prueba: un UPDATE conjunto puede chocar con
        # la unicidad inmediata de domain aunque el estado final sea válido.
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser('/odoo/action-kai_viandas.workday_action', r'''
            await wait(()=>document.querySelector('.o_list_view'),'Hoy no abrió una lista');
            if(document.querySelector('.o_error_dialog')) throw new Error('Hoy dio error');
            await pointer(await wait(()=>document.querySelector('[data-menu-xmlid="kai_viandas.menu_employees_group"]'),'Falta grupo Empleados'));
            const menu=await wait(()=>[...document.querySelectorAll('a')].find(e=>visible(e)&&e.textContent.trim()==='Empleados corporativos'),'Falta menú empleados');
            await pointer(menu);
            if([...document.querySelectorAll('button[name="action_lf_create_employee"]')].some(visible)) throw new Error('Sigue el botón Alta de empleado');
            const nuevo=await wait(()=>[...document.querySelectorAll('button')].find(e=>visible(e)&&/Nuevo/.test(e.textContent)),'Falta Nuevo en la lista');
            await pointer(nuevo);
            await wait(()=>document.querySelector('.o_form_view .o_field_widget[name="lf_new_password"]'),'No abrió el formulario de alta');
            if([...document.querySelectorAll('a')].some(e=>visible(e)&&e.textContent.trim()==='Alta de empleado')) throw new Error('Sigue el menú Alta de empleado');
        ''', self.operator.login, min_clicks=3)

    def test_pointer_week_rows_and_radios_are_not_covered_at_mobile_widths(self):
        employee, _ = self._create_employee()
        for width,height in ((1366,900),(390,844),(360,800)):
            self._real_login(employee.login, 'employee-password-123')
            sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
            self._pointer_browser('/my/viandas?week=2026-09-14', r'''
                const days=[...document.querySelectorAll('details.day')];
                if(days.length!==5) throw new Error('Faltan días');
                for(const index of [1,3,4]) {
                    await pointer(days[index].querySelector('summary'));
                    const radio=days[index].querySelector('input[type=radio][value]:not([value=""])');
                    await pointer(radio);
                    if(!radio.checked) throw new Error('El puntero no seleccionó la opción');
                }
                if(getComputedStyle(document.querySelector('.save-bar')).position!=='static') throw new Error('Guardar no está en flujo');
                if(document.documentElement.scrollWidth>innerWidth) throw new Error('Desborde horizontal');
            ''', None, min_clicks=6, viewport=(width,height), cookies={'session_id': sid})

    def test_chatter_business_clock_with_browser_in_utc_and_native_fallback(self):
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        employee, _ = self._create_employee()
        message = employee.partner_id.with_user(self.operator).message_post(body=Markup('<p>Reloj de evaluación</p>'))
        message.sudo().write({'date': '2026-09-12 12:30:00'})
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.employee_action/{employee.partner_id.id}', r'''
            await wait(()=>[...document.querySelectorAll('.o-mail-Message-date')].some(e=>e.textContent.includes('12/09/2026 09:30')),'Chatter no convirtió a hora de La Fija');
            const date=[...document.querySelectorAll('.o-mail-Message-date')].find(e=>e.textContent.includes('12/09/2026 09:30'));
            if(!date.title.includes('America/Argentina/Buenos_Aires')) throw new Error('Tooltip sin zona');
            const {Message}=odoo.loader.modules.get('@mail/core/common/message_model');
            const getter=Object.getOwnPropertyDescriptor(Message.prototype,'datetime').get;
            const utc=luxon.DateTime.fromISO('2026-09-12T12:30:00',{zone:'utc'});
            if(getter.call({date:utc}).hour!==12) throw new Error('Cambió el reloj nativo de otros registros');
            await pointer(await wait(()=>document.querySelector('button[name="action_lf_manage_access"]'),'No abrió ficha'));
        ''', self.operator.login)
