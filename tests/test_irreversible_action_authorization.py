"""Negative authorization tests for externally side-effecting finance routes."""
import pytest

from cfo.auth import create_access_token, get_password_hash
from cfo.database import SessionLocal
from cfo.models import User, UserRole


IRREVERSIBLE_ACTIONS = [
    (
        "post",
        "/api/accounting/books/batches",
        {
            "database_id": 777,
            "transactions": [{
                "debit_account_code": "6000",
                "credit_account_code": "10001",
                "amount_ils": "118.00",
            }],
        },
    ),
    ("post", "/api/payments/charge", {"amount": 10}),
    ("post", "/api/payments/recurring/r1/cancel", None),
    ("post", "/api/payments/upay/setup", {"email": "a@b.com", "password": "x"}),
    ("post", "/api/open-finance/payments", {}),
    ("delete", "/api/open-finance/payments/p1", None),
    ("post", "/api/open-finance/payments/p1/refund", {"amount": 10}),
    ("post", "/api/open-finance/payments/init", {}),
    ("post", "/api/open-finance/mandates", {}),
    ("delete", "/api/open-finance/mandates/m1", None),
    (
        "post",
        "/api/advanced/payments/execute",
        {"bill_id": 999999, "method": "bank_transfer"},
    ),
]


@pytest.fixture(autouse=True)
def _network_must_not_be_reached(monkeypatch):
    """Fail locally if an authorization regression reaches any connector."""
    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.api.routes import open_finance

    async def forbidden_sumit_call(*_args, **_kwargs):
        raise AssertionError("authorization test reached SUMIT connector")

    def forbidden_open_finance_client(*_args, **_kwargs):
        raise AssertionError("authorization test reached Open Finance connector")

    monkeypatch.setattr(SumitIntegration, "charge_customer", forbidden_sumit_call)
    monkeypatch.setattr(SumitIntegration, "cancel_recurring", forbidden_sumit_call)
    monkeypatch.setattr(SumitIntegration, "setup_upay_credentials", forbidden_sumit_call)
    monkeypatch.setattr(SumitIntegration, "create_books_batch", forbidden_sumit_call)
    monkeypatch.setattr(
        open_finance, "get_open_finance_client", forbidden_open_finance_client,
    )


def _create_role_headers(owner, *, role, email):
    db = SessionLocal()
    try:
        row = User(
            organization_id=owner["user"]["organization_id"],
            email=email,
            password_hash=get_password_hash("not-used"),
            full_name=role.value,
            role=role,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        token = create_access_token({"sub": row.id})
        return {"headers": {"Authorization": f"Bearer {token}"}}
    finally:
        db.close()


@pytest.fixture(scope="module")
def viewer(owner):
    return _create_role_headers(
        owner,
        role=UserRole.VIEWER,
        email="irreversible-viewer@example.com",
    )


@pytest.fixture(scope="module")
def regular_user(owner):
    return _create_role_headers(
        owner,
        role=UserRole.USER,
        email="irreversible-user@example.com",
    )


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    IRREVERSIBLE_ACTIONS,
)
def test_viewer_cannot_reach_irreversible_financial_actions(
    client, viewer, method, path, json_body,
):
    response = getattr(client, method)(
        path,
        headers=viewer["headers"],
        **({"json": json_body} if json_body is not None else {}),
    )

    assert response.status_code == 403, (path, response.text)
    detail = response.json()["detail"].lower()
    assert "read-only" in detail or "admin" in detail


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    IRREVERSIBLE_ACTIONS,
)
def test_regular_user_cannot_reach_admin_only_financial_actions(
    client, regular_user, method, path, json_body,
):
    response = getattr(client, method)(
        path,
        headers=regular_user["headers"],
        **({"json": json_body} if json_body is not None else {}),
    )

    assert response.status_code == 403, (path, response.text)
    assert "admin" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    ("path", "json_body"),
    [
        (
            "/api/expenses",
            {
                "supplier_name": "ספק",
                "amount": 100,
                "expense_date": "2026-07-25",
            },
        ),
        (
            "/api/ledger/entries",
            {
                "entry_date": "2026-07-25",
                "memo": "must not persist",
                "lines": [
                    {"account": "1000", "debit": 10, "credit": 0},
                    {"account": "3000", "debit": 0, "credit": 10},
                ],
            },
        ),
        (
            "/api/masav/settings",
            {
                "institution_code": "12345678",
                "sending_institution": "54321",
                "institution_name": "viewer must not change",
            },
        ),
    ],
)
def test_viewer_is_read_only_across_internal_finance_routes(
    client, viewer, path, json_body,
):
    response = client.post(path, json=json_body, headers=viewer["headers"])

    assert response.status_code == 403, (path, response.text)
    assert "read-only" in response.json()["detail"].lower()
