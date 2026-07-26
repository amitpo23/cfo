"""Approval-bound Open Finance payment execution with offline provider doubles."""
import pytest

from cfo.database import SessionLocal
from cfo.models import IrreversibleActionRequest


def _approved_payment(client, owner, *, key: str, payload: dict):
    proposal = client.post(
        "/api/approvals",
        headers=owner["headers"],
        json={
            "action_type": "payment",
            "payload": payload,
            "idempotency_key": key,
        },
    )
    assert proposal.status_code == 201, proposal.text
    action_id = proposal.json()["id"]
    approval = client.post(
        f"/api/approvals/{action_id}/approve",
        headers=owner["headers"],
    )
    assert approval.status_code == 200, approval.text
    return action_id


def test_payment_without_approval_never_builds_provider_client(
    client, owner, monkeypatch,
):
    from cfo.api.routes import open_finance

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("provider client built before approval")

    monkeypatch.setattr(
        open_finance,
        "get_open_finance_client",
        forbidden_client,
    )
    response = client.post(
        "/api/open-finance/payments",
        headers=owner["headers"],
        json={"amount": 10, "currency": "ILS"},
    )

    assert response.status_code == 409, response.text
    assert "approval" in response.json()["detail"].lower()


def test_approved_payment_uses_persisted_payload_and_verifies_readback(
    client, owner, monkeypatch,
):
    from cfo.api.routes import open_finance

    payload = {
        "amount": 125.40,
        "currency": "ILS",
        "creditor": {"name": "Offline Supplier"},
    }
    action_id = _approved_payment(
        client,
        owner,
        key="of-payment:offline-success:v1",
        payload=payload,
    )
    calls = []

    class FakeOpenFinanceClient:
        async def create_payment(self, submitted):
            calls.append(("create", submitted))
            return {"paymentId": "of-approved-001", "status": "PENDING"}

        async def get_payment(self, payment_id):
            calls.append(("readback", payment_id))
            return {
                "paymentId": payment_id,
                "paymentStatus": "PENDING",
                "amount": 125.40,
            }

        async def close(self):
            calls.append(("close", None))

    monkeypatch.setattr(
        open_finance,
        "get_open_finance_client",
        lambda *_args, **_kwargs: FakeOpenFinanceClient(),
    )

    response = client.post(
        "/api/open-finance/payments",
        headers={
            **owner["headers"],
            "X-Rezef-Approval-Id": str(action_id),
        },
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["approval_status"] == "verified"
    assert response.json()["provider_reference"] == "of-approved-001"
    assert calls[:2] == [
        ("create", payload),
        ("readback", "of-approved-001"),
    ]

    db = SessionLocal()
    try:
        row = db.get(IrreversibleActionRequest, action_id)
        assert row.status == "verified"
        assert row.provider_reference == "of-approved-001"
        assert row.verification_evidence["paymentStatus"] == "PENDING"
    finally:
        db.close()


def test_changed_payload_and_replay_are_blocked_before_provider_call(
    client, owner, monkeypatch,
):
    from cfo.api.routes import open_finance

    payload = {"amount": 10, "currency": "ILS"}
    action_id = _approved_payment(
        client,
        owner,
        key="of-payment:payload-lock:v1",
        payload=payload,
    )
    calls = []

    class FakeOpenFinanceClient:
        async def create_payment(self, submitted):
            calls.append(("create", submitted))
            return {"paymentId": "of-approved-002"}

        async def get_payment(self, payment_id):
            calls.append(("readback", payment_id))
            return {"paymentId": payment_id, "paymentStatus": "PENDING"}

        async def close(self):
            calls.append(("close", None))

    monkeypatch.setattr(
        open_finance,
        "get_open_finance_client",
        lambda *_args, **_kwargs: FakeOpenFinanceClient(),
    )

    changed = client.post(
        "/api/open-finance/payments",
        headers={
            **owner["headers"],
            "X-Rezef-Approval-Id": str(action_id),
        },
        json={"amount": 11, "currency": "ILS"},
    )
    assert changed.status_code == 409, changed.text
    assert calls == []

    first = client.post(
        "/api/open-finance/payments",
        headers={
            **owner["headers"],
            "X-Rezef-Approval-Id": str(action_id),
        },
        json=payload,
    )
    assert first.status_code == 200, first.text

    replay = client.post(
        "/api/open-finance/payments",
        headers={
            **owner["headers"],
            "X-Rezef-Approval-Id": str(action_id),
        },
        json=payload,
    )
    assert replay.status_code == 409, replay.text
    assert [kind for kind, _ in calls].count("create") == 1
