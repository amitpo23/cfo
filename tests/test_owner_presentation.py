"""Owner presentation: delete a placeholder budget, override an opening, classify without guessing, print a bank pack."""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction
from cfo.services.dashboards import cashflow_truth as truth
from cfo.services.dashboards import liquidity
from cfo.services.dashboards.budget_assumptions import bank_pack, compare_opening, list_assumptions
from cfo.services.dashboards.budget_fill import apply_updates, looks_like_placeholder
from cfo.services.dashboards.filing import Filed, Txn
from cfo.services.dashboards.transfer_queue import apply_accepts, queue_from_filed, suggest


AS_OF = date(2026, 10, 28)


def _txn(txn_id, amount, description, debtor):
    return Txn(txn_id, 1, None, "2026-08-02", amount, description, debtor, "")


def test_the_first_forecast_week_starts_today_and_a_missing_line_does_not_hide_a_known_payment():
    from cfo.services.dashboards.cashflow_truth import week_windows
    assert week_windows(date(2026, 10, 29))[0] == (date(2026, 10, 29), date(2026, 10, 30))
    assert week_windows(date(2026, 10, 29))[1][0] == date(2026, 11, 1)


def test_supplier_default_is_end_of_next_month():
    assert truth.DEFAULT_SUPPLIER_TERMS_MODE == "end_of_next_month"
    assert truth.supplier_due(date(2026, 9, 15), None) == date(2026, 11, 1)


def test_a_placeholder_income_is_warned_and_only_the_owner_deletes_it():
    assert looks_like_placeholder(10_000_000, None)
    assert "לא נמחק" in looks_like_placeholder(10_000_000, 1200)
    assert looks_like_placeholder(62000, 1200) is None

    plan = {"budgetLines": [{
        "id": "sales", "label": "הכנסות", "category": "sales", "kind": "revenue",
        "months": {"2026-10": {"quantity": 1, "rate": 10000000}},
    }]}
    kept = apply_updates(plan, [{"id": "other", "label": "אחר", "category": "office", "kind": "cost", "month": "2026-10", "status": "filled", "amount": 10}])
    assert any(line["id"] == "sales" for line in kept["budgetLines"])
    removed = apply_updates(plan, [{"id": "sales", "remove": True}])
    assert all(line["id"] != "sales" for line in removed["budgetLines"])


def test_budget_entry_shows_the_warning_and_delete_removes_the_line(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "placeholder-budget", "title": "תקציב", "access_mode": "public",
    })
    assert created.status_code == 201, created.text
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [{
        "id": "sales", "label": "הכנסות", "category": "sales", "kind": "revenue",
        "month": "2026-10", "status": "filled", "amount": 10000000,
    }]})
    assert saved.status_code == 200, saved.text
    listed = client.get("/api/financial/budget/lines", headers=owner["headers"], params={
        "year": 2026, "from_month": 10, "to_month": 10,
    })
    line = next(row for row in listed.json()["data"]["lines"] if row["id"] == "sales")
    assert "לא נמחק" in line["placeholder_warning"]
    deleted = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [{
        "id": "sales", "remove": True,
    }]})
    assert deleted.status_code == 200, deleted.text
    again = client.get("/api/financial/budget/lines", headers=owner["headers"], params={
        "year": 2026, "from_month": 10, "to_month": 10,
    })
    assert all(row["id"] != "sales" for row in again.json()["data"]["lines"])


def test_fresh_bank_wins_unless_the_owner_overrides(fresh_org):
    owner = fresh_org()
    synced = datetime(2026, 10, 28, 6, 0)
    plan = {"liquidityEvidence": {"openingBalances": [{
        "date": "2026-10-28", "amount": -12000, "source": "assumption by owner",
        "organizationId": owner["org_id"], "note": "לפי הבעלים", "override": False,
    }]}}
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="chk",
            balance=Decimal("-44000"), balance_as_of=synced, currency="ILS",
        ))
        db.commit()
        fresh = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), AS_OF, plan=plan, classified=[], today=AS_OF,
        )
        plan["liquidityEvidence"]["openingBalances"][0]["override"] = True
        overridden = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), AS_OF, plan=plan, classified=[], today=AS_OF,
        )
    assert fresh["position"]["balance"] == -44000.0
    assert fresh["opening_comparison"]["differs"] is True
    assert fresh["opening_comparison"]["used"] == "bank"
    assert fresh["opening_comparison"]["note"] == "לפי הבעלים"
    assert overridden["position"]["balance"] == -12000.0
    assert overridden["position"]["balance_source"] == "opening_balance"
    assert overridden["opening_comparison"]["used"] == "owner"
    compared = compare_opening(-12000, "2026-10-28", "לפי הבעלים", False, -44000, "2026-10-28", AS_OF)
    assert compared["bank_fresh"] is True and compared["differs"] is True and compared["used"] == "bank"


