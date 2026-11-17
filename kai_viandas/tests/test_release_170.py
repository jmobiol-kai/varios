"""Motivo optativo y actuación sobre el estado que el operador vio."""
import json
from urllib.parse import urlsplit

from freezegun import freeze_time
from lxml import html
import requests

from odoo import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TEST_CURSOR_COOKIE_NAME, _registry_test_lock

from .test_identity import LafijaCommon
from .test_preparation import PreparationCommon
from .test_pages import PagesCommon
from .test_release_160 import TestRelease160


@tagged('post_install', '-at_install')
class TestAccess170(LafijaCommon):
    def test_all_operations_accept_empty_whitespace_and_personal_reason(self):
        labels = {'create': 'Alta de empleado', 'reset': 'Restablecimiento de contraseña',
                  'disable': 'Deshabilitación', 'enable': 'Habilitación',
                  'update': 'Corrección de empresa y sitio'}
        for operation, automatic in labels.items():
            for number, reason in enumerate((False, '   ', 'Solicitud de ABC')):
                with self.subTest(operation=operation, reason=reason):
                    values = {'operation': operation, 'reason': reason,
                              'customer_company_id': self.customer.id, 'website_id': self.website.id,
                              'new_password': 'new-access-password-170'}
                    if operation == 'create':
                        values.update(name='Empleado alta opcional', login=f'lf170-new-{number}')
                    else:
                        employee, _ = self._create_employee(f'lf170-{operation}-{number}')
                        values['employee_id'] = employee.partner_id.id
                        if operation == 'enable':
                            self._manage(employee, 'disable').action_apply()
                    wizard = self.env['lafija.employee.access'].with_user(self.operator).create(values)
                    action = wizard.action_apply()
                    partner = self.env['res.partner'].browse(action['res_id'])
                    notes = partner.message_ids.filtered(lambda m: 'Acceso corporativo:' in (m.body or ''))
                    note = notes.sorted('id')[-1]
                    expected_reason = (reason or '').strip() or automatic
                    self.assertIn('Motivo: ' + expected_reason, str(note.body))
                    self.assertEqual(note.author_id, self.operator.partner_id)
                    self.assertNotIn('new-access-password-170', str(notes.mapped('body')))
                    self.assertFalse(wizard.new_password)
                    user = partner.with_context(active_test=False).user_ids
                    self.assertEqual(user.active, operation != 'disable')

    def test_reason_tracks_confirmed_operation_not_initial_operation(self):
        employee, _ = self._create_employee('lf170-switch')
        wizard = self._manage(employee, 'reset', reason=' ', new_password='switch-password-170')
        wizard.operation = 'disable'
        wizard.action_apply()
        last = employee.partner_id.message_ids.sorted('id')[-1]
        self.assertIn('Motivo: Deshabilitación', str(last.body))
        self.assertNotIn('Restablecimiento de contraseña', str(last.body))
        self.assertFalse(employee.active)

    def test_access_form_has_optional_reason_in_create_and_reset(self):
        model = self.env['lafija.employee.access'].with_user(self.operator)
        self.assertFalse(model._fields['reason'].required)
        self.assertEqual(model._fields['reason'].string, 'Motivo')
        employee, _ = self._create_employee('lf170-form')
        with Form(model.with_context(default_operation='create')) as form:
            form.name = 'Alta desde formulario'
            form.login = 'lf170-form-new'
            form.customer_company_id = self.customer
            form.website_id = self.website
        form.record.action_apply()
        with Form(model.with_context(default_employee_id=employee.partner_id.id, default_operation='reset')) as form:
            form.operation = 'disable'
            form.operation = 'reset'
        form.record.action_apply()
        self.assertTrue(employee.active)


