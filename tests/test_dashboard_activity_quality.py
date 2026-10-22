"""Confirmed duplicate pairs, suspect warnings, and the card-bill check.

BOOKED-only totals, future charges, sync supersede, and card exclusion are
owned by bank_status. These tests do not rebuild those rules.
"""
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
    is_internet_transfer,
    is_journal_transfer,
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
        is_card=False,
    )
    base.update(kwargs)
    return Txn(**base)


def test_card_bill_heuristic_ignores_future_charges():
    assert is_future_charge("חיובים עתידיים מחברת ויזה כאל")
    assert is_future_charge("חיובים   עתידיים מחברת ויזה כא")
    assert not is_future_charge("חיוב ויזה כאל")
    assert is_card_bill("חיוב ויזה כאל")
    assert is_card_bill("ויזה כאל")
    assert is_card_bill("VISA CAL monthly")
    assert not is_card_bill("חיובים עתידיים מחברת ויזה כאל")
    assert not is_card_bill("שופרסל")
    assert is_journal_transfer("העברת יומן")
    assert is_internet_transfer("העברה באינטרנט")
    assert not is_journal_transfer("העברה באינטרנט")


def test_journal_and_internet_transfer_are_one_suspected_pair():
    journal = _txn(
        id=1, status="PENDING", amount=Decimal("40000.00"), description="העברת יומן",
        entry_reference="14073", transaction_date=date(2026, 8, 16), content_fingerprint="j",
    )
    internet = _txn(
        id=2, status="BOOKED", amount=Decimal("40000.00"), description="העברה באינטרנט",
        entry_reference="14073", transaction_date=date(2026, 8, 16), content_fingerprint="i",
    )
    outcome = classify([journal, internet])
    assert len(outcome.pairs) == 1
    assert outcome.pairs[0]["rule"] == "journal_vs_internet"
    assert outcome.pairs[0]["disposition"] == "excluded"
    assert outcome.pairs[0]["left_description"] == "העברת יומן"
    assert outcome.pairs[0]["right_description"] == "העברה באינטרנט"
    assert outcome.drop_ids == set()
    assert not any(item["code"] == "suspected_pair" for item in outcome.warnings)


def test_two_booked_journal_and_internet_rows_warn_until_confirmed():
    journal = _txn(
        id=1, amount=Decimal("40000.00"), description="העברת יומן",
        entry_reference=None, transaction_date=date(2026, 8, 16), content_fingerprint="j",
    )
    internet = _txn(
        id=2, amount=Decimal("40000.00"), description="העברה באינטרנט",
        entry_reference=None, transaction_date=date(2026, 8, 17), content_fingerprint="i",
    )
    outcome = classify([journal, internet])
    assert outcome.pairs[0]["rule"] == "journal_vs_internet"
    assert outcome.pairs[0]["disposition"] == "warning"
    warning = next(item for item in outcome.warnings if item["code"] == "suspected_pair")
    assert warning["rule"] == "journal_vs_internet"
    assert "14073" not in warning["message_he"]
    assert "id" not in warning
    confirmed = classify([journal, internet], confirmed_pairs=[(2, 1)])
    assert confirmed.drop_ids == {1}
    assert confirmed.pairs[0]["disposition"] == "confirmed"
    assert not any(item["code"] == "suspected_pair" for item in confirmed.warnings)
    assert any("שאושרו" in note["message_he"] for note in confirmed.notes)


def test_a_confirmed_pair_that_cannot_be_a_duplicate_is_refused():
    keep = _txn(id=1, amount=Decimal("500.00"), content_fingerprint="a")
    other_amount = _txn(id=2, amount=Decimal("90000.00"), content_fingerprint="b")
    other_account = _txn(id=3, amount=Decimal("500.00"), account_id=11, content_fingerprint="c")
    far = _txn(id=4, amount=Decimal("500.00"), transaction_date=date(2026, 9, 30), content_fingerprint="d")
    outcome = classify(
        [keep, other_amount, other_account, far],
        confirmed_pairs=[(1, 2), (1, 3), (1, 4)],
    )
    assert outcome.drop_ids == set()
    refused = next(item for item in outcome.warnings if item["code"] == "refused_dedupe_pair")
    assert refused["message_he"].startswith("3 ")
    from cfo.services.dashboards.activity_quality import confirmed_drop_ids
    payload = {"dedupePairs": [[1, 2], [1, 3], [1, 4]]}
    assert confirmed_drop_ids([keep, other_amount, other_account, far], payload) == set()
    same = _txn(id=5, amount=Decimal("500.00"), transaction_date=date(2026, 8, 12), content_fingerprint="e")
    assert confirmed_drop_ids([keep, same], {"dedupePairs": [[1, 5]]}) == {5}


