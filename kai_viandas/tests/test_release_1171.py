"""Botón Agregar pedido cliente y columnas de Pedidos · 19.0.1.17.1."""
from pathlib import Path

from lxml import etree
from odoo.modules.module import get_module_path
from odoo.tests import tagged

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1171(SidesCommon):
    def test_pedidos_header_button_and_column_order(self):
        arch = self.env.ref("kai_viandas.reservation_list").with_user(self.operator).arch
        self.assertNotIn("Ver pendientes de cualquier fecha", arch)
        self.assertNotIn("action_pending_all_dates", arch)
        self.assertIn("<header", arch)
        self.assertIn('js_class="lf_reservation_list"', arch)

        opened = self.env["lafija.reservation"].with_user(self.operator).action_create_client_orders()
        self.assertEqual(opened["id"], self.env.ref("kai_viandas.employee_order_action").id)
        self.assertEqual(opened["res_model"], "lafija.employee.order")

        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"]]
        )
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        names = list_arch.xpath("//list/field/@name")
        visible_prefix = [
            "employee_partner_id",
            "customer_company_id",
            "date",
            "name",
            "current_description",
            "current_dessert_description",
            "current_drink_description",
            "pending_description",
            "fulfillment_state",
            "lf_quotation_id",
            "lf_daily_order_id",
            "currency_id",
            "lf_amount",
            "fulfillment_production_ids",
            "attention_label",
            "timing_label",
        ]
        self.assertEqual(names[: len(visible_prefix)], visible_prefix)
        self.assertTrue(list_arch.xpath("//header"))
        self.assertFalse(list_arch.xpath("//button[@name='action_pending_all_dates']"))
        self.assertFalse(list_arch.xpath("//button[@name='action_elaborate']"))
        self.assertTrue(list_arch.xpath("//button[@name='action_open_production']"))

        module_path = Path(get_module_path("kai_viandas"))
        js = (module_path / "static" / "src" / "reservation_list.js").read_text()
        xml = (module_path / "static" / "src" / "reservation_list.xml").read_text()
        self.assertIn("kai_viandas.LfReservationListView", js)
        self.assertIn("onClickAddClientOrder", js)
        self.assertIn("control-panel-always-buttons", xml)
        self.assertIn("Agregar pedido cliente", xml)
        self.assertIn("btn-primary", xml)
        self.assertIn("o_lf_add_client_order_btn", xml)
        self.assertIn('LINK_LABEL = "Nuevo pedido"', js)

        help_arch = self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Agregar pedido cliente", help_arch)
        self.assertIn("Nuevo pedido", help_arch)
        self.assertNotIn("Ver pendientes de cualquier fecha", help_arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.17"), module.latest_version)
