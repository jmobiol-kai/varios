"""Enlace Agregar pedido de cliente en Hoy · 19.0.1.16.4."""
from odoo.tests import tagged

from .test_pages import PagesCommon
from .test_release_114 import TestRelease114
from .test_release_160 import TestRelease160
from .test_release_182 import TestBrowser182


@tagged("post_install", "-at_install")
class TestRelease1164(TestRelease114):
    def test_reservation_list_uses_custom_js_class_and_drops_header_button(self):
        arch = self.env.ref("kai_viandas.reservation_list").with_user(self.operator).arch
        self.assertIn('js_class="lf_reservation_list"', arch)
        self.assertIn('group_create="0"', arch)
        self.assertNotIn("Crear pedidos de clientes", arch)
        self.assertNotIn("action_pending_all_dates", arch)
        self.assertNotIn("Ver pendientes de cualquier fecha", arch)
        opened = self.env["lafija.reservation"].with_user(self.operator).action_create_client_orders()
        self.assertEqual(opened["id"], self.env.ref("kai_viandas.employee_order_action").id)

    def test_operator_help_points_to_the_list_link(self):
        views = self.env["ir.ui.view"].sudo().search([
            ("key", "=", "kai_viandas.help_operator_content"),
        ], limit=1) or self.env.ref("kai_viandas.help_operator_content")
        arch = views.arch if "arch" in views._fields else self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Nuevo pedido", arch)
        self.assertNotIn("Crear pedidos de clientes", arch)


@tagged("post_install", "-at_install")
class TestBrowser1164(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey
    _backend = TestBrowser182._backend

    def test_hoy_link_opens_wizard_grouped_and_ungrouped(self):
        self._backend()
        self.env["res.lang"]._activate_lang("es_AR")
        self.operator.lang = "es_AR"
        action = self.env.ref("kai_viandas.workday_action").id

        def journey(browser, evaluate, wait, pointer, _type):
            wait('document.querySelector(".o_list_view")')
            wait('document.querySelector(".o_breadcrumb")?.textContent.includes("Hoy ·")')
            wait('document.querySelector(".lf_add_client_order")')
            self.assertIn(
                "Nuevo pedido",
                evaluate('document.querySelector(".lf_add_client_order")?.textContent || ""'),
            )
            self.assertFalse(evaluate(
                '!![...document.querySelectorAll(".o_list_group_add")].find('
                'e => (e.textContent || "").includes("Agrega Empresa")'
                ' || (e.textContent || "").includes("Add a "))'
            ))
            self.assertFalse(evaluate(
                '!![...document.querySelectorAll("button,a")].find('
                'e => (e.textContent || "").trim() === "Crear pedidos de clientes")'
            ))
            browser.take_screenshot(prefix="lf164_hoy_sin_agrupar_").result(timeout=10)

            pointer(".lf_add_client_order")
            wait('document.body.textContent.includes("Crear pedidos de empleados")')
            browser.take_screenshot(prefix="lf164_asistente_").result(timeout=10)

            evaluate(f"window.location.href = '/odoo/action-{action}'")
            wait('document.querySelector(".o_list_view")')
            wait('document.querySelector(".lf_add_client_order")')

            # Agrupar por Empresa cliente, como en la captura del operador.
            def open_search_menu():
                if evaluate('!!document.querySelector(".o_searchview_dropdown_toggler")'):
                    pointer(".o_searchview_dropdown_toggler")
                elif evaluate('!!document.querySelector(".o_searchview .o-dropdown")'):
                    pointer(".o_searchview .o-dropdown")
            open_search_menu()
            wait(
                '[...document.querySelectorAll("span,button,a")].some('
                'e => (e.textContent || "").trim() === "Empresa cliente")'
            )
            evaluate('''(() => {
                const items = [...document.querySelectorAll("span,button,a")].filter(
                    e => (e.textContent || "").trim() === "Empresa cliente");
                const item = items[items.length - 1];
                item.scrollIntoView({block: "center"});
                item.click();
            })()''')
            wait('document.querySelector(".o_list_table_grouped, .o_list_view .o_group_name")')
            wait('document.querySelector(".lf_add_client_order")')
            self.assertIn(
                "Nuevo pedido",
                evaluate('document.querySelector(".lf_add_client_order")?.textContent || ""'),
            )
            self.assertFalse(evaluate(
                '!![...document.querySelectorAll(".o_list_group_add")].find('
                'e => (e.textContent || "").includes("Agrega Empresa")'
                ' || (e.textContent || "").includes("Add a "))'
            ))
            browser.take_screenshot(prefix="lf164_hoy_agrupado_").result(timeout=10)
            pointer(".lf_add_client_order")
            wait('document.body.textContent.includes("Crear pedidos de empleados")')

        self._employee_pointer_journey(
            f"/odoo/action-{action}", journey, width=1366, login=self.operator.login,
        )
