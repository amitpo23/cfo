"""Wave 2 item 7.2: liquidity score must be derived from real cash position,
never a hardcoded constant (was: always 20.0 regardless of actual data)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def _make_org(client):
    import uuid
    email = f"liq-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": "Liquidity Test",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["user"]["organization_id"]


def test_liquidity_score_computed_from_cash_and_burn(client):
    """Org with a real bank balance and expense history gets a computed score,
    not the old fabricated constant 20.0."""
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType, Expense
    from cfo.services.ai_intelligence_agent import AIIntelligenceAgent

    org_id = _make_org(client)
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=Decimal("30000")))
        now = datetime.now(timezone.utc)
        for i in range(3):
            db.add(Expense(
                organization_id=org_id,
                supplier_name="Test Supplier",
                expense_date=(now - timedelta(days=i * 10)).date(),
                total=Decimal("10000"),
                status="filed",
                created_at=now - timedelta(days=i * 10),
                category="office",
                description="test expense",
            ))
        db.commit()

        agent = AIIntelligenceAgent(db, org_id)
        score = agent._calculate_liquidity_score()

        # 30000 cash / ~10000 monthly burn ~= 3 months runway -> near-max score.
        # The key assertion: it is NOT the old hardcoded 20.0, and it is a real number.
        assert score is not None
        assert score != 20.0, "Must not be the old fabricated constant"
        assert 0 <= score <= 25
    finally:
        db.close()


def test_liquidity_score_none_when_no_bank_account(client):
    """Org with no bank account at all: honest None, not a fabricated 20.0."""
    from cfo.database import SessionLocal
    from cfo.services.ai_intelligence_agent import AIIntelligenceAgent

    org_id = _make_org(client)
    db = SessionLocal()
    try:
        agent = AIIntelligenceAgent(db, org_id)
        score = agent._calculate_liquidity_score()
        assert score is None
    finally:
        db.close()
