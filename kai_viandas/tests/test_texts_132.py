"""Textos sobre historia conservada y regresión de la atomicidad ante conflicto."""
from freezegun import freeze_time
from lxml import html

from odoo import Command, fields
from odoo.tests import tagged

from .test_preparation import PreparationCommon
from .test_pages import PagesCommon


# Entrada de compatibilidad real; nunca debe convertirse en una salida visible.
LEGACY_WITHDRAWAL = 'Cambio solicitado retirado por el empleado'


@tagged('post_install', '-at_install')
class TestTextPresentation132(PreparationCommon):
    def test_old_event_is_presented_as_annulled_without_rewriting_history(self):
        cut = self._take()
        revision = cut.current_revision_id
        event = self.reservation.sudo()._record_event(
            self.employee, fields.Datetime.to_datetime('2026-09-14 13:35:00'),
            'withdrawal', 'Pollo', 'Pescado', 'Pollo', LEGACY_WITHDRAWAL)
        before = event.read(['kind', 'actor_id', 'occurred_at', 'previous_description',
                             'received_description', 'applied_description', 'result'])
        self.assertEqual(event.with_user(self.operator).result_label, 'Cambio anulado por el empleado')
        self.assertEqual(dict(event.fields_get(['kind'])['kind']['selection'])['withdrawal'],
                         'Cambio anulado por el empleado')
        choice = self.reservation._employee_values()['choices'][-1]
        self.assertEqual(choice, {'text': 'Cambio anulado', 'author': 'Vos',
                                 'date': '14/09/2026 10:35',
                                 'outcome': 'Cambio que se anuló: Pescado. Sigue vigente Pollo.'})
        self.assertEqual(event.read(list(before[0])), before)
        self.assertEqual(cut.current_revision_id, revision)
        self.assertEqual(cut.revision_ids, revision)
        self.assertFalse(self.reservation.sudo().pending)

    def test_last_act_explains_timing_without_implying_pending_and_label_handling_copy(self):
        self._take()
        with freeze_time('2026-09-14 13:35:00'):
            self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
            self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id)],
                                            withdraw_current={self.menu.id: self.chicken.id})
        record = self.reservation.with_user(self.operator)
        self.assertEqual(record.attention_label, 'Sin pendientes')
        self.assertIn('Después de tomar lista', record.timing_label)
        field = record.fields_get(['timing_label'])['timing_label']
        self.assertEqual(field['string'], 'Momento del último acto')
        self.assertEqual(field['help'], 'Incluye elecciones, consultas y anulaciones; no indica un pendiente.')
        replacement = self.env['lafija.label.replacement'].with_user(self.operator)
        self.assertEqual(replacement.fields_get(['note'])['note']['string'],
                         'Qué reemplazo físico de etiquetas se coordinó')
        view = self.env['lafija.label.print'].with_user(self.operator).get_view(
            view_id=self.env.ref('kai_viandas.label_print_form').id, view_type='form')
        self.assertIn('coordiná quitar las etiquetas anteriores', view['arch'])
        self.assertNotIn('retir', view['arch'].lower())


@tagged('post_install', '-at_install')
class TestTextPages132(PagesCommon):
    def test_employee_http_history_normalizes_old_event_and_keeps_actor_time(self):
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        employee, _ = self._create_employee()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        event = record.sudo()._record_event(
            employee, fields.Datetime.to_datetime('2026-09-14 13:35:00'), 'withdrawal',
            'Pollo con arroz', 'Pescado', 'Pollo con arroz', LEGACY_WITHDRAWAL)
        self._real_login(employee.login, 'employee-password-123')
        response = self.url_open(f'/my/viandas/{record.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Cambio anulado', response.text)
        self.assertIn('Cambio que se anuló: Pescado. Sigue vigente Pollo con arroz.', response.text)
        self.assertIn('14/09/2026 10:35', response.text)
        self.assertIn('Vos', response.text)
        self.assertIn('Última acción que enviaste:', response.text)
        self.assertNotIn('retir', response.text.lower())
        self.assertNotIn('271828', response.text)
        self.env.invalidate_all()
        self.assertEqual(event.result, LEGACY_WITHDRAWAL)

    def test_stale_annulment_rolls_back_week_and_preserves_other_unsaved_day(self):
        # El defecto de 1.3.2 conserva ahora el borrador sin guardar parte del envío.
        employee, _ = self._create_employee()
        service = self.env['lafija.reservation'].with_user(employee)
        monday, thursday = self.menus[0], self.menus[3]
        fish = self.env['product.product'].create({'name': 'Pescado pendiente', 'sale_ok': True})
        monday.with_user(self.operator).write({'product_ids': [Command.link(fish.id)]})
        record = service._submit_selections(self.website, [(monday.id, self.product.id)])
        monday.with_user(self.operator).action_take_list()
        service._submit_selections(self.website, [(monday.id, fish.id)])
        self._real_login(employee.login, 'employee-password-123')
        page = html.fromstring(self.url_open('/my/viandas?week=2026-09-14').content)
        token = page.xpath('//input[@name="csrf_token"]/@value')[0]
        old_current = page.xpath(f'//input[@name="withdraw_{monday.id}"]/@value')[0]
        self.assertEqual(page.xpath(f'//input[@name="withdraw_{monday.id}"]/@data-current-description'),
                         ['Pollo con arroz'])
        own = self.env['product.product'].create({'name': 'Vigente corregida por el operador', 'sale_ok': True})
        self.env['lafija.reservation.correction'].with_user(self.operator).create({
            'reservation_id': record.id, 'operation': 'replace', 'product_id': own.id,
            'reason': 'Corrección entre mostrar y guardar el formulario',
        }).action_apply()
        service._submit_selections(self.website, [(monday.id, fish.id)])
        events = record.sudo().event_ids
        response = self.url_open('/my/viandas/reservar', data={
            'csrf_token': token, 'week': '2026-09-14',
            'form_choices': page.xpath('//input[@name="form_choices"]/@value')[0],
            f'menu_{thursday.id}': str(self.product.id),  # Este día se procesa primero.
            f'menu_{monday.id}': old_current, f'withdraw_{monday.id}': old_current,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('La Fija cambió esta vianda mientras elegías.', response.text)
        self.env.invalidate_all()
        self.assertEqual(record.sudo().current_product_id, own)
        self.assertEqual(record.sudo().pending_product_id, fish)
        self.assertEqual(record.sudo().event_ids, events)
        self.assertFalse(service.search([('date', '=', thursday.date)]))
        page = html.fromstring(response.content)
        self.assertEqual(page.xpath(f'//details[@data-menu="{thursday.id}"]/@data-selected'), [''])
        self.assertEqual(page.xpath(f'//input[@name="menu_{thursday.id}" and @checked]/@value'), [str(self.product.id)])
