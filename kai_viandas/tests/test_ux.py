import json

from lxml import html
from odoo.addons.base.models.res_users import ResUsers as NativeUsers
from odoo.exceptions import AccessDenied
from odoo.tests import tagged

from .test_pages import PagesCommon


@tagged("post_install", "-at_install")
class TestUX(PagesCommon):
    def test_operator_real_login_lands_on_menus_and_respects_explicit_destination(self):
        self.operator.with_context(no_reset_password=True).password = "operator-browser-password-123"
        for destination, expected in ((None, "/odoo/action-kai_viandas.orders_action"), ("/odoo", "/odoo")):
            self._anonymous()
            page = self.url_open("/web/login", headers={"Host": "public.test"})
            token = html.fromstring(page.content).xpath("//input[@name='csrf_token']/@value")[0]
            values = {"csrf_token": token, "type": "password", "login": self.operator.login,
                      "password": "operator-browser-password-123"}
            if destination:
                values["redirect"] = destination
            response = self.url_open("/web/login", headers={"Host": "public.test"}, data=values, allow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["Location"], expected)

    def test_http_resave_keeps_unresolved_text_request_and_error_keeps_form(self):
        employee, _ = self._create_employee()
        self._real_login(employee.login, "employee-password-123")
        page = self.url_open("/my/viandas?week=2026-09-14")
        token = html.fromstring(page.content).xpath("//input[@name='csrf_token']/@value")[0]
        values = {"csrf_token": token, "week": "2026-09-14", f"menu_{self.menus[0].id}": str(self.product.id)}
        self.url_open("/my/viandas/reservar", data=values)
        self.env.invalidate_all()
        record = self.env["lafija.reservation"].search([("employee_partner_id", "=", employee.partner_id.id)], limit=1)
        self.url_open(f"/my/viandas/{record.id}/correccion", data={"csrf_token": token, "message": "Necesito una corrección de La Fija."})
        self.env.invalidate_all()
        events = record.event_ids.ids
        response = self.url_open("/my/viandas/reservar", data=values)
        self.env.invalidate_all()
        self.assertTrue(record.pending)
        self.assertEqual(record.event_ids.ids, events)
        self.assertIn("No hiciste cambios", response.text)
        self.assertIn("consulta escrita sigue abierta", response.text)
        response = self.url_open(f"/my/viandas/{record.id}/correccion", data={"csrf_token": token, "message": "x" * 4001})
        self.assertEqual(response.status_code, 400)
        tree = html.fromstring(response.content)
        self.assertTrue(tree.xpath("//textarea[@name='message']"))
        textarea = tree.xpath("//textarea[@name='message']")[0].text_content()
        self.assertEqual(textarea, "x" * 4000, repr(textarea[:150]))
        self.assertIn("Volver a la semana del 14/09", response.text)
        self.assertNotIn("271828", response.text)

    def test_denied_private_session_has_working_logout_and_login_help_is_generic(self):
        self.authenticate(self.private.login, "fixture")
        response = self.url_open("/my/viandas")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Salir y entrar con otra cuenta", response.text)
        self.assertIn("Ir al sitio público", response.text)
        logout = self.url_open("/web/session/logout?redirect=/web/login")
        self.assertEqual(logout.status_code, 200)
        self.assertIn("Entrá a tus viandas", logout.text)
        self._anonymous()
        response = self.url_open("/web/login", headers={"Host": "public.test"})
        self.assertIn("entrá al sitio corporativo", response.text)
        token = html.fromstring(response.content).xpath("//input[@name='csrf_token']/@value")[0]
        for login in ("usuario-inexistente", self._create_employee()[0].login):
            denied = self.url_open("/web/login", headers={"Host": "public.test"}, data={
                "csrf_token": token, "login": login, "password": "incorrect-password", "type": "password",
            })
            self.assertEqual(denied.status_code, 200)
            self.assertIn("entrá al sitio corporativo", denied.text)
            self.assertNotIn("Esta cuenta solo", denied.text)

    def test_browser_employee_form_can_reset_account_without_email(self):
        # B-02: el test debe recorrer el formulario y su validación de campos.
        # Una llamada Python a action_lf_manage_access no prueba este recorrido.
        self.website.domain = "http://corporate.test"
        # Liberar la URL antes de asignarla al otro sitio: la unicidad es
        # inmediata y el orden del flush conjunto no está garantizado.
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        employee, _ = self._create_employee()
        self.assertFalse(employee.email)
        old_token = employee._compute_session_token("ux-reset")
        script = """
            (async () => {
                const wait = async (fn, message) => {
                    for (let n=0;n<200;n++) {
                        const result=fn(); if(result) return result;
                        await new Promise(resolve=>setTimeout(resolve,100));
                    }
                    throw new Error(message);
                };
                const input = async (name, value) => {
                    const el=await wait(()=>document.querySelector('.modal .o_field_widget[name="'+name+'"] input'), 'Falta '+name);
                    el.focus(); el.value=value;
                    el.dispatchEvent(new Event('input',{bubbles:true}));
                    el.dispatchEvent(new Event('change',{bubbles:true})); el.blur();
                };
                const button=await wait(()=>document.querySelector('.o_form_view button[name="action_lf_manage_access"]'), 'No abrió ficha propia');
                if(document.querySelector('.o_form_view .o_field_widget[name="email"]')) throw new Error('Usa ficha fiscal con email');
                button.click();
                const operation=await wait(()=>document.querySelector('.modal .o_field_widget[name="operation"] .o_select_menu_toggler'), 'Gestionar acceso no abrió');
                operation.click();
                const reset=await wait(()=>[...document.querySelectorAll('.o_select_menu_item')].find(o=>o.textContent.includes('Restablecer')), 'No ofrece restablecer');
                reset.click();
                await input('new_password','new-browser-password-456');
                await input('reason','Restablecimiento desde el formulario web');
                await wait(()=>document.querySelector('.lf_credentials textarea')?.value.includes('new-browser-password-456'), 'No preparó el acceso para copiar');
                document.querySelector('.lf_credentials button').click();
                await wait(()=>/copiado|Ctrl\+C/.test(document.querySelector('.lf_credentials [role="status"]').textContent), 'No confirmó la copia ni ofreció copia manual');
                await wait(()=>document.querySelector('.modal button[name="action_apply"]'), 'Falta confirmar');
                [...document.querySelectorAll('.modal button[name="action_apply"]')].find(b => b.getClientRects().length).click();
                await wait(()=>!document.querySelector('.modal') && document.querySelector('.o_field_widget[name="lf_login"]'), 'No completó restablecimiento');
                if(document.querySelector('.o_field_invalid')) throw new Error('Formulario inválido');
                console.log('test successful');
            })().catch(error=>console.error(error.message));
        """
        self.browser_js(
            f"/odoo/action-kai_viandas.employee_action/{employee.partner_id.id}",
            script, login=self.operator.login, timeout=90,
        )
        self.env.invalidate_all()
        self.assertFalse(employee.email)
        self.assertNotEqual(employee._compute_session_token("ux-reset"), old_token)
        with self.assertRaises(AccessDenied):
            NativeUsers._check_credentials(employee.with_user(employee),
                {"type": "password", "password": "employee-password-123"}, {"interactive": True})
        result = NativeUsers._check_credentials(employee.with_user(employee),
            {"type": "password", "password": "new-browser-password-456"}, {"interactive": True})
        self.assertEqual(result["uid"], employee.id)
