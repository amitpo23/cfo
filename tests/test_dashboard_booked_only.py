"""Cash flow counts BOOKED Open Finance rows only; one P&L source per month.

PR A + E core of the Eliav → Rezef migration plan. No provider calls.
"""
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, Invoice, InvoiceStatus
from cfo.services import bank_status
from cfo.services.dashboards import books, filing
from cfo.services.dashboards.view_model import build_view
from cfo.services.live_cash_flow_service import LiveCashFlowService

GOLDEN = Path(__file__).parent / "fixtures" / "eliav_filing_golden.json"
# The Eliav tool's counterparties. Production code does not carry these names.
_ELIAV_FILING_SCOPE = {
    "pairs": [
        {"organizationId": 2, "accountId": 35},
        {"organizationId": 6},
    ],
    "aliases": [
        ["אליאב", "כהן"],
        ["אליהב", "כהן"],
        "פוד גרופ",
        "פודגרופ",
        "food group",
    ],
}
DUMP = os.environ.get("REZEF_ELIAV_DUMP")  # read-only copy of org 2 / account 35 rows


def _account(db, org_id, name, raw_type="CHECKING", account_type=AccountType.BANK):
    account = Account(
        organization_id=org_id, name=name, account_type=account_type, source="open_finance",
        external_id=f"acc-{name}-{org_id}", currency="ILS", raw_account_type=raw_type,
    )
    db.add(account)
    db.flush()
    return account


def _tx(db, org_id, account, ext, day, amount, description, status="BOOKED", ref=None, eod=None, **raw):
    data = {"status": status}
    if ref is not None:
        data["entryReference"] = ref
    if eod is not None:
        data["balancePerEndDay"] = eod
    data.update(raw)
    row = BankTransaction(
        organization_id=org_id, source="open_finance", external_id=ext, account_id=account.id,
        transaction_date=day, amount=Decimal(str(amount)), description=description,
        currency="ILS", raw_data=data,
    )
    db.add(row)
    db.flush()
    return row


def _august(db, org_id):
    """Booked rows, their PENDING twins, a future card charge and a card account."""
    checking = _account(db, org_id, "checking")
    card = _account(db, org_id, "visa", raw_type="CARD", account_type=AccountType.LIABILITY)
    _tx(db, org_id, checking, "b1", date(2026, 7, 30), -100, "עמלה", eod=-1000)
    _tx(db, org_id, checking, "p1", date(2026, 8, 16), 40000, "העברת יומן", status="PENDING", ref="14073")
    _tx(db, org_id, checking, "b2", date(2026, 8, 16), 40000, "העברה באינטרנט", ref="14073", eod=39000)
    _tx(db, org_id, checking, "p2", date(2026, 8, 17), 10000, "הפקדת מזומן בסניף", status="PENDING", ref="4201")
    _tx(db, org_id, checking, "b3", date(2026, 8, 17), 10000, "הפקדת מזומן", ref="4201", eod=49000)
    _tx(db, org_id, checking, "p3", date(2026, 8, 16), -18523.08, "חיובים עתידיים מחברת ויזה כא",
        status="PENDING", ref="0310")
    _tx(db, org_id, checking, "b4", date(2026, 8, 20), -19112.91, "ויזה כאל", eod=29887.09)
    _tx(db, org_id, checking, "p4", date(2026, 8, 30), -250, "תשלום ספק", status="PENDING", ref="9")
    _tx(db, org_id, card, "c1", date(2026, 8, 5), -700, "סופר", merchantName="שופרסל", type="CARD")
    _tx(db, org_id, card, "c2", date(2026, 8, 9), -300, "דלק", merchantName="פז", type="CARD")
    db.commit()
    return checking, card


