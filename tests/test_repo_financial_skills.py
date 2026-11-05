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



# --------------------------------------------------------------------- #
# Simplify F: the four daily skills. They route an agent through one daily
# loop (file -> match -> optional OF sync -> P&L + cash). The tests keep the
# skill text pointed at endpoints that actually exist on the app.
# --------------------------------------------------------------------- #
import re

import yaml

DAILY_SKILLS = ("daily-file", "daily-bank-match", "of-accounts-sync", "daily-pnl-cash")
SKILLS_DIR = ROOT / ".agents/skills"


def _frontmatter(skill: str) -> tuple[dict, str]:
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert match, f"{skill}: SKILL.md has no frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


def test_daily_skills_exist_with_bilingual_frontmatter():
    for skill in DAILY_SKILLS:
        meta, body = _frontmatter(skill)
        assert meta["name"] == skill
        description = meta["description"]
        assert re.search(r"[֐-׿]", description), f"{skill}: no Hebrew trigger"
        assert re.search(r"[A-Za-z]{4,}", description), f"{skill}: no English trigger"
        assert "חסר" in body, f"{skill}: missing the חסר≠0 rule"
        for forbidden in ("merge", "מיגרציה", "org 6"):
            assert forbidden in body, f"{skill}: does not forbid {forbidden}"
        assert (SKILLS_DIR / skill / "agents/openai.yaml").exists()


def test_rezef_operator_routes_the_daily_loop_in_order():
    text = (SKILLS_DIR / "rezef-operator/SKILL.md").read_text(encoding="utf-8")
    positions = [text.find(f"`{skill}`") for skill in DAILY_SKILLS]
    assert all(pos >= 0 for pos in positions), positions
    assert positions == sorted(positions)


def test_daily_order_doc_links_the_four_skills():
    text = (ROOT / "docs/bookkeeper_kb/00-role-and-daily-order.md").read_text(encoding="utf-8")
    for skill in DAILY_SKILLS:
        assert f"`{skill}`" in text


def test_daily_file_wraps_the_runbook_and_never_runs_the_blocked_script():
    _, body = _frontmatter("daily-file")
    assert "sumit-file-expenses" in body
    assert "sumit_daily_file_expenses.js" in body  # named as forbidden
    assert "GO" in body


def test_of_sync_is_never_implicit_and_never_scheduled():
    policy = yaml.safe_load(
        (SKILLS_DIR / "of-accounts-sync/agents/openai.yaml").read_text(encoding="utf-8")
    )
    assert policy["policy"]["allow_implicit_invocation"] is False
    _, body = _frontmatter("of-accounts-sync")
    assert "20" in body and "/api/sync/runs" in body
    # A subset sync does not advance the checkpoint the nightly cron gate reads.
    assert "POST /api/sync/run?source=open_finance\n" in body
    assert "entity_types=" not in body


def _registered_paths() -> set[str]:
    from cfo.api import app

    # Included routers are lazy here, so app.routes misses them; the schema
    # lists every mounted path (same source as tests/test_rezef_kb.py).
    return {re.sub(r"\{[^}]+\}", "{}", path) for path in app.openapi()["paths"]}


def test_daily_skills_cite_only_registered_endpoints():
    registered = _registered_paths()
    cited = set()
    for skill in DAILY_SKILLS:
        _, body = _frontmatter(skill)
        for raw in re.findall(r"/api/[A-Za-z0-9_\-/{}<>]+", body):
            path = re.sub(r"[{<][^}>]+[}>]", "{}", raw.rstrip("/.,)"))
            cited.add((skill, path))
    assert cited, "daily skills cite no endpoints"
    unknown = sorted((skill, path) for skill, path in cited if path not in registered)
    assert not unknown, unknown
