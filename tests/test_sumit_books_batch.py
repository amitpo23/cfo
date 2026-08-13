"""Official SUMIT books-batch adapter — offline, approval-bound evidence.

The request/response shape is taken from the versioned SUMIT OpenAPI contract
(`Books_Transactions_CreateBatch_Request`).  The API creates an OPEN batch;
SUMIT exposes no batch readback/close endpoint in that contract, so Rezef must
return an explicit unverified boundary and never claim the books were closed.
"""
import asyncio
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from cfo.database import SessionLocal
from cfo.integrations.sumit_integration import SumitAPIError, SumitIntegration
from cfo.integrations.sumit_models import (
    BooksBatchRequest,
    BooksBatchResponse,
    BooksBatchTransaction,
)
from cfo.models import IrreversibleActionRequest


def _request() -> BooksBatchRequest:
    return BooksBatchRequest(
        database_id=777,
        batch_description="Rezef approved batch",
        transactions=[
            BooksBatchTransaction(
                reference1="INV-100",
                reference_date=datetime(2026, 8, 9, 0, 0),
                value_date=datetime(2026, 8, 10, 0, 0),
                debit_account_code="6000",
                credit_account_code="10001",
                amount_ils=Decimal("118.00"),
                details="Office supplies",
            )
        ],
    )


def test_books_batch_model_refuses_unbalanced_or_empty_sides():
    with pytest.raises(ValidationError):
        BooksBatchTransaction(
            debit_account_code="",
            credit_account_code="10001",
            amount_ils=Decimal("118"),
        )
    with pytest.raises(ValidationError):
        BooksBatchTransaction(
            debit_account_code="6000",
            credit_account_code="10001",
            amount_ils=Decimal("0"),
        )
    with pytest.raises(ValidationError):
        BooksBatchRequest(database_id=777, transactions=[])


def test_create_books_batch_uses_the_versioned_swagger_contract_exactly():
    sumit = SumitIntegration(api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="123")
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0,
                "Data": {"BatchURL": "https://app.sumit.co.il/f777/batches/42"},
            })

        sumit.client.request = _fake_post
        try:
            return await sumit.create_books_batch(_request())
        finally:
            await sumit.client.aclose()

    response = asyncio.run(_run())

    assert response.batch_url == "https://app.sumit.co.il/f777/batches/42"
    assert captured["url"] == "/books/transactions/createbatch/"
    assert captured["json"] == {
        "Credentials": {"APIKey": "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", "CompanyID": 123},
        "DatabaseID": 777,
        "BatchDescription": "Rezef approved batch",
        "Transactions": [{
            "Reference1": "INV-100",
            "ReferenceDate": "2026-08-09T00:00:00",
            "ValueDate": "2026-08-10T00:00:00",
            "DebitAccountCode": "6000",
            "CreditAccountCode": "10001",
            "AmountILS": 118.0,
            "Details": "Office supplies",
        }],
    }


def test_create_books_batch_refuses_success_without_batch_url():
    sumit = SumitIntegration(api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="123")

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={"Status": 0, "Data": {}})

        sumit.client.request = _fake_post
        try:
            return await sumit.create_books_batch(_request())
        finally:
            await sumit.client.aclose()

    with pytest.raises(SumitAPIError, match="BatchURL"):
        asyncio.run(_run())


def _approved_batch(client, owner, *, key: str) -> tuple[int, dict]:
    payload = _request().model_dump(mode="json", exclude_none=True)
    proposal = client.post(
        "/api/approvals",
        headers=owner["headers"],
        json={
            "action_type": "sumit_writeback",
            "payload": payload,
            "idempotency_key": key,
            "description": "Create an open SUMIT books batch",
        },
    )
    assert proposal.status_code == 201, proposal.text
    action_id = proposal.json()["id"]
    approval = client.post(
        f"/api/approvals/{action_id}/approve",
        headers=owner["headers"],
    )
    assert approval.status_code == 200, approval.text
    return action_id, payload


