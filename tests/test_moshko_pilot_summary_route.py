"""S4 — endpoint אדמין ללוח הפיילוט. אותה תבנית כמו /moshko/usage
ו-/moshko/focus-metrics: super-admin בלבד."""
import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import LLMUsage, User, UserRole


@pytest.fixture
def moshko_super_admin(client, fresh_org):
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.organization_id == actor["org_id"]).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(data={
            "sub": str(user.id), "role": UserRole.SUPER_ADMIN.value,
            "org_id": user.organization_id,
        })
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": user.id}


def test_route_requires_super_admin(client, fresh_org):
    org = fresh_org()
    r = client.get("/api/admin/moshko/pilot-summary", headers=org["headers"])
    assert r.status_code == 403


def test_route_returns_expected_shape(client, moshko_super_admin, fresh_org):
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        db.add(LLMUsage(
            organization_id=org_id, session_id="wa-1", provider="anthropic",
            model="claude-sonnet-5", input_tokens=10, output_tokens=5,
            cost_usd="0.01", purpose="chat",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/admin/moshko/pilot-summary?organization_id={org_id}",
        headers=moshko_super_admin["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("llm_calls", "cost_usd_total", "assistant_turns", "gaps_opened", "gaps_still_open"):
        assert key in body
    assert body["llm_calls"] == 1
