"""Catalog retrieval picks by the customer's words, not by list position."""
import json
import unittest

from test_engine import ENGINE_PATH, engine


def _row(product_id, name, code="", price=10.0, pack_units=None):
    row = {
        "id": product_id, "name": name, "code": code, "uom_id": 1, "uom_name": "Units",
        "price": price, "currency": "ARS", "free_qty": 3, "company_id": 1, "sale_ok": True,
    }
    if pack_units:
        row["pack_units"] = pack_units
    return row


def _shelf():
    rows = [_row(index, f"PRODUCTO {index}", code=str(10000 + index)) for index in range(1, 261)]
    rows[108] = _row(20005, "FRASCO AMANECER 63 X 360 CC", code="20005", price=1550.0)
    rows.append(_row(20006, "PACK AMANECER 360 X 12", code="20006", price=17000.0, pack_units=12))
    return rows


class RetrievalTests(unittest.TestCase):
    def test_amanecer_360_is_not_cut_off_before_the_price(self):
        rows = _shelf()
        self.assertEqual(rows[108]["id"], 20005)
        self.assertNotIn(20005, [row["id"] for row in engine.public_catalog(rows, 1)])
        question = "a que precio tienen el amanecer 360?"
        chosen = engine.relevant_catalog(rows, 1, question, limit=40)
        self.assertIn(20005, [row["id"] for row in chosen])
        self.assertLessEqual(len(chosen), 40)
        self.assertEqual(chosen[0]["id"], 20005)
        catalog = engine.public_catalog(rows, 1, limit=300)
        decision = engine.interpret(
            json.dumps({"intent": "catalog", "ask": "price", "lines": [{"raw": "amanecer 360"}]}),
            context=[{"direction": "customer", "body": question}],
            catalog=catalog,
            faqs=[],
        )
        self.assertEqual(decision["lines"][0]["product_id"], 20005)
        self.assertEqual(decision["lines"][0]["price"], 1550.0)
        self.assertEqual(decision["lines"][0]["status"], "matched")
        self.assertIn("1550", decision["reply"])
        self.assertIn("PACK AMANECER 360 X 12", decision["reply"])
        by_code = engine.interpret(
            json.dumps({"intent": "catalog", "ask": "price", "lines": [{"code": "20005"}]}),
            context=[{"direction": "customer", "body": "20005"}],
            catalog=catalog,
            faqs=[],
        )
        self.assertEqual(by_code["lines"][0]["product_id"], 20005)

    def test_two_units_stay_ambiguous_and_exact_names_do_too(self):
        twins = engine.public_catalog([
            _row(1, "FRASCO AMANECER 360"),
            _row(2, "FRASCO AMANECER 360 CC"),
        ], 1, limit=10)
        fuzzy = engine.interpret(
            json.dumps({"intent": "catalog", "lines": [{"raw": "amanecer 360"}]}),
            context=[{"direction": "customer", "body": "amanecer 360"}],
            catalog=twins,
            faqs=[],
        )
        self.assertEqual(fuzzy["lines"][0]["status"], "ambiguous")
        same = engine.public_catalog([
            _row(1, "Arroz", code="A"),
            _row(2, "Arroz", code="B"),
        ], 1, limit=10)
        exact = engine.interpret(
            json.dumps({"intent": "order", "lines": [{"raw": "Arroz", "quantity": 1}]}),
            context=[{"direction": "customer", "body": "Arroz"}],
            catalog=same,
            faqs=[],
        )
        self.assertEqual(exact["lines"][0]["status"], "ambiguous")

    def test_prompt_uses_the_ranked_catalog(self):
        suggestion = (ENGINE_PATH.parents[1] / "models" / "ai_suggestion.py").read_text(encoding="utf-8")
        self.assertIn("relevant_catalog", suggestion)
        config = (ENGINE_PATH.parents[1] / "models" / "ai_config.py").read_text(encoding="utf-8")
        self.assertIn("catalog_limit = fields.Integer", config)
        self.assertIn("default=40", config.split("catalog_limit", 1)[1][:180])


if __name__ == "__main__":
    unittest.main()
