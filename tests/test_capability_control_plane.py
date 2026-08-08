"""Machine-readable Rezef capability contract.

The registry is the bridge between product intent, knowledge bases, runtime
workflows and safety gates.  These tests deliberately stay offline: they only
validate versioned files and imports.
"""

from cfo.services import capability_control_plane as control_plane


# סט סגור בכוונה, בשני הכיוונים: יכולת חסרה = הסתרת פער, יכולת עודפת =
# מרשם שהופך לקטלוג מודולים במקום מפת התפעול. שירות תשתית חדש (בקרה,
# observability, כלי) נרשם כ-runtime/tests/knowledge בתוך היכולת שהוא משרת —
# לא כשורה משלו. אם באמת נפתח תחום תפעול חדש, מרחיבים את הסט הזה במודע.
REQUIRED_CAPABILITIES = {
    "sumit-integration",
    "open-finance-ingestion",
    "daily-bookkeeping-cycle",
    "expense-intake-filing",
    "double-entry-books",
    "bank-reconciliation",
    "ap-ar-collections",
    "regulatory-filings",
    "management-reporting",
    "cfo-control",
    "irreversible-actions",
    "conversational-channels",
}


def test_registry_covers_the_full_rezef_operating_scope():
    registry = control_plane.load_registry()

    assert registry["schema_version"] == 1
    assert {item["id"] for item in registry["capabilities"]} == REQUIRED_CAPABILITIES


def test_registry_references_existing_versioned_evidence():
    assert control_plane.validate_registry() == []


def test_registry_evidence_is_tracked_in_git_not_just_present_on_disk():
    """`validate_registry` בודק קיום על הדיסק — ולכן ראיה שקיימת אצל המפתח
    אך מוחרגת ב-.gitignore עוברת מקומית ונופלת ב-CI בלבד. זה קרה בפועל
    ב-08/08/2026: המרשם הצביע על דוח אודיט תחת `reports/`, שמוחרג משום
    שהוא מכיל שמות לקוחות ומזהי חברות. השער הזה מזיז את הכשל למחשב של
    המפתח, במקום להמתין ל-CI."""
    import shutil
    import subprocess

    import pytest

    if shutil.which("git") is None:
        pytest.skip("git לא זמין בסביבה הזו")

    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True,
        cwd=control_plane.REGISTRY_PATH.parent.parent,
    )
    if result.returncode != 0:
        pytest.skip("לא ריפו git")

    tracked = set(result.stdout.splitlines())
    untracked_evidence = [
        f"{item['id']}.{key}: {path}"
        for item in control_plane.load_registry()["capabilities"]
        for key in ("knowledge", "runtime", "tests")
        for path in item.get(key, [])
        if path not in tracked
    ]
    assert untracked_evidence == []


def test_external_ingestion_is_cost_gated_and_tenant_scoped():
    by_id = control_plane.capabilities_by_id()

    for capability_id in ("sumit-integration", "open-finance-ingestion"):
        gates = set(by_id[capability_id]["gates"])
        assert {"organization_scope", "daily_sync_budget", "idempotency"} <= gates


def test_filing_and_irreversible_workflows_cannot_claim_automation_without_gates():
    by_id = control_plane.capabilities_by_id()

    assert "triple_verification" in by_id["regulatory-filings"]["gates"]
    assert "owner_approval" in by_id["irreversible-actions"]["gates"]
    assert by_id["irreversible-actions"]["status"] != "operational"


def test_every_capability_has_an_honest_boundary_and_next_gate():
    for capability in control_plane.load_registry()["capabilities"]:
        assert capability["honest_boundary"].strip()
        assert capability["next_gate"].strip()


def test_infrastructure_services_are_folded_into_the_capability_they_serve():
    """המרשם הוא מפת תפעול, לא קטלוג מודולים.

    רגרסיה מ-05/08/2026: בקרת הכיסוי (`roster_coverage`) נרשמה בטעות כיכולת
    שלוש-עשרה. היא אינה תחום תפעול אלא ראיה על בריאות האינטגרציה, ומקומה
    כ-runtime/tests בתוך `sumit-integration`.
    """
    by_id = control_plane.capabilities_by_id()
    sumit = by_id["sumit-integration"]

    assert "src/cfo/services/roster_coverage.py" in sumit["runtime"]
    assert "scripts/roster_health.py" in sumit["runtime"]
    assert "tests/test_roster_coverage.py" in sumit["tests"]
    assert "roster-coverage" not in by_id
