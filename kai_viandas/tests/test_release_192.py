"""Límites del padrón y actualización del cron sin reactivar copias."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from ..models import employee_batch, padron_io
from .test_release_190 import BatchCommon


@tagged('post_install', '-at_install')
class TestPadronLimits192(BatchCommon):
    def test_fixed_limits_and_form_explain_independent_submissions(self):
        self.assertEqual(padron_io.MAX_ROWS, 200)
        self.assertEqual(padron_io.MAX_INPUT_BYTES, 512 * 1024)
        self.assertEqual(employee_batch.MAX_RUN_SECONDS, 240)
        arch = self.env.ref('kai_viandas.employee_batch_form').arch_db
        self.assertIn('Hasta 200 personas por envío', arch)
        self.assertIn('cada uno con su propia vista previa, confirmación y CSV de accesos', arch)
        self.assertNotIn('500', arch)

    def test_edited_preview_cannot_bypass_limit_and_does_not_create_users(self):
        source = 'nombre;usuario\n' + '\n'.join(f'Persona {i};abc.persona{i}' for i in range(200))
        batch = self.batch(source)
        batch.action_load()
        self.assertEqual(batch.state, 'validated', batch.notice)
        self.assertFalse(batch.line_ids.mapped('user_id'))
        self.env['lafija.employee.batch.line'].with_user(self.operator).create({
            'batch_id': batch.id, 'row_number': 202, 'name': 'Persona extra', 'login': 'abc.extra'})
        batch.action_validate()
        self.assertEqual(batch.state, 'draft')
        self.assertIn('entre 1 y 200 filas', batch.notice)
        self.assertIn('cada uno con su vista previa, confirmación y CSV de accesos', batch.notice)
        with self.assertRaises(ValidationError):
            batch.action_confirm()
        self.assertFalse(batch.line_ids.mapped('user_id'))

    def test_budget_includes_revalidation_before_any_identity(self):
        batch = self.ready()
        elapsed = [0]
        validate = type(batch)._validate_rows

        def slow_validation(record, **kwargs):
            result = validate(record, **kwargs)
            elapsed[0] = 240
            return result

        with patch.object(employee_batch.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                patch.object(type(batch), '_validate_rows', slow_validation), \
                patch.object(type(self.env['lafija.employee.onboarding']), '_create_identity') as create, \
                self.assertRaisesRegex(ValidationError, 'No se confirmó ninguna alta'), self.cr.savepoint():
            batch._create_all()
        create.assert_not_called()
        self.assertFalse(batch.line_ids.mapped('user_id'))
        self.assertFalse(list(padron_io.runtime_dir(self.env.cr.dbname).glob('*.csv')))

    def test_older_oversized_queued_batch_is_rejected_without_truncating_rows(self):
        source = 'nombre;usuario\n' + '\n'.join(f'Persona {i};abc.anterior{i}' for i in range(201))
        # Simular un lote encolado antes de actualizar desde el máximo anterior.
        with patch.object(padron_io, 'MAX_ROWS', 500):
            batch = self.ready(text=source)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            batch._create_all()
        self.assertEqual(len(batch.line_ids), 201)
        self.assertFalse(batch.line_ids.mapped('user_id'))
        self.assertEqual(batch.state, 'queued')
        self.assertFalse(self.env['res.users'].search([('login', '=like', 'abc.anterior%')]))

    def test_budget_after_last_row_rolls_back_all_accounts_before_csv(self):
        batch = self.ready()
        elapsed = [0]
        create = type(self.env['lafija.employee.onboarding'])._create_identity
        calls = []

        def slow_last_identity(service, **kwargs):
            result = create(service, **kwargs)
            calls.append(kwargs['login'])
            if len(calls) == len(batch.line_ids):
                elapsed[0] = 240
            return result

        with patch.object(employee_batch.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                patch.object(type(self.env['lafija.employee.onboarding']), '_create_identity', slow_last_identity), \
                patch.object(padron_io, 'publish_credentials') as publish, \
                self.assertRaisesRegex(ValidationError, 'No se confirmó ninguna alta'), self.cr.savepoint():
            batch._create_all()
        self.assertEqual(len(calls), 2)
        publish.assert_not_called()
        self.assertFalse(batch.line_ids.mapped('user_id'))
        self.assertFalse(self.env['res.users'].with_context(active_test=False).search([('login', 'in', calls)]))
        self.assertEqual(batch.state, 'queued')

    def test_cron_upgrade_keeps_activation_owner_nextcall_and_triggers(self):
        cron = self.env.ref('kai_viandas.cron_employee_batch')
        self.assertEqual((cron.interval_number, cron.interval_type), (1, 'hours'))
        # Simular el cron de 1.9.1 deshabilitado por neutralización.
        nextcall = fields.Datetime.now() + timedelta(hours=3)
        cron.write({'interval_number': 1, 'interval_type': 'minutes', 'active': False, 'nextcall': nextcall})
        owner = cron.user_id
        trigger = cron._trigger(at=nextcall)
        self.env['lafija.employee.batch']._set_cron_interval()
        self.assertEqual((cron.interval_number, cron.interval_type), (1, 'hours'))
        self.assertFalse(cron.active)
        self.assertEqual(cron.user_id, owner)
        self.assertEqual(cron.nextcall, nextcall)
        self.assertTrue(trigger.exists())
        with patch.object(type(cron), 'write') as write:
            self.env['lafija.employee.batch']._set_cron_interval()
        write.assert_not_called()

    def test_confirmation_still_triggers_hourly_cron_immediately(self):
        cron = self.env.ref('kai_viandas.cron_employee_batch')
        batch = self.batch()
        batch.action_load()
        with patch.object(type(cron), '_trigger', autospec=True) as trigger:
            batch.action_confirm()
        trigger.assert_called_once()
        self.assertEqual(trigger.call_args.args[0].ids, cron.ids)
        self.assertEqual(batch.state, 'queued')
