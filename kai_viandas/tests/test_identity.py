from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import AccessDenied, AccessError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.base.models.res_users import ResUsers as NativeUsers


class LafijaCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.user_admin").tz = "America/Argentina/Buenos_Aires"
        cls.customer = cls.env["res.partner"].create({"name": "ABC de prueba", "is_company": True})
        cls.website = cls.env["website"].create({
            "name": "Empresas de prueba", "domain": "http://corporate.test",
            "lf_corporate_site": True, "specific_user_account": True,
            "auth_signup_uninvited": "b2b",
        })
        cls.operator = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Operador de prueba", "login": "lf-operator",
            "group_ids": [Command.set([cls.env.ref("kai_viandas.group_operator").id])],
        })
        cls.private = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Particular de prueba", "login": "lf-private",
            "email": "private@example.test", "password": "private-password-123",
            "group_ids": [Command.set([cls.env.ref("base.group_portal").id])],
        })
        # Si la categoría Viandas existe (p.ej. copia de 00lafija), el menú la exige.
        Category = cls.env["product.category"]
        cls.plate_categ = Category.search([("complete_name", "=", "Viandas")], limit=1) or Category.create({"name": "Viandas"})
        cls.env["ir.default"].sudo().set("product.template", "categ_id", cls.plate_categ.id)

    def setUp(self):
        super().setUp()
        # Los menús comunes son del 14–18/09/2026. No dependen del día UTC
        # de ejecución ni se vuelven pasados al correr de noche. Los escenarios
        # horarios conservan sus freeze_time propios, anidados sobre este reloj.
        self.enterContext(freeze_time("2026-09-14 12:00:00", tick=True))

    def _create_employee(self, login="abc-juan"):
        wizard = self.env["lafija.employee.access"].with_user(self.operator).create({
            "operation": "create", "name": "Juan de prueba", "login": login,
            "customer_company_id": self.customer.id, "website_id": self.website.id,
            "new_password": "employee-password-123", "reason": "Alta solicitada por ABC",
        })
        result = wizard.action_apply()
        partner = self.env["res.partner"].browse(result["res_id"])
        return partner.user_ids, wizard

    def _manage(self, user, operation, **values):
        return self.env["lafija.employee.access"].with_user(self.operator).create({
            "employee_id": user.partner_id.id, "operation": operation,
            "reason": "Corrección solicitada por ABC", **values,
        })


