"""
Credit-line breach detector (PR2 of the bookkeeper daily-cycle plan).

Builds on PR1 (`Account.credit_limit` — the bank overdraft framework, מסגרת
חח"ד; NULL = unknown, never a guessed floor). This module compares the
org's daily cash-balance walk against the known credit-limit floor(s) and
raises a CfoInsight when the balance breaches, or comes within 10%, of the
framework.

Basis limitation — read before trusting the numbers:
  `CashFlowService.get_daily_cash_position` is ORG-LEVEL: it sums the legacy
  `Transaction` table across every account of the org, not per bank account,
  and it walks the window `[now - days, now]` — i.e. the *recorded* daily
  balance, not a genuine forward cash-flow forecast (despite the "projected"
  wording in the calling convention). It also inherits a known accuracy
  limitation: its opening balance is derived by summing ALL historical
  `Transaction` rows rather than the real synced `Account.balance`, which
  `CashFlowService.get_cash_burn_rate` documents can produce an artificially
  large negative starting balance (see that method's inline comment). This
  detector is explicitly scoped to PR2 and does not attempt to fix
  `cash_flow_service` — it uses the function as specified and flags the
  limitation here instead of silently trusting the numbers.

  Because of the org-level basis, when multiple accounts carry a
  `credit_limit` the floor is computed against the SUM of all known limits
  (`basis: "org_level"` in the result) — there is no way, with the current
  data model, to attribute the walked balance to one specific account.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Account, AccountType, CfoInsight
from .cash_flow_service import CashFlowService

INSIGHT_TYPE = "credit_line_breach"
WARNING_BAND = Decimal("0.10")  # within 10% of the framework floor => warning


def get_credit_line_status(db: Session, organization_id: int, days: int = 30) -> dict[str, Any]:
    """Compare the org's daily cash-balance walk against the known credit-limit
    floor(s). Returns a dict with `status` in {"ok", "warning", "breach", "unknown"}.
    """
    accounts = (
        db.query(Account)
        .filter(
            Account.organization_id == organization_id,
            Account.account_type == AccountType.BANK,
            Account.credit_limit.isnot(None),
        )
        .all()
    )
    if not accounts:
        return {
            "status": "unknown",
            "reason": "לא ידועה מסגרת אשראי לאף חשבון",
            "accounts": [],
            "breach_date": None,
            "warning_date": None,
            "min_headroom": None,
        }

    total_credit_limit = sum((Decimal(a.credit_limit) for a in accounts), Decimal("0"))
    floor = -total_credit_limit
    warning_threshold = floor + (WARNING_BAND * total_credit_limit)  # -0.9 * total

    daily = CashFlowService(db).get_daily_cash_position(organization_id, days=days)

    breach_date: Optional[str] = None
    warning_date: Optional[str] = None
    min_headroom: Optional[Decimal] = None

    for day in daily:
        balance = Decimal(str(day["closing_balance"]))
        headroom = balance - floor
        if min_headroom is None or headroom < min_headroom:
            min_headroom = headroom
        if breach_date is None and balance < floor:
            breach_date = day["date"]
        if warning_date is None and balance < warning_threshold:
            warning_date = day["date"]

    if breach_date is not None:
        status = "breach"
    elif warning_date is not None:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "basis": "org_level",
        "accounts": [
            {"account_id": a.id, "name": a.name, "credit_limit": float(a.credit_limit)}
            for a in accounts
        ],
        "breach_date": breach_date,
        "warning_date": warning_date,
        "min_headroom": float(min_headroom) if min_headroom is not None else None,
        "total_credit_limit": float(total_credit_limit),
        "floor": float(floor),
    }


def check_and_alert(db: Session, organization_id: int) -> dict[str, Any]:
    """Run `get_credit_line_status` and upsert/resolve a CfoInsight accordingly.

    - breach/warning -> upsert a fingerprinted insight (critical/high).
    - ok -> resolve any previously-active credit_line_breach insight for this
      org (the underlying condition cleared). There's no generic
      "auto-resolve on condition clear" flow elsewhere in the codebase
      (bank_expense_gap's scan_and_alert only ever creates, never resolves;
      resolution elsewhere is a manual /insights/{id}/status call) — this is
      new, narrowly-scoped behavior for this one insight_type, safe because
      it only ever touches active credit_line_breach rows for this org.
    - unknown -> no-op (nothing to alert on, nothing to resolve).
    """
    status = get_credit_line_status(db, organization_id)

    if status["status"] in ("breach", "warning"):
        basis = status["basis"]
        is_breach = status["status"] == "breach"
        date_str = status["breach_date"] if is_breach else status["warning_date"]
        severity = "critical" if is_breach else "high"
        fingerprint = f"credit_line:{basis}:{date_str}"
        total_limit = status["total_credit_limit"]
        headroom = status["min_headroom"]

        if is_breach:
            title = f"חריגה ממסגרת האשראי הבנקאית — {date_str}"
            message = (
                f"התחזית התזרימית מציגה יתרה שחוצה את מסגרת האשראי הכוללת "
                f"(₪{total_limit:,.2f}) בתאריך {date_str}. הפער מתחת למסגרת: "
                f"₪{abs(headroom):,.2f}. יש לפעול מול הבנק או לצמצם הוצאות מיידית."
            )
        else:
            title = f"התקרבות למסגרת האשראי הבנקאית — {date_str}"
            message = (
                f"התחזית התזרימית מציגה יתרה בטווח 10% ממסגרת האשראי הכוללת "
                f"(₪{total_limit:,.2f}) בתאריך {date_str}. המרווח שנותר עד המסגרת: "
                f"₪{headroom:,.2f}."
            )

        evidence = {
            "basis": basis,
            "date": date_str,
            "total_credit_limit": total_limit,
            "min_headroom": headroom,
            "accounts": status["accounts"],
        }
        recommended_action = (
            "פנה לבנק להגדלת המסגרת או צמצם הוצאות מתוכננות בתקופה הקרובה."
        )

        existing = db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id,
            CfoInsight.fingerprint == fingerprint,
        ).first()
        if existing:
            existing.insight_type = INSIGHT_TYPE
            existing.severity = severity
            existing.title = title
            existing.message = message
            existing.evidence = evidence
            existing.recommended_action = recommended_action
            if existing.status == "resolved":
                existing.status = "active"
                existing.resolved_at = None
            existing.updated_at = datetime.utcnow()
            insight_id = existing.id
        else:
            insight = CfoInsight(
                organization_id=organization_id,
                fingerprint=fingerprint,
                insight_type=INSIGHT_TYPE,
                severity=severity,
                title=title,
                message=message,
                evidence=evidence,
                recommended_action=recommended_action,
                status="active",
            )
            db.add(insight)
            db.flush()
            insight_id = insight.id

        db.commit()
        return {**status, "insight_id": insight_id, "fingerprint": fingerprint}

    if status["status"] == "ok":
        active = db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id,
            CfoInsight.insight_type == INSIGHT_TYPE,
            CfoInsight.status == "active",
        ).all()
        resolved_ids = []
        now = datetime.utcnow()
        for ins in active:
            ins.status = "resolved"
            ins.resolved_at = now
            ins.updated_at = now
            resolved_ids.append(ins.id)
        if resolved_ids:
            db.commit()
        return {**status, "resolved_insight_ids": resolved_ids}

    # unknown — nothing to alert on.
    return status
