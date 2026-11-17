import base64
import csv
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import _registry_test_lock
from odoo.addons.base.models.res_users import ResUsers as NativeUsers

from ..models import padron_io
from .test_identity import LafijaCommon
from .test_pages import PagesCommon
from .test_release_160 import TestRelease160


class BatchCommon(LafijaCommon):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory(prefix='lf190-test-')
        self.addCleanup(self.directory.cleanup)
        self.enterContext(patch.object(padron_io, 'runtime_dir', return_value=Path(self.directory.name)))

    def batch(self, text='nombre;usuario\nJuan Pérez;abc.jperez\nAna Gómez;abc.agomez', **values):
        return self.env['lafija.employee.batch'].with_user(self.operator).create({
            'customer_company_id': self.customer.id, 'website_id': self.website.id,
            'prefix': 'abc', 'source_text': text, **values})

    def ready(self, **values):
        batch = self.batch(**values)
        batch.action_load()
        self.assertEqual(batch.state, 'validated', batch.notice)
        batch.action_confirm()
        self.assertEqual(batch.state, 'queued')
        return batch

    def complete(self, **values):
        batch = self.ready(**values)
        batch._create_all()
        self.assertEqual(batch.state, 'done')
        return batch


@tagged('post_install', '-at_install')
class TestPadron190(BatchCommon):
    def test_csv_and_text_same_quotes_accents_blank_lines_and_no_accounts_in_preview(self):
        source = 'nombre;usuario\r\n"Gómez; Ana";abc.ana\r\n\r\n"Nombre ""citado""\ncompuesto";abc.nombre\r\n'
        before = self.env['res.users'].search_count([])
        text = self.batch(source)
        upload = self.batch(False, upload=base64.b64encode(source.encode('utf-8-sig')), upload_name='padron.csv')
        with patch.object(type(self.env['mail.mail']), 'send') as send:
            text.action_load()
            upload.action_load()
        self.assertEqual(text.state, 'validated')
        self.assertEqual(text.line_ids.mapped('name'), upload.line_ids.mapped('name'))
        self.assertEqual(text.line_ids.mapped('row_number'), [2, 5])
        self.assertEqual(self.env['res.users'].search_count([]), before)
        send.assert_not_called()

    def test_bad_headers_shape_encoding_and_boundaries(self):
        for raw in (b'nombre;empresa\nAna;ABC', b'nombre;password\nAna;x', b'nombre;usuario;usuario\nA;b;c',
                    b'nombre;usuario\nA;b;c', b'\xff\xfe', b'nombre;usuario\n"sin cierre', b'nombre;usuario\n\n'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                padron_io.parse_padron(raw)
        valid = 'nombre;usuario\n' + '\n'.join('Persona;' for _ in range(200))
        self.assertEqual(len(padron_io.parse_padron(valid)), 200)
        with self.assertRaisesRegex(ValidationError, 'hasta 200 filas.*varios envíos'):
            padron_io.parse_padron(valid + '\nPersona;')
        with self.assertRaises(ValidationError):
            padron_io.parse_padron(b'x' * (padron_io.MAX_INPUT_BYTES + 1))

    def test_missing_name_bad_company_site_and_csv_login_errors_are_visible(self):
        batch = self.batch('nombre;usuario\n;abc.sin.nombre\nNombre;=SUM(1)')
        batch.action_load()
        self.assertEqual(batch.state, 'draft')
        self.assertTrue(all(batch.line_ids.mapped('error')))
        batch.write({'customer_company_id': self.operator.partner_id.id})
        batch.action_validate()
        self.assertEqual(batch.state, 'draft')
        with self.assertRaises(ValidationError):
            batch.action_confirm()

    def test_generated_user_legajo_and_numeric_suffix_are_visible_and_stable(self):
        self._create_employee(login='abc.juan.perez')
        batch = self.batch('nombre;usuario;legajo\nJuan Pérez;;\nAna Gómez;;00123\nPersona;Mi.Usuario;')
        batch.action_load()
        self.assertEqual(batch.line_ids.mapped('login'), ['abc.juan.perez.2', 'abc.00123', 'Mi.Usuario'])
        before = batch.line_ids.mapped('login')
        batch.action_validate()
        self.assertEqual(batch.line_ids.mapped('login'), before)
        batch.write({'prefix': 'xyz'})
        batch.action_validate()
        self.assertEqual(batch.line_ids.mapped('login'), ['xyz.juan.perez', 'xyz.00123', 'Mi.Usuario'])

    def test_duplicate_names_need_confirmation_and_duplicate_logins_cannot_override(self):
        batch = self.batch('nombre;usuario\nJuan Pérez;abc.uno\nJuan Pérez;abc.dos')
        batch.action_load()
        self.assertEqual(batch.state, 'draft')
        self.assertTrue(all(batch.line_ids.mapped('warning')))
        batch.write({'confirm_duplicate_names': True})
        batch.action_validate()
        self.assertEqual(batch.state, 'validated')
        batch.line_ids[1].write({'login': 'abc.uno'})
        batch.action_validate()
        self.assertEqual(batch.state, 'draft')
        self.assertIn('repetido', batch.line_ids[1].error)

    def test_explicit_logins_check_archived_internal_and_other_sites(self):
        employee, _ = self._create_employee(login='taken.employee')
        self._manage(employee, 'disable').action_apply()
        batch = self.batch('nombre;usuario\nInterno;lf-operator\nParticular;lf-private\nArchivado;taken.employee')
        batch.action_load()
        self.assertEqual(batch.state, 'draft')
        self.assertTrue(all('existente' in r.error for r in batch.line_ids))

    def test_input_edit_invalidates_preview_and_queued_is_immutable(self):
        batch = self.batch()
        batch.action_load()
        batch.line_ids[0].write({'name': 'Otro nombre'})
        self.assertEqual(batch.state, 'draft')
        with self.assertRaises(ValidationError):
            batch.action_confirm()
        batch.action_validate()
        batch.action_confirm()
        with self.assertRaises(ValidationError):
            batch.line_ids[0].write({'login': 'abc.otro'})
        with self.assertRaises(AccessError):
            batch.write({'state': 'done'})

    def test_revalidate_at_confirmation_and_at_worker_start(self):
        batch = self.batch()
        batch.action_load()
        self._create_employee(login='abc.jperez')
        batch.action_confirm()
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.line_ids.mapped('user_id'))
        other = self.ready(text='nombre;usuario\nMaría;abc.maria')
        self._create_employee(login='abc.maria')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            other._create_all()
        self.assertFalse(other.line_ids.user_id)

    def test_all_identities_audit_passwords_and_individual_still_share_service(self):
        batch = self.ready()
        with patch.object(type(self.env['mail.mail']), 'send') as send:
            batch._create_all()
        send.assert_not_called()
        rows = list(csv.DictReader(io.StringIO(batch._credentials().decode('utf-8-sig')), delimiter=';'))
        for csv_row in rows:
            self.assertRegex(csv_row['contraseña'], r'^[1-9][0-9]{5}$')
        for row, csv_row in zip(batch.line_ids, rows):
            user = row.user_id.sudo()
            self.assertFalse(user.email or row.partner_id.parent_id or row.partner_id.child_ids)
            self.assertEqual(user.website_id, self.website)
            self.assertEqual(row.partner_id.lf_customer_company_id, self.customer)
            self.assertTrue(user._lf_can_use_site(self.website))
            auth = NativeUsers._check_credentials(user.with_user(user), {'type': 'password', 'password': csv_row['contraseña']}, {'interactive': True})
            self.assertEqual(auth['uid'], user.id)
            audit = ' '.join(row.partner_id.message_ids.mapped('body'))
            self.assertIn(batch.name, audit)
            self.assertNotIn(csv_row['contraseña'], audit + ' '.join(batch.message_ids.mapped('body')))
            self.assertEqual(row.partner_id.message_ids.filtered(lambda m: batch.name in (m.body or '')).author_id, self.operator.partner_id)
        self.assertFalse(batch.source_text or batch.upload)

    def test_error_in_last_row_rolls_back_every_identity_and_note(self):
        batch = self.ready()
        before_users = self.env['res.users'].search_count([])
        before_partners = self.env['res.partner'].search_count([])
        service_type = type(self.env['lafija.employee.onboarding'])
        original = service_type._create_identity
        def fail_last(service, **values):
            result = original(service, **values)
            if values['login'] == 'abc.agomez':
                raise ValidationError('Incidencia sintética al final')
            return result
        with self.assertRaises(ValidationError), self.cr.savepoint(), patch.object(service_type, '_create_identity', fail_last):
            batch._create_all()
        self.env.invalidate_all()
        self.assertEqual(self.env['res.users'].search_count([]), before_users)
        self.assertEqual(self.env['res.partner'].search_count([]), before_partners)
        self.assertFalse(batch.line_ids.mapped('user_id'))

    def test_reconfirm_and_recover_do_not_recreate_or_rotate_passwords(self):
        batch = self.ready()
        progress = batch.progress_id
        batch.action_confirm()
        self.assertEqual(batch.progress_id, progress)
        batch._create_all()
        users = batch.line_ids.user_id
        data = batch._credentials()
        batch.action_confirm()
        batch._create_all()
        self.assertEqual(batch.line_ids.user_id, users)
        self.assertEqual(batch._credentials(), data)

    def test_credentials_expiry_is_checked_even_without_cleanup_and_file_loss_has_exit(self):
        with freeze_time('2026-09-14 12:00:00'):
            batch = self.complete()
        path = padron_io.credential_path(self.cr.dbname, batch.sudo().credential_token)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with freeze_time('2026-09-14 12:14:59'):
            data = batch._credentials()
            self.assertTrue(data)
        with freeze_time('2026-09-14 12:15:00'), self.assertRaises(AccessError):
            batch._credentials()
        self.assertTrue(path.exists())
        with freeze_time('2026-09-14 12:10:00'):
            path.unlink()
            with self.assertRaisesRegex(AccessError, 'restablecimiento'):
                batch._credentials()
        self.assertEqual(batch.state, 'done')

    def test_other_operator_external_roles_cannot_read_batch_or_credentials(self):
        batch = self.complete()
        other = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Otro operador', 'login': 'another-op',
            'group_ids': [Command.set([self.env.ref('kai_viandas.group_operator').id])]})
        employee, _ = self._create_employee('another.employee')
        for user in (other, employee, self.private, self.env.ref('base.public_user')):
            with self.subTest(user=user.id), self.assertRaises(AccessError):
                batch.with_user(user)._credentials()
            with self.assertRaises(AccessError):
                batch.with_user(user).read(['line_ids'])
        with self.assertRaises(AccessError):
            batch.read(['credential_token'])
        self.assertFalse(self.env['ir.attachment'].search([('res_model', '=', batch._name), ('res_id', '=', batch.id)]))

    def test_purge_expired_and_orphan_files_keeps_recent_download(self):
        batch = self.complete()
        recent = padron_io.credential_path(self.cr.dbname, batch.sudo().credential_token)
        old = recent.with_name('0' * 32 + '.csv')
        old.write_bytes(b'archivo sintetico')
        os.utime(old, (1, 1))
        padron_io.purge_credentials(self.cr.dbname)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_forbidden_source_not_persisted_and_worker_timeout_rolls_back(self):
        before = self.env['lafija.employee.batch'].search_count([])
        with self.assertRaises(ValidationError):
            self.batch('nombre;usuario;contraseña\nPersona;abc.nombre;no-guardar')
        self.assertEqual(self.env['lafija.employee.batch'].search_count([]), before)
        batch = self.ready()
        with patch('odoo.addons.kai_viandas.models.employee_batch.MAX_RUN_SECONDS', -1), self.assertRaises(ValidationError), self.cr.savepoint():
            batch._create_all()
        self.assertFalse(batch.line_ids.user_id)

    def test_new_batch_action_is_kept_without_menu_and_no_new_business_roles(self):
        self.assertFalse(self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"), ("name", "=", "menu_employee_batch"),
        ]))
        action = self.env.ref('kai_viandas.employee_batch_action')
        self.assertEqual(action.res_model, 'lafija.employee.batch')
        self.assertFalse(self.operator.has_group('base.group_system'))
        self.assertFalse(self.operator.has_group('base.group_erp_manager'))
        self.assertFalse(self.env['lafija.employee.batch.progress'].with_user(self.operator).has_access('read'))

    def test_context_defaults_cannot_forge_state_owner_or_row_result(self):
        batch = self.env['lafija.employee.batch'].with_user(self.operator).with_context(
            default_state='done', default_create_uid=self.private.id, default_credential_token='f' * 32,
            default_source_text='nombre;contraseña\nPersona;no-persistir',
        ).create({'customer_company_id': self.customer.id, 'website_id': self.website.id})
        self.assertEqual(batch.state, 'draft')
        self.assertEqual(batch.create_uid, self.operator)
        self.assertFalse(batch.sudo().credential_token)
        self.assertFalse(batch.source_text)
        row = self.env['lafija.employee.batch.line'].with_user(self.operator).with_context(
            default_user_id=self.private.id).create({'batch_id': batch.id, 'row_number': 2, 'name': 'Persona', 'login': 'abc.persona'})
        self.assertFalse(row.user_id)

    def test_csv_formula_safety_quoting_newlines_and_exact_credentials(self):
        names = ['=HYPERLINK("evil")', '+1+1', '-1+2', '@SUM(1)', ' \t=2', 'Nombre; "citado"\nsegunda línea']
        rows = [(name, f'abc.persona{i}', 'Lf-password_individual123') for i, name in enumerate(names)]
        data = padron_io.credentials_csv('P-1', '=Empresa', 'https://corporate.test', rows)
        values = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig')), delimiter=';'))
        self.assertEqual(len(values), len(rows))
        for original, row in zip(rows, values):
            self.assertEqual(row['usuario'], original[1])
            self.assertEqual(row['contraseña'], original[2])
            self.assertFalse(row['nombre'].lstrip().startswith(('=', '+', '-', '@')))
        self.assertEqual(values[-1]['nombre'], names[-1])
        with self.assertRaises(ValidationError):
            padron_io.credentials_csv('P', 'Empresa', 'https://test', [('A', '00123', 'Lf-password')])


