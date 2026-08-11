"""תצוגת ספרים לתיק — עבר שיובא, הווה חי, ומה חוסם.

הפער שזה סוגר: הנתונים בפרוד ומאומתים, ואין דרך להסתכל עליהם. 15,060
פקודות יומן ו-1,004 כרטיסים היו נגישים רק בשאילתת SQL ידנית.

ההפרדה בין שתי התקופות אינה קוסמטית — מקור האמת שלהן שונה:

  * **עד קו החיתוך** — הספרים מההנה"ח הקודמת (חשבשבת). הם דווחו כבר
    לרשויות ולכן הם הרשומה הנכונה לתקופה הזו.
  * **מקו החיתוך** — התקופה החיה, שמסונכרנת מ-SUMIT.

ערבוב השניים היה מציג את אותה תנועה פעמיים: פעם כפקודת יומן היסטורית
ופעם כהוצאה שנמשכה מהספק.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func

from . import tenant_routing

DEFAULT_CUTOFF = date(2026, 6, 30)


def org_books_view(
    organization_id: int,
    *,
    cutoff: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """תמונת הספרים המלאה של תיק אחד, או None אם אינו קיים."""
    from ..models import Account, Expense, Invoice, JournalEntry, Organization

    boundary = cutoff or DEFAULT_CUTOFF

    with tenant_routing.session_for(organization_id) as db:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if org is None:
            return None

        # ---------- העבר שיובא ----------
        journal = (
            db.query(JournalEntry)
            .filter(JournalEntry.organization_id == organization_id)
            .all()
        )
        debit = credit = Decimal(0)
        for entry in journal:
            for line in entry.lines or []:
                debit += Decimal(str(line.get("debit", 0) or 0))
                credit += Decimal(str(line.get("credit", 0) or 0))

        dates = [e.entry_date for e in journal if e.entry_date]
        imported_past = {
            "journal_entries": len(journal),
            "sources": sorted({e.source for e in journal if e.source}),
            "debit_total": str(debit),
            "credit_total": str(credit),
            "imbalance": str(debit - credit),
            "balanced": debit == credit,
            "one_sided": sum(
                1 for e in journal
                if e.raw_data and e.raw_data.get("one_sided")
            ),
            "first_date": min(dates).isoformat() if dates else None,
            "last_date": max(dates).isoformat() if dates else None,
        }

        # ---------- ההווה החי ----------
        def _expenses(*conditions):
            query = db.query(func.count(Expense.id)).filter(
                Expense.organization_id == organization_id,
                Expense.expense_date > boundary,
            )
            for condition in conditions:
                query = query.filter(condition)
            return query.scalar() or 0

        live_expenses = _expenses()
        live_period = {
            "from": (boundary.replace(day=boundary.day) if False else boundary).isoformat(),
            "expenses": live_expenses,
            "unfiled": _expenses(Expense.account_id.is_(None)),
            "zero_sum": _expenses(func.coalesce(Expense.total, 0) == 0),
            "invoices": db.query(func.count(Invoice.id)).filter(
                Invoice.organization_id == organization_id,
                Invoice.issue_date > boundary,
            ).scalar() or 0,
        }

        # ---------- האינדקס ----------
        accounts = (
            db.query(Account)
            .filter(
                Account.organization_id == organization_id,
                Account.source_account_code.isnot(None),
            )
            .all()
        )
        by_sort: dict[str, int] = {}
        for account in accounts:
            by_sort[str(account.sort_code or "—")] = by_sort.get(str(account.sort_code or "—"), 0) + 1
        index = {
            "accounts": len(accounts),
            "sources": sorted({a.source for a in accounts if a.source}),
            "by_sort_code": dict(sorted(by_sort.items(), key=lambda kv: -kv[1])[:8]),
        }

        # ---------- חסמים ----------
        # מנוסחים כפעולה ולא כסטטוס: מי שקורא צריך לדעת מה לעשות.
        blockers: list[str] = []
        if not imported_past["balanced"] and journal:
            blockers.append(
                f"הספרים שיובאו אינם מאוזנים בפער {imported_past['imbalance']} — "
                "להצליב מול מאזן הבוחן של ההנה\"ח הקודמת"
            )
        if live_period["zero_sum"]:
            blockers.append(
                f"{live_period['zero_sum']} מסמכים בתקופה החיה בסכום 0 — "
                "הסכום לא נמשך מהספק, ואי אפשר לתייק או לדווח עליהם"
            )
        if live_period["unfiled"] and not accounts:
            blockers.append("אין אינדקס חשבונות — אי אפשר לתייק")
        elif live_period["unfiled"]:
            blockers.append(
                f"{live_period['unfiled']} הוצאות בתקופה החיה טרם תויקו לכרטיס"
            )

        return {
            "organization_id": organization_id,
            "name": org.name,
            "tax_id": org.tax_id,
            "cutoff": boundary.isoformat(),
            "imported_past": imported_past,
            "live_period": live_period,
            "index": index,
            "blockers": blockers,
        }