def test_opening_on_the_budget_form_carries_date_note_and_the_bank_figure(client, fresh_org):
    owner = fresh_org()
    client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "opening-note", "title": "יתרה", "access_mode": "public",
    })
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [{
        "id": "opening_balance", "label": "יתרת פתיחה", "category": "opening_balance", "kind": "financing",
        "month": "2026-10-28", "status": "filled", "amount": -12000, "note": "דף בנק", "override": False,
    }]})
    assert saved.status_code == 200, saved.text
    listed = client.get("/api/financial/budget/lines", headers=owner["headers"], params={
        "year": 2026, "from_month": 10, "to_month": 10,
    })
    opening = next(row for row in listed.json()["data"]["assumptions"] if row["kind"] == "opening_balance")
    assert opening["amount"] == -12000.0
    assert opening["month"] == "2026-10-28"
    assert opening["note"] == "דף בנק"
    assert opening["override"] is False


def test_a_suggestion_is_not_applied_until_the_owner_accepts_it():
    known = _txn(1, -15, "עמלה", "ספק אלפא")
    unknown = _txn(2, -100, "תשלום", "ספק אלפא")
    alone = _txn(3, -50, "תשלום", "שם חדש")
    paired = [
        (known, Filed("bank_fees", "rule:bank_fees", "bank_fees")),
        (unknown, Filed("suppliers_direct", "default", "suppliers_direct")),
        (alone, Filed("suppliers_direct", "default", "suppliers_direct")),
    ]
    report = queue_from_filed(paired, [])
    by_id = {row["id"]: row for row in report["rows"]}
    assert 1 not in by_id
    assert by_id[2]["suggestion"]["suggestion"] is True
    assert by_id[2]["suggestion"]["category"] == "bank_fees"
    assert by_id[2]["category"] is None
    assert by_id[3]["suggestion"] is None
    assert suggest("שם חדש", [], []) is None
    coverage = report["coverage"]
    assert coverage["classified"] + coverage["unclassified"] == coverage["total"]
    assert coverage["balanced"] is True
    assert coverage["total"] == -165.0

    from cfo.services.dashboards.filing import classify
    plan = apply_accepts({}, [{"counterparty": "ספק אלפא", "category": "bank_fees"}])
    assert plan["statusRules"][0]["field"] == "counterparty"
    again = [(txn, classify(txn, custom_rules=plan["statusRules"])) for txn, _filed in paired]
    filed = queue_from_filed(again, plan["statusRules"])
    assert all(row["id"] != 2 for row in filed["rows"])


