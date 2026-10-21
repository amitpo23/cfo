"""Dashboard view-layer dedupe and card netting. No provider calls."""
import ast
import csv
import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction
from cfo.services.dashboards.activity_quality import (
    Txn,
    classify,
    is_card_bill,
    is_future_charge,
)


def _txn(**kwargs) -> Txn:
    base = dict(
        id=1,
        organization_id=2,
        account_id=10,
        transaction_date=date(2026, 8, 10),
        amount=Decimal("-100.00"),
        description="ספק",
        status="BOOKED",
        entry_reference=None,
        content_fingerprint="fp",
        superseded_by_id=None,
        source="open_finance",
        category_name=None,
        merchant_name="ספק",
    )
    base.update(kwargs)
    return Txn(**base)


def _counted_total(outcome) -> Decimal:
    return sum((txn.amount for txn in outcome.counted), Decimal("0"))


def test_future_charge_text_and_card_bill_heuristic():
    assert is_future_charge("חיובים עתידיים מחברת ויזה כאל")
    assert is_future_charge("חיובים   עתידיים מחברת ויזה כא")
    assert not is_future_charge("חיוב ויזה כאל")
    assert is_card_bill("חיוב ויזה כאל")
    assert is_card_bill("VISA CAL monthly")
    assert not is_card_bill("חיובים עתידיים מחברת ויזה כאל")
    assert not is_card_bill("שופרסל")


def test_pending_then_booked_with_changed_description_counts_booked_only():
    pending = _txn(
        id=1, transaction_date=date(2026, 8, 2), amount=Decimal("-71300.00"),
        description="הרשאה זמנית", status="PENDING", entry_reference="ref-aug",
        content_fingerprint="pending-fp",
    )
    booked = _txn(
        id=2, transaction_date=date(2026, 8, 4), amount=Decimal("-71300.00"),
        description="ספק מזון — ניסוח חדש", status="BOOKED", entry_reference="ref-aug",
        content_fingerprint="booked-fp",
    )
    outcome = classify([pending, booked])
    assert _counted_total(outcome) == Decimal("-71300.00")
    assert [txn.id for txn in outcome.counted] == [2]
    assert outcome.excluded_counts["pending_superseded"] == 1
    assert outcome.pairs[0]["rule"] == "entry_reference"
    assert outcome.pairs[0]["disposition"] == "excluded"
    assert not any(item["code"] == "suspected_pair" for item in outcome.warnings)


def test_entry_reference_match_keeps_booked_amount_when_they_differ():
    pending = _txn(id=1, status="PENDING", amount=Decimal("-50.00"), entry_reference="ref")
    booked = _txn(id=2, status="BOOKED", amount=Decimal("-80.00"), entry_reference="ref")
    outcome = classify([pending, booked])
    assert _counted_total(outcome) == Decimal("-80.00")
    assert any("נבדלים בסכום" in note["message_he"] for note in outcome.notes)


def test_fingerprint_fallback_within_three_days_and_not_on_the_fourth():
    pending = _txn(
        id=1, status="PENDING", transaction_date=date(2026, 8, 1),
        content_fingerprint="same", entry_reference=None,
    )
    near = _txn(
        id=2, status="BOOKED", transaction_date=date(2026, 8, 4),
        content_fingerprint="same", entry_reference=None,
    )
    near_outcome = classify([pending, near])
    assert near_outcome.excluded_counts["pending_superseded"] == 1
    assert _counted_total(near_outcome) == Decimal("-100.00")

    far = _txn(
        id=3, status="BOOKED", transaction_date=date(2026, 8, 5),
        content_fingerprint="same", entry_reference=None,
    )
    far_outcome = classify([pending, far])
    assert far_outcome.excluded_counts["pending_superseded"] == 0
    assert far_outcome.excluded_counts["non_booked"] == 1
    assert not any(item["code"] == "suspected_pair" for item in far_outcome.warnings)


def test_changed_description_without_reference_warns_and_keeps_the_booked_row():
    pending = _txn(
        id=1, status="PENDING", description="טיוטה", content_fingerprint="a",
        entry_reference=None, transaction_date=date(2026, 8, 2),
    )
    booked = _txn(
        id=2, status="BOOKED", description="נוסח אחר", content_fingerprint="b",
        entry_reference=None, transaction_date=date(2026, 8, 3),
    )
    outcome = classify([pending, booked])
    assert _counted_total(outcome) == Decimal("-100.00")
    warning = next(item for item in outcome.warnings if item["code"] == "suspected_pair")
    assert warning["rule"] == "ambiguous_pending"
    assert "לא הוסר ככפילות" in warning["message_he"]
    assert "id" not in warning


