#!/bin/bash
# Point msb_lafija_quick_checkout at kai_viandas (do not rename that module).
# Usage: patch_msb_lafija_quick_checkout.sh /path/to/msb_lafija_quick_checkout
set -euo pipefail
DIR=${1:?path to msb_lafija_quick_checkout}
python3 - "$DIR" << 'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for path in root.rglob("*"):
    if not path.is_file() or path.suffix not in {".py", ".xml", ".md", ".csv"}:
        continue
    if "__pycache__" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    text2 = text.replace("msb_lafija_quick_checkout", "MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER")
    text2 = text2.replace("msb_lafija", "kai_viandas")
    text2 = text2.replace("MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER", "msb_lafija_quick_checkout")
    if text2 != text:
        path.write_text(text2, encoding="utf-8")
        print("patched", path)
PY