def test_cash_flow_counts_booked_rows_only(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        _august(db, org["org_id"])
        cash = LiveCashFlowService(db, org["org_id"]).monthly_cash_flow(months=2, as_of_date=date(2026, 8, 31))
        aug = next(m for m in cash["months"] if m["month"] == "2026-08")
        # PENDING twins (40,000 and 10,000), the future card charge and card rows are out.
        assert aug["inflows"] == 50000.0
        assert aug["outflows"] == 19112.91
        pending = bank_status.pending_summary(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31))
        assert pending["excluded_future_card_charges"] == 1
        assert pending["count"] == 3
        assert pending["months"] == [{"month": "2026-08", "inflows": 50000.0, "outflows": 250.0, "count": 3}]


def test_card_accounts_are_detail_only(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        _august(db, org["org_id"])
        detail = bank_status.card_breakdown(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31))
        assert detail["role"] == "detail"
        assert detail["months"][0]["total"] == 1000.0
        assert {m["merchant"] for m in detail["months"][0]["merchants"]} == {"שופרסל", "פז"}
        view = build_view(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31))
        aug = view["cashflow"]["months"][-1]
        assert aug["outflows"] == 19112.91  # the card charge once, from checking
        assert view["cashflow"]["basis"] == "booked_only"
        assert view["card_breakdown"]["months"][0]["total"] == 1000.0
        assert view["provider_calls"] == 0


