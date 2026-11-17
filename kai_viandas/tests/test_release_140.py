"""Caché por contenido, pantallas vacías y borrador atómico recuperable."""
import json
import time
from pathlib import Path
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree, html

from odoo import Command
from odoo.tests import Form, tagged
from odoo.tests.common import ChromeBrowser

from ..models.portal_resources import resource_url
from .test_pages import PagesCommon
from .test_identity import LafijaCommon
from .test_ux_round2 import TestUXRound2


@tagged('post_install', '-at_install')
class TestPresentation140(LafijaCommon):
    def test_resource_fingerprint_tracks_bytes_and_reads_once_per_process(self):
        try:
            resource_url.cache_clear()
            with patch.object(Path, 'read_bytes', return_value=b'first') as read:
                first = resource_url('viandas.js')
                self.assertEqual(resource_url('viandas.js'), first)
                read.assert_called_once()
            resource_url.cache_clear()
            with patch.object(Path, 'read_bytes', return_value=b'first'):
                self.assertEqual(resource_url('viandas.js'), first)
            resource_url.cache_clear()
            with patch.object(Path, 'read_bytes', return_value=b'changed'):
                self.assertNotEqual(resource_url('viandas.js'), first)
            with self.assertRaises(ValueError):
                resource_url('../../config')
        finally:
            resource_url.cache_clear()

    def test_empty_actions_are_truthful_even_when_other_dates_have_pending(self):
        actions = self.env['ir.actions.act_window'].with_user(self.operator)
        for xmlid, model in [('reservation_action', 'lafija.reservation'),
                             ('pending_action', 'lafija.reservation'), ('cut_action', 'lafija.preparation.cut')]:
            action = actions._for_xml_id('kai_viandas.' + xmlid)
            help_text = self.env[model].with_user(self.operator).get_empty_list_help(action['help'])
            self.assertNotIn('Create new', help_text)
            self.assertNotIn('Crear nuevo', help_text)
            self.assertIn('filtros', help_text)
        with freeze_time('2026-09-13 15:00:00'):
            action = self.env['lafija.menu.day'].with_user(self.operator).action_workday()
        self.assertIn('Domingo 13/09', action['name'])
        self.assertIn('Puede haber solicitudes de otras fechas', action['help'])
        self.assertNotIn('sin pendientes', action['help'].lower())

    def test_new_menu_title_buttons_and_message_captions(self):
        menu = self.env['lafija.menu.day'].with_user(self.operator)
        with Form(menu, view='kai_viandas.menu_day_form') as form:
            self.assertEqual(form.day_title, 'Nuevo menú del día')
            form.date = '2026-11-02'
            self.assertIn('Lunes 2/11', form.day_title)
        view = menu.get_view(self.env.ref('kai_viandas.menu_day_form').id, 'form')
        arch = etree.fromstring(view['arch'].encode())
        for name in ('action_publish', 'action_refresh_options', 'action_take_list'):
            button = arch.xpath(f'//button[@name="{name}"]')[0]
            self.assertIn('not date', button.get('invisible'))
            self.assertIn('not website_id', button.get('invisible'))
            self.assertNotIn('not id', button.get('invisible'))
        for model, xmlid in [('lafija.menu.day', 'menu_day_form'), ('lafija.reservation', 'reservation_form')]:
            arch = etree.fromstring(self.env[model].with_user(self.operator).get_view(
                self.env.ref('kai_viandas.' + xmlid).id, 'form')['arch'].encode())
            self.assertEqual(len(arch.xpath('//sheet/div[text()="Mensajes · hora de La Fija"]')), 1)
            self.assertFalse(arch.xpath('//form/div[contains(text(), "hora de La Fija")]'))


