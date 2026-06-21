"""Tests for OpenFinanceClient: auth lifecycle, base-URL routing, 401 refresh."""
import asyncio

import httpx
import pytest

from cfo.services.open_finance_client import OpenFinanceClient, OpenFinanceError


def _make_client(handler):
    client = OpenFinanceClient("cid", "secret", "user-1")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def test_token_then_call_uses_bearer_and_v2_base():
    seen = {"token_calls": 0, "auth_headers": [], "urls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            seen["token_calls"] += 1
            return httpx.Response(200, json={"accessToken": "tok-abc", "expiresIn": 3600000})
        seen["auth_headers"].append(request.headers.get("authorization"))
        seen["urls"].append(str(request.url))
        return httpx.Response(200, json={"items": [], "nextPage": None})

    client = _make_client(handler)
    asyncio.run(client.list_accounts())
    asyncio.run(client.list_transactions())
    asyncio.run(client.close())

    # Token fetched once and reused; bearer attached; v2 base used.
    assert seen["token_calls"] == 1
    assert seen["auth_headers"] == ["Bearer tok-abc", "Bearer tok-abc"]
    assert all("https://api.open-finance.ai/v2/data/" in u for u in seen["urls"])


def test_credit_sessions_use_v3_loans_base():
    urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"accessToken": "t", "expiresIn": 1000})
        urls.append(str(request.url))
        return httpx.Response(200, json={"items": [], "count": 0})

    client = _make_client(handler)
    asyncio.run(client.list_credit_sessions("user"))
    asyncio.run(client.list_customers())
    asyncio.run(client.close())

    assert any("/v3/loans/credit-sessions/converted/user" in u for u in urls)
    assert any("/v3/loans/customers" in u for u in urls)


def test_401_triggers_token_refresh_and_retry():
    state = {"token_calls": 0, "data_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            state["token_calls"] += 1
            return httpx.Response(200, json={"accessToken": f"tok-{state['token_calls']}", "expiresIn": 999999})
        state["data_calls"] += 1
        if state["data_calls"] == 1:
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"items": []})

    client = _make_client(handler)
    result = asyncio.run(client.list_accounts())
    asyncio.run(client.close())

    assert result == {"items": []}
    assert state["token_calls"] == 2   # initial + forced refresh
    assert state["data_calls"] == 2    # original 401 + retry


def test_api_error_raises_open_finance_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"accessToken": "t", "expiresIn": 1000})
        return httpx.Response(404, json={"message": "No connection was found", "type": "not_found"})

    client = _make_client(handler)
    with pytest.raises(OpenFinanceError) as exc:
        asyncio.run(client.get_connection("missing"))
    asyncio.run(client.close())
    assert exc.value.status_code == 404
    assert "No connection" in exc.value.message


def test_transactions_date_filter_drops_limit():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"accessToken": "t", "expiresIn": 1000})
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": []})

    client = _make_client(handler)
    asyncio.run(client.list_transactions(date_from="2026-01-01", date_to="2026-02-01"))
    asyncio.run(client.close())

    assert captured["params"].get("dateFrom") == "2026-01-01"
    assert "limit" not in captured["params"]  # mutually exclusive with date filters