def test_booked_sum_matches_the_daily_balance_change(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        checking, _card = _august(db, org["org_id"])
        months = bank_status.balance_reconciliation(
            db, org["org_id"], checking.id, date(2026, 8, 1), date(2026, 8, 31),
        )
        assert months == [{"month": "2026-08", "opening": -1000.0, "booked_net": 30887.09,
                           "closing": 29887.09, "diff": 0.0}]


def test_booked_supersedes_its_pending_twin(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        checking = _account(db, org["org_id"], "checking")
        pending = _tx(db, org["org_id"], checking, "p", date(2026, 8, 14), -1375.31, "חיוב בגין פרעון",
                      status="PENDING", ref="00507001")
        # Same reference a month later with another amount: a different repayment.
        later = _tx(db, org["org_id"], checking, "p2", date(2026, 9, 14), -1373.37, "חיוב בגין פרעון",
                    status="PENDING", ref="00507001")
        booked = _tx(db, org["org_id"], checking, "b", date(2026, 8, 15), -1375.31, "הלוואה- פרעון", ref="00507001")
        assert bank_status.supersede_pending(db, booked) == 1
        assert pending.superseded_by_id == booked.id
        assert later.superseded_by_id is None
        assert bank_status.supersede_pending(db, booked) == 0  # idempotent
        # A PENDING that arrives after its BOOKED twin is marked at once.
        booked2 = _tx(db, org["org_id"], checking, "b2", date(2026, 9, 15), -1373.37, "הלוואה- פרעון", ref="00507001")
        late = _tx(db, org["org_id"], checking, "p3", date(2026, 9, 15), -1373.37, "x", status="PENDING", ref="00507001")
        assert bank_status.supersede_by_booked_twin(db, late) == 1
        assert late.superseded_by_id == booked2.id
        # Future card charges have no BOOKED twin and are never superseded.
        future = _tx(db, org["org_id"], checking, "f", date(2026, 9, 14), -6616.36, "חיובים עתידיים מחברת ויזה כא",
                     status="PENDING", ref="03104341")
        assert bank_status.supersede_by_booked_twin(db, future) == 0
        db.rollback()


def test_sync_upsert_supersedes_pending(client, fresh_org):
    from cfo.services.connector_base import NormalizedBankTransaction
    from cfo.services.sync_engine import SyncEngine

    org = fresh_org()
    with SessionLocal() as db:
        checking = _account(db, org["org_id"], "checking")
        db.commit()
        engine = SyncEngine.__new__(SyncEngine)
        engine.db, engine.org_id, engine.source = db, org["org_id"], "open_finance"

        def item(ext, status, description):
            return NormalizedBankTransaction(
                external_id=ext, account_external_id=checking.external_id,
                transaction_date=date(2026, 8, 16), amount=Decimal("40000"), currency="ILS",
                description=description, raw_data={"status": status, "entryReference": "14073"},
            )
        assert engine._upsert_bank_transaction(item("of-p", "PENDING", "העברת יומן")) == "created"
        assert engine._upsert_bank_transaction(item("of-b", "BOOKED", "העברה באינטרנט")) == "created"
        db.flush()
        rows = {r.external_id: r for r in db.query(BankTransaction).filter_by(organization_id=org["org_id"]).all()}
        assert rows["of-p"].superseded_by_id == rows["of-b"].id
        assert rows["of-b"].superseded_by_id is None
        db.rollback()


@pytest.mark.parametrize("case", json.loads(GOLDEN.read_text(encoding="utf-8")),
                         ids=lambda c: f"{c['description'] or 'empty'}|{c['amount']}|{c['org']}")
def test_filing_matches_the_eliav_tool(case):
    """Expected values were produced by the tool's own classifyTxn (status-model.js)."""
    t = filing.Txn(id=None, organization_id=case["org"], account_id=case["account"], date="2026-08-01",
                   amount=float(case["amount"]), description=case["description"],
                   debtor=case["debtor"], creditor=case["creditor"])
    assert filing.classify_builtin(t, scope=_ELIAV_FILING_SCOPE)[0] == case["expected"]


def test_filing_precedence_decision_then_custom_rule_then_builtin():
    t = filing.Txn(id=7, organization_id=2, account_id=35, date="2026-08-03", amount=-5000.0,
                   description="העברה באינטרנט")
    assert filing.classify(t).category == "transfers_out"
    rules = [{"id": "r1", "contains": "העברה", "category": "salaries", "direction": "out"}]
    assert filing.classify(t, custom_rules=rules).filed_by == "custom_rule:r1"
    assert filing.classify(t, custom_rules=rules).category == "salaries"
    decision = {"7": {"category": "rent", "organizationId": 2, "date": "2026-08-03", "amount": -5000}}
    got = filing.classify(t, decisions=decision, custom_rules=rules)
    assert (got.category, got.filed_by) == ("rent", "decision")
    stale = {"7": {"category": "rent", "organizationId": 2, "date": "2026-08-03", "amount": -4000}}
    got = filing.classify(t, decisions=stale, custom_rules=rules)
    assert got.category == "salaries" and got.decision_mismatch


def _partial_books(db, org_id):
    checking = _account(db, org_id, "checking")
    _tx(db, org_id, checking, "s1", date(2026, 8, 5), 11800, "הפקדת מזומן")
    _tx(db, org_id, checking, "s2", date(2026, 8, 7), -5900, "שיק 1001")
    _tx(db, org_id, checking, "s3", date(2026, 8, 8), -118, "בזק")
    _tx(db, org_id, checking, "s4", date(2026, 8, 9), -2000, "הלוואה- פרעון")
    db.add(Invoice(organization_id=org_id, invoice_number="a-1", issue_date=date(2026, 8, 3),
                   status=InvoiceStatus.SENT, subtotal=Decimal("10000"), tax=Decimal("1800"),
                   total=Decimal("1180000")))
    db.commit()


def test_partial_books_month_uses_cash_basis_and_never_mixes(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        _partial_books(db, org["org_id"])
        pnl = books.monthly_pnl(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31))
        aug = pnl["months"][0]
        # Books have revenue but no costs while the bank shows 5,100 ex-VAT costs: partial.
        assert aug["coverage"] == "partial"
        assert aug["source"] == "cash_basis"
        assert aug["source_label"].startswith("בסיס מזומן")
        assert aug["revenue"] == 10000.0  # 11,800 / 1.18
        assert aug["costs"] == 5100.0      # (5,900 + 118) / 1.18; loan principal is not a cost
        assert aug["net"] == 4900.0
        assert "revenue_by_category" not in aug  # no ledger numbers inside a cash month
        view = build_view(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31))
        assert view["pnl"]["basis"] == "cash_basis"
        assert view["pnl"]["net_income_before_tax"] == 4900.0
        bva = view["budget_vs_actual"]["months"][0]
        assert bva["source"] == "cash_basis"
        assert {line["category"] for line in bva["categories"]} >= {"revenue", "suppliers"}


def test_closed_month_in_the_plan_uses_the_books(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        _partial_books(db, org["org_id"])
        pnl = books.monthly_pnl(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31),
                                plan={"booksClosedMonths": ["2026-08"]})
        aug = pnl["months"][0]
        assert (aug["coverage"], aug["source"]) == ("closed", "ledger")
        assert aug["revenue"] == 10000.0 and aug["costs"] == 0.0
        assert "lines" not in aug


def test_publish_refuses_a_ledger_month_with_partial_books():
    with pytest.raises(ValueError):
        books.assert_publishable({"months": [{"month": "2026-08", "source": "ledger", "coverage": "partial"}]})
    books.assert_publishable({"months": [{"month": "2026-08", "source": "cash_basis", "coverage": "partial"}]})


def test_plan_rejects_unknown_filing_categories(client, fresh_org):
    org = fresh_org()
    created = client.post("/api/dashboards", headers=org["headers"], json={
        "primary_organization_id": org["org_id"], "slug": f"plan-filing-{org['org_id']}",
        "title": "x", "access_mode": "link",
    })
    dashboard_id = created.json()["id"]
    bad = client.put(f"/api/dashboards/{dashboard_id}/plan", headers={**org["headers"], "If-Match": "null"},
                     json={"payload": {"statusRules": [{"contains": "x", "category": "other_in"}]}})
    assert bad.json()["error"]["code"] == "invalid_plan"
    assert bad.status_code == 422, bad.text
    good = client.put(f"/api/dashboards/{dashboard_id}/plan", headers={**org["headers"], "If-Match": "null"},
                      json={"payload": {
                          "statusRules": [{"id": "r1", "contains": "בזק", "category": "office"}],
                          "statusDecisions": {"12": {"category": "rent", "organizationId": org["org_id"],
                                                     "date": "2026-08-01", "amount": -100}},
                          "booksClosedMonths": ["2026-08"]}})
    assert good.status_code == 200, good.text


@pytest.mark.skipif(not DUMP or not Path(DUMP).exists(), reason="set REZEF_ELIAV_DUMP to the read-only org 2 copy")
def test_eliav_august_and_september_match_the_tool(client, fresh_org):
    """Real rows of account 8954 (BOOKED + PENDING), loaded into a scratch org."""
    data = json.loads(Path(DUMP).read_text(encoding="utf-8"))
    org = fresh_org()
    with SessionLocal() as db:
        checking = _account(db, org["org_id"], "8954")
        for row in data["transactions"] + data["pending_transactions"] + data["unknown_status_transactions"]:
            raw = {"status": row["bank_status"], "entryReference": row["reference"]}
            if row.get("balance_per_end_day") is not None:
                raw["balancePerEndDay"] = row["balance_per_end_day"]
            db.add(BankTransaction(
                organization_id=org["org_id"], source="open_finance", external_id=row["external_id"],
                account_id=checking.id, transaction_date=date.fromisoformat(row["date"]),
                amount=Decimal(str(row["amount"])), description=row["description"], currency="ILS",
                raw_data={k: v for k, v in raw.items() if v is not None},
            ))
        db.commit()
        cash = LiveCashFlowService(db, org["org_id"]).monthly_cash_flow(months=3, as_of_date=date(2026, 9, 30))
        by_month = {m["month"]: m for m in cash["months"]}
        assert by_month["2026-08"]["inflows"] == 111358.83
        assert by_month["2026-08"]["outflows"] == 96465.58
        assert by_month["2026-09"]["inflows"] == 67280.0
        assert by_month["2026-09"]["outflows"] == 70205.32
        for month in bank_status.balance_reconciliation(db, org["org_id"], checking.id,
                                                        date(2026, 1, 1), date(2026, 9, 30)):
            if month["diff"] is not None:
                assert month["diff"] == 0.0, month