@tagged('post_install', '-at_install')
class TestConflict140(PagesCommon):
    _pointer_browser = TestUXRound2._pointer_browser

    def _setup_pending(self, outside=False):
        employee, _ = self._create_employee()
        service = self.env['lafija.reservation'].with_user(employee)
        monday = self.menus[0]
        record = service._submit_selections(self.website, [(monday.id, self.product.id)])
        current = self.product
        if outside:
            current = self.env['product.product'].create({'name': 'Guiso propio anterior', 'sale_ok': True})
            self._operator_replace(record, current)
        alternate = self.env['product.product'].create({'name': 'Cerdo del menú', 'sale_ok': True})
        monday.with_user(self.operator).write({'product_ids': [Command.link(alternate.id)]})
        monday.with_user(self.operator).action_take_list()
        service._submit_selections(self.website, [(monday.id, alternate.id)])
        record._request_correction('Consulta que no debe cerrarse')
        self._real_login(employee.login, 'employee-password-123')
        return employee, record, current, alternate

    def _operator_replace(self, record, product):
        return self.env['lafija.reservation.correction'].with_user(self.operator).create({
            'reservation_id': record.id, 'operation': 'replace', 'product_id': product.id,
            'reason': 'Motivo interno 918273',
        }).action_apply()

    def _page(self):
        return html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)

    def _post_data(self, page, current):
        return {'csrf_token': page.xpath('//input[@name="csrf_token"]/@value')[0],
                'form_choices': page.xpath('//input[@name="form_choices"]/@value')[0],
                'week': '2026-09-14',
                f'menu_{self.menus[3].id}': str(self.product.id),
                f'menu_{self.menus[1].id}': str(self.product.id),
                f'menu_{self.menus[0].id}': str(current.id),
                f'withdraw_{self.menus[0].id}': str(current.id)}

    def test_fingerprinted_resources_on_login_week_detail_and_errors(self):
        expected = [resource_url('viandas.css'), resource_url('viandas.js')]
        def check(response):
            tree = html.fromstring(response.content)
            urls = tree.xpath('//link[@rel="stylesheet"]/@href | //script[@src]/@src')
            for url in expected:
                self.assertIn(url, urls)
            self.assertNotIn('/web/assets/', response.text)
        self._anonymous()
        check(self.url_open('/web/login'))
        check(self.url_open('/web/login', data={'csrf_token': 'expired'}))
        employee, record, _, _ = self._setup_pending()
        check(self.url_open('/my/viandas?week=2026-09-14'))
        check(self.url_open(f'/my/viandas/{record.id}'))
        token = self._page().xpath('//input[@name="csrf_token"]/@value')[0]
        check(self.url_open('/my/viandas/reservar', data={'csrf_token': token, 'menu_bad': 'bad'}))
        check(self.url_open(f'/my/viandas/{record.id}/correccion', data={'csrf_token': token, 'message': ''}))
        self.assertEqual(self.url_open('/web/assets/anything/test.js').status_code, 403)

    def test_conflict_preserves_three_drafts_and_atomicity_then_second_save_succeeds(self):
        employee, record, current, alternate = self._setup_pending()
        data = self._post_data(self._page(), current)
        self._operator_replace(record, alternate)
        events = record.sudo().event_ids.ids
        cut = self.menus[0].cut_ids
        revision = cut.current_revision_id
        response = self.url_open('/my/viandas/reservar', data=data, allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/my/viandas?week=', response.headers['Location'])
        self.env.invalidate_all()
        self.assertEqual(record.sudo().event_ids.ids, events)
        self.assertTrue(record.sudo().attention_pending)
        self.assertEqual(cut.current_revision_id, revision)
        service = self.env['lafija.reservation'].with_user(employee)
        self.assertFalse(service.search([('date', 'in', self.menus[1:2].mapped('date') + self.menus[3:4].mapped('date'))]))
        for _ in range(2):  # Recargar GET conserva el borrador, no vuelve a enviar.
            page = self._page()
            self.assertIn('No se guardó ningún día', page.text_content())
            self.assertIn('3 días sin guardar', page.text_content())
            self.assertEqual(page.xpath('//details[@open]/@data-menu'), [str(self.menus[0].id)])
            for menu in (self.menus[0], self.menus[1], self.menus[3]):
                self.assertEqual(page.xpath(f'//input[@name="menu_{menu.id}" and @checked]/@value'), [str(current.id)])
            self.assertNotIn('918273', page.text_content())
        retry = self._post_data(page, current)
        retry.pop(f'withdraw_{self.menus[0].id}')
        response = self.url_open('/my/viandas/reservar', data=retry)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('No se guardó ningún día', response.text)
        self.env.invalidate_all()
        self.assertEqual(record.sudo().current_product_id, alternate)
        self.assertEqual(record.sudo().pending_product_id, current)
        self.assertEqual(len(service.search([])), 3)
        self.assertTrue(record.sudo().attention_pending)
        self.assertEqual(cut.current_revision_id, revision)
        self.assertNotIn('Descartar este borrador', self.url_open('/my/viandas?week=2026-09-14').text)

    def test_outside_old_choice_is_named_without_image_or_new_eligibility_and_can_discard(self):
        employee, record, current, alternate = self._setup_pending(outside=True)
        data = self._post_data(self._page(), current)
        self._operator_replace(record, alternate)
        response = self.url_open('/my/viandas/reservar', data=data)
        self.assertEqual(response.status_code, 200)
        tree = html.fromstring(response.content)
        card = tree.xpath('//input[@data-unavailable="1"]/parent::label')[0]
        self.assertIn(current.name, card.text_content())
        self.assertFalse(card.xpath('.//img'))
        self.assertIn('elegir una opción actual', card.text_content())
        self.assertEqual(self.url_open(f'/my/viandas/opcion/{current.id}/imagen?menu_id={self.menus[0].id}').status_code, 404)
        retry = self._post_data(tree, current)
        retry.pop(f'withdraw_{self.menus[0].id}')
        self.assertEqual(self.url_open('/my/viandas/reservar', data=retry).status_code, 400)
        before = record.sudo().event_ids.ids
        self.url_open('/my/viandas?week=2026-09-14&discard_draft=1')
        self.assertNotIn('Descartar este borrador', self.url_open('/my/viandas?week=2026-09-14').text)
        self.env.invalidate_all()
        self.assertEqual(record.sudo().event_ids.ids, before)
        self.assertEqual(record.sudo().current_product_id, alternate)

    def test_manipulated_conflict_does_not_reveal_foreign_product_or_preserve_it(self):
        employee, record, current, alternate = self._setup_pending()
        page = self._page()
        data = self._post_data(page, current)
        self._operator_replace(record, alternate)
        foreign = self.env['product.product'].create({'name': 'AJENO-918273', 'list_price': 918273})
        for mutation in ('foreign_other_day', 'forged_signature', 'other_employee_signature'):
            tampered = dict(data)
            if mutation == 'foreign_other_day':
                tampered[f'menu_{self.menus[3].id}'] = str(foreign.id)
            elif mutation == 'forged_signature':
                tampered['form_choices'] += '0'
            else:
                other, _ = self._create_employee('otra-cuenta-140')
                # Un formulario legítimo de otra cuenta tampoco acredita esta elección.
                self._real_login(other.login, 'employee-password-123')
                token = self._page().xpath('//input[@name="form_choices"]/@value')[0]
                self._real_login(employee.login, 'employee-password-123')
                tampered['csrf_token'] = self._page().xpath('//input[@name="csrf_token"]/@value')[0]
                tampered['form_choices'] = token
            response = self.url_open('/my/viandas/reservar', data=tampered)
            self.assertEqual(response.status_code, 400, mutation)
            self.assertNotIn(foreign.name, response.text)
            self.assertNotIn('Descartar este borrador', response.text)
        self.env.invalidate_all()
        self.assertEqual(record.sudo().current_product_id, alternate)
        self.assertEqual(len(self.env['lafija.reservation'].with_user(employee).search([])), 1)

    def test_pointer_conflict_keeps_drafts_after_back_and_saves_them_together(self):
        employee, record, current, alternate = self._setup_pending()
        sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
        original = ChromeBrowser._wait_code_ok
        def journey(browser, code, timeout, **kwargs):
            browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                'width': 360, 'height': 800, 'deviceScaleFactor': 1, 'mobile': False})
            def evaluate(expression):
                return browser._websocket_request('Runtime.evaluate', params={
                    'expression': expression, 'returnByValue': True}).get('result', {}).get('value')
            def wait(expression):
                for _ in range(240):
                    if evaluate(expression):
                        return
                    time.sleep(.05)
                self.fail(expression)
            def pointer(selector):
                target = 'document.querySelector(' + json.dumps(selector) + ')'
                evaluate(target + '.scrollIntoView({block:"center"})')
                time.sleep(.15)
                point = evaluate('(()=>{const e=' + target + ';const r=e.getBoundingClientRect();'
                    'const x=r.x+r.width/2,y=r.y+r.height/2;return {x,y,clear:e.contains(document.elementFromPoint(x,y))};})()')
                self.assertTrue(point['clear'], selector)
                for kind in ('mousePressed', 'mouseReleased'):
                    browser._websocket_request('Input.dispatchMouseEvent', params={
                        'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})
                time.sleep(.12)
            wait('document.querySelector("#lf-week-form")')
            # El operador actúa después de cargar el formulario, antes de los toques.
            self._operator_replace(record, alternate)
            for menu in (self.menus[0], self.menus[1], self.menus[3]):
                selector = json.dumps(f'[data-menu="{menu.id}"]')
                if not evaluate(f'document.querySelector({selector})?.open'):
                    pointer(f'[data-menu="{menu.id}"] summary')
                pointer(f'[data-menu="{menu.id}"] label:has(input[value="{current.id}"])')
            pointer('.save-bar button')
            wait('document.querySelector(".day-conflict") && document.readyState==="complete"')
            wait('document.querySelector("[data-save-state]").textContent.includes("3 días sin guardar")')
            self.assertEqual(evaluate('document.querySelector("details[open]").dataset.menu'), str(self.menus[0].id))
            self.assertTrue(evaluate('document.querySelector(".day-state").textContent.includes("Cerdo")'))
            self.assertEqual(evaluate('document.querySelector("details.day input:checked").value'), str(current.id))
            history = browser._websocket_request('Page.getNavigationHistory')
            conflict_entry = history['entries'][history['currentIndex']]['id']
            browser._websocket_request('Page.navigate', params={'url': self.base_url() + f'/my/viandas/{record.id}'})
            wait('document.querySelector(".lf-correction-form")')
            browser._websocket_request('Page.navigateToHistoryEntry', params={'entryId': conflict_entry})
            wait('document.querySelector(".day-conflict") && !document.querySelector(".save-bar button").disabled')
            wait('document.querySelector("[data-save-state]").textContent.includes("3 días sin guardar")')
            pointer('.save-bar button')
            wait('document.querySelector(".success")?.textContent.includes("recibido para revisión")')
            self.assertFalse(evaluate('!!document.querySelector(".day-conflict")'))
            return original(browser, code, timeout, **kwargs)
        with patch.object(ChromeBrowser, '_wait_code_ok', journey):
            self.browser_js('/my/viandas?week=2026-09-14', "console.log('test successful');",
                            login=None, cookies={'session_id': sid}, timeout=90)
        self.env.invalidate_all()
        self.assertEqual(len(self.env['lafija.reservation'].with_user(employee).search([])), 3)
        self.assertEqual(record.sudo().pending_product_id, current)
        self.assertTrue(record.sudo().attention_pending)

    def test_pointer_empty_today_and_new_menu_actions_follow_form_not_only_method(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        with freeze_time('2026-09-13 15:00:00', tick=True):
            self._pointer_browser('/odoo/action-kai_viandas.workday_action', r'''
                await wait(()=>document.querySelector('.o_list_view'),'Hoy no abrió');
                await wait(()=>document.body.textContent.includes('Puede haber solicitudes de otras fechas'),'Falta ayuda de Hoy');
                if(document.body.textContent.includes('Crear nuevo documento')) throw new Error('Invita a crear una reserva');
                await pointer(await wait(()=>document.querySelector('[data-menu-xmlid="kai_viandas.menu_days"]'),'Falta menú Menús'));
                await pointer(await wait(()=>document.querySelector('.o_list_button_add'),'Falta Nuevo'));
                await wait(()=>document.querySelector('.o_form_view'),'No abrió el formulario');
                if(!document.querySelector('h1').textContent.includes('Nuevo menú del día')) throw new Error('Título vacío');
                for(const name of ['action_publish','action_take_list','action_refresh_options']) {
                    if([...document.querySelectorAll('button[name="'+name+'"]')].some(visible)) throw new Error('Acción sin fecha: '+name);
                }
                const clock=[...document.querySelectorAll('.o_form_sheet div')].find(e=>e.textContent==='Mensajes · hora de La Fija');
                if(!clock) throw new Error('Aviso horario fuera de la hoja');
                const input=document.querySelector('[name="date"] input');
                await typeKeys(input,'02/11/2026');
                await pointer(document.querySelector('h1'));
                await wait(()=>[...document.querySelectorAll('button[name="action_publish"]')].some(visible),'No ofrece publicar con datos completos');
                if(document.querySelector('.o_form_saved')) throw new Error('Se guardó antes de pulsar');
                await pointer(await wait(()=>[...document.querySelectorAll('.o_form_button_cancel')].find(visible),'Falta Descartar'));
                await wait(()=>document.querySelector('.o_list_view'),'No volvió a la lista al descartar');
            ''', self.operator.login, min_clicks=4, viewport=(1366,900))
