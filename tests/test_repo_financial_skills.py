"""Repository-level contracts for bundled financial skills.

Skills are operational instructions, not an alternative tax-law data plane.
These tests keep their executable helpers aligned with Rezef's dated VAT
schedule and with the skill text that routes agents to those helpers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GWS_SKILL = ROOT / ".agents/skills/gws-israeli-business-sheets"


def _load_vat_summary_module():
    path = GWS_SKILL / "scripts/vat-summary.py"
    spec = importlib.util.spec_from_file_location("gws_vat_summary", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gws_skill_uses_current_18_percent_vat_contract():
    module = _load_vat_summary_module()

    assert module.VAT_RATE == 0.18
    summary = module.compute_summary(
        [
            {
                "Type": "Income",
                "Amount (excl. VAT)": "1000",
                "VAT (18%)": "180",
                "Category": "Services",
            }
        ]
    )
    assert summary["vat_collected"] == 180.0
    assert summary["vat_liability"] == 180.0


def test_gws_skill_reference_does_not_present_17_percent_as_current():
    reference = (
        GWS_SKILL / "references/israeli-tax-categories.md"
    ).read_text(encoding="utf-8")

    assert "Standard VAT rate: **17%**" not in reference
    assert "Standard VAT rate: **18%**" in reference

