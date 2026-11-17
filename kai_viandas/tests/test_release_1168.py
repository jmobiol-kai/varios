"""Sin aviso azul en el asistente · 19.0.1.16.8."""
from lxml import etree
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tests import tagged

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1168(SidesCommon):
    def test_complete_week_notice_is_removed_from_the_wizard(self):
        views = self.env["lafija.employee.order"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.employee_order_form").id, "form"]]
        )
        arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        self.assertFalse(arch.xpath("//*[contains(@class, 'lf-no-extra-days')]"))
        self.assertFalse(arch.xpath("//field[@name='add_line_notice']"))
        self.assertTrue(arch.xpath("//div[@class='lf-cannot-add-line' or contains(@class, 'lf-cannot-add-line')]"))
        listing = arch.xpath("//field[@name='line_ids']/list")[0]
        create = listing.xpath("./control/create")
        self.assertTrue(create)
        self.assertEqual(create[0].get("string"), "Agregar pedido")

        self.assertNotIn("add_line_notice", self.env["lafija.employee.order"]._fields)

        employee, _ = self._create_employee("abc-1168-fullweek")
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

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.1"), module.latest_version)
        js = Path(get_module_path("kai_viandas"), "static/src/employee_order_list.js").read_text()
        self.assertIn("No hay más días con menú publicado esta semana", js)
