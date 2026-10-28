"""Gaps the CFO agent found on /d/eliav. No provider calls.

Cheque discounting is an advance on customer receipts, not a loan.
Intercompany aliases ignore word order and punctuation, and one bank account
is not added twice. Card totals say when a value is missing, and a month's
low, close and net are different measures.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, ClientDashboard, DashboardEntity, SumitCompany
from cfo.services.dashboards import cash_statement, filing, liquidity
from cfo.services.dashboards.books import cash_basis_month


_ELIAV_SCOPE = {
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


def _txn(**kwargs):
    defaults = dict(id=None, organization_id=2, account_id=35, date="2026-10-01", amount=1000.0,
                    description="", debtor="", creditor="")
    defaults.update(kwargs)
    return filing.Txn(**defaults)


def test_cheque_discounting_is_financing_until_it_matches_an_invoice():
    """Advance in, repayment out. A collection belongs to the invoice's entity."""
    meta = filing.CATEGORIES["check_discounting"]
    assert meta["group"] == "financing"
    advance = _txn(description="ניכיון שיקים", amount=132000.0, organization_id=6)
    repay = _txn(description="צ'קים דחויים", amount=-70000.0, organization_id=6)
    collected = _txn(description="צקים דחויים", amount=70483.0, organization_id=6)
    invoices = [{
        "organization_id": 2, "number": "20055", "date": "2026-06-30", "total": 70483.0,
    }]
    filed = filing.classify_all([advance, repay, collected], invoices=invoices)
    assert filed[id(advance)].category == "loans_in"
    assert filed[id(repay)].category == "loans_out"
    assert filed[id(collected)].category == "intercompany"
    assert filed[id(collected)].extra["customer_receipt_for"] == 2
    assert filed[id(collected)].extra["invoice"] == "20055"
    month = cash_basis_month([(collected, filed[id(collected)])])
    assert month["revenue"] == 0.0


def test_discounting_evidence_is_not_in_debts_known_total(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="chk-1",
            balance=Decimal("-1000"), balance_as_of=datetime(2026, 10, 31), currency="ILS",
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31),
            plan={"liquidityEvidence": {"loans": [
                {"label": "ניכיון צ'קים", "balance": 100000, "asOf": "2026-10-01"},
                {"label": "הלוואת גישור", "balance": 50000, "asOf": "2026-10-01"},
            ]}},
            classified=[], today=date(2026, 10, 31),
        )
    amounts = {row["label"]: row["amount"] for row in section["debts"]}
    assert amounts["מינוס בעו״ש"] == 1000.0
    assert amounts["הלוואה — הלוואת גישור"] == 50000.0
    assert all("ניכיון" not in label for label in amounts)
    assert section["debts_known_total"] == 51000.0
    assert section["advances"][0]["balance"] == 100000.0
    assert section["advances"][0]["counts_as_debt"] is False
    assert "מקדמה" in section["advances"][0]["label"]


def test_unknown_discounting_balance_stays_null(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="chk-2",
            balance=Decimal("-1000"), balance_as_of=datetime(2026, 10, 31), currency="ILS",
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31),
            plan={"liquidityEvidence": {"loans": [
                {"label": "ניכיון שיקים", "balance": None, "asOf": "2026-10-01"},
            ]}},
            classified=[], today=date(2026, 10, 31),
        )
    assert section["advances"][0]["balance"] is None
    assert section["debts_known_total"] == 1000.0


def test_a_live_discounting_loan_is_an_advance(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="ניכיון צ'קים", account_type=AccountType.LIABILITY,
            raw_account_type="LOAN", source="open_finance", external_id="disc-1",
            balance=Decimal("-80000"), balance_as_of=datetime(2026, 10, 20), currency="ILS",
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31), classified=[], today=date(2026, 10, 31),
        )
    assert section["loans"] == []
    assert section["advances"][0]["balance"] == 80000.0
    assert section["debts_known_total"] is None or all("ניכיון" not in row["label"] for row in section["debts"])
    assert all(row.get("counts_as_debt") is not True for row in section["advances"])


