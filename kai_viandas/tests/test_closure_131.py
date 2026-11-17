import base64
import json
import time
from io import BytesIO
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser, save_test_file
from odoo.tools.pdf import PdfReader

from .test_pages import PagesCommon
from .test_preparation import PreparationCommon
from .test_ux_round2 import TestUXRound2


@tagged('post_install', '-at_install')
class TestClosureService(PreparationCommon):
    def _pending(self):
        cut = self._take()
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        return cut

    def _withdraw(self, product=None):
        product = product or self.chicken
        return self.service._submit_selections(self.website, [(self.menu.id, product.id)],
                                               withdraw_current={self.menu.id: product.id})

    def test_withdraw_own_current_keeps_preparation_labels_and_audits_actor_time(self):
        # El cambio debe preceder a su anulación también cuando el reloj real
        # supera la fecha/hora fija del escenario.
        with freeze_time('2026-09-14 13:30:00'):
            cut = self._pending()
        revision = cut.current_revision_id
        action = revision.with_user(self.operator).action_print_labels()
        printed = self.env['lafija.label.print'].browse(action['res_id'])
        pdf = printed.attachment_id.raw
        prior_events = self.reservation.sudo().event_ids
        with freeze_time('2026-09-14 13:35:00'):
            self._withdraw()
        record = self.reservation.sudo()
        self.assertFalse(record.pending)
        self.assertEqual(record.current_product_id, self.chicken)
        self.assertEqual(cut.current_revision_id, revision)
        self.assertEqual(cut.revision_ids, revision)
        self.assertEqual(printed.attachment_id.raw, pdf)
        self.assertFalse(printed.handling_ids)
        event = record.event_ids - prior_events
        self.assertEqual(event.kind, 'withdrawal')
        self.assertEqual(event.actor_id, self.employee)
        self.assertEqual(str(event.occurred_at), '2026-09-14 13:35:00')
        self.assertEqual(event.received_description, 'Pescado')
        self.assertEqual(event.applied_description, 'Pollo')
        choice = self.reservation._employee_values()['choices'][-1]
        self.assertEqual(choice['author'], 'Vos')
        self.assertEqual(choice['date'], '14/09/2026 10:35')
        self.assertEqual(choice['text'], 'Cambio anulado')
        self.assertEqual(choice['outcome'], 'Cambio que se anuló: Pescado. Sigue vigente Pollo.')
        self.assertEqual(event.result, 'Cambio anulado por el empleado')

    def test_withdraw_outside_menu_preserves_written_question_and_resave_is_noop(self):
        outside = self.env['product.product'].create({'name': 'Guiso plan B', 'sale_ok': True})
        self._resolve('replace', product_id=outside.id)
        cut = self._pending()
        self.reservation._request_correction('Necesito respuesta además del plato.')
        self._withdraw(outside)
        record = self.reservation.sudo()
        self.assertFalse(record.pending_product_id)
        self.assertTrue(record.attention_pending)
        self.assertTrue(record.pending)
        self.assertEqual(record.current_product_id, outside)
        self.assertEqual(cut.current_revision_id.line_ids.product_id, outside)
        events, moment = record.event_ids, record.last_employee_change_at
        self._withdraw(outside)
        self.assertEqual(record.event_ids, events)
        self.assertEqual(record.last_employee_change_at, moment)
        self.assertTrue(record.attention_pending)

    def test_operator_changes_current_between_form_and_locked_save_rejects_stale_intent(self):
        self._pending()
        # Formulario con Pollo vigente. El operador corrige a Cerdo antes del
        # guardado, bajo el mismo bloqueo. Pollo sigue dentro del menú: aun así
        # no debe reinterpretarse la anulación como una sustitución nueva.
        self._resolve('replace', product_id=self.pork.id)
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        events = self.reservation.sudo().event_ids
        with self.assertRaisesRegex(ValidationError, 'vigente cambió'):
            self._withdraw()
        self.assertEqual(self.reservation.sudo().event_ids, events)
        self.assertEqual(self.reservation.sudo().current_product_id, self.pork)
        self.assertEqual(self.reservation.sudo().pending_product_id, self.fish)

    def test_only_own_current_can_be_used_as_withdrawal_exception(self):
        other, _ = self._create_employee('abc-foreign-current')
        foreign = self.env['product.product'].create({'name': 'Opción ajena', 'sale_ok': True})
        other_record = self.env['lafija.reservation'].with_user(other)._submit_selections(
            self.website, [(self.menu.id, self.chicken.id)])
        self.env['lafija.reservation.correction'].with_user(self.operator).create({
            'reservation_id': other_record.id, 'operation': 'replace', 'product_id': foreign.id,
            'reason': 'Solo corresponde a otra persona',
        }).action_apply()
        self._pending()
        for expected in ({}, {self.menu.id: foreign.id}):
            with self.assertRaises(ValidationError):
                self.service._submit_selections(self.website, [(self.menu.id, foreign.id)], withdraw_current=expected)
        self.assertEqual(self.reservation.sudo().pending_product_id, self.fish)

    def test_new_pending_has_no_current_to_withdraw_and_keeps_manual_route(self):
        self._take()
        other, _ = self._create_employee('abc-new-pending')
        service = self.env['lafija.reservation'].with_user(other)
        record = service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        with self.assertRaisesRegex(ValidationError, 'vigente cambió'):
            service._submit_selections(self.website, [(self.menu.id, self.chicken.id)],
                                       withdraw_current={self.menu.id: self.chicken.id})
        self.assertFalse(record.sudo().current_product_id)
        self.assertEqual(record.sudo().pending_product_id, self.fish)
        record._request_correction('Cancelar mi reserva nueva, por favor.')
        self.assertTrue(record.sudo().attention_pending)

    def test_queue_and_pdf_share_all_pending_labels_and_do_not_change_quantities(self):
        current_records = []
        for login in ('change-alone', 'change-question', 'question-alone'):
            employee, _ = self._create_employee('abc-' + login)
            current_records.append((employee, self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(self.menu.id, self.chicken.id)])))
        cut = self._take()
        revision = cut.current_revision_id
        expected = {}
        for index, (employee, record) in enumerate(current_records):
            if index < 2:
                self.env['lafija.reservation'].with_user(employee)._submit_selections(self.website, [(self.menu.id, self.fish.id)])
            if index:
                record._request_correction('Consulta de prueba no imprimible')
            expected[record.name] = ['Cambio de opción', 'Cambio de opción y consulta escrita', 'Consulta escrita'][index]
        for has_question in (False, True):
            employee, _ = self._create_employee('abc-new-' + str(has_question))
            record = self.env['lafija.reservation'].with_user(employee)._submit_selections(self.website, [(self.menu.id, self.fish.id)])
            if has_question:
                record._request_correction('Consulta privada de nueva reserva')
            expected[record.name] = 'Nueva reserva y consulta escrita' if has_question else 'Nueva reserva'
        report = self.env['report.kai_viandas.day_sheet'].with_user(self.operator)
        sheet = report._get_report_values(revision.ids)['sheets'][0]
        self.assertEqual({row['reference']: row['type'] for row in sheet['pending']}, expected)
        pending = self.env['lafija.reservation'].with_user(self.operator).search([('name', 'in', list(expected))])
        self.assertEqual({r.name: r.attention_label for r in pending}, expected)
        self.assertEqual(self.reservation.sudo().attention_label, 'Sin pendientes')
        self.assertEqual(sheet['total'], 4)
        self.assertEqual(sheet['products'][0]['quantity'], 4)
        pdf, _ = self.env['ir.actions.report'].with_user(self.operator).with_context(force_report_rendering=True)._render_qweb_pdf(
            'kai_viandas.report_day_sheet', revision.ids)
        text = ' '.join(' '.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages).split())
        for label in expected.values():
            self.assertIn(label, text)
        self.assertNotIn('Consulta privada', text)
        save_test_file(self._testMethodName, pdf, 'planilla_rotulos_', extension='pdf', directory='reports')


