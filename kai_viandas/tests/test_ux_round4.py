import json
import time
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser

from .test_pages import PagesCommon
from . import test_ux_round2


@tagged('post_install', '-at_install')
class TestUXRound4(PagesCommon):
    def _pointer_browser(self, *args, **kwargs):
        original = ChromeBrowser._wait_code_ok
        def capture(browser, *positional, **named):
            result = original(browser, *positional, **named)
            browser.take_screenshot(prefix='ux3_r4_').result(timeout=10)
            return result
        with patch.object(ChromeBrowser, '_wait_code_ok', capture):
            return test_ux_round2.TestUXRound2._pointer_browser(self, *args, **kwargs)

    def test_html_uses_standards_mode_and_stable_server_radio_selection(self):
        employee, _ = self._create_employee()
        self._anonymous()
        self.assertTrue(self.url_open('/web/login').content.lstrip().lower().startswith(b'<!doctype html>'))
        self._real_login(employee.login, 'employee-password-123')
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        for path in ('/my/viandas?week=2026-09-14', f'/my/viandas/{record.id}'):
            response = self.url_open(path)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.lstrip().lower().startswith(b'<!doctype html>'))
        document = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
        self.assertEqual(document.xpath('//form[@id="lf-week-form"]/@autocomplete'), ['off'])
        radios = document.xpath('//input[@type="radio"]')
        self.assertTrue(all(r.get('autocomplete') == 'off' for r in radios))
        self.assertEqual(len({r.get('id') for r in radios}), len(radios))
        day = document.xpath('//details[@data-menu]')[0]
        self.assertEqual(day.get('data-selected'), str(self.product.id))
        self.assertEqual(day.xpath('.//input[@checked]/@value'), [str(self.product.id)])
        self.assertFalse(document.xpath('//*[@id="resultado"]'), 'Sin mensaje no queda un ancla vacía')

    def test_default_week_skips_closed_empty_and_past_reference_menus(self):
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        employee, _ = self._create_employee()
        for menu in self.menus:
            menu.with_user(self.operator).action_take_list()
        next_week = self.env['lafija.menu.day'].with_user(self.operator).create({
            'date': '2026-09-21', 'website_id': self.website.id, 'published': True,
            'product_ids': [Command.set(self.product.ids)],
        })
        later = self.env['lafija.menu.day'].with_user(self.operator).create({
            'date': '2026-09-28', 'website_id': self.website.id, 'published': True,
            'product_ids': [Command.set(self.product.ids)],
        })
        def week():
            doc = html.fromstring(self.url_open('/my/viandas').content)
            return doc.xpath('//input[@name="week"]/@value')[0]
        with freeze_time('2026-09-12 15:00:00'):
            self._real_login(employee.login, 'employee-password-123')
            self.assertEqual(week(), str(next_week.date))
            closed = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
            self.assertFalse(closed.xpath('//details[@data-menu and @open]'))
            self.assertEqual(len(closed.xpath('//*[contains(@class,"cut-badge")]')), 5)
        with freeze_time('2026-09-21 13:01:00'):
            self._real_login(employee.login, 'employee-password-123')
            self.assertEqual(week(), str(later.date))
            # No cambia la regla flexible: todavía se puede enviar por semana explícita.
            page = html.fromstring(self.url_open('/my/viandas?week=2026-09-21').content)
            response = self.url_open('/my/viandas/reservar', data={
                'csrf_token': page.xpath('//input[@name="csrf_token"]/@value')[0],
                'week': '2026-09-21', f'menu_{next_week.id}': str(self.product.id)})
            self.assertIn('elección guardada', response.text)
        inactive = self.env['product.product'].create({'name': 'Opción inactiva', 'sale_ok': True})
        next_week.with_user(self.operator).write({'product_ids': [Command.set(inactive.ids)]})
        inactive.active = False
        with freeze_time('2026-09-12 15:00:00'):
            self._real_login(employee.login, 'employee-password-123')
            self.assertEqual(week(), str(later.date))

    def test_pointer_mobile_drafts_fold_and_save_has_its_own_visible_space(self):
        employee, _ = self._create_employee()
        for viewport in ((390, 844), (360, 800), (360, 480)):
            self._real_login(employee.login, 'employee-password-123')
            sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
            self._pointer_browser('/my/viandas?week=2026-09-14', r'''
                if(document.compatMode!=='CSS1Compat') throw new Error('Página en quirks');
                const days=[...document.querySelectorAll('details.day')];
                const save=document.querySelector('.save-bar');
                const scroll=document.querySelector('.week-scroll');
                for (const index of [0,1,3,4]) {
                    const day=days[index];
                    if(!day.open) await pointer(day.querySelector('summary'));
                    if(days.filter(d=>d.open).length!==1) throw new Error('Más de un día desplegado');
                    const card=[...day.querySelectorAll('label.option-card')].find(e=>e.querySelector('input').value);
                    await pointer(card);
                    await wait(()=>!day.open,'La elección por puntero no plegó el día');
                    if(!day.querySelector('.draft-choice').textContent.includes('Sin guardar: Pollo')) throw new Error('No muestra el borrador al plegar');
                }
                if(!save.textContent.includes('4 días sin guardar')) throw new Error('Falta resumen de cambios');
                const b=save.getBoundingClientRect(), s=scroll.getBoundingClientRect();
                if(b.bottom>innerHeight+1 || b.top<s.bottom-1) throw new Error('Guardar tapa el contenido o queda fuera de pantalla');
                if(getComputedStyle(save).position!=='static') throw new Error('Volvió una barra superpuesta');
                if(document.documentElement.scrollWidth>innerWidth) throw new Error('Desborde horizontal');
                const button=save.querySelector('button'), r=button.getBoundingClientRect();
                if(!button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))) throw new Error('Guardar no es alcanzable');
            ''', None, min_clicks=7, viewport=viewport, cookies={'session_id': sid})
        self.assertFalse(self.env['lafija.reservation'].search([]), 'Elegir sin guardar no crea reservas')

    def test_browser_back_after_post_reloads_current_choices_and_resave_changes_nothing(self):
        employee, _ = self._create_employee()
        second = self.env['product.product'].create({'name': 'Cerdo', 'sale_ok': True})
        self.menus.with_user(self.operator).write({'product_ids': [Command.link(second.id)]})
        self._real_login(employee.login, 'employee-password-123')
        sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
        original = ChromeBrowser._wait_code_ok
        def history_roundtrip(browser, code, timeout, **kwargs):
            def evaluate(expression):
                return browser._websocket_request('Runtime.evaluate', params={
                    'expression': expression, 'returnByValue': True}).get('result', {}).get('value')
            def wait(expression):
                for _ in range(200):
                    if evaluate(expression):
                        return
                    time.sleep(.05)
                self.fail('No se cumplió al navegar: ' + expression)
            # El controlador está fuera de la página: el POST y Atrás pueden
            # destruir su contexto JS sin destruir el conductor de la prueba.
            before = browser._websocket_request('Page.getNavigationHistory')
            entry = before['entries'][before['currentIndex']]['id']
            evaluate(f'document.querySelector(\'input[value="{self.product.id}"]\').click();')
            evaluate('document.querySelector("button[type=submit]").click();')
            wait('document.readyState==="complete" && document.querySelector(".success")?.textContent.includes("elección guardada")')
            after = browser._websocket_request('Page.getNavigationHistory')
            self.assertNotEqual(after['entries'][after['currentIndex']]['id'], entry)
            browser._websocket_request('Page.navigateToHistoryEntry', params={'entryId': entry})
            time.sleep(.4)
            selected = json.dumps(str(self.product.id))
            wait(f'document.readyState==="complete" && document.querySelector("details.day")?.dataset.selected==={selected} && '
                 f'document.querySelector("details.day input:checked")?.value==={selected} && '
                 '!document.querySelector("button[type=submit]")?.disabled')
            evaluate('document.querySelector("button[type=submit]").click();')
            wait('document.readyState==="complete" && document.querySelector(".success")?.textContent.includes("No hiciste cambios")')
            return original(browser, code, timeout, **kwargs)
        with patch.object(ChromeBrowser, '_wait_code_ok', history_roundtrip):
            self.browser_js('/my/viandas?week=2026-09-14', "console.log('test successful');",
                            login=None, cookies={'session_id': sid}, timeout=60)
        self.env.invalidate_all()
        record = self.env['lafija.reservation'].search([('employee_partner_id', '=', employee.partner_id.id)])
        self.assertEqual(record.current_product_id, self.product)
        self.assertEqual(len(record.event_ids.filtered(lambda e: e.kind == 'choice')), 1)

    def test_pointer_correction_shows_pending_choice_and_preserves_open_question(self):
        employee, _ = self._create_employee()
        service = self.env['lafija.reservation'].with_user(employee)
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        record._request_correction('¿Puede ser sin queso?')
        pending = self.env['product.product'].create({'name': 'Verduras asadas', 'sale_ok': True})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(pending.id)]})
        self.menus[0].with_user(self.operator).action_take_list()
        service._submit_selections(self.website, [(self.menus[0].id, pending.id)])
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.reservation_action/{record.id}', r'''
            await pointer(await wait(()=>document.querySelector('button[name="action_correct"]'),'Falta Atender reserva'));
            const pending=await wait(()=>document.querySelector('.modal .o_field_widget[name="pending_choice"]'),'Falta elección pendiente en el formulario');
            if(!pending.textContent.includes('Verduras asadas')) throw new Error('El operador aplica sin ver qué');
            if(!document.querySelector('.modal').textContent.includes('no cierra esa consulta')) throw new Error('No explica el cierre separado');
            if(!document.querySelector('.modal').textContent.includes('Motivo interno (obligatorio)')) throw new Error('No indica motivo obligatorio');
            const reason=document.querySelector('.modal [name="reason"] textarea');
            reason.value='Corrección de evaluación';reason.dispatchEvent(new Event('input',{bubbles:true}));
            const reply=document.querySelector('.modal [name="employee_message"] textarea');
            reply.value='Te cambiamos a Verduras.';reply.dispatchEvent(new Event('input',{bubbles:true}));
            await pointer([...document.querySelectorAll('.modal button[name="action_apply"]')].find(visible));
            await wait(()=>!document.querySelector('.modal'),'No cerró el asistente');
            await wait(()=>document.querySelector('.o_notification')?.textContent.includes('La consulta escrita sigue abierta'),'No confirmó la aplicación y consulta abierta');
            if(!document.querySelector('[name="current_description"]').textContent.includes('Verduras')) throw new Error('La ficha no refleja lo aplicado');
        ''', self.operator.login, min_clicks=2)
        self.env.invalidate_all()
        self.assertEqual(record.sudo().current_product_id, pending)
        self.assertFalse(record.sudo().pending_product_id)
        self.assertTrue(record.sudo().attention_pending)
        values = record._employee_values()
        self.assertTrue(values['request_answered'])
        self.assertIn('Te cambiamos a Verduras.', [m['text'] for m in values['messages']])

    def test_browser_empty_correction_uses_inline_spanish_help(self):
        employee, _ = self._create_employee()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        self._real_login(employee.login, 'employee-password-123')
        sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
        self._pointer_browser(f'/my/viandas/{record.id}', r'''
            await pointer(document.querySelector('.lf-correction-form button[type=submit]'));
            const message=document.querySelector('[name=message]'), error=document.querySelector('.correction-error');
            if(error.hidden || !error.textContent.includes('Escribí la corrección')) throw new Error('Falta validación en línea');
            if(document.activeElement!==message || message.getAttribute('aria-invalid')!=='true') throw new Error('No lleva al campo que falta');
            if(!document.querySelector('.lf-correction-form').noValidate) throw new Error('Sigue el globo nativo');
        ''', None, min_clicks=1, viewport=(390,844), cookies={'session_id':sid})
        self.assertFalse(record.sudo().attention_pending)

    def test_browser_empty_week_and_first_reservation_after_cut_have_clear_states(self):
        employee, _ = self._create_employee()
        self._real_login(employee.login, 'employee-password-123')
        sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
        self.browser_js('/my/viandas?week=2027-10-04', r'''
            if(document.compatMode!=='CSS1Compat') throw new Error('Semana vacía en quirks');
            if(!document.body.textContent.includes('todavía no publicó opciones')) throw new Error('Falta estado vacío');
            if(document.querySelector('.save-bar'))throw new Error('Guardar sin días publicados');
            console.log('test successful');
        ''', login=None, cookies={'session_id':sid})
        self._real_login(employee.login, 'employee-password-123')
        self.menus[0].with_user(self.operator).action_take_list()
        page = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
        response = self.url_open('/my/viandas/reservar', data={
            'csrf_token': page.xpath('//input[@name="csrf_token"]/@value')[0],
            'week': '2026-09-14', f'menu_{self.menus[0].id}': str(self.product.id)})
        self.assertIn('reserva recibida para revisión', response.text)
        self.assertNotIn('cambio recibido', response.text)
        self.env.invalidate_all()
        record = self.env['lafija.reservation'].search([('employee_partner_id', '=', employee.partner_id.id)])
        self.assertEqual(record.attention_label, 'Nueva reserva')
        self.assertFalse(record.current_product_id)

    def test_pointer_menu_reservations_fit_and_pending_choice_is_visible(self):
        employee, _ = self._create_employee()
        self.product.description_sale = 'Pollo con arroz integral, verduras asadas y salsa de hierbas'
        self.menus[0].with_user(self.operator).action_refresh_options()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        record._request_correction('Consulta abierta para probar las columnas')
        self.menus[0].with_user(self.operator).action_take_list()
        alternate = self.env['product.product'].create({'name': 'Tarta de espinaca con calabaza asada y ensalada fresca', 'sale_ok': True})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(alternate.id)]})
        self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, alternate.id)])
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.menu_day_action/{self.menus[0].id}', r'''
            const field=await wait(()=>document.querySelector('[name="reservation_ids"]'),'Faltan reservas del menú');
            const table=await wait(()=>field.querySelector('table'),'Falta tabla de reservas');
            await new Promise(r=>setTimeout(r,250));
            // La tabla nativa usa el ancho de la hoja, incluidos los márgenes
            // negativos del widget relacional; no se compara con su padding.
            if(table.getBoundingClientRect().right>field.closest('.o_form_sheet').getBoundingClientRect().right+2) throw new Error('La tabla desborda su ficha '+JSON.stringify({
                tableWidth:table.clientWidth, tableRight:table.getBoundingClientRect().right, sheetRight:field.closest('.o_form_sheet').getBoundingClientRect().right,
                headers:[...table.querySelectorAll('th')].map(e=>[e.dataset.name,e.style.width,getComputedStyle(e).width])}));
            if(table.scrollWidth>table.clientWidth+2) throw new Error('Hay contenido fuera de la tabla');
            for(const name of ['current_description','pending_description','attention_label','timing_label']) {
                const cell=field.querySelector('td[name="'+name+'"]');
                if(!cell || cell.scrollWidth>cell.clientWidth+2)throw new Error('La columna se corta: '+name+' '+JSON.stringify({
                    cell:cell?.outerHTML, fieldClass:field.className, tableClass:table.parentElement.className,
                    width:cell?.clientWidth, scroll:cell?.scrollWidth, whitespace:cell&&getComputedStyle(cell).whiteSpace}));
            }
            await pointer(await wait(()=>[...field.querySelectorAll('button[name="action_correct"]')].find(visible),'Falta Atender'));
            const pending=await wait(()=>document.querySelector('.modal [name="pending_choice"]'),'No abrió elección pendiente');
            if(!pending.textContent.includes('Tarta de espinaca')) throw new Error('El formulario oculta la opción que aplica');
        ''', self.operator.login, min_clicks=1, viewport=(1366,900))
