"""Empresa cliente del asistente · solo con empleados activos · 19.0.1.16.6."""
from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from ..models.identity import identity_context
from .test_pages import PagesCommon
from .test_release_112 import SidesCommon
from .test_release_160 import TestRelease160
from .test_release_182 import TestBrowser182


@tagged("post_install", "-at_install")
class TestRelease1166(SidesCommon):
    def _companies(self):
        return self.env["lafija.employee.order"].with_user(self.operator)._companies_with_active_employees()

    def test_company_combo_only_lists_companies_with_active_employees(self):
        employee, _ = self._create_employee("abc-1166-ok")
        lonely = self.env["res.partner"].sudo().create({
            "name": "Empresa sin alta 1166",
            "is_company": True,
        })
        archived_company = self.env["res.partner"].sudo().create({
            "name": "Empresa solo archivado 1166",
            "is_company": True,
        })
        archived = self.env["lafija.employee.access"].with_user(self.operator).create({
            "operation": "create",
            "name": "Empleado archivado 1166",
            "login": "abc-1166-arch",
            "customer_company_id": archived_company.id,
            "website_id": self.website.id,
            "new_password": "employee-password-123",
            "reason": "Alta de prueba 1166",
        }).action_apply()
        archived_partner = self.env["res.partner"].browse(archived["res_id"])
        self.assertIn(self.customer, self._companies())
        self.assertIn(archived_company, self._companies())
        archived_partner.user_ids.sudo().with_context(**identity_context()).write({"active": False})
        archived_partner.sudo().with_context(**identity_context()).write({"active": False})
        self.env["lafija.employee.order"].invalidate_model(["allowed_company_ids"])
        companies = self._companies()
        self.assertIn(self.customer, companies)
        self.assertNotIn(lonely, companies)
        self.assertNotIn(archived_company, companies)

        views = self.env["lafija.employee.order"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.employee_order_form").id, "form"]]
        )
        arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        self.assertTrue(arch.xpath("//field[@name='allowed_company_ids']"))
        info = self.env["lafija.employee.order"].with_user(self.operator).fields_get(
            ["customer_company_id", "employee_id"]
        )
        company_domain = str(info["customer_company_id"].get("domain") or "")
        employee_domain = str(info["employee_id"].get("domain") or "")
        self.assertIn("allowed_company_ids", company_domain)
        self.assertIn("active", employee_domain)
        self.assertIn("customer_company_id", employee_domain)

        found = self.env["res.partner"].with_user(self.operator).name_search(
            "", [("id", "in", companies.ids)], operator="ilike", limit=80,
        )
        found_ids = [row[0] for row in found]
        self.assertIn(self.customer.id, found_ids)
        self.assertNotIn(lonely.id, found_ids)
        self.assertNotIn(archived_company.id, found_ids)

        with self.assertRaises(ValidationError):
            self.env["lafija.employee.order"].with_user(self.operator).create({
                "customer_company_id": lonely.id,
            })

        employee_ids = [
            row[0]
            for row in self.env["res.partner"].with_user(self.operator).name_search(
                "",
                [
                    ("active", "=", True),
                    ("lf_corporate_account", "=", True),
                    ("lf_enabled", "=", True),
                    ("is_company", "=", False),
                    ("lf_customer_company_id", "=", self.customer.id),
                ],
                operator="ilike",
                limit=80,
            )
        ]
        self.assertIn(employee.partner_id.id, employee_ids)
        self.assertNotIn(archived_partner.id, employee_ids)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.1"), module.latest_version)


@tagged("post_install", "-at_install")
class TestBrowser1166(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey
    _backend = TestBrowser182._backend

    def test_wizard_company_combo_lists_only_active_employee_companies(self):
        self._backend()
        self.env["res.lang"]._activate_lang("es_AR")
        self.operator.lang = "es_AR"
        expected = self.env["lafija.employee.order"].with_user(
            self.operator
        )._companies_with_active_employees().mapped("name")
        action = self.env.ref("kai_viandas.employee_order_action").id

        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector(".lf-employee-order-form, .o_form_view")')
            wait('document.body.textContent.includes("Crear pedidos de empleados")')
            evaluate('''(() => {
                const field = document.querySelector(".o_field_widget[name='customer_company_id'] input, .o_field_many2one[name='customer_company_id'] input");
                if (field) { field.click(); field.focus(); }
            })()''')
            wait('document.querySelector(".o-autocomplete--dropdown-menu, .ui-autocomplete, .o_m2o_dropdown_option")')
            names = evaluate('''(() => {
                const items = [...document.querySelectorAll(
                    ".o-autocomplete--dropdown-menu li, .ui-autocomplete li, .o-autocomplete--dropdown-item"
                )];
                return items.map(e => (e.textContent || "").trim()).filter(
                    t => t && !/Buscar|Cargar|Search|más/i.test(t)
                );
            })()''')
            for name in expected:
                self.assertIn(name, names)
            self.assertFalse(any("Akamine" in (n or "") for n in names))
            browser.take_screenshot(prefix="lf166_empresas_").result(timeout=10)

        self._employee_pointer_journey(
            f"/odoo/action-{action}", journey, width=1366, login=self.operator.login,
        )