def test_books_batch_route_requires_approval_before_building_sumit_client(
    client, owner, monkeypatch,
):
    from cfo.api.routes import accounting

    def forbidden_sumit(*_args, **_kwargs):
        raise AssertionError("SUMIT client built before approval")

    monkeypatch.setattr(accounting, "sumit_for_org", forbidden_sumit, raising=False)
    response = client.post(
        "/api/accounting/books/batches",
        headers=owner["headers"],
        json=_request().model_dump(mode="json", exclude_none=True),
    )

    assert response.status_code == 409, response.text
    assert "approval" in response.json()["detail"].lower()


def test_approved_books_batch_executes_once_and_stays_explicitly_unverified(
    client, owner, monkeypatch,
):
    from cfo.api.routes import accounting

    action_id, payload = _approved_batch(
        client,
        owner,
        key="sumit-books-batch:offline-success:v1",
    )
    calls = []

    class FakeSumit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def create_books_batch(self, request):
            calls.append(request.model_dump(mode="json", exclude_none=True))
            return BooksBatchResponse(
                batch_url="https://app.sumit.co.il/f777/batches/42",
            )

    monkeypatch.setattr(
        accounting,
        "sumit_for_org",
        lambda *_args, **_kwargs: FakeSumit(),
        raising=False,
    )
    headers = {
        **owner["headers"],
        "X-Rezef-Approval-Id": str(action_id),
    }

    response = client.post(
        "/api/accounting/books/batches",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "approval_request_id": action_id,
        "approval_status": "executed_unverified",
        "batch_url": "https://app.sumit.co.il/f777/batches/42",
        "batch_closed": False,
        "verification_required": "Verify open/closed status in the SUMIT batches portal",
    }
    assert calls == [payload]

    replay = client.post(
        "/api/accounting/books/batches",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 409, replay.text
    assert calls == [payload]

    db = SessionLocal()
    try:
        row = db.get(IrreversibleActionRequest, action_id)
        assert row.status == "executed"
        assert row.provider_reference == "https://app.sumit.co.il/f777/batches/42"
        assert row.verification_evidence is None
    finally:
        db.close()


def test_books_batch_refuses_payload_drift_before_provider_resolution(
    client, owner, monkeypatch,
):
    from cfo.api.routes import accounting

    action_id, payload = _approved_batch(
        client,
        owner,
        key="sumit-books-batch:payload-drift:v1",
    )

    def forbidden_sumit(*_args, **_kwargs):
        raise AssertionError("SUMIT client built for changed approved intent")

    monkeypatch.setattr(accounting, "sumit_for_org", forbidden_sumit)
    payload["batch_description"] = "changed after approval"
    response = client.post(
        "/api/accounting/books/batches",
        headers={
            **owner["headers"],
            "X-Rezef-Approval-Id": str(action_id),
        },
        json=payload,
    )

    assert response.status_code == 409, response.text

    db = SessionLocal()
    try:
        assert db.get(IrreversibleActionRequest, action_id).status == "approved"
    finally:
        db.close()


def test_books_batch_provider_failure_is_redacted_and_not_replayable(
    client, owner, monkeypatch,
):
    from cfo.api.routes import accounting

    action_id, payload = _approved_batch(
        client,
        owner,
        key="sumit-books-batch:provider-failure:v1",
    )

    class FailingSumit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def create_books_batch(self, _request):
            raise RuntimeError("provider-secret-must-not-leak")

    monkeypatch.setattr(
        accounting,
        "sumit_for_org",
        lambda *_args, **_kwargs: FailingSumit(),
    )
    headers = {
        **owner["headers"],
        "X-Rezef-Approval-Id": str(action_id),
    }
    response = client.post(
        "/api/accounting/books/batches",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 502, response.text
    assert "provider-secret" not in response.text

    replay = client.post(
        "/api/accounting/books/batches",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 409, replay.text

    db = SessionLocal()
    try:
        row = db.get(IrreversibleActionRequest, action_id)
        assert row.status == "failed"
        assert row.error == "SUMIT books batch failed: RuntimeError"
    finally:
        db.close()