@pytest.mark.parametrize("debtor,creditor,description", [
    ("אליאב כהן", "", ""),
    ("כהן אליאב", "", ""),
    ("אליאב-כהן", "", ""),
    ("אליאב, כהן", "", ""),
    ('אליאב כהן בע"מ', "", ""),
    ("", "פוד-גרופ", ""),
    ("", "Food Group", ""),
    ("", "food-group", ""),
    ("", "", "העברה לפוד גרופ"),
    ("אליהב כהן", "", ""),
    ("כהן אליהב", "", ""),
])
def test_intercompany_aliases_ignore_order_and_punctuation(debtor, creditor, description):
    chef = _txn(organization_id=2, account_id=35, debtor=debtor, creditor=creditor, description=description, amount=500)
    food = _txn(organization_id=6, account_id=9, debtor=debtor, creditor=creditor, description=description, amount=-500)
    assert filing.classify_builtin(chef, scope=_ELIAV_SCOPE)[0] == "intercompany"
    assert filing.classify_builtin(food, scope=_ELIAV_SCOPE)[0] == "intercompany"


@pytest.mark.parametrize("debtor,creditor,description,org,account", [
    ("כהן", "", "", 6, 9),
    ("", "", "", 2, 35),
    ("אליאב כהן", "", "", 2, 36),
    ("פוד גרופ", "", "", 2, 36),
])
def test_unknown_or_out_of_scope_counterparty_is_not_intercompany(debtor, creditor, description, org, account):
    txn = _txn(organization_id=org, account_id=account, debtor=debtor, creditor=creditor,
               description=description or "תקבול", amount=500)
    assert filing.classify_builtin(txn, scope=_ELIAV_SCOPE)[0] != "intercompany"
    assert filing.is_intercompany_counterparty("") is False
    assert filing.is_intercompany_counterparty("כהן") is False


