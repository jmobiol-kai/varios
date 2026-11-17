"""Referencias pedido–vianda–OF, menú del día y OF hecha no entrega · 19.0.1.14.2."""
from lxml import etree
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import save_test_file

from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease142(TestRelease114):
    def _arch(self, model, xmlid, view_type="form", user=None, sudo=False):
        record = self.env[model].with_user(user or self.operator)
        if sudo:
            record = record.sudo()
        views = record.get_views([(self.env.ref(xmlid).id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def test_take_list_origin_is_date_and_dish_and_links_sale_order(self):
        plate = self._goods_plate("Milanesa de prueba 142")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        mo = reservation.fulfillment_production_ids
        daily = reservation._lf_daily_orders()
        self.assertTrue(daily)
        self.assertEqual(mo.origin, f"{reservation.date} · {plate.display_name}")
        self.assertIn(daily, mo.lf_sale_order_ids)
        self.assertIn(reservation, mo.lf_reservation_ids)
        self.assertEqual(reservation.lf_daily_order_id, daily)
        line = daily.order_line.filtered(lambda item: item.product_id == plate)[:1]
        self.assertIn(reservation.name, line.lf_reservation_ref or "")

    def test_origin_is_date_and_dish(self):
        Reservation = self.env["lafija.reservation"]
        plate = self.env["product.product"].new({"name": "Pastel De Papa"})
        record = Reservation.new({"date": "2026-11-20"})
        self.assertEqual(
            Reservation._lf_format_production_origin(record, product=plate),
            "2026-11-20 · Pastel De Papa",
        )

    def test_mo_done_marks_prepared_not_delivered_and_leaves_picking_open(self):
        plate = self._goods_plate("Estofado de prueba 142")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        self._take()
        reservation = self._reservation()
        reservation.action_elaborate()
        mo = reservation.fulfillment_production_ids.filtered(lambda production: production.state == "confirmed")
        for move in mo.move_raw_ids:
            if "quantity" in move._fields:
                move.quantity = move.product_uom_qty
            else:
                move.quantity_done = move.product_uom_qty
        mo.sudo().button_mark_done()
        reservation.invalidate_recordset()
        self.assertEqual(reservation.fulfillment_state, "prepared")
        self.assertNotEqual(reservation.fulfillment_state, "delivered")
        self.assertFalse(reservation.delivered_at)
        self.assertFalse(reservation.delivered_by)
        order = reservation._lf_daily_orders()
        outgoing = order.picking_ids.filtered(lambda picking: picking.picking_type_code == "outgoing" and picking.state != "cancel")
        self.assertTrue(all(picking.state != "done" for picking in outgoing) or not outgoing)
        self.assertTrue(all(
            (line.qty_delivered or 0) == 0
            for line in order.order_line.filtered(lambda line: not line.display_type)
        ))

    def test_views_expose_references_and_menu_day_shifts_when_list_is_taken(self):
        cut_arch = self._arch("lafija.preparation.cut", "kai_viandas.cut_form")
        self.assertTrue(cut_arch.xpath("//page[@name='lf_fulfillment']"))
        grid_fields = [
            field.get("name")
            for field in cut_arch.xpath("//field[@name='current_line_ids']/list/field")
        ]
        self.assertEqual(grid_fields[0], "reservation_name")
        self.assertIn("lf_daily_order_id", grid_fields)
        self.assertIn("fulfillment_production_ids", grid_fields)
        self.assertIn("fulfillment_state", grid_fields)

        list_arch = self._arch("lafija.reservation", "kai_viandas.reservation_list", view_type="list")
        list_fields = [field.get("name") for field in list_arch.xpath("//list/field")]
        self.assertEqual(list_fields[0], "name")
        self.assertIn("fulfillment_state", list_fields)
        self.assertIn("lf_daily_order_id", list_fields)

        menu_arch = self._arch("lafija.menu.day", "kai_viandas.menu_day_form")
        plates = menu_arch.xpath("//group[@name='lf_offer_plates']")
        self.assertTrue(plates)
        self.assertEqual(plates[0].get("invisible"), "list_taken")
        banner = menu_arch.xpath("//div[@name='lf_taken_banner']")
        self.assertTrue(banner)
        self.assertEqual(banner[0].get("invisible"), "not list_taken")
        self.assertTrue(menu_arch.xpath("//button[@name='action_open_fulfillment']"))
        offer_page = menu_arch.xpath("//page[@name='lf_offer']")
        self.assertTrue(offer_page)
        self.assertEqual(offer_page[0].get("invisible"), "not list_taken")
        res_fields = [
            field.get("name")
            for field in menu_arch.xpath("//field[@name='reservation_ids']/list/field")
        ]
        self.assertEqual(res_fields[0], "name")
        self.assertIn("fulfillment_state", res_fields)
        self.assertNotIn("state", res_fields)

        cut = self._take()
        action = self.menu.with_user(self.operator).action_open_fulfillment()
        self.assertEqual(action["res_model"], "lafija.preparation.cut")
        self.assertEqual(action["res_id"], cut.id)
        self.assertEqual(action.get("view_id"), self.env.ref("kai_viandas.cut_form").id)

        mo_arch = self._arch("mrp.production", "mrp.mrp_production_form_view", sudo=True)
        self.assertTrue(mo_arch.xpath("//page[@name='lf_viandas']"))
        self.assertTrue(mo_arch.xpath("//field[@name='lf_sale_order_ids']"))
        self.assertTrue(mo_arch.xpath("//field[@name='lf_reservation_ids']"))
        self.assertTrue(mo_arch.xpath("//field[@name='lf_reservation_ids']//field[@name='customer_company_id']"))
        self.assertTrue(mo_arch.xpath("//field[@name='lf_reservation_ids']//field[@name='lf_daily_order_id']"))
        self.assertTrue(mo_arch.xpath("//button[@name='action_lf_open_sale_orders']"))
        self.assertTrue(mo_arch.xpath("//button[@name='action_lf_open_reservations']"))

        sale_arch = self._arch("sale.order", "sale.view_order_form")
        self.assertTrue(sale_arch.xpath("//button[@name='action_lf_open_productions']"))
        self.assertTrue(sale_arch.xpath("//button[@name='action_lf_open_reservations']"))
        self.assertTrue(sale_arch.xpath("//field[@name='order_line']//field[@name='lf_reservation_ref']"))
        save_test_file(self._testMethodName, etree.tostring(menu_arch, pretty_print=True), "lf142_menu_day_", extension="xml")

    def test_label_and_day_sheet_include_vianda_number(self):
        plate = self._goods_plate("Ñoquis de prueba 142")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(plate.id)]})
        self._resolve("replace", product_id=plate.id)
        cut = self._take()
        reservation = self._reservation()
        action = cut.current_revision_id.with_user(self.operator).action_print_labels()
        batch = self.env["lafija.label.print"].browse(action["res_id"])
        from lxml import html
        document, _ = self.env["ir.actions.report"].with_user(self.operator)._render_qweb_html(
            "kai_viandas.report_labels", batch.ids)
        tree = html.fromstring(document)
        self.assertIn(reservation.name, " ".join(tree.text_content().split()))
        values = self.env["report.kai_viandas.day_sheet"].with_user(self.operator)._get_report_values(cut.current_revision_id.ids)
        refs = [line["reference"] for company in values["sheets"][0]["companies"] for line in company["lines"]]
        self.assertIn(reservation.name, refs)
