"""Alta de empleado desde el formulario Nuevo · 19.0.1.17.3."""
from lxml import etree
from odoo.addons.base.models.res_users import ResUsers as NativeUsers
from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease1173(SidesCommon):
    def test_employee_is_created_from_the_form_with_a_working_password(self):
        self.assertFalse(self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"), ("name", "=", "menu_employee_create"),
        ]))
        employees = self.env.ref("kai_viandas.menu_employees_group")
        leaves = self.env["ir.ui.menu"].search([("parent_id", "=", employees.id)])
        self.assertEqual(leaves.mapped("name"), ["Empleados corporativos"])
        self.assertTrue(self.env.ref("kai_viandas.employee_access_action"))

        views = self.env["res.partner"].with_user(self.operator).with_context(
            lf_employee_form=1, active_test=False,
        ).get_views([[self.env.ref("kai_viandas.employee_list").id, "list"],
                      [self.env.ref("kai_viandas.employee_form").id, "form"]])
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        self.assertFalse(list_arch.xpath("//button[@name='action_lf_create_employee']"))
        self.assertFalse(list_arch.xpath("//button[normalize-space()='Alta de empleado']"))
        self.assertNotEqual(list_arch.get("create"), "0")
        self.assertFalse(list_arch.xpath("//button[@name='action_lf_manage_access']"))

        form_arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        self.assertNotEqual(form_arch.get("create"), "0")
        self.assertFalse(form_arch.xpath("//button[@name='action_lf_create_employee']"))
        self.assertTrue(form_arch.xpath("//field[@name='lf_new_login']"))
        self.assertTrue(form_arch.xpath("//field[@name='lf_new_password']"))
        self.assertTrue(form_arch.xpath("//field[@name='lf_customer_company_id']"))
        self.assertTrue(form_arch.xpath("//field[@name='name']"))
        self.assertFalse(form_arch.xpath("//button[@name='action_lf_manage_access']"))

        help_arch = self.env.ref("kai_viandas.help_operator_content").arch
        self.assertNotIn("Empleados → Alta de empleado", help_arch)
        self.assertIn("Empleados corporativos", help_arch)
        self.assertIn("Nuevo", help_arch)
        self.assertIn("contraseña del portal", help_arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.1.17"), module.latest_version)

        Partner = self.env["res.partner"].with_user(self.operator).with_context(
            lf_employee_form=1, active_test=False,
        )
        form = Form(Partner, view="kai_viandas.employee_form")
        form.name = "Nuria de prueba"
        form.lf_customer_company_id = self.customer
        form.website_id = self.website
        form.lf_new_login = "abc-1173-nuria"
        form.lf_new_password = "portal-password-1173"
        partner = form.save()
        self.assertTrue(partner.lf_corporate_account)
        self.assertTrue(partner.lf_enabled)
        self.assertEqual(partner.lf_customer_company_id, self.customer)
        self.assertEqual(partner.website_id, self.website)
        self.assertFalse(partner.email)
        self.assertEqual(partner.lf_login, "abc-1173-nuria")
        user = partner.user_ids
        self.assertEqual(len(user), 1)
        self.assertTrue(user.share)
        self.assertTrue(user.has_group("kai_viandas.group_corporate_employee"))
        self.assertTrue(user._lf_can_use_site(self.website))
        result = NativeUsers._check_credentials(
            user.with_user(user),
            {"type": "password", "password": "portal-password-1173"},
            {"interactive": True},
        )
        self.assertEqual(result["uid"], user.id)
        self.assertNotIn("portal-password-1173", "".join(partner.message_ids.mapped("body")))
        self.assertIn("Alta de empleado", "".join(partner.message_ids.mapped("body")))

        with self.assertRaises(ValidationError), self.cr.savepoint():
            empty = Form(Partner, view="kai_viandas.employee_form")
            empty.name = "Sin clave"
            empty.lf_customer_company_id = self.customer
            empty.website_id = self.website
            empty.lf_new_login = "abc-1173-sin-clave"
            empty.lf_new_password = "   "
            empty.save()