def test_combined_daily_low_sums_checking_accounts_and_labels_the_net(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        first = Account(
            organization_id=owner["org_id"], name="עו״ש א", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="a",
            balance=Decimal("-50"), balance_as_of=datetime(2026, 10, 10), currency="ILS",
        )
        second = Account(
            organization_id=owner["org_id"], name="עו״ש ב", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="b",
            balance=Decimal("-30"), balance_as_of=datetime(2026, 10, 10), currency="ILS",
        )
        db.add_all([first, second])
        db.flush()
        booked = {"status": "BOOKED"}
        for account, day, amount, close in (
            (first, date(2026, 9, 30), 0, -100),
            (first, date(2026, 10, 1), 0, -100),
            (first, date(2026, 10, 10), 50, -50),
            (second, date(2026, 9, 30), 0, -20),
            (second, date(2026, 10, 1), 0, -20),
            (second, date(2026, 10, 10), -10, -30),
        ):
            db.add(BankTransaction(
                organization_id=owner["org_id"], account_id=account.id, source="open_finance",
                transaction_date=day, amount=Decimal(str(amount)), description="תנועה",
                raw_data={**booked, "balancePerEndDay": close}, external_id=f"{account.id}-{day.isoformat()}",
            ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31), classified=[], today=date(2026, 10, 31),
        )
    october = section["months"][0]
    assert october["min"] == -120.0
    assert october["last"] == -80.0
    assert october["min"] != october["last"]
    assert "יתרה" in october["min_definition"]
    assert "לא הנטו" in october["last_definition"]
    assert "לא אמורים להיות שווים" in section["balance_vs_flow_note"]
    assert october["opening"] == -120.0
    assert october["reconciliation_diff"] == 0.0
    assert "שווה" in october["reconciliation_note"]


def test_card_totals_name_unknowns_and_the_transaction_bucket_is_not_a_balance(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        visa = Account(
            organization_id=owner["org_id"], name="Visa", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="visa",
            balance=Decimal("-3200"), balance_as_of=datetime(2026, 10, 26), currency="ILS",
            credit_limit=Decimal("16000"), available_limit=Decimal("11950"),
        )
        other = Account(
            organization_id=owner["org_id"], name="Max", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="max",
            balance=Decimal("-500"), balance_as_of=datetime(2026, 10, 26), currency="ILS",
        )
        db.add_all([visa, other])
        db.flush()
        db.add(BankTransaction(
            organization_id=owner["org_id"], account_id=visa.id, source="open_finance",
            transaction_date=date(2026, 10, 20), amount=Decimal("-40"), description="קניה",
            raw_data={"status": "BOOKED"}, external_id="visa-1",
        ))
        db.add(BankTransaction(
            organization_id=owner["org_id"], account_id=visa.id, source="open_finance",
            transaction_date=date(2026, 10, 21), amount=Decimal("-10"), description="קניה",
            raw_data={"status": "ODD"}, external_id="visa-odd",
        ))
        db.commit()
        odd = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31), classified=[], today=date(2026, 10, 31),
        )
        db.query(BankTransaction).filter_by(external_id="visa-odd").delete()
        db.commit()
        clean = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31), classified=[], today=date(2026, 10, 31),
        )
    assert odd["card_activity"]["defined"] is True
    assert odd["card_activity"]["amount"] is None
    assert odd["card_activity"]["excluded_count"] == 1
    assert "לא ידוע" in odd["card_activity"]["definition"]
    summary = clean["card_summary"]
    assert summary["available"] is None and summary["available_unknown"] == 1
    assert summary["credit_limit"] is None and summary["credit_limit_unknown"] == 1
    assert summary["balance"] == 3700.0 and summary["balance_unknown"] == 0
    activity = clean["card_activity"]
    assert activity["defined"] is True
    assert activity["key"] == "cards"
    assert activity["count"] == 1
    assert activity["amount"] == -40.0
    assert activity["counts_as_debt"] is False
    assert "אינו יתרת" in activity["definition"]
    visa_row = next(card for card in clean["cards"] if card["name"] == "Visa")
    assert visa_row["date_mismatch"] is True
    assert visa_row["as_of"] == "2026-10-26"
    assert visa_row["last_data"] == "2026-10-20"
    assert "2026-10-26" in visa_row["date_note"] and "2026-10-20" in visa_row["date_note"]


def _office(db, office_id, target_id, name):
    db.add(SumitCompany(
        office_organization_id=office_id, company_id=f"file-{target_id}", name=name, status="active",
        target_organization_id=target_id,
    ))


