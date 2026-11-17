from freezegun import freeze_time

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .test_reservation import ReservationCommon


class PreparationCommon(ReservationCommon):
    def setUp(self):
        super().setUp()
        self.employee, _ = self._create_employee()
        self.menu = self.menus[0]
        self.service = self.env["lafija.reservation"].with_user(self.employee)
        with freeze_time("2026-09-08 12:00:00"):
            self.reservation = self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id)])

    def _take(self):
        with freeze_time("2026-09-14 13:05:00"):
            result = self.menu.with_user(self.operator).action_take_list()
        return self.env["lafija.preparation.cut"].browse(result["res_id"])

    def _resolve(self, operation, **kwargs):
        return self.env["lafija.reservation.correction"].with_user(self.operator).create({
            "reservation_id": self.reservation.id, "operation": operation,
            "reason": "ABC solicita corregir el caso", **kwargs,
        }).action_apply()

    def _confirm_draft_mos(self, reservations=None):
        records = (reservations or self.reservation).sudo()
        mos = records.fulfillment_production_ids.filtered(lambda mo: mo.state == "draft")
        if mos:
            mos.action_confirm()
        return mos


@tagged("post_install", "-at_install")
class TestPreparation(PreparationCommon):
    def test_list_includes_last_applied_choice_and_repetition_keeps_first_revision(self):
        with freeze_time("2026-09-14 12:30:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.pork.id)])
        cut = self._take()
        first = cut.current_revision_id
        self.assertEqual(first.line_ids.description, "Cerdo")
        self.assertEqual(cut.taken_by, self.operator)
        self.assertEqual(self._take(), cut)
        self.assertEqual(cut.current_revision_id, first)
        self.assertEqual(len(cut.revision_ids), 1)

    def test_late_before_cut_applies_after_cut_is_pending_and_new_reservation_stays_out(self):
        with freeze_time("2026-09-14 13:02:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.pork.id)])
        cut = self._take()
        self.assertTrue(cut.current_revision_id.line_ids.after_reference_time)
        with freeze_time("2026-09-14 13:06:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
            other, _ = self._create_employee("abc-second")
            new = self.env["lafija.reservation"].with_user(other)._submit_selections(self.website, [(self.menu.id, self.chicken.id)])
        self.assertEqual(self.reservation.current_description, "Cerdo")
        self.assertEqual(self.reservation.pending_description, "Pescado")
        self.assertTrue(self.reservation.after_preparation_cut)
        self.assertTrue(new.pending)
        self.assertFalse(new.current_description)
        self.assertEqual(cut.current_revision_id.line_ids.reservation_id, self.reservation.sudo())
        with freeze_time("2026-09-17 16:00:00"):
            payload = self.reservation._employee_values()
        self.assertEqual(payload["current"], "Cerdo")
        self.assertEqual(payload["pending"], "Pescado")
        self.assertTrue(payload["needs_attention"])

    def test_accept_restore_and_cancel_keep_every_preparation_revision(self):
        cut = self._take()
        first = cut.current_revision_id
        with freeze_time("2026-09-14 13:06:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        moment = self.reservation.last_employee_change_at
        self._resolve("accept")
        second = cut.current_revision_id
        self.assertEqual(second.number, 2)
        self.assertEqual(second.line_ids.description, "Pescado")
        self.assertEqual(first.line_ids.description, "Pollo")
        self.assertFalse(self.reservation.pending)
        self.assertEqual(self.reservation.last_employee_change_at, moment)
        self.assertTrue(self.reservation.after_preparation_cut)
        self._resolve("restore", previous_line_id=first.line_ids.id)
        self.assertEqual(cut.current_revision_id.line_ids.description, "Pollo")
        self._resolve("cancel")
        self.assertFalse(cut.current_revision_id.line_ids)
        self.assertEqual(self.reservation.state, "cancelled")
        self.assertEqual(len(cut.revision_ids), 4)
        with self.assertRaises(AccessError):
            first.line_ids.write({"description": "Borrar el pasado"})
        with self.assertRaises(AccessError):
            first.unlink()

    def test_rejection_keeps_operational_choice_and_projects_only_response(self):
        cut = self._take()
        first = cut.current_revision_id
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        self.reservation.sudo().message_post(body="NOTA INTERNA 987654.32")
        self._resolve("reject", employee_message="La preparación ya comenzó. Conservamos pollo.")
        payload = self.reservation._employee_values()
        self.assertEqual(payload["current"], "Pollo")
        self.assertFalse(payload["needs_attention"])
        self.assertEqual(cut.current_revision_id, first)
        self.assertEqual(payload["messages"][-1]["text"], "La preparación ya comenzó. Conservamos pollo.")
        self.assertNotIn("987654", str(payload))
        self.assertNotIn("ABC solicita", str(payload))

    def test_employee_can_request_correction_even_after_cancellation(self):
        self._take()
        self._resolve("cancel")
        self.reservation._request_correction("Me equivoqué, necesito conservar la vianda.")
        self.assertTrue(self.reservation.pending)
        self.assertEqual(self.reservation.state, "cancelled")
        self._resolve("replace", product_id=self.pork.id)
        self.assertEqual(self.reservation.state, "active")
        self.assertEqual(self.reservation.current_description, "Cerdo")
        self.assertTrue(self.reservation.pending)  # Corregir el plato no cierra la solicitud escrita.
        self._resolve("close_request")
        self.assertFalse(self.reservation.pending)
        other, _ = self._create_employee("abc-other")
        with self.assertRaises(AccessError):
            self.reservation.with_user(other)._request_correction("No es mía")

    def test_saving_unchanged_days_does_not_create_false_late_event(self):
        self._take()
        original_event = self.reservation.last_employee_change_at
        self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id)])
        self.assertFalse(self.reservation.pending)
        self.assertEqual(self.reservation.last_employee_change_at, original_event)
        self.assertEqual(len(self.reservation.sudo().event_ids), 1)

    def test_text_request_survives_week_resave_and_actual_choice_change(self):
        self.reservation._request_correction("Necesito que La Fija revise esta vianda.")
        last = self.reservation.last_employee_change_at
        events = self.reservation.sudo().event_ids
        self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id)])
        self.assertTrue(self.reservation.pending)
        self.assertEqual(self.reservation.last_employee_change_at, last)
        self.assertEqual(self.reservation.sudo().event_ids, events)
        self.service._submit_selections(self.website, [(self.menu.id, self.pork.id), (self.menus[1].id, self.chicken.id)])
        self.assertEqual(self.reservation.current_description, "Cerdo")
        self.assertTrue(self.reservation.attention_pending)
        self.assertTrue(self.reservation.pending)
        self._resolve("note", employee_message="Lo estamos revisando.")
        self.assertTrue(self.reservation.pending)
        self.assertEqual(self.reservation.sudo().event_ids[-1].kind, "response")
        self._resolve("close_request", employee_message="Ya atendimos la solicitud.")
        self.assertFalse(self.reservation.pending)
        self.assertEqual(self.reservation.current_description, "Cerdo")

    def test_closing_text_request_does_not_accept_or_erase_pending_option(self):
        self._take()
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        self.reservation._request_correction("Además, revisen mi solicitud escrita.")
        self._resolve("close_request")
        self.assertTrue(self.reservation.pending)
        self.assertFalse(self.reservation.attention_pending)
        self.assertEqual(self.reservation.pending_description, "Pescado")
        self.assertEqual(self.reservation.current_description, "Pollo")
        self._resolve("accept")
        self.assertFalse(self.reservation.pending)

    def test_accepting_pending_option_does_not_close_text_request(self):
        self._take()
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        self.reservation._request_correction("Una solicitud que necesita respuesta.")
        self._resolve("accept")
        self.assertEqual(self.reservation.current_description, "Pescado")
        self.assertFalse(self.reservation.sudo().pending_product_id)
        self.assertTrue(self.reservation.pending)

    def test_employee_times_and_today_filter_follow_admin_timezone(self):
        with freeze_time("2026-09-14 12:30:00"):
            self.reservation._request_correction("Consulta a las nueve y media.")
            payload = self.reservation.with_context(tz="UTC")._employee_values()
            self.assertEqual(payload['messages'][-1]['date'], '14/09/2026 09:30')
            self.assertEqual(payload['messages'][-1]['author'], 'Vos')
            self.assertEqual(payload['date_label'], 'Lunes 14/09')
            self.assertFalse(self.reservation.after_reference_time)
            self.assertEqual(self.reservation.sudo().change_local, '14/09/2026 09:30')
            self.assertIn(self.reservation.sudo(), self.env['lafija.reservation'].with_user(self.operator).search([('is_today', '=', True)]))

    def test_only_operator_can_take_and_resolve_and_attribution_is_audited(self):
        with self.assertRaises(AccessError):
            self.menu.with_user(self.employee).action_take_list()
        with self.assertRaises(AccessError):
            self.env["lafija.reservation.correction"].with_user(self.employee).create({"reservation_id": self.reservation.id})
        new_company = self.env["res.partner"].create({"name": "Empresa corregida", "is_company": True})
        cut = self._take()
        first = cut.current_revision_id
        self._resolve("reassign", customer_company_id=new_company.id)
        self.assertEqual(first.line_ids.customer_company_id, self.customer)
        self.assertEqual(cut.current_revision_id.line_ids.customer_company_id, new_company)
        self.assertIn("ABC de prueba", self.reservation.sudo().event_ids[-1].result)
        with self.assertRaises(ValidationError):
            self.menu.with_user(self.operator).write({"date": "2026-09-21"})
