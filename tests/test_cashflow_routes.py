"""רגרסיה: ראוטר ה-cashflow (היה שבור — current_user.get על User) + burn/liquidity NaN."""
import pytest


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "cfowner@example.com", "password": "secret123", "full_name": "CF Owner",
    })
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"}}


def test_cashflow_core_routes_no_crash(client, acc):
    """ראוטרי cashflow שאינם תלויי-SUMIT/forecast-postgres לא קורסים (גם על ארגון ריק)."""
    paths = [
        "/api/cashflow/monthly", "/api/cashflow/daily", "/api/cashflow/burn-rate",
        "/api/cashflow/liquidity-ratios", "/api/cashflow/receivables-aging",
        "/api/cashflow/payables-aging",
    ]
    crashed = []
    for p in paths:
        try:
            r = client.get(p, headers=acc["headers"])
            if r.status_code == 500:
                crashed.append((p, r.text[:100]))
        except Exception as exc:
            crashed.append((p, f"{type(exc).__name__}: {exc}"))
    assert not crashed, crashed


def test_burn_rate_no_nan(client, acc):
    """burn-rate על ארגון ריק לא מחזיר Infinity (תקין ל-JSON)."""
    r = client.get("/api/cashflow/burn-rate", headers=acc["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["runway_months"] == 999.0  # היה float('inf')


def test_liquidity_no_nan(client, acc):
    r = client.get("/api/cashflow/liquidity-ratios", headers=acc["headers"])
    assert r.status_code == 200, r.text
    # יחסים סופיים תקינים ל-JSON (היו inf)
    assert isinstance(r.json().get("current_ratio"), (int, float))


def test_cashflow_requires_auth(client):
    assert client.get("/api/cashflow/monthly").status_code == 403