def test_accepting_a_counterparty_rule_classifies_the_next_transfer(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "classify-queue", "title": "סיווג", "access_mode": "public",
    })
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        db.add(BankTransaction(
            organization_id=owner["org_id"], transaction_date=date(2026, 8, 2),
            amount=Decimal("-15"), description="עמלה", source="open_finance", external_id="fee-1",
            raw_data={"status": "BOOKED", "debtorName": "ספק אלפא"},
        ))
        db.add(BankTransaction(
            organization_id=owner["org_id"], transaction_date=date(2026, 8, 3),
            amount=Decimal("-100"), description="תשלום", source="open_finance", external_id="pay-1",
            raw_data={"status": "BOOKED", "debtorName": "ספק אלפא"},
        ))
        db.commit()
    listed = client.get(
        f"/api/dashboards/{dashboard_id}/unclassified-transfers",
        headers=owner["headers"], params={"start": "2026-07-01", "end": "2026-10-31"},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["coverage"]["balanced"] is True
    waiting = next(row for row in body["rows"] if row["description"] == "תשלום")
    assert waiting["suggestion"]["suggestion"] is True
    assert waiting["category"] is None
    accepted = client.post(
        f"/api/dashboards/{dashboard_id}/classification-rules",
        headers=owner["headers"],
        json={"accepts": [{"counterparty": "ספק אלפא", "category": waiting["suggestion"]["category"]}]},
    )
    assert accepted.status_code == 200, accepted.text
    again = client.get(
        f"/api/dashboards/{dashboard_id}/unclassified-transfers",
        headers=owner["headers"], params={"start": "2026-07-01", "end": "2026-10-31"},
    )
    assert all(row["description"] != "תשלום" for row in again.json()["rows"])


def test_open_finance_payee_is_shown_and_a_blank_counterparty_still_files(client, fresh_org):
    """A bank memo or merchant name fills the counterparty. «אשר» still files a row
    that has none, by the transaction's own date, amount and description.
    A placeholder is not stored as a name, and a sibling with the same date and
    amount but a different description stays in the queue.
    """
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "classify-blank-party", "title": "סיווג", "access_mode": "public",
    })
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        rows = [
            BankTransaction(
                organization_id=owner["org_id"], transaction_date=date(2026, 10, 7),
                amount=Decimal("-5730.00"), description="העב' לאחר-נייד",
                source="open_finance", external_id="blank-diab-day",
                raw_data={"status": "BOOKED"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], transaction_date=date(2026, 10, 7),
                amount=Decimal("-5730.00"), description="העב' לאחר-נייד ב",
                source="open_finance", external_id="sibling-same-amount",
                raw_data={"status": "BOOKED"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], transaction_date=date(2026, 10, 7),
                amount=Decimal("-200.00"), description="העב' לאחר-נייד",
                source="open_finance", external_id="memo-diab",
                raw_data={"status": "BOOKED", "description": {
                    "description": "העב' לאחר-נייד",
                    "additionalInfo": '{"purposeDescription": "דיאב פייסל"}',
                }},
            ),
            BankTransaction(
                organization_id=owner["org_id"], transaction_date=date(2026, 10, 8),
                amount=Decimal("-86.50"), description="חיוב כרטיס",
                source="open_finance", external_id="merchant-pizza",
                raw_data={"status": "BOOKED", "merchantName": "Pizza Market"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], transaction_date=date(2026, 10, 9),
                amount=Decimal("-40.00"), description="העברה בלי שם",
                source="open_finance", external_id="placeholder-merchant",
                raw_data={"status": "BOOKED", "merchantName": "—"},
            ),
        ]
        db.add_all(rows)
        db.commit()
        ids = {row.external_id: row.id for row in rows}

    listed = client.get(
        f"/api/dashboards/{dashboard_id}/unclassified-transfers",
        headers=owner["headers"], params={"start": "2026-07-01", "end": "2026-10-31"},
    )
    assert listed.status_code == 200, listed.text
    by_id = {row["id"]: row for row in listed.json()["rows"]}
    assert by_id[ids["memo-diab"]]["counterparty"] == "דיאב פייסל"
    assert by_id[ids["merchant-pizza"]]["counterparty"] == "Pizza Market"
    assert by_id[ids["blank-diab-day"]]["counterparty"] == ""
    assert by_id[ids["placeholder-merchant"]]["counterparty"] == ""
    assert by_id[ids["sibling-same-amount"]]["counterparty"] == ""

    accepted = client.post(
        f"/api/dashboards/{dashboard_id}/classification-rules",
        headers=owner["headers"],
        json={"accepts": [
            {"transaction_id": ids["blank-diab-day"], "category": "supplier_transfers", "counterparty": ""},
            {"transaction_id": ids["placeholder-merchant"], "category": "rent", "counterparty": "—",
             "date": "1999-01-01", "amount": 1},
        ]},
    )
    assert accepted.status_code == 200, accepted.text
    again = client.get(
        f"/api/dashboards/{dashboard_id}/unclassified-transfers",
        headers=owner["headers"], params={"start": "2026-07-01", "end": "2026-10-31"},
    )
    again_by_id = {row["id"]: row for row in again.json()["rows"]}
    assert ids["blank-diab-day"] not in again_by_id
    assert ids["placeholder-merchant"] not in again_by_id
    assert again_by_id[ids["sibling-same-amount"]]["counterparty"] == ""
    assert again_by_id[ids["memo-diab"]]["counterparty"] == "דיאב פייסל"
    assert again_by_id[ids["merchant-pizza"]]["counterparty"] == "Pizza Market"

    from cfo.models import DashboardPlan
    with SessionLocal() as db:
        payload = db.get(DashboardPlan, dashboard_id).payload
    rules = payload.get("statusRules") or []
    assert rules == []
    stored = payload["statusDecisions"]
    blank = stored[str(ids["blank-diab-day"])]
    assert blank["category"] == "supplier_transfers"
    assert blank["date"] == "2026-10-07"
    assert blank["amount"] == -5730.0
    assert blank["description"] == "העב' לאחר-נייד"
    assert blank["organizationId"] == owner["org_id"]
    placeholder = stored[str(ids["placeholder-merchant"])]
    assert placeholder["category"] == "rent"
    assert placeholder["date"] == "2026-10-09"
    assert placeholder["amount"] == -40.0
    assert "—" not in str(payload)
    assert "חסר" not in str(stored)


