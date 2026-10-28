"""Live bank loans supersede the plan's loan evidence for the same entity.

Production, 27/10/2026: an entity was connected to Open Finance and its live
loan accounts arrived next to the plan's loan evidence (a manual observation
recorded before the connection). The liquidity tab listed every loan twice,
including a bridge loan the bank had already repaid, and the known debt total
was overstated. The bank's balance now wins; the evidence keeps only what the
feed does not carry, the maturity date, matched by name and nearest balance.
Evidence with no live loan left is not counted. No provider calls.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import Account, AccountType, Organization
from cfo.services.dashboards import liquidity

TODAY = date(2026, 10, 27)


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _org(db):
    org = Organization(name="Loans Co", is_active=True)
    db.add(org)
    db.flush()
    return org.id


def _loan(db, org_id, name, balance):
    db.add(Account(
        organization_id=org_id, name=name, account_type=AccountType.LIABILITY, raw_account_type="LOAN",
        balance=Decimal(str(balance)), source="open_finance", balance_as_of=datetime(2026, 10, 26),
        external_id=f"of-{name}-{balance}",
    ))


def _plan(org_id, loans):
    return {"liquidityEvidence": {"loans": [dict(loan, organizationId=org_id) for loan in loans]}}


EVIDENCE = [
    {"label": "גישור", "balance": 62708.33, "asOf": "2026-10-14", "maturity": "2026-10-25"},
    {"label": "גישור", "balance": 61351.38, "asOf": "2026-10-14", "maturity": "2026-11-25"},
    {"label": "גישור", "balance": 41024.43, "asOf": "2026-10-14", "maturity": "2026-12-25"},
    {"label": "הלוואה עסקית", "balance": 261254.84, "asOf": "2026-10-14", "maturity": "2031-01-10"},
]


def _build(db, org_id, plan):
    return liquidity.build_liquidity(db, org_id, date(2026, 7, 1), TODAY, plan=plan, classified=[], today=TODAY)


def test_live_loans_are_listed_once_with_the_evidence_maturity():
    with SessionLocal() as db:
        org_id = _org(db)
        _loan(db, org_id, "גישור", 61508.89)
        _loan(db, org_id, "גישור", 41130.30)
        _loan(db, org_id, "הלוואה עסקית", 261798.75)
        db.commit()

        result = _build(db, org_id, _plan(org_id, EVIDENCE))

        loans = sorted((loan["balance"], loan.get("maturity"), loan["source"]) for loan in result["loans"])
        assert loans == [
            (41130.30, "2026-12-25", "accounts"),
            (61508.89, "2026-11-25", "accounts"),
            (261798.75, "2031-01-10", "accounts"),
        ]


def test_evidence_with_no_live_loan_left_is_not_a_debt():
    with SessionLocal() as db:
        org_id = _org(db)
        _loan(db, org_id, "גישור", 61508.89)
        db.commit()

        result = _build(db, org_id, _plan(org_id, EVIDENCE[:2]))

        amounts = [debt["amount"] for debt in result["debts"]]
        assert 62708.33 not in amounts
        assert amounts.count(61508.89) == 1


def test_the_maturity_event_carries_the_live_balance():
    with SessionLocal() as db:
        org_id = _org(db)
        _loan(db, org_id, "גישור", 61508.89)
        db.commit()

        result = _build(db, org_id, _plan(org_id, EVIDENCE[1:2]))

        maturity = next(event for event in result["upcoming"] if event["kind"] == "loan_maturity")
        assert maturity["date"] == "2026-11-25"
        assert maturity["amount"] == -61508.89


def test_without_a_live_connection_the_evidence_still_stands():
    with SessionLocal() as db:
        org_id = _org(db)
        db.commit()

        result = _build(db, org_id, _plan(org_id, EVIDENCE[1:2]))

        assert [(loan["balance"], loan["source"]) for loan in result["loans"]] == [(61351.38, "plan.liquidityEvidence")]
        assert result["loans"][0]["provider_data"] is False


def test_evidence_for_a_loan_the_feed_never_reports_stays():
    """A loan at a bank that is not connected is still a debt."""
    with SessionLocal() as db:
        org_id = _org(db)
        _loan(db, org_id, "ניידת", 6725.49)
        db.commit()

        result = _build(db, org_id, _plan(org_id, EVIDENCE[1:2]))

        assert sorted(loan["name"] for loan in result["loans"]) == ["גישור", "ניידת"]
