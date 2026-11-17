"""Cambiar contraseña en el menú de acciones · 19.0.1.17.4."""
from lxml import etree
from odoo.addons.base.models.res_users import ResUsers as NativeUsers
from odoo.exceptions import AccessDenied, ValidationError
from odoo.tests import Form, tagged

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1174(SidesCommon):
    def test_change_password_action_and_form_edits(self):
        action = self.env.ref("kai_viandas.employee_change_password_action")
        self.assertEqual(action.name, "Cambiar contraseña")
        self.assertEqual(action.binding_model_id, self.env.ref("base.model_res_partner"))
        self.assertEqual(action.binding_type, "action")
        self.assertIn("form", (action.binding_view_types or ""))
        self.assertIn("list", (action.binding_view_types or ""))

        views = self.env["res.partner"].with_user(self.operator).with_context(
            lf_employee_form=1, active_test=False,
        ).get_views([[self.env.ref("kai_viandas.employee_list").id, "list"],
                      [self.env.ref("kai_viandas.employee_form").id, "form"]])
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        form_arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        self.assertFalse(list_arch.xpath("//button[@name='action_lf_manage_access']"))
        self.assertFalse(form_arch.xpath("//button[@name='action_lf_manage_access']"))
        self.assertFalse(form_arch.xpath("//*[normalize-space()='Gestionar acceso']"))
        self.assertNotEqual(form_arch.get("edit"), "0")

        help_arch = self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Cambiar contraseña", help_arch)
        self.assertNotIn("Gestionar acceso", help_arch)
        self.assertIn("Nueva contraseña", help_arch)
        self.assertIn("Habilitado para viandas", help_arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.17"), module.latest_version)

        employee, _ = self._create_employee("abc-1174-pwd")
        partner = employee.partner_id
        other, _ = self._create_employee("abc-1174-other")

        # One or several selected partners open the native wizard with a line each.
        action_one = partner.with_user(self.operator).action_lf_change_password()
        self.assertEqual(action_one["res_model"], "change.password.wizard")
        self.assertEqual(action_one["name"], "Cambiar contraseña")
        self.assertEqual(action_one["target"], "new")
        wizard = self.env["change.password.wizard"].browse(action_one["res_id"])
        self.assertEqual(wizard.user_ids.user_id, employee)
        self.assertEqual(wizard.user_ids.user_login, "abc-1174-pwd")
        self.assertFalse(wizard.user_ids.new_passwd)

        action_many = (partner | other.partner_id).with_user(self.operator).action_lf_change_password()
        many = self.env["change.password.wizard"].browse(action_many["res_id"])
        self.assertEqual(set(many.user_ids.user_id.ids), {employee.id, other.id})

        wizard.user_ids.new_passwd = "nuevo-password-1174"
        wizard.with_user(self.operator).change_password_button()
        with self.assertRaises(AccessDenied):
            NativeUsers._check_credentials(
                employee.with_user(employee),
                {"type": "password", "password": "employee-password-123"},
                {"interactive": True},
            )
        result = NativeUsers._check_credentials(
            employee.with_user(employee),
            {"type": "password", "password": "nuevo-password-1174"},
            {"interactive": True},
        )
        self.assertEqual(result["uid"], employee.id)
        bodies = " ".join(partner.message_ids.mapped("body"))
        self.assertIn("Acceso corporativo: Cambiar contraseña", bodies)
        self.assertNotIn("nuevo-password-1174", bodies)

        # Empresa and enabled stay editable on the employee form.
        other_company = self.env["res.partner"].create({"name": "Otra empresa 1174", "is_company": True})
        form = Form(partner.with_user(self.operator).with_context(lf_employee_form=1),
                    view="kai_viandas.employee_form")
        form.lf_customer_company_id = other_company
        form.lf_enabled = False
        form.save()
        self.assertEqual(partner.lf_customer_company_id, other_company)
        self.assertFalse(partner.lf_enabled)
        self.assertFalse(employee.active)
        later = " ".join(partner.message_ids.mapped("body"))
        self.assertIn("Deshabilitar", later)
        self.assertIn("Corregir empresa y sitio", later)

        with self.assertRaises(ValidationError):
            self.customer.with_user(self.operator).action_lf_change_password()
