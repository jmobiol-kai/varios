"""The trainer group can teach the assistant and cannot see the provider or its cost."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _record(xml, record_id):
    match = re.search(
        rf'<record id="{record_id}"[\s\S]*?</record>',
        xml,
    )
    if not match:
        raise AssertionError(record_id)
    return match.group(0)


class TrainerAccessTests(unittest.TestCase):
    def test_trainer_group_does_not_inherit_whatsapp_or_module_user(self):
        xml = (ROOT / "security" / "groups.xml").read_text(encoding="utf-8")
        trainer = _record(xml, "group_trainer")
        manager = _record(xml, "group_manager")
        self.assertIn("base.group_user", trainer)
        self.assertNotIn("group_om_whatsapp_user", trainer)
        self.assertNotIn("ref('group_user')", trainer)
        self.assertIn("ref('group_trainer')", manager)
        self.assertIn("ref('group_user')", manager)

    def test_usage_menus_are_manager_only(self):
        xml = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        for menu_id in ("menu_kai_whatsapp_ai_usage", "menu_kai_whatsapp_ai_usage_wizard"):
            menu = re.search(rf'id="{menu_id}"[\s\S]*?groups="([^"]+)"', xml)
            self.assertIsNotNone(menu, menu_id)
            self.assertEqual(menu.group(1), "group_manager")
        self.assertIn("om_whatsapp_base.om_whatsapp_menu_messages", xml)
        self.assertIn("group_om_whatsapp_user", xml)

    def test_config_is_not_readable_by_trainer_or_user(self):
        rows = (ROOT / "security" / "ir.model.access.csv").read_text(encoding="utf-8").splitlines()
        config_rows = [row for row in rows if "model_kai_whatsapp_ai_config" in row]
        self.assertTrue(config_rows)
        for row in config_rows:
            self.assertNotIn("group_user", row)
            self.assertNotIn("group_trainer", row)
            self.assertIn("group_manager", row)

    def test_sensitive_fields_are_manager_only(self):
        usage = (ROOT / "models" / "ai_usage.py").read_text(encoding="utf-8")
        for name in ("billable_amount", "billable_known", "billable_currency_id", "billable_rate_id"):
            start = usage.index(f"{name} = fields.")
            self.assertIn("groups='kai_whatsapp_ai.group_manager'", usage[start:start + 280], name)
        suggestion = (ROOT / "models" / "ai_suggestion.py").read_text(encoding="utf-8")
        training = (ROOT / "models" / "ai_training.py").read_text(encoding="utf-8")
        for source in (suggestion, training):
            field = re.search(r"provider_error = fields\.Char\((?:.|\n)*?\)", source)
            self.assertIsNotNone(field)
            self.assertIn("groups='kai_whatsapp_ai.group_manager'", field.group(0))
        views = (ROOT / "views" / "ai_suggestion_views.xml").read_text(encoding="utf-8")
        self.assertIn('name="provider_error"', views)
        self.assertIn('groups="kai_whatsapp_ai.group_manager"', views)
        self.assertIn("customer_visible_text", suggestion)
        self.assertIn("PUBLIC_FAILURE", training)
        self.assertNotIn("gemini", (ROOT / "services" / "engine.py").read_text(encoding="utf-8").split("PUBLIC_FAILURE = ", 1)[1].split("\n", 1)[0].casefold())


if __name__ == "__main__":
    unittest.main()
