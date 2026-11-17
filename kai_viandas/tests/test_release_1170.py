"""Pantalla principal Pedidos · 19.0.1.17.0."""
from datetime import date

from freezegun import freeze_time
from lxml import etree
from odoo.tests import tagged

from ..models.reservation import operation_context
from ..models.time_utils import business_today
from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1170(SidesCommon):
    def test_pedidos_is_landing_grouped_list_with_open_filter(self):
        root = self.env.ref("kai_viandas.menu_root")
        sections = self.env["ir.ui.menu"].search([("parent_id", "=", root.id)], order="sequence,id")
        self.assertEqual(sections.mapped("name"), ["Pedidos", "Menús", "Empleados", "Ayuda", "Horarios de pedido"])
        menu = self.env.ref("kai_viandas.menu_orders")
        action = self.env.ref("kai_viandas.orders_action")
        self.assertEqual(menu.action, action)
        self.assertEqual(menu.sequence, 1)
        self.assertEqual(action.name, "Pedidos")
        self.assertEqual(action.res_model, "lafija.reservation")
        self.assertEqual(action.view_id, self.env.ref("kai_viandas.reservation_list"))
        import ast
        context = action.context or {}
        if isinstance(context, str):
            context = ast.literal_eval(context)
        self.assertTrue(context.get("search_default_upcoming_or_pending"))
        self.assertEqual(context.get("group_by"), ["customer_company_id", "date:day"])

        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"],
             [self.env.ref("kai_viandas.reservation_search").id, "search"]]
        )
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        self.assertEqual(list_arch.get("js_class"), "lf_reservation_list")
        self.assertEqual(list_arch.get("group_create"), "0")
        self.assertFalse(list_arch.xpath("//button[@name='action_elaborate']"))
        self.assertTrue(list_arch.xpath("//button[@name='action_open_production']"))
        search_arch = etree.fromstring(views["views"]["search"]["arch"].encode())
        self.assertTrue(search_arch.xpath("//filter[@name='upcoming_or_pending']"))
        self.assertTrue(search_arch.xpath("//field[@name='customer_company_id']"))
        self.assertTrue(search_arch.xpath("//field[@name='employee_partner_id']"))
        self.assertTrue(search_arch.xpath("//field[@name='date']"))
        self.assertTrue(search_arch.xpath("//field[@name='state']"))

        help_view = self.env.ref("kai_viandas.help_operator_content")
        arch = help_view.arch
        self.assertIn("tiene cuatro entradas", arch)
        self.assertIn("Viandas → Pedidos", arch)
        self.assertIn("Nuevo pedido", arch)
        self.assertIn("Próximos y pendientes", arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.17"), module.latest_version)

        employee, _ = self._create_employee("abc-1170-open")
        by_date = {menu.date: menu for menu in self.menus}
        with freeze_time("2026-09-08 12:00:00"):
            recs = self.env["lafija.reservation"].with_user(employee)._submit_selections(
                self.website,
                [
                    (by_date[date(2026, 9, 17)].id, self.chicken.id),
                    (by_date[date(2026, 9, 14)].id, self.chicken.id),
                    (by_date[date(2026, 9, 18)].id, self.chicken.id),
                    (by_date[date(2026, 9, 15)].id, self.chicken.id),
                ],
            ).sudo()
        future = recs.filtered(lambda rec: rec.date == date(2026, 9, 17))
        past_pending = recs.filtered(lambda rec: rec.date == date(2026, 9, 14))
        cancelled = recs.filtered(lambda rec: rec.date == date(2026, 9, 18))
        past_done = recs.filtered(lambda rec: rec.date == date(2026, 9, 15))
        past_pending.with_context(**operation_context()).write({"pending_product_id": self.pork.id, "pending_description": "Cerdo"})
        self.env["lafija.reservation.correction"].with_user(self.operator).create({
            "reservation_id": cancelled.id,
            "operation": "cancel",
            "reason": "Cancelar para prueba 1170",
        }).action_apply()
        self.assertEqual(cancelled.state, "cancelled")
        with freeze_time("2026-09-16 12:00:00"):
            self.assertEqual(business_today(self.env), date(2026, 9, 16))
            found = self.env["lafija.reservation"].with_user(self.operator).search([
                ("is_open_order", "=", True),
                ("employee_partner_id", "=", employee.partner_id.id),
            ])
            self.assertIn(future, found)
            self.assertIn(past_pending, found)
            self.assertNotIn(cancelled, found)
            self.assertNotIn(past_done, found)
