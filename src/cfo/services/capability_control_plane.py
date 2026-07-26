"""Rezef capability control plane.

This module intentionally contains no business logic and performs no network
or database access.  It loads the versioned capability contract used by agents,
documentation and tests to answer four questions consistently:

1. Which system owns the truth?
2. Which knowledge base and runtime implement the workflow?
3. Which safety gates are mandatory?
4. What prevents the capability from being called complete?
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "docs" / "rezef_capabilities.json"
VALID_STATUSES = {"implemented", "partial", "gated", "blocked", "target"}
REQUIRED_FIELDS = {
    "id",
    "title_he",
    "owner",
    "system_of_record",
    "status",
    "knowledge",
    "runtime",
    "tests",
    "gates",
    "honest_boundary",
    "next_gate",
}


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    """Load the immutable-on-read registry from the repository."""
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def capabilities_by_id() -> dict[str, dict[str, Any]]:
    """Return capability records keyed by their stable identifier."""
    return {
        capability["id"]: capability
        for capability in load_registry()["capabilities"]
    }


def validate_registry() -> list[str]:
    """Return deterministic validation errors; an empty list means valid."""
    registry = load_registry()
    errors: list[str] = []
    capabilities = registry.get("capabilities")

    if registry.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(capabilities, list) or not capabilities:
        return errors + ["capabilities must be a non-empty list"]

    seen: set[str] = set()
    for index, capability in enumerate(capabilities):
        label = capability.get("id") or f"capabilities[{index}]"
        missing = sorted(REQUIRED_FIELDS - capability.keys())
        if missing:
            errors.append(f"{label}: missing fields: {', '.join(missing)}")
            continue
        if capability["id"] in seen:
            errors.append(f"{label}: duplicate id")
        seen.add(capability["id"])
        if capability["status"] not in VALID_STATUSES:
            errors.append(f"{label}: invalid status {capability['status']!r}")
        for field in ("knowledge", "runtime", "tests"):
            values = capability[field]
            if not isinstance(values, list) or not values:
                errors.append(f"{label}: {field} must be a non-empty list")
                continue
            for relative_path in values:
                if not (REPO_ROOT / relative_path).is_file():
                    errors.append(f"{label}: missing {field} evidence: {relative_path}")
        if not capability["gates"]:
            errors.append(f"{label}: gates must be non-empty")

    governance = registry.get("governance", {})
    for key in ("stable_contract", "active_status_board", "bookkeeper_sop"):
        relative_path = governance.get(key)
        if not relative_path or not (REPO_ROOT / relative_path).is_file():
            errors.append(f"governance: missing {key}: {relative_path}")
    return errors


def render_status_summary_he() -> str:
    """Render a compact Hebrew summary for the in-app KB or operator tools."""
    lines = ["## מפת יכולות רצף", ""]
    for capability in load_registry()["capabilities"]:
        lines.append(
            f"- **{capability['title_he']}** — `{capability['status']}`: "
            f"{capability['honest_boundary']}"
        )
    lines.extend(
        [
            "",
            "לוח ההתקדמות הפעיל: `docs/MASTER_EXECUTION_PLAN.md`. "
            "סטטוס כאן מתאר מוכנות מוצר, לא הוכחת פרוד.",
        ]
    )
    return "\n".join(lines)