def _dashboard(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "קבוצה", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _shared_account(db, org_id, number, balance, external):
    account = Account(
        organization_id=org_id, name="עו״ש משותף", account_type=AccountType.BANK,
        raw_account_type="CHECKING", source="open_finance", external_id=external,
        provider_account_number=number, balance=Decimal(str(balance)),
        balance_as_of=datetime(2026, 10, 28), credit_limit=Decimal("5000"), currency="ILS",
    )
    db.add(account)
    db.flush()
    return account


def _inflow(db, org_id, account_id, external):
    db.add(BankTransaction(
        organization_id=org_id, account_id=account_id, source="open_finance",
        transaction_date=date(2026, 10, 5), amount=Decimal("1180"), description="הפקדת מזומן",
        raw_data={"status": "BOOKED"}, external_id=external,
    ))


def test_the_same_bank_account_is_not_summed_twice(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    dashboard_id = _dashboard(client, chef["headers"], chef["org_id"], "eliav-shared-account")
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, dashboard_id)
        dashboard.office_organization_id = office["org_id"]
        primary = db.query(DashboardEntity).filter_by(dashboard_id=dashboard_id, role="primary").one()
        primary.label = "השף"
        db.add(DashboardEntity(
            dashboard_id=dashboard_id, organization_id=food["org_id"], label="פוד גרופ", role="related",
        ))
        _office(db, office["org_id"], chef["org_id"], "השף")
        _office(db, office["org_id"], food["org_id"], "פוד גרופ")
        chef_account = _shared_account(db, chef["org_id"], "12345678", -1000, "chef-chk")
        food_account = _shared_account(db, food["org_id"], "12345678", -1000, "food-chk")
        _inflow(db, chef["org_id"], chef_account.id, "chef-in")
        _inflow(db, food["org_id"], food_account.id, "food-in")
        db.commit()
    view = client.get(
        f"/api/dashboards/{dashboard_id}/view", headers=chef["headers"],
        params={"start": "2026-10-01", "end": "2026-10-31"},
    ).json()
    combined = view["combined"]
    assert combined["liquidity"]["balance"] == -1000.0
    assert combined["liquidity"]["limit"] == 5000.0
    assert combined["liquidity"]["debts_known_total"] == 1000.0
    assert combined["liquidity"]["balance"] != 0
    assert "פעם אחת" in combined["liquidity"]["shared_identity_note"]
    october = next(month for month in combined["cashflow"]["months"] if month["month"] == "2026-10")
    assert october["inflows"] == 1180.0
    chef_revenue = view["entities"][0]["view"]["pnl"]["total_revenue"]
    assert combined["pnl"]["total_revenue"] == pytest.approx(chef_revenue, abs=0.05)
    assert combined["pnl"]["total_revenue"] == pytest.approx(1000.0, abs=0.05)
    assert combined["cash_forecast"]["opening"]["amount"] == -1000.0
    assert combined["cash_forecast"]["weeks"]
    assert all(week["net"] is None and week["closing"] is None for week in combined["cash_forecast"]["weeks"])
    assert "פעם אחת" in combined["cash_forecast"]["shared_identity_note"]


def test_disagreeing_copies_stay_unknown_and_a_short_number_is_not_an_identity(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    dashboard_id = _dashboard(client, chef["headers"], chef["org_id"], "eliav-shared-conflict")
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, dashboard_id)
        dashboard.office_organization_id = office["org_id"]
        db.add(DashboardEntity(
            dashboard_id=dashboard_id, organization_id=food["org_id"], label="פוד גרופ", role="related",
        ))
        _office(db, office["org_id"], chef["org_id"], "השף")
        _office(db, office["org_id"], food["org_id"], "פוד גרופ")
        chef_account = _shared_account(db, chef["org_id"], "12345678", -1000, "chef-chk")
        food_account = _shared_account(db, food["org_id"], "12345678", -1500, "food-chk")
        _inflow(db, chef["org_id"], chef_account.id, "chef-in")
        _inflow(db, food["org_id"], food_account.id, "food-in")
        db.commit()
    conflict = client.get(
        f"/api/dashboards/{dashboard_id}/view", headers=chef["headers"],
        params={"start": "2026-10-01", "end": "2026-10-31"},
    ).json()["combined"]["liquidity"]
    assert conflict["balance"] is None
    assert conflict["debts_known_total"] is None
    assert "לא ידועה" in conflict["shared_identity_note"]

    chef_b = fresh_org()
    food_b = fresh_org()
    office_b = fresh_org()
    other_id = _dashboard(client, chef_b["headers"], chef_b["org_id"], "eliav-short-number")
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, other_id)
        dashboard.office_organization_id = office_b["org_id"]
        db.add(DashboardEntity(
            dashboard_id=other_id, organization_id=food_b["org_id"], label="פוד גרופ", role="related",
        ))
        _office(db, office_b["org_id"], chef_b["org_id"], "השף")
        _office(db, office_b["org_id"], food_b["org_id"], "פוד גרופ")
        _shared_account(db, chef_b["org_id"], "1234", -100, "chef-short")
        _shared_account(db, food_b["org_id"], "1234", -40, "food-short")
        db.commit()
    short = client.get(
        f"/api/dashboards/{other_id}/view", headers=chef_b["headers"],
        params={"start": "2026-10-01", "end": "2026-10-31"},
    ).json()["combined"]["liquidity"]
    assert short["balance"] == -140.0
    assert short.get("shared_identity_note") in (None, "")
