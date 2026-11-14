"""IA Agent 19.0.1.11.0: branding, cost group, day totals, messages, product sheet."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


class Release111Tests(unittest.TestCase):
    def test_app_name_is_ia_agent(self):
        manifest = (ROOT / "__manifest__.py").read_text(encoding="utf-8")
        menu = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        self.assertIn("'name': 'IA Agent'", manifest)
        self.assertIn("'version': '19.0.1.11.0'", manifest)
        self.assertIn('<field name="name">IA Agent</field>', menu)
        hooks = (ROOT / "hooks.py").read_text(encoding="utf-8")
        self.assertIn("admin@kaizendo.com.ar", hooks)
        self.assertNotIn("uid", hooks)

    def test_cost_viewer_is_not_implied_and_owns_provider_cost(self):
        groups = (ROOT / "security" / "groups.xml").read_text(encoding="utf-8")
        self.assertIn('id="group_cost_viewer"', groups)
        self.assertNotIn("group_cost_viewer", groups.split('id="group_cost_viewer"', 1)[0])
        access = (ROOT / "security" / "ir.model.access.csv").read_text(encoding="utf-8")
        call_rows = [row for row in access.splitlines() if "model_kai_whatsapp_ai_call" in row]
        rate_rows = [row for row in access.splitlines() if "model_kai_whatsapp_ai_provider_rate" in row]
        self.assertEqual(len(call_rows), 1)
        self.assertIn("group_cost_viewer", call_rows[0])
        self.assertNotIn("group_manager", call_rows[0])
        self.assertNotIn("group_trainer", call_rows[0])
        self.assertTrue(all("group_cost_viewer" in row for row in rate_rows))
        self.assertFalse(any("group_manager" in row or "group_trainer" in row for row in rate_rows))
        usage = (ROOT / "models" / "ai_usage.py").read_text(encoding="utf-8")
        cost = usage[usage.index("cost_usd = fields."):usage.index("cost_usd = fields.") + 240]
        self.assertIn("group_cost_viewer", cost)
        self.assertNotIn("group_manager", cost)
        views = (ROOT / "views" / "ai_usage_views.xml").read_text(encoding="utf-8")
        self.assertIn('name="group_day"', views)
        self.assertIn("occurred_at:day", views)
        self.assertIn("search_default_group_day", views)
        self.assertIn('sum="Total del día"', views)
        self.assertIn('sum="Consultas"', views)
        self.assertIn('sum="Costo USD"', views)
        self.assertIn('name="provider_cost_usd"', views)
        self.assertIn('name="billable_currency_id" column_invisible="1"', views)
        self.assertNotIn('name="billable_known"', views)
        menu = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        calls = menu[menu.index('id="menu_kai_whatsapp_ai_calls"'):]
        self.assertIn('groups="group_cost_viewer"', calls[:400])

    def test_messages_menu_replaces_the_two_logs(self):
        menu = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        self.assertIn('id="menu_kai_whatsapp_ai_messages" name="Mensajes"', menu)
        self.assertIn("group_trainer", menu[menu.index("menu_kai_whatsapp_ai_messages"):menu.index("menu_kai_whatsapp_ai_messages") + 400])
        self.assertIn("base.group_no_one", menu)
        self.assertIn("<field name=\"active\" eval=\"False\"/>", menu)
        self.assertIn("Mensajes sin IA", menu)
        form = (ROOT / "views" / "ai_suggestion_views.xml").read_text(encoding="utf-8")
        self.assertIn("Enviar respuesta", form)
        self.assertIn("Descartar", form)
        self.assertIn("Enviar de nuevo", form)
        self.assertIn("action_retry_whatsapp", form)
        self.assertIn("delivery_status", form)
        self.assertNotIn("cost_usd", form)
        suggestion = (ROOT / "models" / "ai_suggestion.py").read_text(encoding="utf-8")
        self.assertIn("action_om_whatsapp_retry", suggestion)
        self.assertIn("WhatsApp no está vinculado", suggestion)

    def test_sheets_leave_the_top_bar_for_the_product(self):
        menu = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        specs = menu[menu.index('id="menu_kai_whatsapp_ai_specs"'):menu.index('id="menu_kai_whatsapp_ai_specs"') + 220]
        self.assertIn('parent="sale.product_menu_catalog"', specs)
        self.assertIn("Fichas técnicas", specs)
        page = (ROOT / "views" / "product_template_views.xml").read_text(encoding="utf-8")
        self.assertIn('string="Ficha técnica"', page)
        self.assertIn("action_kai_ensure_spec", page)
        self.assertIn("kai_fit_ids", page)
        bridge = (REPO / "kai_whatsapp_ai_stock" / "__manifest__.py").read_text(encoding="utf-8")
        self.assertIn("'auto_install': True", bridge)
        self.assertIn("'stock'", bridge)
        moved = (REPO / "kai_whatsapp_ai_stock" / "views" / "menu.xml").read_text(encoding="utf-8")
        self.assertIn("stock.menu_stock_inventory_control", moved)


if __name__ == "__main__":
    unittest.main()