@tagged('post_install', '-at_install')
class TestClosureBrowser(PagesCommon):
    _pointer_browser = TestUXRound2._pointer_browser

    def _pending_record(self, outside=False):
        employee, _ = self._create_employee()
        service = self.env['lafija.reservation'].with_user(employee)
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        if outside:
            own = self.env['product.product'].create({'name': 'Guiso propio plan B', 'sale_ok': True})
            self.env['lafija.reservation.correction'].with_user(self.operator).create({
                'reservation_id': record.id, 'operation': 'replace', 'product_id': own.id, 'reason': 'Plan B',
            }).action_apply()
        pending = self.env['product.product'].create({'name': 'Pescado del menú', 'sale_ok': True})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(pending.id)]})
        self.menus[0].with_user(self.operator).action_take_list()
        service._submit_selections(self.website, [(self.menus[0].id, pending.id)])
        record._request_correction('Consulta escrita que se conserva')
        return employee, record, pending

    def test_http_own_current_outside_menu_card_no_image_foreign_post_rejected(self):
        employee, record, pending = self._pending_record(outside=True)
        current = record.sudo().current_product_id
        foreign = self.env['product.product'].create({'name': 'Plato secreto ajeno', 'sale_ok': True})
        self._real_login(employee.login, 'employee-password-123')
        response = self.url_open('/my/viandas?week=2026-09-14')
        doc = html.fromstring(response.content)
        radio = doc.xpath(f'//input[@type="radio" and @value="{current.id}"]')[0]
        self.assertNotIn('checked', radio.attrib)
        self.assertIn('Vigente · elegila para anular el cambio pedido', radio.getparent().text_content())
        self.assertFalse(radio.getparent().xpath('.//img'))
        self.assertNotIn(foreign.name, response.text)
        self.assertEqual(doc.xpath(f'//input[@name="withdraw_{self.menus[0].id}"]/@value'), [str(current.id)])
        self.assertEqual(self.url_open(f'/my/viandas/opcion/{current.id}/imagen?menu_id={self.menus[0].id}').status_code, 404)
        token = doc.xpath('//input[@name="csrf_token"]/@value')[0]
        for expected in ({}, {f'withdraw_{self.menus[0].id}': str(foreign.id)}):
            rejected = self.url_open('/my/viandas/reservar', data={
                'csrf_token': token, 'week': '2026-09-14', f'menu_{self.menus[0].id}': str(foreign.id), **expected})
            self.assertEqual(rejected.status_code, 400)
            self.assertNotIn(foreign.name, rejected.text)
        response = self.url_open('/my/viandas/reservar', data={
            'csrf_token': token, 'week': '2026-09-14', f'menu_{self.menus[0].id}': str(current.id),
            f'withdraw_{self.menus[0].id}': str(current.id)}, allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        page = self.url_open(response.headers['Location'])
        self.assertIn('Lunes 14/09: anulaste el cambio pedido. Sigue vigente Guiso propio plan B.', page.text)
        self.assertIn('Tu consulta escrita sigue abierta', page.text)
        detail = self.url_open(f'/my/viandas/{record.id}')
        self.assertIn('Cambio anulado', detail.text)
        self.assertIn('Cambio que se anuló: Pescado del menú. Sigue vigente Guiso propio plan B.', detail.text)
        self.assertIn('Última acción que enviaste:', detail.text)
        self.assertNotIn('retir', detail.text.lower())
        self.assertNotIn('Plan B', detail.text)  # El motivo interno no se presenta.

    def test_pointer_withdraw_save_and_back_keep_server_choice_at_390_and_360(self):
        employee, record, pending = self._pending_record(outside=True)
        current = record.sudo().current_product_id
        original = ChromeBrowser._wait_code_ok
        for width, height in ((390, 844), (360, 800)):
            self.env['lafija.reservation'].with_user(employee)._submit_selections(self.website, [(self.menus[0].id, pending.id)])
            self._real_login(employee.login, 'employee-password-123')
            sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
            def roundtrip(browser, code, timeout, **kwargs):
                def evaluate(expression):
                    return browser._websocket_request('Runtime.evaluate', params={
                        'expression': expression, 'returnByValue': True}).get('result', {}).get('value')
                def wait(expression):
                    for _ in range(200):
                        if evaluate(expression):
                            return
                        time.sleep(.05)
                    self.fail('No se cumplió al navegar: ' + expression)
                def pointer(selector):
                    target = 'document.querySelector(' + json.dumps(selector) + ')'
                    evaluate(target + '.scrollIntoView({block:"center"})')
                    time.sleep(.15)
                    point = evaluate('(()=>{const e=' + target + ';const r=e.getBoundingClientRect();'
                        'const x=r.x+r.width/2,y=r.y+r.height/2;return {x,y,clear:e.contains(document.elementFromPoint(x,y))};})()')
                    self.assertTrue(point['clear'], selector + ' está tapado')
                    for kind in ('mousePressed', 'mouseReleased'):
                        browser._websocket_request('Input.dispatchMouseEvent', params={
                            'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})
                browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                    'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False})
                before = browser._websocket_request('Page.getNavigationHistory')
                entry = before['entries'][before['currentIndex']]['id']
                day = f'details[data-menu="{self.menus[0].id}"]'
                if not evaluate('document.querySelector(' + json.dumps(day) + ').open'):
                    pointer(day + ' summary')
                wait('document.querySelector(' + json.dumps(day) + ').open')
                # La sesión puede recordar este día abierto después del reenvío
                # anterior. No cerrarlo por dar por supuesto un estado inicial.
                image = browser._websocket_request('Page.captureScreenshot')['data']
                save_test_file(self._testMethodName, base64.b64decode(image), f'vigente_{width}_',
                               extension='png', directory='screenshots')
                pointer(f'label:has(input[id="lf-choice-{self.menus[0].id}-{current.id}"])')
                wait('document.querySelector("[data-save-state]").textContent.includes("1 día sin guardar")')
                self.assertFalse(evaluate('document.querySelector(' + json.dumps(day) + ').open'))
                draft = 'document.querySelector(' + json.dumps(day + ' .draft-choice') + ')'
                self.assertFalse(evaluate(draft + '.hidden'))
                self.assertEqual(evaluate(draft + '.textContent'),
                                 'Sin guardar: anular el cambio pedido. Sigue Guiso propio plan B.')
                self.assertTrue(evaluate('document.documentElement.scrollWidth<=innerWidth'))
                image = browser._websocket_request('Page.captureScreenshot')['data']
                save_test_file(self._testMethodName, base64.b64decode(image), f'anular_plegado_{width}_',
                               extension='png', directory='screenshots')
                pointer('.save-bar button')
                wait('document.readyState==="complete" && document.querySelector(".success")?.textContent.includes("anulaste el cambio pedido")')
                browser._websocket_request('Page.navigateToHistoryEntry', params={'entryId': entry})
                time.sleep(.4)
                wait('document.readyState==="complete" && document.querySelector(' + json.dumps(day) + ')?.dataset.selected===' +
                    json.dumps(str(current.id)) + ' && document.querySelector(' + json.dumps(day + ' input:checked') + ')?.value===' +
                    json.dumps(str(current.id)) + ' && !document.querySelector(".save-bar button")?.disabled')
                pointer('.save-bar button')
                wait('document.readyState==="complete" && document.querySelector(".success")?.textContent.includes("No hiciste cambios")')
                return original(browser, code, timeout, **kwargs)
            with patch.object(ChromeBrowser, '_wait_code_ok', roundtrip):
                self.browser_js('/my/viandas?week=2026-09-14', "console.log('test successful');",
                                login=None, cookies={'session_id': sid}, timeout=90)
            self.env.invalidate_all()
            self.assertFalse(record.sudo().pending_product_id)
            self.assertTrue(record.sudo().attention_pending)
        self.assertEqual(len(record.sudo().event_ids.filtered(lambda e: e.kind == 'withdrawal')), 2)

    def test_pointer_reply_visible_before_focus_keyboard_privacy_and_notices_replace(self):
        employee, _ = self._create_employee()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        record._request_correction('Mi consulta por responder.')
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.reservation_action/{record.id}', r'''
            const attend=async()=>{
                await pointer(await wait(()=>document.querySelector('button[name="action_correct"]'),'Falta Atender reserva'));
                await wait(()=>document.querySelector('.modal [name="employee_message"] textarea'),'No abrió el asistente');
            };
            await attend();
            for(const name of ['employee_message','reason']) {
                const field=document.querySelector('.modal [name="'+name+'"] textarea');
                if(document.activeElement===field || field.matches(':hover')) throw new Error('La señal visual debe probarse sin foco ni hover');
                const style=getComputedStyle(field);
                if(parseFloat(style.borderBottomWidth)<1 || style.borderBottomStyle==='none' ||
                   ['transparent','rgba(0, 0, 0, 0)'].includes(style.borderBottomColor)) throw new Error('Campo sin borde visible: '+name);
                if(!field.placeholder) throw new Error('Campo sin ayuda: '+name);
            }
            const reply=document.querySelector('.modal [name="employee_message"] textarea');
            if(reply.placeholder!=='Escribí la respuesta que verá el empleado') throw new Error('Respuesta sin placeholder acordado');
            if(document.querySelector('.modal [name="reason"] textarea').placeholder!==
               'Motivo de esta actuación; no se muestra al empleado') throw new Error('Motivo sin placeholder acordado');
            await typeKeys(reply,'Recibimos tu consulta y estamos revisando.');
            await typeKeys(document.querySelector('.modal [name="reason"] textarea'),'CENTINELA INTERNO 918273');
            await pointer([...document.querySelectorAll('.modal button[name="action_apply"]')].find(visible));
            await wait(()=>!document.querySelector('.modal'),'No cerró el asistente');
            await wait(()=>document.querySelector('.o_notification')?.textContent.includes('sigue pendiente'),'Falta confirmación de respuesta');
            await attend();
            // Odoo 19 usa SelectMenu, no un elemento select del navegador.
            await pointer(document.querySelector('.modal [name="operation"] .o_select_menu_toggler'));
            await pointer(await wait(()=>[...document.querySelectorAll('.o_field_selection_menu .dropdown-item')].find(
                e=>visible(e)&&e.textContent.trim()==='Cerrar solicitud sin cambiar la vianda'),'Falta la opción de cierre'));
            await wait(()=>document.querySelector('.modal [name="operation"] input')?.value.includes('Cerrar solicitud'),'No eligió Cerrar solicitud');
            await typeKeys(document.querySelector('.modal [name="reason"] textarea'),'Cierre revisado por La Fija');
            await pointer([...document.querySelectorAll('.modal button[name="action_apply"]')].find(visible));
            await wait(()=>!document.querySelector('.modal'),'No cerró la consulta');
            const notices=()=>[...document.querySelectorAll('.o_notification')].filter(visible).map(e=>e.textContent).join('\n');
            await wait(()=>notices().includes('cerrada'),'Falta confirmación de cierre');
            if(notices().includes('sigue abierta') || notices().includes('sigue pendiente')) throw new Error('Los avisos se contradicen');
            await wait(()=>!notices().includes('cerrada'),'La confirmación rutinaria quedó pegajosa');
        ''', self.operator.login, min_clicks=8)
        self.env.invalidate_all()
        values = record._employee_values()
        self.assertFalse(values['attention_pending'])
        self.assertIn('Recibimos tu consulta y estamos revisando.', [m['text'] for m in values['messages']])
        self.assertNotIn('918273', str(values))
        self.assertIn('918273', ' '.join(record.sudo().event_ids.mapped('result')))
        # Contraste por HTTP real del empleado, no solo el servicio de proyección.
        self.public_site.domain = 'http://public.test'
        self.public_site.flush_recordset(['domain'])
        self.website.domain = self.base_url()
        self._real_login(employee.login, 'employee-password-123')
        response = self.url_open(f'/my/viandas/{record.id}')
        self.assertIn('Recibimos tu consulta y estamos revisando.', response.text)
        self.assertNotIn('918273', response.text)

    def test_pointer_publication_notice_survives_form_refresh_and_then_expires(self):
        menu = self.env['lafija.menu.day'].with_user(self.operator).create({
            'date': '2026-10-19', 'website_id': self.website.id, 'product_ids': [Command.set(self.product.ids)]})
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.menu_day_action/{menu.id}', r'''
            await pointer(await wait(()=>document.querySelector('button[name="action_publish"]'),'Falta Publicar'));
            await wait(()=>document.querySelector('[name="published"] input')?.checked,'La ficha no refrescó');
            if(document.querySelector('[name="revision"]').textContent.trim()!=='2') throw new Error('Revisión desactualizada');
            await wait(()=>document.querySelector('.o_notification')?.textContent.includes('Menú publicado'),'Aviso perdido durante el refresco');
            await wait(()=>!document.querySelector('.o_notification'),'Aviso pegajoso');
        ''', self.operator.login)
