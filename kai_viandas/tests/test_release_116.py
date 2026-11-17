"""OF automática por plato y día; el chef confirma en Manufactura · 19.0.1.17.8."""
from lxml import etree
from odoo import Command
from odoo.tests import tagged

from .test_release_115 import TestRelease115


@tagged("post_install", "-at_install")
class TestRelease116(TestRelease115):
    def _submit_other(self, employee, plate):
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menu.id, plate.id)])
        return self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", employee.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)

    def test_vigente_without_taken_list_creates_draft_orders_and_groups_by_dish(self):
        salad = self._goods_plate("Ensalada vegetariana 116")
        merluza = self._goods_plate("Filet merluza 116")
        self.menu.with_user(self.operator).write({
            "product_ids": [Command.link(salad.id), Command.link(merluza.id)],
        })
        self._resolve("replace", product_id=salad.id)
        first = self._reservation()
        employee_a, company_a = self._other_company_employee("lf116-ensalada")
        second = self._submit_other(employee_a, salad)
        employee_b, company_b = self._other_company_employee("lf116-merluza")
        third = self._submit_other(employee_b, merluza)
        self.assertFalse(self.menu.cut_ids, "este caso debe partir sin lista tomada")
        self.assertTrue(second.exists() and second.state == "active")
        self.assertEqual(second.sudo().current_product_id, salad)
        self.assertEqual(third.sudo().current_product_id, merluza)
        self.assertFalse(first.sudo().lf_daily_order_id)

        first.invalidate_recordset()
        second.invalidate_recordset()
        third.invalidate_recordset()
        salad_mo = (first | second).sudo().fulfillment_production_ids.filtered(lambda mo: mo.state != "cancel")
        merluza_mo = third.sudo().fulfillment_production_ids.filtered(lambda mo: mo.state != "cancel")
        self.assertEqual(len(salad_mo), 1)
        self.assertEqual(salad_mo.state, "draft")
        self.assertEqual(salad_mo.product_qty, 2)
        self.assertEqual(salad_mo.product_id, salad)
        self.assertEqual(salad_mo.origin, f"{first.date} · {salad.display_name}")
        self.assertEqual(len(merluza_mo), 1)
        self.assertEqual(merluza_mo.state, "draft")
        self.assertEqual(merluza_mo.product_qty, 1)
        self.assertEqual(merluza_mo.product_id, merluza)
        self.assertNotEqual(salad_mo, merluza_mo)
        self.assertFalse(first._lf_daily_orders())
        self.assertFalse(second.sudo()._lf_daily_orders())
        self.assertFalse(third.sudo()._lf_daily_orders())

        self._confirm_draft_mos(first | second | third)
        first.invalidate_recordset()
        second.invalidate_recordset()
        third.invalidate_recordset()
        self.assertEqual(salad_mo.state, "confirmed")
        self.assertEqual(merluza_mo.state, "confirmed")
        self.assertEqual(first.fulfillment_state, "in_progress")
        self.assertEqual(second.sudo().fulfillment_state, "in_progress")
        self.assertEqual(third.sudo().fulfillment_state, "in_progress")
        self.assertFalse(salad_mo.lf_sale_order_id)
        self.assertFalse(merluza_mo.lf_sale_order_id)

    def test_confirming_shared_draft_does_not_split(self):
        plate, first, second, _other = self._shared_setup("Guiso completo 116", "lf116-completo")
        draft = first.fulfillment_production_ids
        self.assertEqual(draft.state, "draft")
        self.assertEqual(draft.product_qty, 2)
        self._confirm_draft_mos(first | second)
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertEqual(draft.state, "confirmed")
        self.assertEqual(draft.product_qty, 2)
        self.assertEqual(first.fulfillment_production_ids, draft)
        self.assertEqual(second.fulfillment_production_ids, draft)
        self.assertEqual(first.fulfillment_state, "in_progress")
        self.assertEqual(second.fulfillment_state, "in_progress")

    def test_action_elaborate_accumulates_without_confirming(self):
        plate, first, second, _other = self._shared_setup("Milanesa parcial 116", "lf116-parcial")
        draft = first.fulfillment_production_ids
        self.assertEqual(draft.state, "draft")
        self.assertEqual(draft.product_qty, 2)
        first.action_elaborate()
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertEqual(draft.state, "draft")
        self.assertEqual(draft.product_qty, 2)
        self.assertEqual(first.fulfillment_state, "to_prepare")
        self.assertEqual(second.fulfillment_state, "to_prepare")
        self.assertEqual(set(draft.lf_reservation_ids.ids), {first.id, second.id})

    def test_hoy_list_does_not_expose_elaborate(self):
        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [(self.env.ref("kai_viandas.reservation_list").id, "list")])
        arch = etree.fromstring(views["views"]["list"]["arch"])
        self.assertFalse(arch.xpath("//button[@name='action_elaborate']"))
        self.assertTrue(arch.xpath("//field[@name='fulfillment_production_ids'][@widget='many2many_tags']"))
        ver = arch.xpath("//button[@name='action_open_production']")
        self.assertTrue(ver)
        self.assertEqual(ver[0].get("string"), "Ver orden")
        form = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [(self.env.ref("kai_viandas.reservation_form").id, "form")])
        form_arch = etree.fromstring(form["views"]["form"]["arch"])
        self.assertFalse(form_arch.xpath("//header//button[@name='action_elaborate']"))
        form_ver = form_arch.xpath("//header//button[@name='action_open_production']")
        self.assertTrue(form_ver)
        self.assertEqual(form_ver[0].get("string"), "Ver orden")

    def test_action_elaborate_on_cancelled_does_not_create_mo(self):
        plate = self._goods_plate("Cancelada 116")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        reservation = self._reservation()
        reservation.invalidate_recordset()
        before = reservation.sudo().fulfillment_production_ids
        self.env["lafija.reservation.correction"].with_user(self.operator).create({
            "reservation_id": reservation.id, "operation": "cancel", "reason": "Cancelar para prueba 116",
        }).action_apply()
        reservation.invalidate_recordset()
        self.assertEqual(reservation.state, "cancelled")
        action = reservation.with_user(self.operator).action_elaborate()
        reservation.invalidate_recordset()
        self.assertFalse(reservation.sudo().fulfillment_production_ids)
        self.assertTrue(action)
        self.assertNotIn(reservation, before.exists() and before.lf_reservation_ids)
