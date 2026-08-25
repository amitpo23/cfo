"""S9 — endpoint אדמין למדד המיקוד. אותה תבנית בדיוק כמו /moshko/usage:
super-admin בלבד, org_id/date_from/date_to אופציונליים."""
import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import ChatMessage, User, UserRole


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
    r = client.get("/api/admin/moshko/focus-metrics", headers=org["headers"])
    assert r.status_code == 403


def test_route_returns_expected_shape(client, moshko_super_admin, fresh_org):
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            organization_id=org_id, user_id=1, session_id="s1",
            role="assistant", content="תשובה",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/admin/moshko/focus-metrics?organization_id={org_id}",
        headers=moshko_super_admin["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "assistant_turns", "giveup_rate", "gaps_per_100_turns",
        "regression_pass_rate", "period",
    ):
        assert key in body
    assert body["assistant_turns"] == 1
