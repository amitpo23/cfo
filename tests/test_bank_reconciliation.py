"""Tests for bank reconciliation matching."""
from datetime import date

from cfo.services.bank_reconciliation import reconcile, BankTxnLite, DocLite


def test_inflow_and_outflow_propose_candidates_without_confirming():
    txns = [
        BankTxnLite(1, 1170.0, date(2026, 6, 5), "תשלום מאת אקמה"),
        BankTxnLite(2, -450.0, date(2026, 6, 7), "ספק כלשהו"),
        BankTxnLite(3, -99.0, date(2026, 6, 9), "לא ידוע"),
    ]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 4), "אקמה בעמ")]
    bills = [DocLite("b1", "bill", 450.0, date(2026, 6, 6), "ספק כלשהו")]

    res = reconcile(txns, invoices, bills, [])
    assert res["matched_count"] == 0
    assert res["candidate_count"] == 2
    matched = {m["bank_txn_id"]: (m["entity_type"], m["entity_id"]) for m in res["candidates"]}
    assert matched[1] == ("invoice", "i1")
    assert matched[2] == ("bill", "b1")
    assert res["unmatched_txns"] == [1, 2, 3]


def test_amount_outside_tolerance_does_not_match():
    txns = [BankTxnLite(1, -100.0, date(2026, 6, 5), "x")]
    bills = [DocLite("b1", "bill", 130.0, date(2026, 6, 5), "x")]
    res = reconcile(txns, [], bills, [])
    assert res["matched_count"] == 0
    assert res["unmatched_txns"] == [1]


def test_equal_amount_candidates_do_not_claim_document():
    txns = [
        BankTxnLite(1, -200.0, date(2026, 6, 5), "ספק"),
        BankTxnLite(2, -200.0, date(2026, 6, 6), "ספק"),
    ]
    bills = [DocLite("b1", "bill", 200.0, date(2026, 6, 5), "ספק")]
    res = reconcile(txns, [], bills, [])
    # Both remain review candidates; neither claims the document.
    assert res["matched_count"] == 0
    assert res["candidate_count"] == 2
    assert len(res["unmatched_txns"]) == 2


def test_score_capped_at_one():
    txns = [BankTxnLite(1, 1000.0, date(2026, 6, 5), "אקמה בעמ")]
    invoices = [DocLite("i1", "invoice", 1000.0, date(2026, 6, 5), "אקמה בעמ")]
    res = reconcile(txns, invoices, [], [])
    assert res["candidates"][0]["score"] <= 1.0


def test_unmatched_txn_details_carries_is_provisional_additively():
    """unmatched_txns stays a bare list[int] (existing consumers:
    financial_synthesis.py, BankInsightsDashboard.tsx's number[] typing) --
    is_provisional surfaces only via a new, additive field."""
    txns = [
        BankTxnLite(1, -99.0, date(2026, 6, 9), "לא ידוע", is_provisional=True),
        BankTxnLite(2, -50.0, date(2026, 6, 9), "גם לא ידוע", is_provisional=False),
    ]
    res = reconcile(txns, [], [], [])
    assert res["unmatched_txns"] == [1, 2]
    details = {d["id"]: d["is_provisional"] for d in res["unmatched_txn_details"]}
    assert details == {1: True, 2: False}
