"""Spanish catalogs for the WhatsApp menus. No Odoo runtime."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_po(path):
    text = path.read_text(encoding="utf-8")
    entries = {}
    for block in re.split(r"\n\n", text.strip()):
        match = re.search(r'^msgid "(.*)"$', block, re.M)
        if not match or match.group(1) == "":
            continue
        msgid = match.group(1)
        msgstr = re.search(r'^msgstr "(.*)"$', block, re.M).group(1)
        comment = re.search(r"^#\. (.+)$", block, re.M)
        occurrences = re.findall(r"^#: (.+)$", block, re.M)
        entries[msgid] = {
            "msgstr": msgstr,
            "comment": comment.group(1) if comment else "",
            "occurrences": occurrences,
        }
    return entries


class SpanishCatalogTests(unittest.TestCase):
    def test_screenshot_labels_and_structure(self):
        kai = load_po(ROOT / "kai_whatsapp_ai" / "i18n" / "es.po")
        base = load_po(ROOT / "om_whatsapp_base" / "i18n" / "es.po")
        self.assertIn('"Language: es\\n"', (ROOT / "kai_whatsapp_ai" / "i18n" / "es.po").read_text(encoding="utf-8"))
        expected = [
            (kai, {
                "AI Suggestions": "Sugerencias de IA",
                "Usage summary": "Resumen de uso",
                "Product sheets": "Fichas de producto",
                "Activity guide": "Guía de actividades",
                "Jar and closure fit": "Compatibilidad de envases y tapas",
                "AI Provider": "Proveedor de IA",
                "Monthly usage": "Uso mensual",
            }),
            (base, {
                "Messages": "Mensajes",
                "Templates": "Plantillas",
                "Configuration": "Configuración",
                "Accounts": "Cuentas",
                "Document": "Documento",
                "Message": "Mensaje",
                "WhatsApp Status": "Estado de WhatsApp",
                "WhatsApp Messages": "Mensajes de WhatsApp",
                "Received": "Recibido",
                "Queued": "En cola",
            }),
        ]
        for catalog, pairs in expected:
            for src, dst in pairs.items():
                self.assertEqual(catalog[src]["msgstr"], dst)
                self.assertTrue(catalog[src]["occurrences"])
                self.assertTrue(catalog[src]["comment"].startswith("module:"))
        for kept in ("Reglas del agente", "Respuestas al entrenador", "Entrenadores"):
            self.assertNotIn(kept, kai)
            self.assertNotIn(kept, base)
        menu = (ROOT / "kai_whatsapp_ai" / "views" / "menu.xml").read_text(encoding="utf-8")
        self.assertIn('name="Reglas del agente"', menu)
        self.assertIn('name="Respuestas al entrenador"', menu)
        manifest = (ROOT / "kai_whatsapp_ai" / "__manifest__.py").read_text(encoding="utf-8")
        self.assertIn("'version': '19.0.1.5.0'", manifest)
        base_manifest = (ROOT / "om_whatsapp_base" / "__manifest__.py").read_text(encoding="utf-8")
        self.assertIn("'version': '19.0.1.1.1'", base_manifest)


if __name__ == "__main__":
    unittest.main()
