"""Enlace Agregar pedido de cliente en Hoy · 19.0.1.16.5."""
from odoo.tests import tagged

from .test_pages import PagesCommon
from .test_release_114 import TestRelease114
from .test_release_160 import TestRelease160
from .test_release_182 import TestBrowser182
from .test_release_1164 import TestRelease1164


@tagged("post_install", "-at_install")
class TestRelease1165(TestRelease1164):
    def test_assets_register_the_js_patch_without_template_inherit(self):
        manifest = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(manifest)
        self.assertTrue(manifest.latest_version.startswith("19.0.1.1"), manifest.latest_version)
        arch = self.env.ref("kai_viandas.reservation_list").arch
        self.assertIn('js_class="lf_reservation_list"', arch)
        self.assertIn('group_create="0"', arch)
        self.assertIn("lf-reservations", arch)
        from pathlib import Path
        from odoo.modules.module import get_module_path
        import ast
        module_manifest = ast.literal_eval((Path(get_module_path("kai_viandas")) / "__manifest__.py").read_text())
        backend = module_manifest["assets"]["web.assets_backend"]
        self.assertIn("kai_viandas/static/src/reservation_list.js", backend)
        self.assertNotIn("kai_viandas/static/src/reservation_list.xml", backend)
        self.assertFalse((Path(get_module_path("kai_viandas")) / "static/src/reservation_list.xml").exists())


@tagged("post_install", "-at_install")
class TestBrowser1165(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey
    _backend = TestBrowser182._backend

    def test_hoy_link_opens_wizard_and_never_shows_native_group_input(self):
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
                '!![...document.querySelectorAll(".o_list_group_add, .o_list_footer button, .o_list_footer a")].find('
                'e => /Agrega\\s+Empresa|Add a /i.test(e.textContent || ""))'
            ))
            self.assertFalse(evaluate('!!document.querySelector(".o_list_group_input")'))

            pointer(".lf_add_client_order")
            wait('document.body.textContent.includes("Crear pedidos de empleados")')
            self.assertFalse(evaluate('!!document.querySelector(".o_list_group_input")'))

            evaluate(f"window.location.href = '/odoo/action-{action}'")
            wait('document.querySelector(".o_list_view")')
            wait('document.querySelector(".lf_add_client_order")')

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
            evaluate(
                '(() => {'
                '  const items = [...document.querySelectorAll("span,button,a")].filter('
                '    e => (e.textContent || "").trim() === "Empresa cliente");'
                '  const item = items[items.length - 1];'
                '  item.scrollIntoView({block: "center"});'
                '  item.click();'
                '})()'
            )
            wait('document.querySelector(".o_list_table_grouped, .o_list_view .o_group_name")')
            wait('document.querySelector(".lf_add_client_order")')
            self.assertIn(
                "Nuevo pedido",
                evaluate('document.querySelector(".lf_add_client_order")?.textContent || ""'),
            )
            self.assertFalse(evaluate(
                '!![...document.querySelectorAll(".o_list_group_add, .o_list_footer button, .o_list_footer a")].find('
                'e => /Agrega\\s+Empresa|Add a /i.test(e.textContent || ""))'
            ))
            self.assertFalse(evaluate('!!document.querySelector(".o_list_group_input")'))
            pointer(".lf_add_client_order")
            wait('document.body.textContent.includes("Crear pedidos de empleados")')
            self.assertFalse(evaluate('!!document.querySelector(".o_list_group_input")'))

        self._employee_pointer_journey(
            f"/odoo/action-{action}", journey, width=1366, login=self.operator.login,
        )
