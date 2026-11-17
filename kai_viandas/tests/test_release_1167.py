"""Enlace Agregar pedido en el asistente · 19.0.1.16.7."""
from lxml import etree
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tests import tagged

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1167(SidesCommon):
    def test_add_link_stays_visible_and_is_renamed(self):
        views = self.env["lafija.employee.order"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.employee_order_form").id, "form"]]
        )
        arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        listing = arch.xpath("//field[@name='line_ids']/list")[0]
        self.assertEqual(listing.get("js_class"), "lf_employee_order_list")
        create = listing.xpath("./control/create")
        self.assertTrue(create)
        self.assertEqual(create[0].get("string"), "Agregar pedido")
        self.assertTrue(arch.xpath("//div[@class='lf-cannot-add-line' or contains(@class, 'lf-cannot-add-line')]"))
        self.assertFalse(arch.xpath("//*[contains(@class, 'lf-no-extra-days')]"))
        self.assertFalse(arch.xpath("//field[@name='add_line_notice']"))

        scss = (Path(get_module_path("kai_viandas")) / "static/src/backend.scss").read_text()
        self.assertNotIn(
            ".lf-employee-order-form:has(.lf-no-extra-days",
            scss,
        )
        self.assertNotIn("o_field_x2many_list_row_add", scss)

        employee, _ = self._create_employee("abc-1167-fullweek")
        wizard = self.env["lafija.employee.order"].with_user(self.operator).new({
            "customer_company_id": self.customer.id,
            "employee_id": employee.partner_id.id,
            "week_start": "2026-09-14",
        })
        wizard.line_ids = [
            (0, 0, values)
            for values in wizard._line_values_for_week(wizard.employee_id, wizard.week_start)
        ]
        self.assertFalse(wizard.can_add_line)
        self.assertFalse(hasattr(wizard, "add_line_notice") and "add_line_notice" in wizard._fields)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.1"), module.latest_version)
        assets = Path(get_module_path("kai_viandas"), "static/src/employee_order_list.js")
        self.assertTrue(assets.exists())
        js = assets.read_text()
        self.assertIn("No hay más días con menú publicado esta semana", js)
        self.assertIn("lf_employee_order_list", js)
        self.assertIn("patch(ListRenderer.prototype", js)
