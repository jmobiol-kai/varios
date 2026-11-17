"""Elaboración, fabricación, pedido diario y entrega · 19.0.1.14.0."""
from freezegun import freeze_time
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import save_test_file
from lxml import etree

from .test_preparation import PreparationCommon
from ..models.reservation import operation_context
from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease114(SidesCommon, PreparationCommon):
    def _goods_plate(self, name="Pastel de prueba 114"):
        unit = self.env.ref("uom.product_uom_unit")
        plate = self.env["product.product"].create({
            "name": name, "description_sale": name, "list_price": 1500, "type": "consu",
            "is_storable": True, "sale_ok": True, "categ_id": self.plate_categ.id,
            "uom_id": unit.id,
        })
        component = self.env["product.product"].create({
            "name": f"{name} componente", "type": "consu", "is_storable": True,
            "uom_id": unit.id,
        })
        self.env["mrp.bom"].create({
            "product_tmpl_id": plate.product_tmpl_id.id, "product_id": plate.id,
            "product_qty": 1, "type": "normal",
            "bom_line_ids": [Command.create({"product_id": component.id, "product_qty": 1})],
        })
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", self.env.company.id)], limit=1)
        self.env["stock.quant"]._update_available_quantity(component, warehouse.lot_stock_id, 20)
        if "qty_available" in plate._fields:
            self.env["stock.quant"]._update_available_quantity(plate, warehouse.lot_stock_id, 20)
        return plate

    def _take_sides(self):
        with self.env.cr.savepoint():
            pass
        self.service._submit_selections(
            self.website, [(self.menu.id, self.chicken.id, self.flan.id, self.water.id)])
        return self._take()

    def _lines(self, order):
        return order.order_line.filtered(lambda line: not line.display_type and line.product_uom_qty)

    def _reservation(self):
        return self.reservation.with_user(self.operator)

    def test_take_list_does_not_create_a_daily_order(self):
        cut = self._take_sides()
        self.assertFalse(self.reservation._lf_daily_orders())
        self.assertFalse(self.reservation.sudo().lf_quotation_id)
        self.assertEqual(self._take(), cut)
        self.assertFalse(self.reservation._lf_daily_orders())

    def test_revision_updates_undelivered_line_and_keeps_marks_when_choice_is_unchanged(self):
        cut = self._take()
        reservation = self._reservation()
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        self.assertEqual(cut.to_prepare_count, 1)
        reservation.action_elaborate()
        # Sin receta no avanza; el pollo de prueba no tiene LdM.
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        # Una corrección que no cambia el triple no debe perder marcas posteriores.
        reservation.with_context(lf_skip=True)
        first = reservation.fulfillment_state
        self._resolve("replace", product_id=self.chicken.id, dessert_id=False, drink_id=False)
        self.assertEqual(cut.current_revision_id.number, 2)
        self.assertEqual(reservation.fulfillment_state, first)
        self._resolve("replace", product_id=self.pork.id)
        self.assertFalse(reservation._lf_daily_orders())
        self.assertEqual(reservation.fulfillment_state, "to_prepare")

    def test_elaborate_without_bom_warns_and_does_not_create_empty_mo(self):
        self._take()
        before = self.env["mrp.production"].search_count([])
        action = self._reservation().action_elaborate()
        self.assertEqual(self._reservation().fulfillment_state, "to_prepare")
        self.assertEqual(self.env["mrp.production"].search_count([]), before)
        self.assertEqual(action["tag"], "lf_operation_feedback")
        self.assertIn("lista de materiales", action["params"]["message"])

    def test_elaborate_confirms_mo_and_done_marks_prepared_cancel_returns_to_prepare(self):
        plate = self._goods_plate()
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        cut = self._take()
        reservation = self._reservation()
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        drafts = reservation.fulfillment_production_ids
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts.state, "draft")
        self._confirm_draft_mos(reservation)
        self.assertEqual(reservation.fulfillment_state, "in_progress")
        self.assertEqual(cut.in_progress_count, 1)
        productions = reservation.fulfillment_production_ids
        self.assertEqual(productions, drafts)
        self.assertEqual(len(productions), 1)
        self.assertEqual(productions.product_id, plate)
        self.assertEqual(productions.product_qty, 1)
        self.assertEqual(productions.state, "confirmed")
        self.assertFalse(reservation._lf_daily_orders())
        self.assertEqual(productions.origin, f"{reservation.date} · {plate.display_name}")
        self.assertFalse(productions.lf_sale_order_id)
        self.assertTrue(reservation.fulfillment_started_at)
        self.assertEqual(reservation.fulfillment_started_by, self.operator)
        self.assertFalse(reservation.prepared_at)
        self.assertIn("fulfillment", reservation.event_ids.mapped("kind"))
        for move in productions.move_raw_ids:
            if "quantity" in move._fields:
                move.quantity = move.product_uom_qty
            else:
                move.quantity_done = move.product_uom_qty
        productions.sudo().button_mark_done()
        reservation.invalidate_recordset()
        self.assertEqual(productions.state, "done")
        self.assertEqual(reservation.fulfillment_state, "prepared")
        self.assertTrue(reservation.prepared_at)
        self.assertEqual(cut.prepared_count, 1)
        # Si cambia la vianda, vuelve a por elaborar y se desvinculan las OF anteriores.
        other = self._goods_plate("Milanesa de prueba 114")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(other.id)]})
        self._resolve("replace", product_id=other.id)
        reservation.invalidate_recordset()
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        # Cancelar la OF de una vianda en elaboración la devuelve a por elaborar.
        employee, _ = self._create_employee("lf114-cancel")
        with self.env.cr.savepoint():
            pass
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menu.id, other.id)])
        pending = self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", employee.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        if not pending.current_product_id:
            self.env["lafija.reservation.correction"].with_user(self.operator).create({
                "reservation_id": pending.id, "operation": "accept", "reason": "Incluir vianda 114 para cancelar OF",
            }).action_apply()
        pending = pending.with_user(self.operator)
        self.assertEqual(pending.fulfillment_state, "to_prepare")
        self._confirm_draft_mos(pending)
        self.assertEqual(pending.fulfillment_state, "in_progress")
        mo = pending.fulfillment_production_ids.filtered(lambda production: production.state == "confirmed")
        mo.sudo().action_cancel()
        pending.invalidate_recordset()
        self.assertEqual(mo.state, "cancel")
        self.assertEqual(pending.fulfillment_state, "to_prepare")
        self.assertEqual(reservation.fulfillment_state, "to_prepare")

    def test_deliver_only_from_prepared_validates_picking_when_present_and_can_undo_mark(self):
        plate = self._goods_plate("Bondiola de prueba 114")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        with self.assertRaises(ValidationError):
            reservation.action_mark_delivered()
        self._confirm_draft_mos(reservation)
        mo = reservation.fulfillment_production_ids
        for move in mo.move_raw_ids:
            if "quantity" in move._fields:
                move.quantity = move.product_uom_qty
            else:
                move.quantity_done = move.product_uom_qty
        mo.sudo().button_mark_done()
        self.assertEqual(reservation.fulfillment_state, "prepared")
        self.assertNotEqual(reservation.fulfillment_state, "delivered")
        self.assertFalse(reservation.delivered_at)
        self.assertFalse(reservation._lf_daily_orders())
        reservation.action_mark_delivered()
        self.assertEqual(reservation.fulfillment_state, "delivered")
        self.assertTrue(reservation.delivered_at)
        self.assertEqual(reservation.delivered_by, self.operator)
        reservation.action_unmark_delivered()
        self.assertEqual(reservation.fulfillment_state, "prepared")
        self.assertFalse(reservation.delivered_at)

    def test_period_quotation_reuses_daily_order_and_does_not_duplicate_invoicing(self):
        self._take_sides()
        self.assertFalse(self.reservation._lf_daily_orders())
        self.reservation.sudo().with_context(**operation_context()).write({"fulfillment_state": "prepared"})
        self.reservation.with_user(self.operator).action_add_to_quotation()
        daily = self.reservation._lf_daily_orders()
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily.state, "draft")
        before = self.env["sale.order"].search_count([])
        with freeze_time("2026-10-01 15:00:00"):
            batch = self.env["lafija.quotation.preparation"].with_user(self.operator).create({
                "customer_company_id": self.customer.id,
            })
        batch.action_refresh()
        self.assertEqual({row["id"] for row in batch.snapshot["eligible"]}, {self.reservation.id})
        self.assertFalse(batch.snapshot["included"])
        batch.action_prepare()
        self.assertEqual(self.env["sale.order"].search_count([]), before)
        self.assertEqual(batch.order_id, daily)
        self.assertEqual(batch.order_id.state, "draft")
        batch.action_refresh()
        self.assertEqual({row["id"] for row in batch.snapshot["included"]}, {self.reservation.id})
        self.assertFalse(batch.snapshot["eligible"])

    def test_portal_history_hides_fulfillment_events(self):
        plate = self._goods_plate("Evento portal 114")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        self._confirm_draft_mos(reservation)
        payload = reservation.with_user(self.employee)._employee_values()
        self.assertIn("fulfillment", reservation.event_ids.mapped("kind"))
        self.assertNotIn("En elaboración", str(payload.get("choices")))

    def test_cut_form_and_reservation_views_expose_fulfillment_controls(self):
        cut = self._take()
        views = cut.with_user(self.operator).get_views([(self.env.ref("kai_viandas.cut_form").id, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        self.assertTrue(arch.xpath("//field[@name='to_prepare_count']"))
        self.assertTrue(arch.xpath("//field[@name='current_line_ids']"))
        self.assertTrue(arch.xpath("//button[@name='action_open_production']"))
        self.assertTrue(arch.xpath("//button[@name='action_mark_delivered']"))
        search = self.env["lafija.reservation"].with_user(self.operator).get_views([(self.env.ref("kai_viandas.reservation_search").id, "search")])
        search_arch = etree.fromstring(search["views"]["search"]["arch"])
        self.assertTrue(search_arch.xpath("//filter[@name='to_deliver']"))
        self.assertTrue(search_arch.xpath("//filter[@name='delivered']"))
        action = self.env.ref("kai_viandas.delivery_action")
        self.assertEqual(action.name, "Entregas del día")
        save_test_file(self._testMethodName, etree.tostring(arch, pretty_print=True), "lf114_cut_form_", extension="xml")
