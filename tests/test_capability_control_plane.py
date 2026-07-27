"""Machine-readable Rezef capability contract.

The registry is the bridge between product intent, knowledge bases, runtime
workflows and safety gates.  These tests deliberately stay offline: they only
validate versioned files and imports.
"""

from cfo.services import capability_control_plane as control_plane


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
