"""Órdenes de fabricación en borrador al tomar la lista · 19.0.1.14.1."""
from odoo import Command
from odoo.tests import tagged

from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease141(TestRelease114):
    def test_take_list_creates_draft_mo_without_confirming(self):
        plate = self._goods_plate("Ñoquis de prueba 141")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        cut = self._take()
        reservation = self._reservation()
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        mo = reservation.fulfillment_production_ids
        self.assertEqual(len(mo), 1)
        self.assertEqual(mo.state, "draft")
        self.assertEqual(mo.product_id, plate)
        self.assertEqual(mo.product_qty, 1)
        daily = reservation._lf_daily_orders()
        self.assertEqual(mo.origin, f"{reservation.date} · {plate.display_name}")
        self.assertIn(daily, mo.lf_sale_order_ids)
        self.assertEqual(cut.current_line_ids.fulfillment_production_ids, mo)

    def test_elaborate_confirms_existing_draft_and_does_not_create_another(self):
        plate = self._goods_plate("Lasagna de prueba 141")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        draft = reservation.fulfillment_production_ids
        self.assertEqual(draft.state, "draft")
        before = self.env["mrp.production"].search_count([])
        reservation.action_elaborate()
        self.assertEqual(reservation.fulfillment_state, "in_progress")
        self.assertEqual(reservation.fulfillment_production_ids, draft)
        self.assertEqual(draft.state, "confirmed")
        self.assertEqual(self.env["mrp.production"].search_count([]), before)

    def test_revision_updates_draft_qty_or_cancels_unused_without_changing_state(self):
        plate = self._goods_plate("Estofado de prueba 141")
        other = self._goods_plate("Milanesa de prueba 141")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id), Command.link(other.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        first = self._reservation()
        draft = first.fulfillment_production_ids
        self.assertEqual(draft.state, "draft")
        employee, _ = self._create_employee("lf141-segundo")
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menu.id, plate.id)])
        second = self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", employee.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        cut = first.menu_id.cut_ids[:1]
        if second not in cut.current_revision_id.line_ids.reservation_id or not second.current_product_id:
            self.env["lafija.reservation.correction"].with_user(self.operator).create({
                "reservation_id": second.id, "operation": "accept", "reason": "Sumar vianda 141 a la lista",
            }).action_apply()
        second = second.with_user(self.operator)
        first.invalidate_recordset()
        self.assertEqual(first.fulfillment_state, "to_prepare")
        self.assertEqual(second.fulfillment_state, "to_prepare")
        shared = first.fulfillment_production_ids
        self.assertEqual(shared, second.fulfillment_production_ids)
        self.assertEqual(shared.state, "draft")
        self.assertEqual(shared.product_qty, 2)
        self._resolve("replace", product_id=other.id)
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertEqual(first.fulfillment_state, "to_prepare")
        self.assertEqual(second.fulfillment_state, "to_prepare")
        self.assertEqual(first.fulfillment_production_ids.product_id, other)
        self.assertEqual(first.fulfillment_production_ids.state, "draft")
        self.assertEqual(first.fulfillment_production_ids.product_qty, 1)
        self.assertEqual(second.fulfillment_production_ids, shared)
        self.assertEqual(shared.product_id, plate)
        self.assertEqual(shared.state, "draft")
        self.assertEqual(shared.product_qty, 1)

    def test_cancelling_a_draft_during_revision_does_not_mark_in_progress(self):
        plate = self._goods_plate("Cancelación borrador 141")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        mo = reservation.fulfillment_production_ids
        self.assertEqual(mo.state, "draft")
        mo.sudo().action_cancel()
        reservation.invalidate_recordset()
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        self.assertNotEqual(reservation.fulfillment_state, "in_progress")

    def test_cancel_confirmed_mo_returns_to_prepare_with_new_draft(self):
        plate = self._goods_plate("Vuelta a borrador 141")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        reservation.action_elaborate()
        confirmed = reservation.fulfillment_production_ids.filtered(lambda mo: mo.state == "confirmed")
        self.assertEqual(reservation.fulfillment_state, "in_progress")
        confirmed.sudo().action_cancel()
        reservation.invalidate_recordset()
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        drafts = reservation.fulfillment_production_ids.filtered(lambda mo: mo.state == "draft")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts.product_id, plate)
        self.assertNotEqual(drafts, confirmed)
