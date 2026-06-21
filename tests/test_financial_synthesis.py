"""Tests for the cross-source synthesis engine (SUMIT books + bank)."""
from datetime import date

from cfo.services.financial_synthesis import build_synthesis, link_payments, PaymentLite
from cfo.services.bank_reconciliation import BankTxnLite, DocLite


def _actions_by_type(report):
    out = {}
    for a in report["required_actions"]:
        out.setdefault(a["type"], []).append(a)
    return out


def test_unmatched_outflow_becomes_file_expense_action():
    bank = [BankTxnLite(1, -300.0, date(2026, 6, 5), "ספק לא ידוע")]
    report = build_synthesis(bank, [], [], [])
    by = _actions_by_type(report)
    assert "file_expense" in by
    assert by["file_expense"][0]["amount"] == 300.0


def test_unmatched_inflow_becomes_record_income_action():
    bank = [BankTxnLite(1, 900.0, date(2026, 6, 5), "תקבול")]
    report = build_synthesis(bank, [], [], [])
    by = _actions_by_type(report)
    assert "record_income" in by


def test_matched_bank_to_invoice_produces_no_action():
    bank = [BankTxnLite(1, 1170.0, date(2026, 6, 6), "אקמה")]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 6), "אקמה")]
    report = build_synthesis(bank, invoices, [], [])
    assert report["reconciliation"]["matched"] == 1
    # The matched invoice should not appear as uncollected.
    assert "collect_receivable" not in _actions_by_type(report)


def test_unpaid_invoice_without_bank_match_is_uncollected():
    invoices = [DocLite("i2", "invoice", 500.0, date(2026, 5, 1), "בטא")]
    report = build_synthesis([], invoices, [], [], unpaid_invoice_ids={"i2"})
    by = _actions_by_type(report)
    assert "collect_receivable" in by


def test_vat_position():
    report = build_synthesis([], [], [], [], output_vat=1800.0, input_vat=500.0)
    vat = report["vat_summary"]
    assert vat["output_vat"] == 1800.0
    assert vat["input_vat"] == 500.0
    assert vat["net_vat"] == 1300.0
    assert vat["direction"] == "לתשלום"


def test_vat_refund_direction():
    report = build_synthesis([], [], [], [], output_vat=100.0, input_vat=400.0)
    assert report["vat_summary"]["net_vat"] == -300.0
    assert report["vat_summary"]["direction"] == "להחזר"


def test_link_payment_to_invoice():
    pays = [PaymentLite("p1", 1170.0, date(2026, 6, 7), name="אקמה")]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 6), "אקמה"),
                DocLite("i2", "invoice", 500.0, date(2026, 5, 1), "בטא")]
    res = link_payments(pays, invoices, [])
    assert res["linked_count"] == 1
    assert res["links"][0]["entity_type"] == "invoice"
    assert res["links"][0]["entity_id"] == "i1"


def test_payment_amount_mismatch_not_linked():
    pays = [PaymentLite("p1", 999.0, date(2026, 6, 7), name="אקמה")]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 6), "אקמה")]
    res = link_payments(pays, invoices, [])
    assert res["linked_count"] == 0
    assert res["unlinked"] == ["p1"]
