"""Tests for VAT split recovery + connector mapping."""
from datetime import date
from decimal import Decimal

from cfo.services.vat_utils import split_inclusive, vat_rate_for


def test_rate_by_date():
    assert vat_rate_for(date(2025, 6, 1)) == Decimal("0.18")
    assert vat_rate_for(date(2024, 6, 1)) == Decimal("0.17")


def test_split_inclusive_18pct_reconstructs_gross():
    sub, vat = split_inclusive(23600, date(2025, 6, 30))
    # 23600 / 1.18 = 20000 net, 3600 VAT.
    assert sub == Decimal("20000.00")
    assert vat == Decimal("3600.00")
    assert sub + vat == Decimal("23600.00")


def test_split_preserves_sign_for_credit_notes():
    sub, vat = split_inclusive(-23600, date(2025, 6, 30))
    assert sub == Decimal("-20000.00")
    assert vat == Decimal("-3600.00")
    assert sub + vat == Decimal("-23600.00")


def test_split_zero_is_zero():
    assert split_inclusive(0, date(2025, 1, 1)) == (Decimal("0.00"), Decimal("0.00"))


def test_connector_list_mapping_derives_vat():
    from cfo.integrations.sumit_integration import SumitIntegration
    intg = SumitIntegration(api_key="k", company_id="1")
    doc = {"DocumentID": 5, "DocumentNumber": "100", "Type": 5,
           "DocumentValue": 23600, "Date": "2025-06-30", "CustomerID": 9}
    resp = intg._document_response_from_list(doc)
    assert resp.total_amount == Decimal("23600")
    assert resp.vat_amount == Decimal("3600.00")


def test_connector_prefers_explicit_vat_field():
    from cfo.integrations.sumit_integration import SumitIntegration
    intg = SumitIntegration(api_key="k", company_id="1")
    doc = {"DocumentID": 6, "DocumentValue": 1000, "Date": "2025-06-30", "VAT": 123}
    resp = intg._document_response_from_list(doc)
    assert resp.vat_amount == Decimal("123")


# --- live SUMIT connector (sumit_connector) VAT derivation -------------------
# The live sync path uses SumitConnector, not SumitIntegration. It must derive
# VAT via inclusive split when the document carries no vat_amount, instead of
# silently zeroing it (which under-reports VAT in the ledger / VAT report / P&L).
class _FakeDoc:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_live_connector_splits_when_vat_amount_absent():
    from cfo.services.sumit_connector import _derive_subtotal_tax
    doc = _FakeDoc(date=date(2025, 6, 30))  # no vat_amount attribute at all
    subtotal, tax = _derive_subtotal_tax(doc, Decimal("23600"))
    assert tax == Decimal("3600.00")
    assert subtotal == Decimal("20000.00")
    assert subtotal + tax == Decimal("23600")


def test_live_connector_splits_when_vat_amount_none():
    from cfo.services.sumit_connector import _derive_subtotal_tax
    doc = _FakeDoc(date=date(2025, 6, 30), vat_amount=None)
    subtotal, tax = _derive_subtotal_tax(doc, Decimal("23600"))
    assert tax == Decimal("3600.00")
    assert subtotal + tax == Decimal("23600")


def test_live_connector_respects_explicit_vat_amount():
    from cfo.services.sumit_connector import _derive_subtotal_tax
    doc = _FakeDoc(date=date(2025, 6, 30), vat_amount=Decimal("180.00"))
    subtotal, tax = _derive_subtotal_tax(doc, Decimal("1180.00"))
    assert tax == Decimal("180.00")
    assert subtotal == Decimal("1000.00")


def test_live_connector_respects_explicit_subtotal_when_present():
    from cfo.services.sumit_connector import _derive_subtotal_tax
    doc = _FakeDoc(date=date(2025, 6, 30), vat_amount=Decimal("180.00"),
                   subtotal=Decimal("1000.00"))
    subtotal, tax = _derive_subtotal_tax(doc, Decimal("1180.00"))
    assert subtotal == Decimal("1000.00")
    assert tax == Decimal("180.00")
