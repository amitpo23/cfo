"""SUMIT_MODULE_COVERAGE.md listed "payment pages" as a vague Partial item.
The real API surface is POST /billing/payments/beginredirect/ (verified
against the downloaded swagger.json) — given a customer + line items, SUMIT
creates the accounting document AND a hosted payment page, returning
RedirectURL for the customer to pay via. Useful for the collections
workflow: send a payment link with an overdue-invoice reminder instead of
just a balance notice.
"""
import asyncio

import httpx

from cfo.integrations.sumit_integration import SumitAPIError, SumitIntegration
from cfo.integrations.sumit_models import ChargeRequest


def _sumit():
    return SumitIntegration(api_key="test-key", company_id="1")


def test_create_payment_link_returns_the_redirect_url():
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0,
                "Data": {"RedirectURL": "https://pay.sumit.co.il/abc123"},
            })

        sumit.client.request = _fake_post
        try:
            return await sumit.create_payment_link(
                ChargeRequest(customer_id="Acme Ltd", amount="1500", description="חשבונית INV-1"),
                redirect_url="https://app.example.com/paid",
            )
        finally:
            await sumit.client.aclose()

    result = asyncio.run(_run())

    assert result.payment_url == "https://pay.sumit.co.il/abc123"
    assert captured["url"] == "/billing/payments/beginredirect/"
    assert captured["json"]["Customer"] == {"Name": "Acme Ltd", "SearchMode": "Automatic"}
    assert captured["json"]["Items"][0]["UnitPrice"] == 1500.0
    assert captured["json"]["RedirectURL"] == "https://app.example.com/paid"
    # No CancelRedirectURL/ExpirationHours passed -> must not appear at all.
    assert "CancelRedirectURL" not in captured["json"]


def test_create_payment_link_uses_numeric_customer_id_as_sumit_id():
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0, "Data": {"RedirectURL": "https://pay.sumit.co.il/xyz"},
            })

        sumit.client.request = _fake_post
        try:
            return await sumit.create_payment_link(
                ChargeRequest(customer_id="2095660683", amount="500"),
            )
        finally:
            await sumit.client.aclose()

    asyncio.run(_run())

    assert captured["json"]["Customer"] == {"ID": 2095660683}


def test_create_payment_link_raises_when_sumit_omits_the_url():
    sumit = _sumit()

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={"Status": 0, "Data": {}})

        sumit.client.request = _fake_post
        try:
            return await sumit.create_payment_link(
                ChargeRequest(customer_id="Acme Ltd", amount="1500"),
            )
        finally:
            await sumit.client.aclose()

    try:
        asyncio.run(_run())
        raised = None
    except SumitAPIError as e:
        raised = e

    assert raised is not None