@tagged('post_install', '-at_install')
class TestPadronPages190(BatchCommon, PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def setUp(self):
        super().setUp()
        self.env['res.lang']._activate_lang('es_AR')
        self.operator.lang = 'es_AR'
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'

    def test_http_creator_expiration_and_forbidden_sessions(self):
        batch = self.complete()
        self.authenticate(self.operator.login, 'fixture')
        url = f'/lafija/padron/{batch.id}/credenciales'
        headers = {'Host': 'public.test'}
        self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
        first = self.url_open(url, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertIn('no-store', first.headers['Cache-Control'])
        self.assertEqual(first.content, self.url_open(url, headers=headers).content)
        other = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Otro operador HTTP', 'login': 'other-http190',
            'group_ids': [Command.set([self.env.ref('kai_viandas.group_operator').id])]})
        self.authenticate(other.login, 'fixture')
        self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
        self.assertEqual(self.url_open(url, headers=headers).status_code, 403)
        self._anonymous()
        self.assertIn(self.url_open(url, headers=headers, allow_redirects=False).status_code, (302, 303, 403))
        self.authenticate(self.private.login, 'private-password-123')
        self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
        self.assertEqual(self.url_open(url, headers=headers).status_code, 403)
        employee, _ = self._create_employee('http.employee')
        self._real_login(employee.login, 'employee-password-123')
        self.assertEqual(self.url_open(url).status_code, 403)
        self.authenticate(self.operator.login, 'fixture')
        self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
        batch._store({'credentials_until': fields.Datetime.now() - timedelta(seconds=1)})
        self.assertEqual(self.url_open(url, headers=headers).status_code, 403)

    def test_pointer_edit_preview_queue_visible_progress_and_reopen_result(self):
        batch = self.batch('nombre;usuario\nAna;lf-private\nJuan;abc.juan')
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self.operator.password = 'operator190-password'
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector("button[name=action_load]")')
            pointer('button[name=action_load]')
            wait('document.querySelector("[name=error]")?.textContent.includes("existente")')
            self.assertFalse(evaluate('Boolean(document.querySelector("button[name=action_confirm]"))'))
            pointer('.o_field_one2many .o_data_row [name=login]')
            wait('document.querySelector("[name=login] input")')
            pointer('[name=login] input')
            browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyDown', 'key': 'a', 'code': 'KeyA', 'modifiers': 2, 'windowsVirtualKeyCode': 65})
            browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyUp', 'key': 'a', 'code': 'KeyA', 'windowsVirtualKeyCode': 65})
            type_keys('abc.ana')
            self.assertEqual(evaluate('document.querySelector("[name=login] input").value'), 'abc.ana')
            pointer('button[name=action_validate]')
            wait('document.querySelector("button[name=action_confirm]")')
            with _registry_test_lock:
                self.env.invalidate_all()
                self.assertFalse(batch.line_ids.user_id)
            pointer('button[name=action_confirm]')
            wait('document.querySelector(".modal-footer .btn-primary")')
            pointer('.modal-footer .btn-primary')
            wait('document.querySelector("[name=progress_text]")?.textContent.includes("espera")')
            with _registry_test_lock:
                self.env.invalidate_all()
                self.assertEqual(batch.state, 'queued')
                batch.sudo().progress_id.write({'processed': 1, 'attempt': 1})
                self.env.flush_all()
            wait('document.querySelector("[name=progress_text]")?.textContent.includes("Procesando 1 de 2")')
            # El HttpCase comparte cursor con sus peticiones; serializar esta
            # actualización de fixture. La contención real va en lafija-qa.
            with _registry_test_lock:
                batch._create_all()
                self.env.flush_all()
            wait('document.querySelector("button[name=action_download]")')
            self.assertIn('2 altas confirmadas', evaluate('document.querySelector("[name=progress_text]").textContent'))
            browser.take_screenshot(prefix='lf190_lote_resultado_').result(timeout=10)
        self._employee_pointer_journey(f'/odoo/lafija.employee.batch/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual(len(batch.line_ids.user_id), 2)
        self.assertEqual(batch.line_ids.mapped('login'), ['abc.ana', 'abc.juan'])
