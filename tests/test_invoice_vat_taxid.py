"""חשבונית מס מרצף: מחיר נטו + מע"מ, ח.פ לקוח, ושליחה במייל רק לבקשה.

כל הקריאות ל-SUMIT מדומות (``_post`` / connector מזויף). שמות ומספרים סינתטיים.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.integrations.sumit_integration import SumitIntegration
from cfo.integrations.sumit_models import DocumentItem, DocumentRequest, DocumentResponse
from cfo.models import Contact, Invoice
from cfo.services import document_issuance_service
from cfo.services.document_issuance_service import DocumentIssuanceService

ISSUE = date(2026, 11, 9)
SYNTHETIC_TAX_ID = "123456782"


class _UnlimitedTestBudget:
    def claim(self, _kind):
        return None


def _sumit_capturing():
    sumit = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
        request_limiter=_UnlimitedTestBudget(),
    )
    sumit._enforce_paid_action_budget = lambda endpoint: None
    calls = []

    async def _post(path, payload):
        calls.append((path, payload))
        return {"DocumentID": 7001, "DocumentNumber": 30001, "CustomerID": 501}

    sumit._post = _post
    return sumit, calls


def _create(request):
    sumit, calls = _sumit_capturing()

    async def run():
        try:
            return await sumit.create_document(request)
        finally:
            await sumit.client.aclose()

    return asyncio.run(run()), calls


def _invoice_request(**overrides):
    fields = dict(
        customer_id="לקוח בדיקה בע\"מ",
        document_type="invoice",
        items=[DocumentItem(description="ייעוץ", quantity=Decimal("1"),
                            price=Decimal("60000"), vat_rate=Decimal("18"))],
        issue_date=ISSUE,
    )
    fields.update(overrides)
    return DocumentRequest(**fields)


# ==================== Fix 1 — VAT ====================

def test_net_price_is_sent_as_vat_excluded_and_totals_include_vat():
    response, calls = _create(_invoice_request())

    path, payload = calls[0]
    assert path == "/accounting/documents/create/"
    assert payload["VATIncluded"] is False
    # יחידת VATRate ב-SUMIT (18 או 0.18) לא מתועדת; בשיעור החוקי לא שולחים
    # אותו ו-SUMIT מחיל את ברירת המחדל של החברה.
    assert "VATRate" not in payload
    assert payload["Items"][0]["UnitPrice"] == 60000.0
    assert response.total_amount == Decimal("70800")
    assert response.vat_amount == Decimal("10800")


def test_gross_price_mode_keeps_vat_included():
    request = _invoice_request(
        items=[DocumentItem(description="ייעוץ", price=Decimal("70800"), vat_rate=Decimal("18"))],
        prices_include_vat=True,
    )
    response, calls = _create(request)

    assert calls[0][1]["VATIncluded"] is True
    assert response.total_amount == Decimal("70800")
    assert response.vat_amount == Decimal("10800")


def test_default_request_is_net():
    assert DocumentRequest(customer_id="x", document_type="invoice", items=[]).prices_include_vat is False


@pytest.mark.parametrize("rate", ["17", "0"])
def test_non_statutory_vat_rate_is_refused_before_any_sumit_call(rate):
    request = _invoice_request(
        items=[DocumentItem(description="ייעוץ", price=Decimal("100"), vat_rate=Decimal(rate))],
    )
    with pytest.raises(ValueError, match="מע\"מ"):
        _create(request)


# ==================== Fix 3 — document type + email ====================

def test_invoice_maps_to_tax_invoice_only():
    assert SumitIntegration._map_document_type("invoice") == "Invoice"
    assert SumitIntegration._map_document_type("invoice_receipt") == "InvoiceAndReceipt"
    _response, calls = _create(_invoice_request())
    assert calls[0][1]["Details"]["Type"] == "Invoice"


def test_no_send_by_email_unless_requested():
    _response, calls = _create(_invoice_request(customer_email="client@example.com"))
    assert "SendByEmail" not in calls[0][1]["Details"]


def test_send_by_email_with_recipient_override():
    _response, calls = _create(_invoice_request(
        send_by_email=True, email_address="billing@example.com",
    ))
    assert calls[0][1]["Details"]["SendByEmail"] == {
        "EmailAddress": "billing@example.com",
        "Original": True,
        "SendAsPaymentRequest": False,
    }


# ==================== Fix 2 — customer ח.פ ====================

def test_new_customer_by_name_carries_company_number_and_email():
    _response, calls = _create(_invoice_request(
        customer_tax_id=SYNTHETIC_TAX_ID, customer_email="client@example.com",
    ))
    assert calls[0][1]["Details"]["Customer"] == {
        "Name": "לקוח בדיקה בע\"מ",
        "SearchMode": "Automatic",
        "CompanyNumber": SYNTHETIC_TAX_ID,
        "EmailAddress": "client@example.com",
    }


def test_existing_sumit_customer_is_referenced_by_id():
    _response, calls = _create(_invoice_request(customer_id="501", customer_tax_id=SYNTHETIC_TAX_ID))
    assert calls[0][1]["Details"]["Customer"] == {"ID": 501}


# ==================== service layer ====================

class _FakeClient:
    def __init__(self):
        self.requests = []
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def create_document(self, request):
        self.requests.append(request)
        return DocumentResponse(
            document_id="SUMIT-T-1", document_number="30001", document_type=request.document_type,
            customer_id="501", total_amount=Decimal("0"), vat_amount=Decimal("0"),
            status="open", issue_date=ISSUE,
        )

    async def send_document(self, request):
        self.sent.append(request)
        return {}


@pytest.fixture
def fake_sumit(monkeypatch):
    client = _FakeClient()

    class _Connector:
        async def _get_client(self):
            return client

    monkeypatch.setattr(
        document_issuance_service, "get_connector_for_org",
        lambda _db, _org, preferred_source=None: (_Connector(), 1, "sumit"),
    )
    return client


def _issue(org, **kwargs):
    fields = dict(
        document_type="invoice",
        customer_id="לקוח סינתטי",
        customer_name="לקוח סינתטי",
        issue_date=ISSUE,
        items=[{"description": "ייעוץ", "quantity": 1, "unit_price": 60000, "vat_rate": 18}],
    )
    fields.update(kwargs)
    with SessionLocal() as db:
        result = asyncio.run(DocumentIssuanceService(db, org["org_id"]).create_document(**fields))
        contact = db.query(Contact).filter(
            Contact.organization_id == org["org_id"], Contact.name == fields["customer_name"],
        ).first()
        return result, contact.tax_id if contact else None


def test_service_passes_normalized_tax_id_and_stores_it(fake_sumit, fresh_org):
    result, stored = _issue(fresh_org(), customer_tax_id="12-345678-2")
    request = fake_sumit.requests[0]
    assert request.customer_tax_id == SYNTHETIC_TAX_ID
    assert request.prices_include_vat is False
    assert stored == SYNTHETIC_TAX_ID
    assert result["subtotal"] == 60000
    assert result["total"] == 70800
    assert result["warnings"] == []


@pytest.mark.parametrize("bad", ["12345", "12345678a", "1234567890"])
def test_service_rejects_malformed_tax_id_in_hebrew(fake_sumit, fresh_org, bad):
    with pytest.raises(ValueError, match="ח.פ"):
        _issue(fresh_org(), customer_tax_id=bad)
    assert fake_sumit.requests == []


def test_allocation_warning_when_over_threshold_without_tax_id(fake_sumit, fresh_org):
    result, _ = _issue(fresh_org())
    assert any("הקצאה" in w for w in result["warnings"])


def test_no_allocation_warning_below_threshold(fake_sumit, fresh_org):
    result, _ = _issue(fresh_org(), items=[
        {"description": "ייעוץ", "quantity": 1, "unit_price": 1000, "vat_rate": 18},
    ])
    assert result["warnings"] == []


def test_missing_vat_rate_defaults_to_dated_statutory_rate(fake_sumit, fresh_org):
    result, _ = _issue(fresh_org(), items=[{"description": "ייעוץ", "quantity": 1, "unit_price": 100}])
    assert fake_sumit.requests[0].items[0].vat_rate == Decimal("18")
    assert result["total"] == 118


def test_gross_mode_splits_vat_out_of_the_price(fake_sumit, fresh_org):
    result, _ = _issue(fresh_org(), prices_include_vat=True, items=[
        {"description": "ייעוץ", "quantity": 1, "unit_price": 70800, "vat_rate": 18},
    ])
    assert fake_sumit.requests[0].prices_include_vat is True
    assert result["subtotal"] == 60000
    assert result["tax"] == 10800
    assert result["total"] == 70800


def test_email_is_sent_only_when_asked_with_override(fake_sumit, fresh_org):
    _issue(fresh_org(), recipient_email="client@example.com", send_email=False)
    assert fake_sumit.requests[0].send_by_email is False

    _issue(fresh_org(), customer_name="לקוח שני", recipient_email="client@example.com",
           send_email=True, send_to_email="billing@example.com")
    request = fake_sumit.requests[1]
    assert request.send_by_email is True
    assert request.email_address == "billing@example.com"
    # SendByEmail בתוך בקשת היצירה — בלי קריאת send נפרדת בתשלום.
    assert fake_sumit.sent == []


# ==================== route + approval gate ====================

def test_approved_route_accepts_new_fields(client, fake_sumit, fresh_org):
    from test_document_issuance import _approved_document
    org = fresh_org()
    body = {
        "document_type": "invoice",
        "customer_id": "לקוח מסלול",
        "customer_name": "לקוח מסלול",
        "customer_email": "client@example.com",
        "customer_tax_id": SYNTHETIC_TAX_ID,
        "prices_include_vat": False,
        "send_to_sumit": True,
        "send_email": True,
        "recipient_email": "billing@example.com",
        "items": [{"description": "ייעוץ", "quantity": 1, "unit_price": 60000, "vat_rate": 18}],
    }
    approval_id = _approved_document(org, body, "invoice-vat-taxid-route")
    response = client.post(
        "/api/financial/documents", json=body,
        headers={**org["headers"], "X-Rezef-Approval-Id": str(approval_id)},
    )
    assert response.status_code == 200, response.text
    request = fake_sumit.requests[0]
    assert request.customer_tax_id == SYNTHETIC_TAX_ID
    assert request.send_by_email is True
    assert request.email_address == "billing@example.com"
    assert response.json()["data"]["total"] == 70800


def test_invoices_route_does_not_auto_send_when_email_present():
    from cfo.api.routes.financial_operations import CreateInvoiceRequest
    request = CreateInvoiceRequest(
        customer_id="c", customer_name="c", customer_email="client@example.com",
        items=[{"description": "x", "quantity": 1, "unit_price": 1}],
    )
    assert request.send_email is False
    assert request.items[0].vat_rate is None
