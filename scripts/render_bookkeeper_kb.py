#!/usr/bin/env python3
"""Renders docs/bookkeeper_kb/03-classification-bridge.md from
src/cfo/services/israeli_tax_rules.py (TAX_RULES + VERIFICATION_NEEDED).

The generated block is wrapped in <!-- BEGIN/END GENERATED --> markers and is
byte-identical to `israeli_tax_rules.render_bridge_table_he()` — this is
enforced by tests/test_israeli_tax_rules.py::test_generated_doc_file_matches_current_render.
Do not edit the generated block by hand; re-run this script after any change
to TAX_RULES/VERIFICATION_NEEDED.

    python scripts/render_bookkeeper_kb.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DOC_PATH = ROOT / "docs" / "bookkeeper_kb" / "03-classification-bridge.md"

HEADER = """# גשר סיווג — קטגוריית הוצאה -> כרטיס SUMIT -> מס הכנסה -> מע"מ תשומות

מסמך זה הוא **תמונת-מראה** של `src/cfo/services/israeli_tax_rules.py` —
הטבלה שלמטה (בין `<!-- BEGIN GENERATED -->` ל-`<!-- END GENERATED -->`)
נוצרת אוטומטית ע"י `scripts/render_bookkeeper_kb.py` ואסור לערוך אותה ידנית.
לשינוי כלל — לערוך את `TAX_RULES`/`VERIFICATION_NEEDED` בקוד ואז להריץ מחדש
את הסקריפט. מקור-האמת המשפטי הוא
[01-income-tax-recognition.md](01-income-tax-recognition.md) +
[02-vat-input-deductibility.md](02-vat-input-deductibility.md).

"""


def main() -> None:
    from cfo.services.israeli_tax_rules import render_bridge_table_he

    content = HEADER + render_bridge_table_he() + "\n"
    DOC_PATH.write_text(content, encoding="utf-8")
    print(f"OK: wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