def test_a_memo_name_does_not_invent_a_party_or_an_intercompany_match():
    from types import SimpleNamespace
    from cfo.services.dashboards.filing import classify, classify_builtin, txn_from_row

    memo = txn_from_row(SimpleNamespace(
        id=7, organization_id=6, account_id=None, transaction_date=date(2026, 10, 7),
        amount=Decimal("-7000"), description="העב' לאחר-נייד",
        raw_data={"description": {
            "description": "העב' לאחר-נייד",
            "additionalInfo": '{"purposeDescription": "שף אליהב כהן"}',
        }},
    ))
    assert memo.debtor == "" and memo.creditor == ""
    assert memo.party_label == "שף אליהב כהן"
    repeated = txn_from_row(SimpleNamespace(
        id=8, organization_id=6, account_id=None, transaction_date=date(2026, 10, 7),
        amount=Decimal("-12"), description="העב' לאחר-נייד",
        raw_data={"description": {"description": "העב' לאחר-נייד", "additionalInfo": "העב' לאחר-נייד"}},
    ))
    assert repeated.party_label == ""
    missing = txn_from_row(SimpleNamespace(
        id=9, organization_id=6, account_id=None, transaction_date=date(2026, 10, 26),
        amount=Decimal("-2154"), description="שיק",
        raw_data={"merchantName": "חסר", "payee": "—"},
    ))
    assert missing.debtor == "" and missing.creditor == "" and missing.party_label == ""

    scope = {"pairs": [{"organizationId": 6}], "aliases": [["אליהב", "כהן"]]}
    assert classify_builtin(memo, scope=scope)[0] != "intercompany"
    named = Txn(7, 6, None, "2026-10-07", -7000.0, "העב' לאחר-נייד", "", "שף אליהב כהן")
    assert classify_builtin(named, scope=scope)[0] == "intercompany"

    plan = apply_accepts({}, [{
        "counterparty": "",
        "category": "supplier_transfers",
        "transaction_id": 7,
        "organization_id": 6,
        "date": "2026-10-07",
        "amount": -7000.0,
        "description": "העב' לאחר-נייד",
    }])
    assert plan.get("statusRules") in (None, [])
    decision = plan["statusDecisions"]["7"]
    assert decision["amount"] == -7000.0
    assert decision["description"] == "העב' לאחר-נייד"
    assert "שף" not in str(plan["statusDecisions"])
    filed = classify(memo, decisions=plan["statusDecisions"])
    assert filed.filed_by == "decision" and filed.category == "supplier_transfers"
    changed = Txn(
        7, 6, None, "2026-10-07", -7000.0, "העברה אחרת", "", "", memo.party_label,
    )
    assert classify(changed, decisions=plan["statusDecisions"]).filed_by != "decision"
    with_name = apply_accepts({}, [{"counterparty": "דיאב פייסל", "category": "supplier_transfers"}])
    matched = Txn(3, 6, None, "2026-10-05", -1097.0, "העב' לאחר-נייד", "", "", "דיאב פייסל")
    assert classify(matched, custom_rules=with_name["statusRules"]).category == "supplier_transfers"


def test_the_bank_pack_names_the_source_and_a_missing_figure(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "print-pack", "title": "לבנק", "access_mode": "public",
    })
    dashboard_id = created.json()["id"]
    client.patch(f"/api/dashboards/{dashboard_id}", headers=owner["headers"], json={"status": "active", "access_mode": "public"})
    pack = client.get(f"/api/dashboards/{dashboard_id}/bank-pack", headers=owner["headers"])
    assert pack.status_code == 200, pack.text
    body = pack.json()
    assert body["title_he"] == "חבילה לבנק"
    assert body["pnl"]["revenue"]["amount"] is None
    assert body["pnl"]["revenue"]["missing_label"].startswith("חסר נכון ל-")
    assert body["pnl"]["revenue"]["source"] == "ספרים"
    assert body["pnl"]["revenue"]["as_of"]
    assert body["forecast"]["supplier_terms"] == "end_of_next_month"
    public = client.get("/api/public/d/print-pack/bank-pack")
    assert public.status_code == 200, public.text
    assert public.json()["title_he"] == "חבילה לבנק"
    assumptions = list_assumptions(None, ["2026-10"], as_of=AS_OF)
    printed = bank_pack({"pnl": {}, "cash_forecast": {"weeks": [{"start": "2026-10-25", "in": None}]}}, assumptions, as_of=AS_OF)
    assert printed["forecast"]["weeks"][0]["in_missing"].startswith("חסר נכון ל-")