def test_future_charge_pending_is_excluded_and_not_a_suspected_pair():
    future = _txn(
        id=1, status="PENDING", amount=Decimal("-999.00"),
        description="חיובים עתידיים מחברת ויזה כאל",
        transaction_date=date(2026, 8, 2), content_fingerprint="future",
    )
    booked = _txn(
        id=2, status="BOOKED", amount=Decimal("-999.00"), description="משהו אחר",
        transaction_date=date(2026, 8, 3), content_fingerprint="other",
    )
    outcome = classify([future, booked])
    assert outcome.excluded_counts["future_charge"] == 1
    assert _counted_total(outcome) == Decimal("-999.00")
    assert not any(item["code"] == "suspected_pair" for item in outcome.warnings)


def test_superseded_by_id_is_not_counted_even_when_booked():
    row = _txn(id=4, status="BOOKED", superseded_by_id=9, amount=Decimal("-40.00"))
    manual = _txn(id=5, source="manual", status=None, amount=Decimal("15.00"), content_fingerprint="m")
    outcome = classify([row, manual])
    assert outcome.excluded_counts["superseded_by_id"] == 1
    assert _counted_total(outcome) == Decimal("15.00")


def test_missing_open_finance_status_is_not_counted_and_other_sources_are():
    unknown = _txn(id=1, status=None, amount=Decimal("-20.00"))
    legacy = _txn(id=2, source=None, status=None, amount=Decimal("7.00"))
    outcome = classify([unknown, legacy])
    assert outcome.excluded_counts["non_booked"] == 1
    assert _counted_total(outcome) == Decimal("7.00")


def test_two_booked_rows_with_one_reference_stay_until_confirmed():
    first = _txn(id=1, entry_reference="dup", content_fingerprint="a")
    second = _txn(id=2, entry_reference="dup", content_fingerprint="b", description="עותק")
    outcome = classify([first, second])
    assert _counted_total(outcome) == Decimal("-200.00")
    assert any(item["rule"] == "duplicate_booked_reference" for item in outcome.warnings)
    confirmed = classify([first, second], confirmed_pairs=[(1, 2)])
    assert _counted_total(confirmed) == Decimal("-100.00")
    assert confirmed.excluded_counts["confirmed_pair"] == 1
    assert not any(item["code"] == "suspected_pair" for item in confirmed.warnings)


def test_same_fingerprint_booked_rows_warn_and_are_not_removed():
    first = _txn(id=1, content_fingerprint="same", entry_reference=None)
    second = _txn(id=2, content_fingerprint="same", entry_reference=None, transaction_date=date(2026, 8, 11))
    outcome = classify([first, second])
    assert _counted_total(outcome) == Decimal("-200.00")
    assert any(item["rule"] == "duplicate_booked_fingerprint" for item in outcome.warnings)


def test_detail_accounts_leave_the_cash_total_and_feed_the_drilldown():
    card = _txn(
        id=1, account_id=20, amount=Decimal("-40.00"), merchant_name="שופרסל",
        category_name="מזון", description="שופרסל",
    )
    bill = _txn(id=2, account_id=10, amount=Decimal("-40.00"), description="חיוב ויזה כאל")
    outcome = classify([card, bill], detail_account_ids={20})
    assert _counted_total(outcome) == Decimal("-40.00")
    assert [txn.id for txn in outcome.detail] == [1]
    view = outcome.as_view()
    assert view["detail"]["merchants"][0]["merchant"] == "שופרסל"
    assert view["detail"]["merchants"][0]["net"] == "-40.00"
    assert view["detail"]["categories"][0]["category"] == "מזון"
    assert view["billing_cycles"][0]["status"] == "ok"
    assert not any(item["code"] == "card_bill_mismatch" for item in outcome.warnings)