@tagged('post_install', '-at_install')
class TestCorrection170(PreparationCommon):
    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-09-14 13:00:00', tick=True))
        self.cut = self._take()

    def _wizard(self, operation, **values):
        return self.env['lafija.reservation.correction'].with_user(self.operator).create({
            'reservation_id': self.reservation.id, 'operation': operation,
            'reason': 'Motivo interno 170', 'employee_message': 'Respuesta conservada 170', **values})

    def _unchanged_state(self):
        record = self.reservation.sudo()
        return (record.state, record.current_product_id.id, record.pending_product_id.id,
                record.attention_pending, record.event_ids.ids, record.message_ids.ids,
                self.cut.revision_ids.ids)

    def test_all_operational_actions_require_reconfirmation_after_new_request(self):
        for operation in ('accept', 'reject', 'close_request', 'replace', 'restore', 'cancel', 'reassign'):
            with self.subTest(operation=operation):
                self._resolve('replace', product_id=self.chicken.id)
                self.reservation._request_correction('Consulta original')
                self.service._submit_selections(self.website, [(self.menu.id, self.pork.id)])
                wizard = self._wizard(operation, product_id=self.fish.id,
                    previous_line_id=self.cut.current_revision_id.line_ids.id,
                    customer_company_id=self.customer.id)
                old_reference = wizard.observed_state
                self.reservation._request_correction('Consulta adicional ' + operation)
                before = self._unchanged_state()
                result = wizard.action_apply()
                self.assertEqual(self._unchanged_state(), before)
                self.assertEqual(result['params']['type'], 'warning')
                self.assertEqual(result['params']['next']['res_id'], wizard.id)
                self.assertEqual(result['params']['next']['name'], 'Editar pedido')
                self.assertNotEqual(wizard.observed_state, old_reference)
                self.assertIn('No se aplicó', wizard.conflict_notice)
                self.assertIn('Consulta adicional ' + operation, wizard.request_text)
                self.assertEqual(wizard.reason, 'Motivo interno 170')
                self.assertEqual(wizard.employee_message, 'Respuesta conservada 170')
                confirmed = wizard.action_apply()
                self.assertTrue(confirmed['params']['close'])
                self.assertEqual(confirmed['params']['type'], 'success')
                self.assertEqual(len(self.reservation.sudo().event_ids), len(before[4]) + 1)

    def test_pending_replaced_and_operator_correction_are_detected(self):
        self.service._submit_selections(self.website, [(self.menu.id, self.pork.id)])
        wizard = self._wizard('accept')
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        before = self._unchanged_state()
        wizard.action_apply()
        self.assertEqual(self._unchanged_state(), before)
        self.assertEqual(wizard.pending_choice, 'Pescado')
        self._resolve('replace', product_id=self.pork.id)
        before = self._unchanged_state()
        wizard.action_apply()
        self.assertEqual(self._unchanged_state(), before)
        self.assertEqual(wizard.current_choice, 'Cerdo')
        self.assertFalse(wizard.pending_choice)

    def test_response_warns_but_preserves_current_pending_and_open_request(self):
        self.reservation._request_correction('Consulta inicial')
        wizard = self._wizard('note')
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        self.reservation._request_correction('Otra consulta mientras se responde')
        revisions = self.cut.revision_ids.ids
        count = len(self.reservation.sudo().event_ids)
        result = wizard.action_apply()
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn('cambió mientras', result['params']['message'])
        self.assertTrue(result['params']['close'])
        self.assertEqual(self.reservation.sudo().pending_product_id, self.fish)
        self.assertTrue(self.reservation.sudo().attention_pending)
        self.assertEqual(self.cut.revision_ids.ids, revisions)
        self.assertEqual(len(self.reservation.sudo().event_ids), count + 1)
        payload = self.reservation._employee_values()
        self.assertIn('Respuesta conservada 170', str(payload))
        self.assertNotIn('Motivo interno 170', str(payload))

    def test_employee_resubmission_without_change_does_not_conflict(self):
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        wizard = self._wizard('accept')
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        result = wizard.action_apply()
        self.assertTrue(result['params']['close'])
        self.assertEqual(result['params']['type'], 'success')
        self.assertEqual(self.reservation.sudo().current_product_id, self.fish)

    def test_form_preserves_reference_from_open_before_first_save(self):
        model = self.env['lafija.reservation.correction'].with_user(self.operator)
        form = Form(model.with_context(default_reservation_id=self.reservation.id))
        reference = form.observed_state
        self.assertTrue(reference)
        self.reservation._request_correction('Llegó después de abrir el formulario')
        form.reason = 'Conservar motivo'
        form.employee_message = 'Conservar respuesta'
        form.operation = 'close_request'
        wizard = form.save()
        self.assertEqual(wizard.observed_state, reference)
        before = self._unchanged_state()
        wizard.action_apply()
        self.assertEqual(self._unchanged_state(), before)


