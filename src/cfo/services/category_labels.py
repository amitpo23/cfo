"""One Hebrew label per category key, for every page that shows a category.

Budget rows, the P&L, the dashboard's comparison rows and its filing categories
each keep their own table. This module reads them in one order, so a key such
as ``salaries`` is never shown raw: the P&L labels first, then the budget
labels and the plan's budget catalog, then the dashboard comparison rows and filing categories. An unknown key
is returned as sent. ``frontend/src/services/categoryLabels.ts`` mirrors it.
"""
from __future__ import annotations

UNCATEGORIZED = "other"
UNCATEGORIZED_HE = "לא מסווג"


def _tables() -> list[dict]:
    from .budget_service import BUDGET_CATEGORIES_HEBREW
    from .dashboards.filing import CATEGORIES, PNL_ROWS
    from .dashboards.plan_budget import budget_catalog
    from .financial_reports_service import FinancialReportsService
    return [
        FinancialReportsService.CATEGORY_HEBREW,
        BUDGET_CATEGORIES_HEBREW,
        {row["key"]: row["label_he"] for row in budget_catalog()},
        {row["id"]: row["label"] for row in PNL_ROWS},
        {key: value["label"] for key, value in CATEGORIES.items()},
    ]


def all_labels() -> dict[str, str]:
    out: dict[str, str] = {}
    for table in reversed(_tables()):
        out.update(table)
    return out


def hebrew(key: str | None) -> str:
    text = (key or "").strip()
    for table in _tables():
        if text in table:
            return table[text]
        if text.casefold() in table:
            return table[text.casefold()]
    return text
