"""Admin restrictions outrank trainer rules and stay unread by the trainer."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "services" / "engine.py"
SPEC = importlib.util.spec_from_file_location("kai_whatsapp_ai_engine_restrictions", ENGINE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

REPLY = engine.DEFAULT_RESTRICTION_REPLY


def _rows():
    return [
        {
            "id": 1,
            "name": "Uso de Odoo",
            "audience": "trainer",
            "description": "No responder preguntas sobre cómo usar Odoo, menús, configuración o soporte del sistema.",
            "reply_text": REPLY,
            "active": True,
            "sequence": 10,
            "company_id": 1,
        },
        {
            "id": 2,
            "name": "Desarrollo de software",
            "audience": "trainer",
            "description": "No escribir código, ni desarrollar o modificar módulos, scripts o integraciones.",
            "reply_text": REPLY,
            "active": True,
            "sequence": 20,
            "company_id": 1,
        },
        {
            "id": 3,
            "name": "Costos internos",
            "audience": "customer",
            "description": "No informar el costo interno ni el margen.",
            "reply_text": "Eso lo ve una persona de la empresa.",
            "active": True,
            "sequence": 30,
            "company_id": 1,
        },
        {
            "id": 4,
            "name": "Proveedor",
            "audience": "both",
            "description": "No nombrar al proveedor ni una clave.",
            "reply_text": "Eso no lo puedo decir.",
            "active": True,
            "sequence": 5,
            "company_id": 1,
        },
        {
            "id": 5,
            "name": "Inactiva",
            "audience": "trainer",
            "description": "No hablar de odoo aunque esté inactiva.",
            "reply_text": "No.",
            "active": False,
            "sequence": 1,
            "company_id": 1,
        },
        {
            "id": 6,
            "name": "Otra compañía",
            "audience": "both",
            "description": "No mezclar compañías.",
            "reply_text": "No.",
            "active": True,
            "sequence": 1,
            "company_id": 9,
        },
    ]


class RestrictionPromptTests(unittest.TestCase):
    def test_audience_filter_and_priority_in_each_prompt(self):
        rows = _rows()
        customer = engine.active_restrictions(rows, "customer", company_id=1)
        trainer = engine.active_restrictions(rows, "trainer", company_id=1)
        self.assertEqual([row["name"] for row in customer], ["Proveedor", "Costos internos"])
        self.assertEqual([row["name"] for row in trainer], ["Proveedor", "Uso de Odoo", "Desarrollo de software"])

        customer_prompt = engine.build_messages(
            [{"direction": "customer", "body": "precio del frasco"}],
            [],
            [],
            preferences=[{"id": 8, "scope": "global", "title": "Tono", "body": "Hablá de vos."}],
            restrictions=customer,
        )[0]["content"]
        self.assertLess(customer_prompt.index("Mandatory restrictions"), customer_prompt.index("You classify"))
        self.assertLess(customer_prompt.index("Proveedor"), customer_prompt.index("Costos internos"))
        self.assertLess(customer_prompt.index("Highest priority"), customer_prompt.index("lowest authority"))
        self.assertIn("override operator preferences", customer_prompt)
        self.assertNotIn("Uso de Odoo", customer_prompt)
        self.assertNotIn("Desarrollo de software", customer_prompt)
        self.assertNotIn("Inactiva", customer_prompt)
        self.assertIn("do not quote the forbidden-topic text", customer_prompt)
        self.assertIn("do not name the external provider", customer_prompt)

        trainer_prompt = engine.build_training_messages(
            [{"role": "trainer", "body": "tuteá"}],
            [{"name": "Tapa TO", "code": "T63"}],
            [{"id": 3, "title": "Tono", "state": "activa"}],
            trainer,
        )[0]["content"]
        self.assertLess(trainer_prompt.index("Mandatory restrictions"), trainer_prompt.index("You help a business owner"))
        self.assertLess(trainer_prompt.index("Proveedor"), trainer_prompt.index("Uso de Odoo"))
        self.assertLess(trainer_prompt.index("Uso de Odoo"), trainer_prompt.index("Desarrollo de software"))
        self.assertNotIn("Costos internos", trainer_prompt)
        self.assertNotIn("Inactiva", trainer_prompt)
        self.assertNotIn("untrusted_customer_messages", engine.build_training_messages(
            [{"role": "trainer", "body": "tuteá"}], [], [], trainer,
        )[1]["content"])

    def test_empty_restrictions_leave_the_prompt_unchanged(self):
        bare = engine.build_messages([{"direction": "customer", "body": "hola"}], [], [])
        self.assertTrue(bare[0]["content"].startswith("You classify"))
        self.assertNotIn("Mandatory restrictions", bare[0]["content"])

    def test_trainer_request_is_refused_and_not_stored_as_a_proposal(self):
        trainer = engine.active_restrictions(_rows(), "trainer", company_id=1)
        self.assertEqual(engine.restriction_for_text(
            "quiero que le haga preguntas al agente sobre el uso del odoo", trainer,
        )["name"], "Uso de Odoo")
        self.assertEqual(engine.restriction_for_text(
            "desarrollame un modulo de stock", trainer,
        )["name"], "Desarrollo de software")
        self.assertIsNone(engine.restriction_for_text("precio del frasco amanecer 360", trainer))
        self.assertIsNone(engine.restriction_for_text("sistema de cierre para la tapa", trainer))

        parsed = engine.parse_training_reply(json.dumps({
            "reply": "Puedo explicarte los menús de Odoo y dejarte la regla.",
            "proposals": [{
                "title": "Uso de Odoo",
                "body": "Cuando pregunten cómo usar Odoo, explicá los menús y la configuración.",
                "scope": "global",
            }],
        }), trainer)
        self.assertTrue(parsed["refused"])
        self.assertEqual(parsed["proposals"], [])
        self.assertEqual(parsed["reply"], REPLY)
        self.assertNotIn("menús", parsed["reply"].casefold())
        self.assertNotIn("odoo", parsed["reply"].casefold())

    def test_seed_and_access_are_admin_only(self):
        names = [item["name"] for item in engine.SEED_RESTRICTIONS]
        self.assertEqual(names, ["Uso de Odoo", "Desarrollo de software"])
        self.assertTrue(all(item["audience"] == "trainer" for item in engine.SEED_RESTRICTIONS))
        self.assertTrue(all(item["reply_text"] == REPLY for item in engine.SEED_RESTRICTIONS))
        self.assertEqual(engine.SEED_COMPANY_NAME, "00IA")
        access = (ROOT / "security" / "ir.model.access.csv").read_text(encoding="utf-8").splitlines()
        restriction_rows = [row for row in access if "model_kai_whatsapp_ai_restriction" in row]
        self.assertEqual(len(restriction_rows), 1)
        self.assertIn("base.group_system,1,1,1,1", restriction_rows[0])
        self.assertNotIn("group_trainer", restriction_rows[0])
        self.assertNotIn("group_user", restriction_rows[0])
        self.assertNotIn("group_manager", restriction_rows[0])
        menu = (ROOT / "views" / "menu.xml").read_text(encoding="utf-8")
        self.assertIn('id="menu_kai_whatsapp_ai_restrictions"', menu)
        self.assertIn('name="Restricciones"', menu)
        self.assertIn('parent="om_whatsapp_base.om_whatsapp_menu_config"', menu)
        self.assertIn('groups="base.group_system"', menu)
        seed = (ROOT / "models" / "ai_restriction.py").read_text(encoding="utf-8")
        self.assertIn("noupdate", seed)
        self.assertIn("SEED_COMPANY_NAME", (ROOT / "hooks.py").read_text(encoding="utf-8") + seed)
        migration = (ROOT / "migrations" / "19.0.1.17.0" / "post-migrate.py").read_text(encoding="utf-8")
        self.assertIn("seed_restrictions", migration)


if __name__ == "__main__":
    unittest.main()
