"""Allowlist gate and the 19.0.1.8.0 upgrade. No Odoo runtime."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "services" / "engine.py"
SPEC = importlib.util.spec_from_file_location("kai_whatsapp_ai_engine_allow", ENGINE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

MIGRATION = ROOT / "migrations" / "19.0.1.8.0" / "post-migrate.py"


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))


def _load_migration():
    spec = importlib.util.spec_from_file_location("kai_whatsapp_ai_migrate_180", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AllowlistGateTests(unittest.TestCase):
    def test_unknown_number_does_not_reach_the_provider(self):
        listed = ["+54 9 11 5555-0001"]
        self.assertEqual(engine.customer_message_plan(
            number="5491155550002", allowlist=listed, restrict=True, auto_reply=True,
        ), "no_provider")
        self.assertFalse(engine.customer_reaches_provider("5491155550002", listed, True))

    def test_allowlisted_with_auto_reply_is_sent(self):
        listed = ["11 5555 0001"]
        self.assertEqual(engine.normalize_e164("11 5555 0001"), "+1155550001")
        self.assertEqual(engine.customer_message_plan(
            number="+1155550001", allowlist=listed, restrict=True, auto_reply=True,
            reply_text="Para miel, la tapa TO.",
        ), "sent")

    def test_allowlisted_without_auto_reply_stays_a_suggestion(self):
        listed = ["+1155550001"]
        self.assertEqual(engine.customer_message_plan(
            number="+1155550001", allowlist=listed, restrict=True, auto_reply=False,
        ), "suggestion")
        self.assertFalse(engine.should_auto_reply_customer(
            auto_reply=False, number="+1155550001", allowlist=listed,
            generation_state="done", reply_text="Listo.", already_sent=False,
        ))

    def test_empty_list_does_not_block_and_failure_is_not_sent(self):
        self.assertEqual(engine.customer_message_plan(
            number="+1155550002", allowlist=[], restrict=True, auto_reply=True,
        ), "suggestion")
        self.assertFalse(engine.should_auto_reply_customer(
            auto_reply=True, number="+1155550001", allowlist=["+1155550001"],
            generation_state="done", reply_text=engine.PUBLIC_FAILURE, already_sent=False,
        ))

    def test_trainer_number_stays_on_the_training_path(self):
        self.assertEqual(engine.customer_message_plan(
            number="+1155550001", allowlist=["+1155550001"], restrict=True, auto_reply=True,
            trainer_numbers=["+1155550001"],
        ), "training")

    def test_upgrade_rewrites_the_retired_model_and_does_not_enable_auto_reply(self):
        manifest = (ROOT / "__manifest__.py").read_text(encoding="utf-8")
        self.assertIn("'version': '19.0.1.11.0'", manifest)
        self.assertEqual(MIGRATION.parent.name, "19.0.1.8.0")
        migration = _load_migration()
        self.assertEqual(migration.OLD_MODEL, "gemini-2.5-flash-lite")
        self.assertEqual(migration.NEW_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(engine.GEMINI_FLASH_LITE_MODEL, migration.NEW_MODEL)
        cursor = _Cursor()
        migration.migrate(cursor, "19.0.1.7.0")
        query, params = cursor.calls[0]
        self.assertIn("kai_whatsapp_ai_config", query)
        self.assertNotIn("auto_reply_customers", query)
        self.assertEqual(params, (migration.NEW_MODEL, migration.OLD_MODEL))
        config = (ROOT / "models" / "ai_config.py").read_text(encoding="utf-8")
        self.assertIn("auto_reply_customers = fields.Boolean", config)
        self.assertIn("default=False", config.split("auto_reply_customers", 1)[1][:180])
        self.assertIn("restrict_to_allowlist = fields.Boolean", config)
        self.assertIn("default=True", config.split("restrict_to_allowlist", 1)[1][:220])
        access = (ROOT / "security" / "ir.model.access.csv").read_text(encoding="utf-8")
        allow_rows = [row for row in access.splitlines() if "model_kai_whatsapp_ai_allow" in row]
        self.assertEqual(len(allow_rows), 1)
        self.assertIn("group_manager", allow_rows[0])
        self.assertNotIn("group_trainer", allow_rows[0])
        menu = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        self.assertIn('id="menu_kai_whatsapp_ai_usage" model="ir.ui.menu"', menu)
        self.assertIn("Command.set([ref('group_manager')])", menu)


if __name__ == "__main__":
    unittest.main()
