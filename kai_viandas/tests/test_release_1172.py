"""Sin etiqueta suelta Semana en el asistente · 19.0.1.17.2."""
from datetime import timedelta
from lxml import etree
from odoo import fields
from odoo.tests import tagged, Form

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1172(SidesCommon):
    def test_week_label_is_not_shown_as_orphan_on_empty_or_filled_form(self):
        views = self.env["lafija.employee.order"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.employee_order_form").id, "form"]]
        )
        arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        self.assertFalse(arch.xpath("//label[@for='week_start']"))
        self.assertFalse(arch.xpath("//label[normalize-space()='Semana']"))
        week_label = arch.xpath("//field[@name='week_label']")
        self.assertTrue(week_label)
        self.assertEqual(week_label[0].get("nolabel"), "1")
        week_group = arch.xpath("//field[@name='week_label']/ancestor::group[@invisible]")
        self.assertTrue(week_group)
        self.assertIn("employee_id", week_group[0].get("invisible") or "")
        self.assertTrue(arch.xpath("//button[@name='action_previous_week']"))
        self.assertTrue(arch.xpath("//button[@name='action_next_week']"))
        self.assertTrue(arch.xpath("//field[@name='week_start']"))

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.17"), module.latest_version)

        employee, _ = self._create_employee("abc-1172-week")
        empty = self.env["lafija.employee.order"].with_user(self.operator).new({})
        self.assertFalse(empty.week_label)
        self.assertFalse(empty.week_start)
        form = Form(self.env["lafija.employee.order"].with_user(self.operator), view="kai_viandas.employee_order_form")
        form.customer_company_id = self.customer
        form.employee_id = employee.partner_id
        filled = form.save()
        self.assertTrue(filled.week_start)
        self.assertTrue(filled.week_label)
        self.assertRegex(filled.week_label, r"\d{2}/\d{2}")
        original = filled.week_start
        filled.action_next_week()
        self.assertEqual(filled.week_start, original + timedelta(days=7))
        filled.action_previous_week()
        self.assertEqual(filled.week_start, original)
