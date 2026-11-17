"""Sin menú Hoy ni Alta desde padrón · 19.0.1.16.9."""
from odoo.tests import tagged

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1169(SidesCommon):
    def test_hoy_and_padron_menus_are_removed_and_actions_remain(self):
        root = self.env.ref("kai_viandas.menu_root")
        sections = self.env["ir.ui.menu"].search([("parent_id", "=", root.id)], order="sequence,id")
        self.assertEqual(sections.mapped("name"), ["Pedidos", "Menús", "Empleados", "Ayuda", "Horarios de pedido"])
        xmlids = self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"),
            ("name", "in", ["menu_today", "menu_employee_batch"]),
        ])
        self.assertFalse(xmlids)

        self.assertTrue(self.env.ref("kai_viandas.workday_action"))
        self.assertEqual(self.env.ref("kai_viandas.workday_action").state, "code")
        self.assertTrue(callable(self.env["lafija.menu.day"].action_workday))
        batch = self.env.ref("kai_viandas.employee_batch_action")
        self.assertEqual(batch.res_model, "lafija.employee.batch")
        self.assertTrue(self.env.ref("kai_viandas.employee_order_action"))

        employees = self.env.ref("kai_viandas.menu_employees_group")
        leaves = self.env["ir.ui.menu"].search([("parent_id", "=", employees.id)], order="sequence,id")
        self.assertNotIn("Alta desde padrón", leaves.mapped("name"))
        self.assertIn("Empleados corporativos", leaves.mapped("name"))
        self.assertNotIn("Alta de empleado", leaves.mapped("name"))
        self.assertEqual(leaves.mapped("name"), ["Empleados corporativos"])

        help_view = self.env.ref("kai_viandas.help_operator_content")
        arch = help_view.arch
        self.assertIn("tiene cuatro entradas", arch)
        self.assertNotIn("Viandas → Hoy", arch)
        self.assertNotIn("tiene tres entradas", arch)
        self.assertIn("no está en el menú por ahora", arch)
        self.assertNotIn("Empleados → Alta de empleado", arch)
        self.assertIn("Empleados corporativos", arch)
        self.assertIn("Nuevo", arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.1"), module.latest_version)
