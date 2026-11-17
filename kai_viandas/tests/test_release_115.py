"""Una sola OF por plato y día, todas las empresas juntas · 19.0.1.15.0."""
from lxml import etree
from odoo import Command
from odoo.tests import tagged

from ..models.reservation import operation_context
from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease115(TestRelease114):
    def _other_company_employee(self, login):
        other = self.env["res.partner"].create({"name": "Otra empresa 115", "is_company": True})
        wizard = self.env["lafija.employee.access"].with_user(self.operator).create({
            "operation": "create", "name": "Ana de otra empresa", "login": login,
            "customer_company_id": other.id, "website_id": self.website.id,
            "new_password": "employee-password-123", "reason": "Alta otra empresa 115",
        })
        result = wizard.action_apply()
        partner = self.env["res.partner"].browse(result["res_id"])
        return partner.user_ids, other

    def _add_to_list(self, employee, plate):
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menu.id, plate.id)])
        reservation = self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", employee.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        cut = self.menu.cut_ids[:1]
        if reservation not in cut.current_revision_id.line_ids.reservation_id or not reservation.current_product_id:
            self.env["lafija.reservation.correction"].with_user(self.operator).create({
                "reservation_id": reservation.id, "operation": "accept", "reason": "Sumar vianda 115 a la lista",
            }).action_apply()
        return reservation.with_user(self.operator)

    def _shared_setup(self, plate_name, login):
        plate = self._goods_plate(plate_name)
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        first = self._reservation()
        employee, company = self._other_company_employee(login)
        second = self._add_to_list(employee, plate)
        first.invalidate_recordset()
        second.invalidate_recordset()
        return plate, first, second, company

    def test_two_companies_share_one_draft_mo_for_the_dish_and_day(self):
        plate, first, second, other = self._shared_setup("Milanesa compartida 115", "lf115-ana")
        mo = first.fulfillment_production_ids
        self.assertEqual(mo, second.fulfillment_production_ids)
        self.assertEqual(len(mo), 1)
        self.assertEqual(mo.state, "draft")
        self.assertEqual(mo.product_qty, 2)
        self.assertEqual(mo.origin, f"{first.date} · {plate.display_name}")
        first_order = first._lf_daily_orders()
        second_order = second._lf_daily_orders()
        self.assertEqual(len(first_order), 1)
        self.assertEqual(len(second_order), 1)
        self.assertNotEqual(first_order, second_order)
        self.assertEqual(first_order.partner_id, first.customer_company_id)
        self.assertEqual(second_order.partner_id, other)
        self.assertEqual(mo.lf_sale_order_ids, first_order | second_order)
        self.assertEqual(set(mo.lf_reservation_ids.ids), {first.id, second.id})

    def test_elaborate_one_vianda_splits_shared_draft_and_leaves_the_other_to_prepare(self):
        plate, first, second, _other = self._shared_setup("Estofado compartido 115", "lf115-ana2")
        draft = first.fulfillment_production_ids
        self.assertEqual(draft, second.fulfillment_production_ids)
        self.assertEqual(draft.product_qty, 2)
        first.action_elaborate()
        first.invalidate_recordset()
        second.invalidate_recordset()
        confirmed = first.fulfillment_production_ids.filtered(lambda mo: mo.state == "confirmed")
        leftover = second.fulfillment_production_ids.filtered(lambda mo: mo.state == "draft")
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed.product_qty, 1)
        self.assertEqual(first.fulfillment_state, "in_progress")
        self.assertEqual(second.fulfillment_state, "to_prepare")
        self.assertEqual(leftover.product_qty, 1)
        self.assertEqual(leftover.product_id, plate)
        self.assertNotEqual(leftover, confirmed)
        self.assertNotIn(second, confirmed.lf_reservation_ids)
        for move in confirmed.move_raw_ids:
            if "quantity" in move._fields:
                move.quantity = move.product_uom_qty
            else:
                move.quantity_done = move.product_uom_qty
        confirmed.sudo().button_mark_done()
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertEqual(first.fulfillment_state, "prepared")
        self.assertEqual(second.fulfillment_state, "to_prepare")
        self.assertFalse(first.delivered_at)

    def test_add_while_confirmed_creates_delta_draft_without_changing_confirmed_qty(self):
        plate = self._goods_plate("Lasagna tardía 115")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        first = self._reservation()
        first.action_elaborate()
        confirmed = first.fulfillment_production_ids.filtered(lambda mo: mo.state == "confirmed")
        self.assertEqual(confirmed.product_qty, 1)
        employee, _company = self._other_company_employee("lf115-tardio")
        second = self._add_to_list(employee, plate)
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertEqual(confirmed.product_qty, 1)
        self.assertEqual(confirmed.state, "confirmed")
        self.assertEqual(first.fulfillment_state, "in_progress")
        self.assertEqual(second.fulfillment_state, "to_prepare")
        delta = second.fulfillment_production_ids.filtered(lambda mo: mo.state == "draft")
        self.assertEqual(len(delta), 1)
        self.assertEqual(delta.product_qty, 1)
        self.assertEqual(delta.product_id, plate)
        self.assertNotEqual(delta, confirmed)
        self.assertNotIn(second, confirmed.lf_reservation_ids)
        self.assertIn(first, confirmed.lf_reservation_ids)

    def test_merge_per_company_drafts_and_leaves_done_untouched(self):
        plate = self._goods_plate("Fusión borradores 115")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        first = self._reservation()
        shared = first.fulfillment_production_ids
        employee, _company = self._other_company_employee("lf115-fusion")
        second = self._add_to_list(employee, plate)
        # Simular el esquema anterior: dos OF en borrador, una por empresa.
        first.with_context(**operation_context()).write({"fulfillment_production_ids": [(3, shared.id)]})
        second.with_context(**operation_context()).write({"fulfillment_production_ids": [(3, shared.id)]})
        shared.with_context(_lf_syncing_drafts=True).action_cancel()
        group_first, _skipped = first._lf_wanted_production_groups(first)
        group_second, _ = second._lf_wanted_production_groups(second)
        mo_first = first._lf_make_production(group_first[0], confirm=False)
        mo_second = second._lf_make_production(group_second[0], confirm=False)
        self.assertEqual(mo_first.product_qty, 1)
        self.assertEqual(mo_second.product_qty, 1)
        historical = self.env["mrp.production"].sudo().create({
            "product_id": plate.id,
            "product_qty": 1,
            "product_uom_id": plate.uom_id.id,
            "bom_id": group_first[0]["bom"].id,
            "origin": "S00643 · V-000075",
            "company_id": self.env.company.id,
        })
        # El merge solo une OF en borrador vinculadas a viandas; esta (sin viandas, origen histórico) no se reescribe.
        self.env["lafija.reservation"]._lf_merge_draft_productions_by_dish_day()
        first.invalidate_recordset()
        second.invalidate_recordset()
        merged = first.fulfillment_production_ids.filtered(lambda mo: mo.state == "draft")
        self.assertEqual(merged, second.fulfillment_production_ids.filtered(lambda mo: mo.state == "draft"))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.product_qty, 2)
        self.assertEqual(merged.origin, f"{first.date} · {plate.display_name}")
        self.assertEqual(historical.origin, "S00643 · V-000075")
        self.assertFalse(historical.lf_reservation_ids)

    def test_viandas_tab_lists_company_and_sale_orders(self):
        views = self.env["mrp.production"].with_user(self.operator).get_views(
            [(self.env.ref("mrp.mrp_production_form_view").id, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        self.assertTrue(arch.xpath("//page[@name='lf_viandas']"))
        self.assertTrue(arch.xpath("//field[@name='lf_sale_order_ids']"))
        self.assertTrue(arch.xpath("//field[@name='lf_reservation_ids']//field[@name='name']"))
        self.assertTrue(arch.xpath("//field[@name='lf_reservation_ids']//field[@name='customer_company_id']"))
        self.assertTrue(arch.xpath("//field[@name='lf_reservation_ids']//field[@name='lf_daily_order_id']"))
        self.assertTrue(arch.xpath("//button[@name='action_lf_open_sale_orders']"))
        self.assertTrue(arch.xpath("//button[@name='action_lf_open_reservations']"))