def test_loan_reference_with_another_amount_is_not_a_pair():
    pending = _txn(
        id=1, status="PENDING", amount=Decimal("-1375.31"), description="חיוב בגין פרעון",
        entry_reference="00507001", transaction_date=date(2026, 8, 14), content_fingerprint="a",
    )
    later = _txn(
        id=2, status="PENDING", amount=Decimal("-1373.37"), description="חיוב בגין פרעון",
        entry_reference="00507001", transaction_date=date(2026, 9, 14), content_fingerprint="b",
    )
    booked = _txn(
        id=3, amount=Decimal("-1375.31"), description="הלוואה- פרעון",
        entry_reference="00507001", transaction_date=date(2026, 8, 15), content_fingerprint="c",
    )
    outcome = classify([pending, later, booked])
    assert [(item["left_id"], item["right_id"]) for item in outcome.pairs] == [(1, 3)]
    assert outcome.pairs[0]["rule"] == "entry_reference"
    assert outcome.pairs[0]["disposition"] == "excluded"


def test_reference_outside_five_days_is_not_listed():
    pending = _txn(
        id=1, status="PENDING", entry_reference="ref", transaction_date=date(2026, 8, 1),
        content_fingerprint="a",
    )
    booked = _txn(
        id=2, entry_reference="ref", transaction_date=date(2026, 8, 7), content_fingerprint="b",
    )
    assert classify([pending, booked]).pairs == []


def test_two_booked_rows_with_one_reference_stay_until_confirmed():
    first = _txn(id=1, entry_reference="dup", content_fingerprint="a")
    second = _txn(id=2, entry_reference="dup", content_fingerprint="b", description="עותק")
    outcome = classify([first, second])
    assert outcome.drop_ids == set()
    assert any(item["rule"] == "duplicate_booked_reference" for item in outcome.warnings)
    confirmed = classify([first, second], confirmed_pairs=[(1, 2)])
    assert confirmed.drop_ids == {2}
    assert not any(item["code"] == "suspected_pair" for item in confirmed.warnings)


def test_same_fingerprint_booked_rows_warn_and_are_not_removed():
    first = _txn(id=1, content_fingerprint="same", entry_reference=None)
    second = _txn(
        id=2, content_fingerprint="same", entry_reference=None, transaction_date=date(2026, 8, 12),
    )
    near = classify([first, second])
    assert any(item["rule"] == "duplicate_booked_fingerprint" for item in near.warnings)
    far = _txn(
        id=3, content_fingerprint="same", entry_reference=None, transaction_date=date(2026, 8, 14),
    )
    assert not any(item["code"] == "suspected_pair" for item in classify([first, far]).warnings)


def test_billing_cycle_mismatch_and_unknown_only_warn():
    card = _txn(
        id=1, account_id=20, is_card=True, amount=Decimal("-10200.00"),
        description="קפה",
    )
    bill = _txn(id=2, account_id=10, amount=Decimal("-10000.00"), description="חיוב ויזה כאל")
    mismatch = classify([card, bill], card_account_ids={20})
    assert mismatch.billing_cycles[0]["status"] == "mismatch"
    assert mismatch.drop_ids == set()
    assert any(item["code"] == "card_bill_mismatch" for item in mismatch.warnings)

    quiet = _txn(id=3, account_id=10, amount=Decimal("-10200.00"), description="העברה")
    unknown = classify([card, quiet], card_account_ids={20})
    assert unknown.billing_cycles[0]["status"] == "unknown"
    assert unknown.billing_cycles[0]["bill_total"] is None


def test_one_percent_boundary_is_inclusive():
    card = _txn(id=1, account_id=20, is_card=True, amount=Decimal("-10100.00"), description="קפה")
    bill = _txn(id=2, account_id=10, amount=Decimal("-10000.00"), description="חיוב ויזה כאל")
    outcome = classify([card, bill], card_account_ids={20})
    assert outcome.billing_cycles[0]["status"] == "ok"
    assert not any(item["code"] == "card_bill_mismatch" for item in outcome.warnings)


def test_journal_transfer_on_another_account_is_not_paired():
    journal = _txn(
        id=1, account_id=10, amount=Decimal("40000.00"), description="העברת יומן",
        transaction_date=date(2026, 8, 16), content_fingerprint="j",
    )
    internet = _txn(
        id=2, account_id=11, amount=Decimal("40000.00"), description="העברה באינטרנט",
        transaction_date=date(2026, 8, 16), content_fingerprint="i",
    )
    assert classify([journal, internet]).pairs == []


def test_invalid_pair_payload_does_not_drop_rows():
    from cfo.services.dashboards.activity_quality import parse_confirmed_pairs
    pairs, warnings = parse_confirmed_pairs({"dedupePairs": {"keepId": 1}})
    assert pairs == []
    assert warnings[0]["code"] == "invalid_dedupe_pairs"
    kept, skipped = parse_confirmed_pairs({"dedupePairs": [[1, 1], {"keepId": 4, "dropId": 5}, True]})
    assert kept == [(4, 5)]
    assert skipped[0]["code"] == "invalid_dedupe_pairs"


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