@tagged("post_install", "-at_install")
class TestIdentity(LafijaCommon):
    def test_operator_has_business_roles_without_user_administration(self):
        self.assertTrue(self.operator.has_group("account.group_account_manager"))
        self.assertTrue(self.operator.has_group("website.group_website_designer"))
        self.assertFalse(self.operator.has_group("base.group_system"))
        self.assertFalse(self.operator.has_group("base.group_erp_manager"))

    def test_account_created_by_operator_with_provenance_and_without_email(self):
        with patch.object(type(self.env["res.users"]), "_action_reset_password") as invite:
            employee, wizard = self._create_employee()
        invite.assert_not_called()
        self.assertTrue(employee.share)
        self.assertFalse(employee.has_group("base.group_user"))
        self.assertFalse(employee.email)
        self.assertFalse(employee.partner_id.parent_id)
        self.assertEqual(employee.website_id, self.website)
        self.assertEqual(employee.partner_id.lf_customer_company_id, self.customer)
        self.assertTrue(employee._lf_can_use_site(self.website))
        self.assertFalse(wizard.new_password)
        self.assertEqual(employee.partner_id.lf_account_status, "new")
        audit = employee.partner_id.message_ids.filtered(lambda m: "Alta solicitada por ABC" in (m.body or ""))
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.author_id, self.operator.partner_id)
        self.assertNotIn("employee-password-123", "".join(employee.partner_id.message_ids.mapped("body")))

    def test_native_identity_rule_keeps_employee_separate(self):
        employee, _ = self._create_employee()
        self.assertEqual(self.env["res.partner"].with_user(employee).search([]), employee.partner_id)
        self.assertEqual(self.env["res.users"].with_user(employee).search([]), employee)
        with self.assertRaises(AccessError):
            employee.partner_id.with_user(employee).read(["lf_customer_company_id"])

    def test_independent_employee_cannot_gain_descendants_visible_by_native_rule(self):
        employee, _ = self._create_employee()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["res.partner"].create({"name": "Compañero bajo empleado", "parent_id": employee.partner_id.id})
        self.assertEqual(self.env["res.partner"].with_user(employee).search([]), employee.partner_id)

    def test_reset_revokes_password_and_changes_session_token_without_mail(self):
        employee, _ = self._create_employee()
        old_token = employee._compute_session_token("test-session")
        with patch.object(type(self.env["mail.mail"]), "send") as send:
            self._manage(employee, "reset", new_password="new-password-456").action_apply()
        send.assert_not_called()
        with self.assertRaises(AccessDenied):
            NativeUsers._check_credentials(employee.with_user(employee),
                {"type": "password", "password": "employee-password-123"}, {"interactive": True},
            )
        result = NativeUsers._check_credentials(employee.with_user(employee),
            {"type": "password", "password": "new-password-456"}, {"interactive": True},
        )
        self.assertEqual(result["uid"], employee.id)
        self.assertNotEqual(old_token, employee._compute_session_token("test-session"))

    def test_password_only_needs_a_value_and_default_is_six_digits(self):
        access = self.env["lafija.employee.access"].with_user(self.operator)
        self.assertRegex(access.create({"operation": "create"}).new_password, r"^[1-9][0-9]{5}$")
        values = {
            "operation": "create", "name": "Ana de prueba", "login": "abc-ana",
            "customer_company_id": self.customer.id, "website_id": self.website.id,
        }
        for blank in ("", "   "):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                access.create({**values, "new_password": blank}).action_apply()
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.env["lafija.employee.onboarding"].with_user(self.operator)._create_identity(
                    name="Ana de prueba", login="abc-ana", password=blank,
                    company=self.customer, website=self.website, reason="Prueba",
                )
        result = access.create({**values, "new_password": "123456"}).action_apply()
        employee = self.env["res.partner"].browse(result["res_id"]).user_ids
        result = NativeUsers._check_credentials(employee.with_user(employee),
            {"type": "password", "password": "123456"}, {"interactive": True},
        )
        self.assertEqual(result["uid"], employee.id)
        for blank in ("", "   "):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._manage(employee, "reset", new_password=blank).action_apply()
        self._manage(employee, "reset", new_password="1").action_apply()
        result = NativeUsers._check_credentials(employee.with_user(employee),
            {"type": "password", "password": "1"}, {"interactive": True},
        )
        self.assertEqual(result["uid"], employee.id)

    def test_disable_keeps_classification_and_reenable_is_possible(self):
        employee, _ = self._create_employee()
        self.assertTrue(employee._lf_is_corporate_subject())
        self._manage(employee, "disable").action_apply()
        self.assertFalse(employee.active)
        self.assertFalse(employee.partner_id.lf_enabled)
        self.assertTrue(employee._lf_is_corporate_subject())
        self.assertFalse(employee._lf_can_use_site(self.website))
        self.assertEqual(employee.partner_id.lf_account_status, "disabled")
        self._manage(employee, "enable").action_apply()
        self.assertTrue(employee._lf_can_use_site(self.website))

    def test_ordinary_write_cannot_bypass_action_with_forged_context(self):
        employee, _ = self._create_employee()
        with self.assertRaises(AccessError), self.cr.savepoint():
            employee.partner_id.with_user(self.operator).with_context(
                _lf_identity_operation=True,
            ).write({"lf_enabled": False})
        self.assertTrue(employee.partner_id.lf_enabled)
        with self.assertRaises(AccessError), self.cr.savepoint():
            employee.with_user(employee).write({"password": "unauthorized-123"})

    def test_corporate_group_without_mark_cannot_be_committed(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.private.write({"group_ids": [Command.link(self.env.ref("kai_viandas.group_corporate_employee").id)]})
        self.assertFalse(self.private._lf_is_corporate_subject())

    def test_group_editor_cannot_remove_corporate_classification_and_keeps_cache_safe(self):
        employee, _ = self._create_employee()
        self.assertTrue(employee._lf_is_corporate_subject())
        group = self.env.ref("kai_viandas.group_corporate_employee")
        with self.assertRaises(ValidationError), self.cr.savepoint():
            group.write({"user_ids": [Command.unlink(employee.id)]})
        self.assertTrue(employee._lf_is_corporate_subject())
        self.assertTrue(employee._lf_can_use_site(self.website))

    def test_operator_can_repair_preexisting_mark_group_inconsistency(self):
        employee, _ = self._create_employee()
        self.assertTrue(employee._lf_is_corporate_subject())
        # Estado heredado defectuoso, imposible de producir con la acción normal.
        self.cr.execute("UPDATE res_partner SET lf_corporate_account = false WHERE id = %s", [employee.partner_id.id])
        self.env.invalidate_all()
        self.env.registry.clear_cache()
        self.assertTrue(employee._lf_is_corporate_subject())
        self.assertFalse(employee._lf_can_use_site(self.website))
        self.assertEqual(employee.partner_id.lf_account_status, "review")
        employee.partner_id.with_user(self.operator).action_lf_manage_access()
        self._manage(employee, "update", customer_company_id=self.customer.id,
                     website_id=self.website.id).action_apply()
        self.assertTrue(employee._lf_can_use_site(self.website))

    def test_unauthorized_role_cannot_manage_and_account_cannot_be_captured(self):
        with self.assertRaises(AccessError):
            self.env["lafija.employee.access"].with_user(self.private).create({"reason": "No autorizado"})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._manage(self.private, "reset", new_password="must-not-change-123").action_apply()
        employee, _ = self._create_employee()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._create_employee(login=employee.login)

    def test_v13_intercepted_invitation_and_private_security_notice(self):
        # Interceptar entrega evita confundir auto_delete/fallo SMTP con ausencia de envío.
        mail_type = type(self.env["mail.mail"])
        with patch.object(mail_type, "send", autospec=True, return_value=True) as send:
            self.env["res.users"].with_context(no_reset_password=False, install_mode=False).create({
                "name": "Control V13", "login": "lf-v13",
                "email": "v13@example.test", "password": "private-control-123",
                "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
            })
            self.assertGreater(send.call_count, 0, "Sin contexto, el alta nativa intenta enviar invitación")
        with patch.object(mail_type, "send", autospec=True, return_value=True) as send:
            self.private.write({"password": "private-new-password-123"})
            self.assertGreater(send.call_count, 0, "El aviso de seguridad B2C debe conservarse")