def test_billing_cycle_mismatch_and_unknown_only_warn():
    card = _txn(id=1, account_id=20, amount=Decimal("-10200.00"), description="קפה", merchant_name="קפה")
    bill = _txn(id=2, account_id=10, amount=Decimal("-10000.00"), description="חיוב ויזה כאל")
    mismatch = classify([card, bill], detail_account_ids={20})
    assert _counted_total(mismatch) == Decimal("-10000.00")
    assert mismatch.billing_cycles[0]["status"] == "mismatch"
    assert any(item["code"] == "card_bill_mismatch" for item in mismatch.warnings)

    quiet_bill = _txn(id=3, account_id=10, amount=Decimal("-10200.00"), description="העברה")
    unknown = classify([card, quiet_bill], detail_account_ids={20})
    assert unknown.billing_cycles[0]["status"] == "unknown"
    assert unknown.billing_cycles[0]["bill_total"] is None
    assert _counted_total(unknown) == Decimal("-10200.00")


def test_one_percent_boundary_is_inclusive():
    card = _txn(id=1, account_id=20, amount=Decimal("-10100.00"), description="קפה", merchant_name="קפה")
    bill = _txn(id=2, account_id=10, amount=Decimal("-10000.00"), description="חיוב ויזה כאל")
    outcome = classify([card, bill], detail_account_ids={20})
    assert outcome.billing_cycles[0]["status"] == "ok"


def test_entry_reference_on_another_account_is_not_auto_removed():
    pending = _txn(id=1, account_id=10, status="PENDING", entry_reference="ref")
    booked = _txn(id=2, account_id=11, status="BOOKED", entry_reference="ref")
    outcome = classify([pending, booked])
    assert [txn.id for txn in outcome.counted] == [2]
    assert outcome.excluded_counts["pending_superseded"] == 0
    assert not any(item["code"] == "suspected_pair" for item in outcome.warnings)


def test_invalid_pair_payload_does_not_drop_rows():
    from cfo.services.dashboards.activity_quality import parse_confirmed_pairs, parse_detail_account_ids
    pairs, warnings = parse_confirmed_pairs({"dedupePairs": {"keepId": 1}})
    assert pairs == []
    assert warnings[0]["code"] == "invalid_dedupe_pairs"
    ids, id_warnings = parse_detail_account_ids({"detailAccountIds": [20, "nope", True]})
    assert ids == {20}
    assert id_warnings