def test_dashboard_drops_only_a_confirmed_pair_and_warns_on_the_card_bill(client, fresh_org):
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
            organization_id=owner["org_id"], name="ויזה כאל", account_type=AccountType.LIABILITY,
            source="open_finance", external_id="of-card", raw_account_type="CARD",
        )
        db.add_all([checking, card])
        db.flush()
        journal = BankTransaction(
            organization_id=owner["org_id"], source="open_finance", external_id="journal-booked",
            account_id=checking.id, transaction_date=date(2026, 8, 16),
            amount=Decimal("40000.00"), description="העברת יומן", currency="ILS",
            raw_data={"status": "BOOKED", "entryReference": "ref-journal-net"},
        )
        internet = BankTransaction(
            organization_id=owner["org_id"], source="open_finance", external_id="internet-booked",
            account_id=checking.id, transaction_date=date(2026, 8, 16),
            amount=Decimal("40000.00"), description="העברה באינטרנט", currency="ILS",
            raw_data={"status": "BOOKED", "entryReference": "ref-internet-net"},
        )
        db.add_all([
            journal,
            internet,
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="card-shop",
                account_id=card.id, transaction_date=date(2026, 8, 5),
                amount=Decimal("-1000.00"), description="שופרסל", currency="ILS",
                raw_data={"status": "BOOKED", "merchantName": "שופרסל", "type": "CARD"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="card-bill",
                account_id=checking.id, transaction_date=date(2026, 8, 20),
                amount=Decimal("-19112.91"), description="ויזה כאל", currency="ILS",
                raw_data={"status": "BOOKED", "entryReference": "bill-1"},
            ),
        ])
        db.commit()
        journal_id = journal.id
        internet_id = internet.id
        assert journal.superseded_by_id is None
        assert journal.content_fingerprint is None

    first = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=owner["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    august = next(month for month in body["cashflow"]["months"] if month["month"] == "2026-08")
    assert august["inflows"] == 80000.0
    assert august["outflows"] == 19112.91
    quality = body["cashflow"]["activity_quality"]
    assert any(item["rule"] == "journal_vs_internet" for item in quality["warnings"])
    assert quality["billing_cycles"][0]["status"] == "mismatch"
    assert "ref-journal-net" not in first.text
    assert "journal-booked" not in first.text

    saved = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**owner["headers"], "If-Match": "null"},
        json={"payload": {"dedupePairs": [{"keepId": internet_id, "dropId": journal_id}]}},
    )
    assert saved.status_code == 200, saved.text
    second = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=owner["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert second.status_code == 200, second.text
    august = next(month for month in second.json()["cashflow"]["months"] if month["month"] == "2026-08")
    assert august["inflows"] == 40000.0
    assert august["outflows"] == 19112.91
    warnings = second.json()["cashflow"]["activity_quality"]["warnings"]
    assert not any(item.get("rule") == "journal_vs_internet" for item in warnings)
    assert any(item["code"] == "card_bill_mismatch" for item in warnings)
    with SessionLocal() as db:
        row = db.query(BankTransaction).filter_by(external_id="journal-booked").one()
        assert row.superseded_by_id is None
        assert row.content_fingerprint is None
        # The cash-basis P&L reads the same row set as the cash flow.
        from cfo.services.dashboards import books
        plan = saved.json()["payload"]
        filed = books.classified_bank(db, owner["org_id"], date(2026, 8, 1), date(2026, 8, 31), plan)
        filed_ids = {txn.id for txn, _result in filed}
        assert journal_id not in filed_ids
        assert internet_id in filed_ids


def test_report_csv_lists_journal_and_internet_transfer(fresh_org, tmp_path):
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
                organization_id=owner["org_id"], source="open_finance", external_id="csv-journal",
                account_id=account.id, transaction_date=date(2026, 8, 16),
                amount=Decimal("40000.00"), description="העברת יומן", currency="ILS",
                raw_data={"status": "PENDING", "entryReference": "14073"},
            ),
            BankTransaction(
                organization_id=owner["org_id"], source="open_finance", external_id="csv-internet",
                account_id=account.id, transaction_date=date(2026, 8, 16),
                amount=Decimal("40000.00"), description="העברה באינטרנט", currency="ILS",
                raw_data={"status": "BOOKED", "entryReference": "14073"},
            ),
        ])
        db.commit()
        account_id = account.id
    report = _report()
    destination = tmp_path / "dq.csv"
    from cfo.config import settings
    assert report.main(
        ["--organization-id", str(owner["org_id"]), "--output", str(destination)],
        url=settings.database_url,
    ) == 0
    with destination.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    match = next(row for row in rows if row["entry_reference"] == "14073")
    assert match["organization_id"] == str(owner["org_id"])
    assert match["account_id"] == str(account_id)
    assert match["month"] == "2026-08"
    assert match["rule"] == "journal_vs_internet"
    assert match["disposition"] == "excluded"
    assert match["left_description"] == "העברת יומן"
    assert match["right_description"] == "העברה באינטרנט"
    assert match["left_status"] == "PENDING"
    assert match["right_status"] == "BOOKED"
    with SessionLocal() as db:
        pending = db.query(BankTransaction).filter_by(external_id="csv-journal").one()
        assert pending.superseded_by_id is None
