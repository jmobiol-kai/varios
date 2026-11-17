"""Menús de primer nivel y botón de pedidos en Hoy · 19.0.1.16.3."""
from odoo.tests import tagged

from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease1163(TestRelease114):
    def test_top_menu_order_and_removed_groups(self):
        root = self.env.ref("kai_viandas.menu_root")
        sections = self.env["ir.ui.menu"].search([("parent_id", "=", root.id)], order="sequence,id")
        self.assertEqual(sections.mapped("name"), ["Pedidos", "Menús", "Empleados", "Ayuda", "Horarios de pedido"])
        menus = self.env.ref("kai_viandas.menu_days")
        self.assertEqual(menus.parent_id, root)
        self.assertEqual(menus.name, "Menús")
        self.assertEqual(menus.action, self.env.ref("kai_viandas.menu_day_action"))
        self.assertEqual(menus.group_ids, self.env.ref("kai_viandas.group_operator"))
        missing = self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"),
            ("name", "in", [
                "menu_preparation_group", "menu_reservations_group",
                "menu_reservations", "menu_quotation", "menu_employee_order",
            ]),
        ])
        self.assertFalse(missing)
        # Acciones conservadas.
        self.assertEqual(self.env.ref("kai_viandas.menu_day_action").name, "Menús del día")
        self.assertEqual(self.env.ref("kai_viandas.reservation_action").res_model, "lafija.reservation")
        self.assertEqual(self.env.ref("kai_viandas.quotation_preparation_action").res_model, "lafija.quotation.preparation")
        self.assertEqual(self.env.ref("kai_viandas.employee_order_action").res_model, "lafija.employee.order")

    def test_hoy_header_button_opens_employee_order_wizard(self):
        opened = self.env["lafija.reservation"].with_user(self.operator).action_create_client_orders()
        action = self.env.ref("kai_viandas.employee_order_action")
        self.assertEqual(opened["id"], action.id)
        self.assertEqual(opened["res_model"], "lafija.employee.order")
        arch = self.env.ref("kai_viandas.reservation_list").with_user(self.operator).arch
        self.assertNotIn("Crear pedidos de clientes", arch)
        self.assertNotIn("Cargar pedidos", arch)

    def test_operator_help_matches_new_menus(self):
        views = self.env["ir.ui.view"].sudo().search([
            ("key", "=", "kai_viandas.help_operator_content"),
        ], limit=1) or self.env.ref("kai_viandas.help_operator_content")
        arch = views.arch if "arch" in views._fields else self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("tiene cuatro entradas", arch)
        self.assertNotIn("tiene tres entradas", arch)
        self.assertNotIn("tiene cinco entradas", arch)
        self.assertIn("<strong>Menús</strong>", arch)
        self.assertIn("Nuevo pedido", arch)
        self.assertIn("no está en el menú por ahora", arch)
        self.assertNotIn("Viandas → Hoy", arch)
        self.assertNotIn("Preparación →", arch)
        self.assertNotIn("→ Preparación", arch)
        self.assertNotIn("Reservas →", arch)
        self.assertNotIn("→ Reservas", arch)
        self.assertNotIn("Consultar reservas", arch)
        self.assertNotIn("Cargar pedidos", arch)
        self.assertIn("Viandas → Menús", arch)
