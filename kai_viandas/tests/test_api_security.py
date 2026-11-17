import xmlrpc.client

from odoo.exceptions import AccessDenied, AccessError
from odoo.tests import tagged
from odoo.addons.base.models.res_users import ResUsersApikeys as NativeKeys

from .test_identity import LafijaCommon
from .test_pages import PagesCommon


def _api_key_expiration(env):
    # El fixture congela Python para los menús, pero el core valida la caducidad
    # de las claves con now() de PostgreSQL. Usar ese mismo reloj en esta prueba.
    env.cr.execute("SELECT (now() AT TIME ZONE 'UTC') + interval '1 day'")
    return env.cr.fetchone()[0]


@tagged("post_install", "-at_install")
class TestAPIData(LafijaCommon):
    def test_interactive_flag_does_not_authorize_api_and_existing_keys_are_rejected(self):
        employee, _ = self._create_employee()
        for environment in ({}, {"interactive": False}, {"interactive": True}):
            with self.assertRaises(AccessDenied):
                employee.with_user(employee)._check_credentials(
                    {"type": "password", "password": "employee-password-123"}, environment)
        keys = self.env["res.users.apikeys"].with_user(employee).sudo()
        expiration = _api_key_expiration(self.env)
        with self.assertRaises(AccessDenied):
            keys._generate(None, "Clave corporativa prohibida", expiration)
        # Una clave que hubiese existido antes de clasificar la cuenta tampoco sirve.
        old_key = NativeKeys._generate(keys, None, "Clave anterior de prueba", expiration)
        self.assertEqual(NativeKeys._check_credentials(keys, scope="rpc", key=old_key), employee.id)
        with self.assertRaises(AccessDenied):
            self.env["res.users.apikeys"]._check_credentials(scope="rpc", key=old_key)
        private_key = self.env["res.users.apikeys"].with_user(self.private).sudo()._generate(None, "Clave particular", expiration)
        self.assertEqual(self.env["res.users.apikeys"]._check_credentials(scope="rpc", key=private_key), self.private.id)

    def test_attribute_supplement_is_not_an_uncovered_price(self):
        employee, _ = self._create_employee()
        attribute = self.env["product.attribute"].create({"name": "Guarnición de prueba"})
        value = self.env["product.attribute.value"].create({"name": "Extra", "attribute_id": attribute.id, "default_extra_price": 987654.32})
        with self.assertRaises(AccessError):
            value.with_user(employee).read(["default_extra_price"])
        self.assertFalse(self.env["product.attribute.value"].with_user(employee).search([("id", "=", value.id)]))
        # La regla corporativa no cambia los datos nativos del particular.
        self.assertEqual(value.with_user(self.private).read(["default_extra_price"])[0]["default_extra_price"], 987654.32)


@tagged("post_install", "-at_install")
class TestAPIAndRecoveryPages(PagesCommon):
    def test_operator_authenticated_by_native_api_can_generate_internal_labels(self):
        employee, _ = self._create_employee()
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        action = self.menus[0].with_user(self.operator).action_take_list()
        revision = self.env["lafija.preparation.cut"].browse(action["res_id"]).current_revision_id
        key = self.env["res.users.apikeys"].with_user(self.operator).sudo()._generate(
            None, "Operador autorizado", _api_key_expiration(self.env))
        self.assertEqual(NativeKeys._check_credentials(
            self.env["res.users.apikeys"], scope="rpc", key=key), self.operator.id)
        self.opener.cookies.clear()
        response = self.url_open("/json/2/lafija.preparation.revision/action_print_labels",
            json={"ids": revision.ids}, headers={"Host": "public.test", "Authorization": f"Bearer {key}",
                "X-Odoo-Database": self.env.cr.dbname})
        self.assertEqual(response.status_code, 200, response.text[:1500])
        self.assertEqual(response.json()["res_model"], "lafija.label.print")
        self.assertEqual(revision.print_ids.actor_id, self.operator)
        self.assertTrue(revision.print_ids.attachment_id.raw.startswith(b"%PDF"))

    def test_reset_token_on_public_site_does_not_reopen_corporate_self_service(self):
        employee, _ = self._create_employee()
        self.env["ir.config_parameter"].sudo().set_param("auth_signup.reset_password", True)
        self._anonymous()
        for user, allowed in ((employee, False), (self.private, True)):
            user.partner_id.signup_prepare(signup_type="reset")
            token = user.partner_id._generate_signup_token()
            response = self.url_open(f"/web/reset_password?token={token}", headers={"Host": "public.test"})
            if allowed:
                self.assertEqual(response.status_code, 200, response.text[:1000])
                self.assertIn('name="password"', response.text)
            else:
                self.assertNotEqual(response.status_code, 200, response.text[:1000])
                self.assertNotIn('name="password"', response.text)

    def test_corporate_password_and_key_fail_on_noninteractive_transports(self):
        employee, _ = self._create_employee()
        expiration = _api_key_expiration(self.env)
        key = NativeKeys._generate(self.env["res.users.apikeys"].with_user(employee).sudo(), None, "Anterior", expiration)
        self.assertEqual(NativeKeys._check_credentials(
            self.env["res.users.apikeys"], scope="rpc", key=key), employee.id)
        self._anonymous()
        headers = {"Host": "public.test"}
        payload = xmlrpc.client.dumps((self.env.cr.dbname, employee.login, "employee-password-123", {"interactive": True}), methodname="authenticate")
        response = self.url_open("/xmlrpc/2/common", data=payload, headers={**headers, "Content-Type": "text/xml"})
        values, _ = xmlrpc.client.loads(response.content)
        self.assertFalse(values[0])
        response = self.url_open("/jsonrpc", json={"jsonrpc": "2.0", "id": 1, "method": "call",
            "params": {"service": "common", "method": "authenticate", "args": [self.env.cr.dbname, employee.login, key, {"interactive": True}]}}, headers=headers)
        self.assertFalse(response.json().get("result"))
        response = self.url_open("/json/2/product.template/search_read", json={"domain": [], "fields": ["list_price"]},
            headers={**headers, "Authorization": f"Bearer {key}", "X-Odoo-Database": self.env.cr.dbname})
        self.assertIn(response.status_code, (401, 403), response.text)
        self.assertNotIn("271828", response.text)

    def test_operator_reset_invalidates_old_session_and_real_login_uses_new_password(self):
        employee, _ = self._create_employee()
        self._real_login(employee.login, "employee-password-123")
        self.assertEqual(self.url_open("/my/viandas").status_code, 200)
        self._manage(employee, "reset", new_password="replacement-password-123").action_apply()
        response = self.url_open("/my/viandas", allow_redirects=False)
        self.assertIn(response.status_code, (303, 403))
        response = self._real_login(employee.login, "employee-password-123")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No se pudo iniciar sesión", response.text)
        response = self._real_login(employee.login, "replacement-password-123")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.url_open("/my/viandas").status_code, 200)
