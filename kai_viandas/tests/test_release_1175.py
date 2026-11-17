"""Atender solo si pending, pedido diario progresivo y Monto · 19.0.1.17.5."""
from lxml import etree
from odoo import Command
from odoo.tests import tagged

from ..models.reservation import operation_context
from .test_preparation import PreparationCommon
from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1175(SidesCommon, PreparationCommon):
    def _lines(self, order):
        return order.order_line.filtered(lambda line: not line.display_type and line.product_uom_qty)

    def test_atender_row_is_hidden_unless_pending_and_form_keeps_correct(self):
        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"],
             [self.env.ref("kai_viandas.reservation_form").id, "form"]]
        )
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        buttons = list_arch.xpath("//button[@name='action_correct']")
        self.assertTrue(buttons)
        self.assertEqual(buttons[0].get("invisible"), "not pending")
        self.assertEqual(buttons[0].get("string"), "Editar")

        form_arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        form_buttons = form_arch.xpath("//header//button[@name='action_correct']")
        self.assertTrue(form_buttons)
        self.assertEqual(form_buttons[0].get("string"), "Editar")
        self.assertFalse(form_buttons[0].get("invisible"))

        self.assertFalse(self.reservation.pending)
        self.reservation.sudo().with_context(**operation_context()).write({
            "pending_product_id": self.pork.id,
            "pending_description": "Cerdo",
        })
        self.assertTrue(self.reservation.pending)

    def test_pedidos_list_shows_monto_and_ventas_menu(self):
        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"]]
        )
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        monto = list_arch.xpath("//field[@name='lf_amount']")
        self.assertTrue(monto)
        self.assertEqual(monto[0].get("sum"), "Monto")
        self.assertTrue(list_arch.xpath("//field[@name='lf_daily_order_id']"))

        root = self.env.ref("kai_viandas.menu_root")
        sections = self.env["ir.ui.menu"].search([("parent_id", "=", root.id)], order="sequence,id")
        self.assertEqual(sections.mapped("name"), ["Pedidos", "Menús", "Empleados", "Ayuda", "Horarios de pedido"])
        group = self.env.ref("kai_viandas.menu_orders_group")
        self.assertEqual(group.parent_id, root)
        self.assertEqual(self.env.ref("kai_viandas.menu_orders").parent_id, group)
        sales = self.env.ref("kai_viandas.menu_daily_sales")
        self.assertEqual(sales.parent_id, group)
        self.assertEqual(sales.name, "Ventas")
        action = self.env.ref("kai_viandas.daily_sale_order_action")
        self.assertEqual(sales.action, action)
        self.assertEqual(action.res_model, "sale.order")
        self.assertIn("lf_preparation_date", action.domain)

        help_arch = self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Pedidos → Ventas", help_arch)
        self.assertIn("columna <strong>Monto</strong>", help_arch)
        self.assertIn("Editar</strong> en la fila solo aparece si requiere atención", help_arch)
        self.assertNotIn("Atender</strong> en la fila o", help_arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.17"), module.latest_version)
