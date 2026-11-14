"""Inbound privacy, blocked numbers, automatic send user, and delete actions."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "services" / "engine.py"
SPEC = importlib.util.spec_from_file_location("kai_whatsapp_ai_engine_privacy", ENGINE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

MIGRATION = ROOT / "migrations" / "19.0.1.9.0" / "post-migrate.py"


class _Cursor:
    def __init__(self, param=None, accounts=()):
        self.param = param
        self.accounts = list(accounts)
        self.calls = []
        self._query = ""

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))
        self._query = query

    def fetchone(self):
        if "ir_config_parameter" in self._query:
            return (self.param,) if self.param is not None else None
        if "kai_whatsapp_ai_inbound" in self._query and "SELECT" in self._query:
            return None
        return None

    def fetchall(self):
        if "om_whatsapp_account" in self._query:
            return list(self.accounts)
        return []


def _load_migration():
    spec = importlib.util.spec_from_file_location("kai_whatsapp_ai_migrate_190", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivacyTests(unittest.TestCase):
    def test_blocked_number_is_not_processed_even_without_the_allowlist(self):
        self.assertEqual(engine.customer_message_plan(
            number="+1155550009", allowlist=[], restrict=False, auto_reply=True,
            blocked=["+1155550009"], block_enabled=True,
        ), "blocked")
        self.assertEqual(engine.customer_message_plan(
            number="+1155550009", allowlist=[], restrict=False, auto_reply=True,
            blocked=["+1155550009"], block_enabled=False,
        ), "suggestion")

    def test_receive_list_drops_other_inbound_numbers(self):
        self.assertTrue(engine.inbound_kept("+1155550002", []))
        self.assertTrue(engine.inbound_kept("+54 9 11 5555-0001", ["+5491155550001"]))
        self.assertFalse(engine.inbound_kept("+5491155550002", ["+5491155550001"]))
        receive = (ROOT / "models" / "om_whatsapp_account.py").read_text(encoding="utf-8")
        gate = receive.split("def _om_whatsapp_receive", 1)[1].split("super()._om_whatsapp_receive", 1)[0]
        self.assertIn("if not from_me", gate)
        self.assertIn("inbound_kept", gate)

    def test_automatic_send_uses_an_account_user(self):
        self.assertEqual(engine.choose_send_user(
            configured_id=2, configured_active=True, configured_allowed=True, member_ids=[2, 5],
        ), 2)
        self.assertEqual(engine.choose_send_user(
            configured_id=9, configured_active=True, configured_allowed=False, member_ids=[5],
        ), 5)
        self.assertIsNone(engine.choose_send_user(
            configured_id=False, configured_active=False, configured_allowed=False, member_ids=[],
        ))
        deliver = (ROOT / "models" / "ai_suggestion.py").read_text(encoding="utf-8")
        body = deliver.split("def _deliver_reply", 1)[1].split("def _auto_send_user", 1)[0]
        self.assertIn("with_user", body)
        self.assertIn("if automatic", body)

    def test_delete_actions_stay_in_odoo_and_keep_the_contact(self):
        message = (ROOT / "models" / "mail_message.py").read_text(encoding="utf-8")
        channel = (ROOT / "models" / "discuss_channel.py").read_text(encoding="utf-8")
        script = (ROOT / "static" / "src" / "discuss" / "delete_actions.js").read_text(encoding="utf-8")
        self.assertIn("def action_om_whatsapp_delete_in_odoo", message)
        self.assertNotIn("update_content(", message.split("def action_om_whatsapp_delete_in_odoo", 1)[1])
        self.assertIn("def action_om_whatsapp_delete_conversation", channel)
        self.assertLess(channel.index("kai.whatsapp.ai.suggestion"), channel.index("channel.sudo().unlink()"))
        self.assertNotIn("res.partner').sudo().browse(partner_id).unlink", channel)
        self.assertNotIn("om.whatsapp.account').sudo().browse(account_id).unlink", channel)
        self.assertIn("solo en Odoo", script)
        self.assertIn("teléfono del cliente", script)
        self.assertIn("message_type === \"om_whatsapp\"", script)
        self.assertIn("channel_type === \"om_whatsapp\"", script)
        self.assertIn("group_om_whatsapp_manager", script)
        self.assertIn("user.isSystem", script)

    def test_upgrade_copies_the_inbound_parameter_and_leaves_auto_reply_off(self):
        self.assertEqual(MIGRATION.parent.name, "19.0.1.9.0")
        migration = _load_migration()
        self.assertEqual(migration.INBOUND_PARAM, "om_whatsapp.inbound_allowlist")
        self.assertEqual(
            migration.inbound_numbers_from_parameter("+54 9 11 5555-0001, +5491155550002"),
            ["+5491155550001", "+5491155550002"],
        )
        empty = _Cursor(param="  ")
        migration.migrate(empty, "19.0.1.8.0")
        self.assertEqual(len(empty.calls), 1)
        filled = _Cursor(param="+5491155550001", accounts=[(4, 1)])
        migration.migrate(filled, "19.0.1.8.0")
        joined = "\n".join(query for query, _params in filled.calls)
        self.assertIn("INSERT INTO kai_whatsapp_ai_inbound", joined)
        self.assertNotIn("auto_reply_customers", joined)
        self.assertNotIn("DELETE FROM ir_config_parameter", joined)
        config = (ROOT / "models" / "ai_config.py").read_text(encoding="utf-8")
        self.assertIn("block_numbers = fields.Boolean", config)
        self.assertIn("default=False", config.split("block_numbers", 1)[1][:180])


if __name__ == "__main__":
    unittest.main()