def _report():
    path = Path("scripts/eliav_dq_report.py")
    spec = importlib.util.spec_from_file_location("eliav_dq_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_code_does_not_import_sumit_or_financy_client():
    banned = (
        "sumit_integration", "sumit_connector", "SumitIntegration",
        "open_finance_client", "open_finance_connector", "OpenFinanceClient",
        "financy", "Financy",
    )
    files = [
        Path("src/cfo/services/dashboards/activity_quality.py"),
        Path("scripts/eliav_dq_report.py"),
    ]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            names = []
            if isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
                names.extend(alias.name for alias in node.names)
            else:
                names.extend(alias.name for alias in node.names)
            blob = " ".join(names)
            assert not any(word in blob for word in banned), path


def test_report_refuses_remote_urls_and_is_query_only():
    report = _report()
    with pytest.raises(SystemExit):
        report.assert_local_sqlite("postgresql://neon.tech/cfo")
    report.assert_local_sqlite("sqlite:///tmp/eliav-dq.db")
    from cfo.config import settings
    db, engine = report.open_readonly_session(settings.database_url)
    try:
        with pytest.raises(Exception):
            db.execute(__import__("sqlalchemy").text("CREATE TABLE eliav_dq_should_fail (id int)"))
    finally:
        report.close_readonly_session(db, engine)


def test_dashboard_view_counts_booked_copy_after_a_changed_description(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": "dq-eliav",
        "title": "איכות",
        "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        checking = Account(
            organization_id=owner["org_id"], name="עובר ושב", account_type=AccountType.BANK,
            source="open_finance", external_id="of-checking",
        )
        card = Account(
            organization_id=owner["org_id"], name="ויזה כאל", account_type=AccountType.BANK,
            source="open_finance", external_id="of-card",
        )
        db.add_all([checking, card])
        db.flush()
        db.add_all([
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="pending-aug",
                account_id=checking.id, transaction_date=date(2026, 8, 2),
                amount=Decimal("-71300.00"), description="הרשאה זמנית", currency="ILS",
                raw_data={"status": "PENDING", "entryReference": "ref-aug-71300"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="booked-aug",
                account_id=checking.id, transaction_date=date(2026, 8, 4),
                amount=Decimal("-71300.00"), description="ספק מזון — ניסוח חדש", currency="ILS",
                raw_data={"status": "BOOKED", "entryReference": "ref-aug-71300"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="future-aug",
                account_id=checking.id, transaction_date=date(2026, 8, 5),
                amount=Decimal("-999.00"), description="חיובים עתידיים מחברת ויזה כאל",
                currency="ILS", raw_data={"status": "PENDING", "entryReference": "future-1"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="manual", external_id="manual-in",
                account_id=checking.id, transaction_date=date(2026, 8, 6),
                amount=Decimal("50.00"), description="הפקדה", currency="ILS",
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="card-shop",
                account_id=card.id, transaction_date=date(2026, 8, 8),
                amount=Decimal("-250.00"), description="שופרסל", currency="ILS",
                raw_data={"status": "BOOKED", "entryReference": "card-1", "merchantName": "שופרסל"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="card-bill",
                account_id=checking.id, transaction_date=date(2026, 8, 28),
                amount=Decimal("-250.00"), description="חיוב ויזה כאל", currency="ILS",
                raw_data={"status": "BOOKED", "entryReference": "bill-1"},
            ),
        ])
        db.commit()
        card_id = card.id
        pending = db.query(BankTransaction).filter_by(external_id="pending-aug").one()
        assert pending.superseded_by_id is None
        assert pending.content_fingerprint is None

    saved = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**owner["headers"], "If-Match": "null"},
        json={"payload": {"detailAccountIds": [card_id]}},
    )
    assert saved.status_code == 200, saved.text
    view = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=owner["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["provider_calls"] == 0
    august = next(month for month in body["cashflow"]["months"] if month["month"] == "2026-08")
    assert august["outflows"] == 71550.0
    assert august["inflows"] == 50.0
    quality = body["cashflow"]["activity_quality"]
    assert quality["excluded_counts"]["pending_superseded"] == 1
    assert quality["excluded_counts"]["future_charge"] == 1
    assert quality["excluded_counts"]["detail_account"] == 1
    assert quality["detail"]["merchants"][0]["merchant"] == "שופרסל"
    assert quality["detail"]["merchants"][0]["net"] == "-250.00"
    assert quality["billing_cycles"][0]["status"] == "ok"
    assert "ref-aug-71300" not in view.text
    assert "pending-aug" not in view.text
    with SessionLocal() as db:
        pending = db.query(BankTransaction).filter_by(external_id="pending-aug").one()
        assert pending.superseded_by_id is None
        assert pending.content_fingerprint is None


def test_report_csv_lists_the_pending_booked_pair(fresh_org, tmp_path):
    owner = fresh_org()
    with SessionLocal() as db:
        account = Account(
            organization_id=owner["org_id"], name="עובר ושב", account_type=AccountType.BANK,
            source="open_finance", external_id="of-checking-csv",
        )
        db.add(account)
        db.flush()
        db.add_all([
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="csv-pending",
                account_id=account.id, transaction_date=date(2026, 8, 2),
                amount=Decimal("-71300.00"), description="הרשאה זמנית", currency="ILS",
                raw_data={"status": "PENDING", "entryReference": "ref-csv"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="csv-booked",
                account_id=account.id, transaction_date=date(2026, 8, 4),
                amount=Decimal("-71300.00"), description="ספק מזון — ניסוח חדש", currency="ILS",
                raw_data={"status": "BOOKED", "entryReference": "ref-csv"},
            ),
        ])
        db.commit()
        account_id = account.id
    report = _report()
    destination = tmp_path / "dq.csv"
    from cfo.config import settings
    assert report.main(["--organization-id", str(owner["org_id"]), "--output", str(destination)], url=settings.database_url) == 0
    with destination.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    match = next(row for row in rows if row["entry_reference"] == "ref-csv")
    assert match["organization_id"] == str(owner["org_id"])
    assert match["account_id"] == str(account_id)
    assert match["month"] == "2026-08"
    assert match["rule"] == "entry_reference"
    assert match["disposition"] == "excluded"
    assert match["left_description"] != match["right_description"]
    with SessionLocal() as db:
        pending = db.query(BankTransaction).filter_by(external_id="csv-pending").one()
        assert pending.superseded_by_id is None
