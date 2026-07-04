"""assess_financial_risks()'s liquidity risk (RISK-LIQ-001) hardcoded
potential_impact=100000/expected_loss=60000 regardless of the org's real
liquidity gap -- rendered as real currency figures in AIAnalyticsDashboard.tsx
(potential_impact/expected_loss cards + a "total expected loss" sum). A tiny
org and a massive one would show the exact same ₪100,000/₪60,000. The other
three risk types (credit/cashflow/concentration) already derive
potential_impact from real data with a probability multiplier for
expected_loss -- this brings liquidity risk in line with that pattern
instead of leaving it fully fabricated."""
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, Bill, BillStatus
from cfo.services.ai_analytics_service import AdvancedAIService


def test_liquidity_risk_impact_reflects_real_gap(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="עו\"ש", account_type=AccountType.BANK, balance=5000))
        db.add(Bill(
            organization_id=org_id, external_id="b1", source="manual",
            bill_number="B-1", status=BillStatus.APPROVED,
            total=Decimal("50000"), balance=Decimal("50000"),
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org_id)
        risks = svc.assess_financial_risks()
    finally:
        db.close()

    liq = next(r for r in risks if r.risk_id == "RISK-LIQ-001")
    # gap = payables(50000) - current_assets(5000) = 45000, not the old fixed 100000/60000
    assert liq.potential_impact == 45000
    assert liq.expected_loss == 45000 * 0.6
    assert liq.potential_impact != 100000
    assert liq.expected_loss != 60000