@tagged('post_install', '-at_install')
class TestBrowser170(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-09-14 13:00:00', tick=True))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'

    def _select(self, browser, evaluate, wait, pointer, name, value):
        labels = {'accept': 'Aplicar elección pendiente', 'replace': 'Corregir opción',
                  'close_request': 'Cerrar solicitud sin cambiar la vianda', 'note': 'Responder al empleado'}
        pointer(f'.modal [name="{name}"] .o_select_menu_toggler')
        target = ('Array.from(document.querySelectorAll(".o_field_selection_menu .dropdown-item"))'
                  '.find(e=>e.textContent.trim()===' + json.dumps(labels[value]) + ')')
        wait(target)
        # El selector se obtiene de la estructura real; la elección se hace por puntero.
        index = evaluate('(()=>{const e=' + target + ';return Array.from(e.parentElement.children).indexOf(e)+1;})()')
        pointer(f'.o_field_selection_menu .dropdown-item:nth-child({index})')
        wait('document.querySelector(' + json.dumps(f'.modal [name="{name}"] input') + ').value===' + json.dumps(labels[value]))

    def test_pointer_create_without_reason_in_actual_form(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()

        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector(".modal [name=name] input")')
            for name, value in [('name', 'Alta navegador 170'), ('login', 'lf170-pointer-new')]:
                pointer(f'.modal [name="{name}"] input')
                type_keys(value)
            pointer('.modal [name="customer_company_id"] input')
            type_keys(self.customer.name)
            wait('document.querySelector(".o-autocomplete--dropdown-item")')
            pointer('.o-autocomplete--dropdown-item')
            self.assertFalse(evaluate('document.querySelector(".modal [name=reason]").classList.contains("o_required_modifier")'))
            self.assertFalse(evaluate('document.querySelector(".modal [name=reason] input").value'))
            pointer('.modal button[name="action_apply"]:not([style*="display: none"])')
            wait('!document.querySelector(".modal [name=operation]") && document.querySelector(".o_form_view")')
            browser.take_screenshot(prefix='lf170_alta_sin_motivo_').result(timeout=10)

        self._employee_pointer_journey('/odoo/action-kai_viandas.employee_access_action', journey,
                                       width=1366, login=self.operator.login)
        self.env.invalidate_all()
        user = self.env['res.users'].search([('login', '=', 'lf170-pointer-new')])
        self.assertEqual(len(user), 1)
        self.assertIn('Motivo: Alta de empleado', str(user.partner_id.message_ids.mapped('body')))

    def _two_sessions(self, change):
        employee, _ = self._create_employee('lf170-browser-employee')
        other_product = self.env['product.product'].create({'name': 'Pescado 170', 'description_sale': 'Pescado 170', 'sale_ok': True})
        self.menus[0].with_user(self.operator).write({'product_ids': [Command.link(other_product.id)]})
        service = self.env['lafija.reservation'].with_user(employee)
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        self.menus[0].with_user(self.operator).action_take_list()
        service._submit_selections(self.website, [(self.menus[0].id, other_product.id)])
        record._request_correction('Consulta previa 170')
        login = self._real_login(employee.login, 'employee-password-123')
        self.assertEqual(login.status_code, 303)
        employee_http = requests.Session()
        self.addCleanup(employee_http.close)
        session_id = self.opener.cookies.get('session_id', domain=urlsplit(self.base_url()).hostname, path='/')
        employee_http.cookies.set('session_id', session_id, domain='corporate.test', path='/')
        employee_http.headers['Host'] = 'corporate.test'
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self.env.flush_all()
        second = None
        if change == 'operator':
            second = self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Segundo operador 170', 'login': 'lf170-second-operator',
                'password': 'second-operator-password-170',
                'group_ids': [Command.set([self.env.ref('kai_viandas.group_operator').id])]})
            self.env.flush_all()

        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector("button[name=action_correct]")')
            pointer('button[name="action_correct"]')
            wait('document.querySelector(".modal [name=reason] textarea")')
            operation = 'accept' if change == 'choice' else 'close_request' if change == 'request' else 'replace'
            self._select(browser, evaluate, wait, pointer, 'operation', operation)
            if operation == 'replace':
                pointer('.modal [name="product_id"] input')
                type_keys(self.product.name)
                wait('document.querySelector(".o-autocomplete--dropdown-item")?.textContent.includes('
                     + json.dumps(self.product.name) + ')')
                pointer('.o-autocomplete--dropdown-item')
            for name, value in [('reason', 'INTERNO 170 NO PUBLICAR'), ('employee_message', 'Respuesta escrita 170')]:
                pointer(f'.modal [name="{name}"] textarea')
                type_keys(value)
            # Cada sesión participa en el cursor aislado habilitado por browser_js.
            employee_http.cookies.set(TEST_CURSOR_COOKIE_NAME, self.http_request_key)
            if change == 'choice':
                # Segunda sesión: POST real del empleado mientras el formulario sigue abierto.
                response = employee_http.get(self.base_url() + '/my/viandas?week=2026-09-14', timeout=20)
                self.assertEqual(response.status_code, 200)
                tree = html.fromstring(response.content)
                self.assertTrue(tree.xpath('//form[@id="lf-week-form"]'))
                data = {n.get('name'): n.get('value', '') for n in tree.xpath('//form[@id="lf-week-form"]//input[@type="hidden"]')}
                # Elegir su vigente anula el cambio pendiente, sin cambiar la lista.
                data['menu_' + str(self.menus[0].id)] = str(self.product.id)
                response = employee_http.post(self.base_url() + '/my/viandas/reservar', data=data, timeout=20)
                self.assertEqual(response.status_code, 200)
                self.assertIn('anulaste', response.text)
            elif change == 'request':
                response = employee_http.get(self.base_url() + f'/my/viandas/{record.id}', timeout=20)
                self.assertEqual(response.status_code, 200)
                tree = html.fromstring(response.content)
                form = tree.xpath('//form[.//textarea]')[0]
                data = {n.get('name'): n.get('value', '') for n in form.xpath('.//input[@type="hidden"]')}
                data['message'] = 'Consulta NUEVA del empleado 170'
                response = employee_http.post(self.base_url() + form.get('action'), data=data, timeout=20)
                self.assertEqual(response.status_code, 200)
            else:
                # Otra sesión interna real; la acción del operador principal sigue siendo de puntero.
                with requests.Session() as client:
                    client.cookies.set(TEST_CURSOR_COOKIE_NAME, self.http_request_key)
                    auth = client.post(self.base_url() + '/web/session/authenticate', json={'jsonrpc': '2.0', 'id': 1,
                        'params': {'db': self.env.cr.dbname, 'login': second.login,
                                   'password': 'second-operator-password-170'}}, timeout=20).json()
                    self.assertEqual(auth['result']['uid'], second.id)
                    def call(method, args):
                        result = client.post(self.base_url() + '/web/dataset/call_kw/lafija.reservation.correction/' + method,
                            json={'jsonrpc': '2.0', 'id': 2, 'params': {'model': 'lafija.reservation.correction',
                                'method': method, 'args': args, 'kwargs': {}}}, timeout=20).json()
                        self.assertNotIn('error', result, result)
                        return result['result']
                    wid = call('create', [{'reservation_id': record.id, 'operation': 'replace',
                        'product_id': other_product.id, 'reason': 'Segunda actuación 170'}])
                    call('action_apply', [[wid]])
            with _registry_test_lock:
                self.env.invalidate_all()
                before = record.sudo().event_ids.ids
            pointer('.modal button[name="action_apply"]:not([style*="display: none"])')
            wait('document.querySelector(".modal [name=conflict_notice]")?.textContent.includes("No se aplicó")')
            self.assertEqual(evaluate('document.querySelector(".modal .modal-title").textContent.trim()'), 'Editar pedido')
            self.assertEqual(evaluate('document.querySelectorAll(".modal [name=reason] textarea").length'), 1)
            self.assertEqual(evaluate('document.querySelector(".modal [name=reason] textarea").value'), 'INTERNO 170 NO PUBLICAR')
            self.assertEqual(evaluate('document.querySelector(".modal [name=employee_message] textarea").value'), 'Respuesta escrita 170')
            with _registry_test_lock:
                self.env.invalidate_all()
                self.assertEqual(record.sudo().event_ids.ids, before)
            if change == 'request':
                self.assertIn('Consulta NUEVA', evaluate('document.querySelector(".modal [name=request_text]").textContent'))
            elif change == 'operator':
                self.assertIn('Pescado 170', evaluate('document.querySelector(".modal [name=current_choice]").textContent'))
            browser.take_screenshot(prefix='lf170_conflicto_' + change + '_').result(timeout=10)
            if change == 'choice':
                # Ya no hay opción pendiente que aplicar: ahora el operador decide responder.
                self._select(browser, evaluate, wait, pointer, 'operation', 'note')
            pointer('.modal button[name="action_apply"]:not([style*="display: none"])')
            wait('!document.querySelector(".modal [name=reason] textarea")')
            # Cerrar el modal dispara lecturas de chatter/formulario. HttpCase
            # comparte cursor: no leerlo a la vez que esas peticiones pendientes.
            with _registry_test_lock:
                self.env.invalidate_all()
                self.assertEqual(len(record.sudo().event_ids), len(before) + 1)
                self.assertIn('Respuesta escrita 170', str(record._employee_values()))
                self.assertNotIn('INTERNO 170', str(record._employee_values()))

        self._employee_pointer_journey(f'/odoo/action-kai_viandas.reservation_action/{record.id}', journey,
                                       width=1366, login=self.operator.login)

    def test_pointer_employee_changes_pending_in_second_session(self):
        self._two_sessions('choice')

    def test_pointer_employee_sends_request_while_operator_closes(self):
        self._two_sessions('request')

    def test_pointer_second_operator_corrects_before_first_confirms(self):
        self._two_sessions('operator')
