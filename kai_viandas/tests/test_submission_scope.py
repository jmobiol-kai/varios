"""El cálculo de novedades se limita al envío sin ampliar permisos ni alterar mensajes."""
from datetime import date, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_reservation import ReservationCommon


@tagged('post_install', '-at_install')
class TestSubmissionScope(ReservationCommon):
    def setUp(self):
        super().setUp()
        self.employee, _ = self._create_employee()
        self.service = self.env['lafija.reservation'].with_user(self.employee)

    def test_history_size_does_not_expand_snapshot_and_other_employee_is_excluded(self):
        wanted = [(self.menus[i].id, self.chicken.id) for i in (0, 1)]
        records = self.service._submit_selections(self.website, wanted)
        expected = {r.id: r.sudo().event_ids[-1:].id for r in records}
        self.assertEqual(self.service._last_events_for_submission(self.website, wanted), expected)
        history = self.env['lafija.menu.day'].with_user(self.operator).create([
            {'date': date(2025, 1, 1) + timedelta(days=i), 'website_id': self.website.id,
             'published': True, 'product_ids': [Command.set(self.chicken.ids)]} for i in range(30)])
        # Reservas históricas presentadas legítimamente antes del consumo.
        with freeze_time('2024-12-31 15:00:00'):
            for menu in history:
                self.service._submit_selections(self.website, [(menu.id, self.chicken.id)])
        other, _ = self._create_employee('abc-same-dates')
        self.env['lafija.reservation'].with_user(other)._submit_selections(self.website, wanted)
        native_search = type(self.service).search
        examined = []

        def measured(model, domain, *args, **kwargs):
            result = native_search(model, domain, *args, **kwargs)
            if model.env.uid == self.employee.id:
                examined.append((domain, result.ids))
            return result

        with patch.object(type(self.service), 'search', measured):
            self.assertEqual(self.service._last_events_for_submission(self.website, wanted), expected)
        self.assertEqual(len(examined), 1)
        self.assertEqual(examined[0][0], [('date', 'in', self.menus[:2].mapped('date'))])
        self.assertEqual(set(examined[0][1]), set(records.ids))
        self.assertEqual(self.service.search_count([]), 32)

    def test_snapshot_keeps_new_choice_noop_and_annulment_distinct(self):
        monday, tuesday = self.menus[:2]
        wanted = [(monday.id, self.chicken.id), (tuesday.id, self.pork.id)]
        self.assertEqual(self.service._last_events_for_submission(self.website, wanted), {})
        records = self.service._submit_selections(self.website, wanted)
        monday_record = records.filtered(lambda r: r.date == monday.date)
        before = self.service._last_events_for_submission(self.website, wanted)
        self.service._submit_selections(self.website, wanted)
        self.assertEqual(self.service._last_events_for_submission(self.website, wanted), before)
        monday.with_user(self.operator).action_take_list()
        self.service._submit_selections(self.website, [(monday.id, self.fish.id)])
        after_choice = self.service._last_events_for_submission(self.website, wanted)
        self.assertNotEqual(after_choice[monday_record.id], before[monday_record.id])
        monday_record._request_correction('La consulta permanece abierta')
        before_annulment = self.service._last_events_for_submission(self.website, wanted)
        self.service._submit_selections(self.website, [(monday.id, self.chicken.id)],
                                        withdraw_current={monday.id: self.chicken.id})
        after_annulment = self.service._last_events_for_submission(self.website, wanted)
        self.assertNotEqual(after_annulment[monday_record.id], before_annulment[monday_record.id])
        self.assertEqual(monday_record.sudo().event_ids[-1:].kind, 'withdrawal')
        self.assertTrue(monday_record.sudo().attention_pending)
        self.assertEqual({key: value for key, value in after_annulment.items() if key != monday_record.id},
                         {key: value for key, value in before.items() if key != monday_record.id})

    def test_empty_or_oversized_payload_does_not_search_reservation_history(self):
        with patch.object(type(self.service), 'search', side_effect=AssertionError('No consultar historial')):
            self.assertEqual(self.service._last_events_for_submission(self.website, []), {})
            with self.assertRaisesRegex(ValidationError, 'una semana'):
                self.service._last_events_for_submission(self.website, [(i, self.chicken.id) for i in range(1, 9)])
            with self.assertRaises(ValidationError):
                self.service._last_events_for_submission(self.website,
                    [(self.menus[0].id, self.chicken.id), (self.menus[0].id, self.pork.id)])
