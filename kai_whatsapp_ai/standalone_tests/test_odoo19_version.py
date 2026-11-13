"""Odoo 19 rejects a module version that adapt_version cannot place in the 19.0 series.

``1.1`` is rewritten to ``19.0.1.1``. ``1.1.0.1`` has four parts, is left as-is,
fails the series check and the module is marked uninstallable. The translation
bump has to be ``19.0.1.1.1``, which is valid and newer than the installed one.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIE = "19.0"


def adapt_version(version):
    """Same rule as odoo/modules/module.py adapt_version on series 19.0."""
    version_str_parts = version.split(".")
    if not (2 <= len(version_str_parts) <= 5):
        raise ValueError(f"Invalid version {version!r}, must have between 2 and 5 parts")
    if version.startswith(SERIE) and not version_str_parts[0].isdigit():
        version_str_parts[0] = "".join(c for c in version_str_parts[0] if c.isdigit())
    version_parts = [int(v) for v in version_str_parts]
    if len(version_parts) <= 3 and not version.startswith(SERIE):
        return f"{SERIE}.{version}"
    return version


def version_is_accepted(version):
    """Same rule as check_version: after adaptation it must start with ``19.0.``."""
    try:
        adapted = adapt_version(version)
    except ValueError:
        return False
    return adapted.startswith(SERIE + ".")


def parse_version(version):
    """Same ordering as odoo/tools/parse_version.py. A trailing ``.0`` is not newer."""
    import re
    component_re = re.compile(r"(\d+|[a-z]+|\.|-)")
    replace = {"pre": "c", "preview": "c", "-": "final-", "_": "final-", "rc": "c", "dev": "@", "saas": "", "~": ""}.get
    parts = []
    for part in component_re.split((version or "0.1").lower()):
        part = replace(part, part)
        if not part or part == ".":
            continue
        parts.append(part.zfill(8) if part[:1] in "0123456789" else "*" + part)
    parts.append("*final")
    cleaned = []
    for part in parts:
        if part.startswith("*"):
            if part < "*final":
                while cleaned and cleaned[-1] == "*final-":
                    cleaned.pop()
            while cleaned and cleaned[-1] == "00000000":
                cleaned.pop()
        cleaned.append(part)
    return tuple(cleaned)


def manifest_version(module):
    text = (ROOT / module / "__manifest__.py").read_text(encoding="utf-8")
    return ast.literal_eval(text)["version"]


class Odoo19VersionTests(unittest.TestCase):
    def test_four_part_upstream_style_is_rejected(self):
        self.assertEqual(adapt_version("1.1"), "19.0.1.1")
        self.assertTrue(version_is_accepted("1.1"))
        self.assertEqual(adapt_version("1.1.0.1"), "1.1.0.1")
        self.assertFalse(version_is_accepted("1.1.0.1"))

    def test_connector_translation_bump_is_installable_and_newer(self):
        version = manifest_version("om_whatsapp_base")
        self.assertEqual(version, "19.0.1.1.1")
        self.assertTrue(version_is_accepted(version))
        self.assertEqual(adapt_version(version), "19.0.1.1.1")
        installed = adapt_version("1.1")
        self.assertEqual(installed, "19.0.1.1")
        self.assertGreater(parse_version(version), parse_version(installed))

    def test_kai_version_stays_on_the_series(self):
        version = manifest_version("kai_whatsapp_ai")
        self.assertEqual(version, "19.0.1.8.0")
        self.assertTrue(version_is_accepted(version))


if __name__ == "__main__":
    unittest.main()
