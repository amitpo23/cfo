"""Client-dashboard balance sheet and SUMIT portal file import.

Synthetic CSV/XLSX only. No SUMIT or Open Finance client is constructed.
"""
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, Expense, Invoice, InvoiceStatus, JournalEntry

FIXTURES = Path(__file__).parent / "fixtures" / "sumit_portal"
AS_OF = "2026-09-30"
UPLOAD = "/api/admin/sumit-portal-imports"


def _upload(client, headers, content: bytes, filename: str, *, kind: str | None = None,
            as_of: str | None = AS_OF):
    data = {}
    if kind:
        data["kind"] = kind
    if as_of:
        data["as_of"] = as_of
    return client.post(
        UPLOAD,
        headers=headers,
        files={"file": (filename, content, "application/octet-stream")},
        data=data,
    )


def _account(db, org_id, code, name, account_type):
    row = Account(
        organization_id=org_id, name=name, account_type=account_type,
        source="manual", source_account_code=code, currency="ILS", balance=None,
    )
    db.add(row)
    db.flush()
    return row


def _chart(db, org_id):
    _account(db, org_id, "1000", "קופה ראשית", AccountType.ASSET)
    _account(db, org_id, "2000", "ספקים במערכת", AccountType.LIABILITY)
    _account(db, org_id, "3000", "הון", AccountType.EQUITY)
    _account(db, org_id, "4000", "הכנסות", AccountType.REVENUE)
    _account(db, org_id, "5000", "הוצאות", AccountType.EXPENSE)
    db.commit()


def _portal_rows(db, org_id):
    return db.query(JournalEntry).filter_by(
        organization_id=org_id, source="sumit_portal_export",
    ).all()


def test_empty_books_balance_sheet_is_unknown_not_zero(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        _account(db, org["org_id"], "1000", "קופה", AccountType.BANK)
        db.commit()
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]

    assert sheet["status"] == "unknown"
    assert sheet["provider_calls"] == 0
    for section in ("assets", "liabilities", "equity"):
        assert sheet[section]["total"] is None
        assert sheet[section]["lines"] == []
        assert sheet[section]["synced_at"] is None
    assert sheet["equity"]["opening_equity"] is None
    assert sheet["equity"]["retained_earnings"] is None
    assert sheet["balanced"] is None


def test_derived_books_keep_a_posted_zero_and_leave_missing_sections_unknown(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org["org_id"], invoice_number="1", issue_date=date(2026, 8, 2),
            status=InvoiceStatus.SENT, subtotal=Decimal("100"), tax=Decimal("0"), total=Decimal("100"),
        ))
        db.add(Expense(
            organization_id=org["org_id"], supplier_name="ספק", amount=Decimal("80"),
            vat_amount=Decimal("0"), expense_date=date(2026, 8, 15), status="pending",
        ))
        db.commit()
        sheet = build_view(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31))["balance_sheet"]

    assets = {line["code"]: line for line in sheet["assets"]["lines"]}
    liabilities = {line["code"]: line for line in sheet["liabilities"]["lines"]}
    assert assets["1100"]["amount"] == 100
    assert liabilities["2200"]["amount"] == 0
    assert sheet["liabilities"]["total"] == 0
    assert sheet["equity"]["retained_earnings"] == 20
    assert sheet["equity"]["opening_equity"] is None
    assert sheet["equity"]["total"] is None
    assert sheet["balanced"] is None
    for line in sheet["assets"]["lines"] + sheet["liabilities"]["lines"]:
        assert line["source"] == "rezef_books"
        assert line["source_label"]
        assert line["synced_at"]
    assert sheet["basis"] == "rezef_books"
    assert sheet["provider_calls"] == 0


def test_expense_after_the_as_of_date_does_not_become_a_zero_sheet(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        db.add(Expense(
            organization_id=org["org_id"], supplier_name="ספק", amount=Decimal("80"),
            vat_amount=Decimal("0"), expense_date=date(2026, 10, 15), status="pending",
        ))
        db.commit()
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]

    assert sheet["assets"]["total"] is None
    assert sheet["liabilities"]["total"] is None
    assert sheet["status"] == "unknown"


def test_portal_balance_sheet_csv_maps_accounts_and_is_idempotent(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view
    from cfo.services.ledger_service import trial_balance

    org = fresh_org()
    content = (FIXTURES / "balance_sheet.csv").read_bytes()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    first = _upload(client, org["headers"], content, "balance_sheet.csv", kind="balance_sheet")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["provider_calls"] == 0
    assert body["inserted"] == 4
    assert body["mapped_count"] == 3
    assert body["unmapped_count"] == 1
    assert body["unmapped"][0]["code"] == "9999"
    assert body["imported_at"]
    assert body["as_of"] == AS_OF

    second = _upload(client, org["headers"], content, "balance_sheet.csv", kind="balance_sheet")
    assert second.status_code == 200, second.text
    again = second.json()
    assert again["inserted"] == 0 and again["updated"] == 0 and again["unchanged"] == 4

    with SessionLocal() as db:
        rows = _portal_rows(db, org["org_id"])
        assert len(rows) == 4
        stamp = next(row.raw_data["imported_at"] for row in rows if row.external_id.endswith(":1000"))
        assert trial_balance(db, org["org_id"])["entry_count"] == 0
        codes = {row.source_account_code for row in db.query(Account).filter_by(organization_id=org["org_id"])}
        assert "9999" not in codes
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]

    assert sheet["basis"] == "sumit_portal_export"
    assert sheet["synced_at"]
    assets = {line["code"]: line for line in sheet["assets"]["lines"]}
    assert assets["1000"]["amount"] == 1500.5
    assert assets["1000"]["mapped"] is True
    assert assets["1000"]["source"] == "sumit_portal_export"
    assert assets["1000"]["synced_at"] == stamp
    assert assets["9999"]["mapped"] is False
    assert assets["9999"]["mark"] == "לא ממופה"
    assert assets["9999"]["amount"] == 10
    assert sheet["assets"]["total"] == 1510.5
    assert sheet["unclassified"]["label"] == "ללא סיווג"
    assert sheet["unclassified"]["amount"] == 0
    assert sheet["unclassified"]["row_count"] == 0
    assert sheet["file_total"] == 3011
    assert sheet["presented_total"] == sheet["file_total"]
    assert sheet["liabilities"]["total"] == 400
    assert sheet["equity"]["total"] == 1100.5
    assert sheet["equity"]["opening_equity"] is None
    assert sheet["status"] == "partial"
    for line in sheet["assets"]["lines"]:
        assert line["source_label"]
        assert line["synced_at"]

    third = _upload(client, org["headers"], content, "balance_sheet.csv", kind="balance_sheet")
    assert third.status_code == 200
    with SessionLocal() as db:
        kept = next(row for row in _portal_rows(db, org["org_id"]) if row.external_id.endswith(":1000"))
        assert kept.raw_data["imported_at"] == stamp
        assert len(_portal_rows(db, org["org_id"])) == 4


def test_reimport_updates_one_line_and_drops_a_removed_line_without_duplicating(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    original = (FIXTURES / "balance_sheet.csv").read_bytes()
    assert _upload(client, org["headers"], original, "balance_sheet.csv").status_code == 200
    revised = (
        "מפתח,שם חשבון,סעיף,יתרה\n"
        "1000,קופה,נכסים,1600.00\n"
        "2000,ספקים,התחייבויות,400\n"
        "3000,הון מניות,הון,1200.00\n"
    ).encode()
    updated = _upload(client, org["headers"], revised, "balance_sheet.csv", kind="balance_sheet")
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["inserted"] == 0
    assert body["updated"] == 2
    assert body["unchanged"] == 1
    assert body["removed"] == 1
    with SessionLocal() as db:
        rows = _portal_rows(db, org["org_id"])
        assert len(rows) == 3
        amounts = {row.external_id: row.raw_data["line"]["amount"] for row in rows}
        assert amounts[f"balance_sheet:{AS_OF}:1000"] == "1600.00"
        assert all(not key.endswith(":9999") for key in amounts)


def test_portal_balance_sheet_is_not_added_to_the_derived_ledger(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
        db.add(Invoice(
            organization_id=org["org_id"], invoice_number="9", issue_date=date(2026, 9, 2),
            status=InvoiceStatus.SENT, subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118"),
        ))
        db.commit()
    content = (FIXTURES / "balance_sheet.csv").read_bytes()
    assert _upload(client, org["headers"], content, "balance_sheet.csv", kind="balance_sheet").status_code == 200
    with SessionLocal() as db:
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]
    assert sheet["presentation"] == "compared"
    assert sheet["basis"] is None
    portal = sheet["portal"]
    books = sheet["books"]
    assert portal["basis_label"] and books["basis_label"]
    assert portal["basis_label"] != books["basis_label"]
    assert portal["synced_at"] and books["synced_at"]
    assert portal["liabilities"]["total"] == 400
    assert books["liabilities"]["total"] == 18
    assert portal["assets"]["lines"][0]["source"] == "sumit_portal_export"
    assert books["assets"]["lines"][0]["source"] == "rezef_books"
    assert sheet["difference"]["liabilities"]["gap"] == 382
    assert sheet["difference"]["liabilities"]["flagged"] is True
    assert sheet["difference"]["assets"]["flagged"] is True
    assert sheet["difference"]["equity"]["gap"] is None
    assert sheet["difference"]["equity"]["flagged"] is False


def test_section_gap_is_flagged_only_above_one_shekel():
    from cfo.services.dashboards.balance_sheet import section_gap

    assert section_gap(101, 100)["flagged"] is False
    assert section_gap(100, 101)["gap"] == -1
    assert section_gap(101.01, 100)["flagged"] is True
    assert section_gap(None, 100)["gap"] is None
    assert section_gap(None, 100)["flagged"] is False


def test_unsectioned_import_lines_stay_in_the_file_total(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    content = (
        "מפתח,שם חשבון,סעיף,יתרה\n"
        "1000,קופה,נכסים,1500.50\n"
        "2000,ספקים,התחייבויות,400\n"
        "3000,הון מניות,הון,1100.50\n"
        "9999,כרטיס לא מוכר,נכסים,10\n"
        "7777,בלי סעיף,,25\n"
        "4000,הכנסה שנכנסה למאזן,הכנסות,7\n"
    ).encode()
    assert _upload(client, org["headers"], content, "balance_sheet.csv", kind="balance_sheet").status_code == 200
    with SessionLocal() as db:
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]
    assets = {line["code"]: line for line in sheet["assets"]["lines"]}
    assert assets["9999"]["mark"] == "לא ממופה"
    assert assets["9999"]["amount"] == 10
    assert sheet["assets"]["total"] == 1510.5
    loose = {line["code"]: line for line in sheet["unclassified"]["lines"]}
    assert sheet["unclassified"]["label"] == "ללא סיווג"
    assert set(loose) == {"7777", "4000"}
    assert sheet["unclassified"]["amount"] == 32
    assert sheet["unclassified"]["row_count"] == 2
    assert sheet["file_total"] == 3043
    assert sheet["presented_total"] == (
        sheet["assets"]["total"] + sheet["liabilities"]["total"] + sheet["equity"]["total"] + sheet["unclassified"]["amount"]
    )
    assert sheet["presented_total"] == sheet["file_total"]


def test_blank_amount_stays_unknown_and_an_explicit_zero_stays_zero(client, fresh_org):
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    content = (
        "מפתח,שם חשבון,סעיף,יתרה\n"
        "1000,קופה,נכסים,\n"
        "2000,ספקים,התחייבויות,0\n"
    ).encode()
    response = _upload(client, org["headers"], content, "partial.csv", kind="balance_sheet")
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]
    assets = sheet["assets"]["lines"][0]
    assert assets["amount"] is None
    assert sheet["assets"]["total"] is None
    assert sheet["liabilities"]["total"] == 0
    assert sheet["liabilities"]["lines"][0]["synced_at"]


def test_invalid_amount_rejects_the_file_and_writes_nothing(client, fresh_org):
    org = fresh_org()
    content = "מפתח,שם חשבון,סעיף,יתרה\n1000,קופה,נכסים,לא-מספר\n".encode()
    response = _upload(client, org["headers"], content, "bad.csv", kind="balance_sheet")
    assert response.status_code == 400
    with SessionLocal() as db:
        assert _portal_rows(db, org["org_id"]) == []


def test_profit_loss_and_ledger_cards_xlsx_show_on_the_dashboard(client, fresh_org):
    import openpyxl
    from cfo.services.dashboards.view_model import build_view

    org = fresh_org()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    pnl = (FIXTURES / "profit_loss.csv").read_bytes()
    assert _upload(client, org["headers"], pnl, "profit_loss.csv", kind="profit_loss").status_code == 200

    workbook = openpyxl.Workbook()
    grid = workbook.active
    for row in (FIXTURES / "ledger_cards.csv").read_text(encoding="utf-8").splitlines():
        grid.append(row.split(","))
    buffer = BytesIO()
    workbook.save(buffer)
    cards = _upload(client, org["headers"], buffer.getvalue(), "ledger_cards.xlsx", kind="ledger_cards")
    assert cards.status_code == 200, cards.text
    assert cards.json()["inserted"] == 2

    again = _upload(client, org["headers"], buffer.getvalue(), "ledger_cards.xlsx", kind="ledger_cards")
    assert again.json()["unchanged"] == 2 and again.json()["inserted"] == 0

    with SessionLocal() as db:
        assert len(_portal_rows(db, org["org_id"])) == 5
        sheet = build_view(db, org["org_id"], date(2026, 9, 1), date(2026, 9, 30))["balance_sheet"]

    profit = sheet["imports"]["profit_loss"]
    assert profit["status"] == "partial"
    assert profit["total_revenue"] == 8000
    assert profit["total_expenses"] == 2530
    assert profit["synced_at"]
    assert profit["lines"][0]["source"] == "sumit_portal_export"
    cards_view = sheet["imports"]["ledger_cards"]
    assert cards_view["status"] == "ready"
    assert cards_view["cards"][0]["code"] == "1000"
    assert cards_view["cards"][0]["amount"] == 1700.5
    assert cards_view["cards"][0]["synced_at"]
    assert cards_view["total"] is None


def test_import_is_scoped_to_the_organization(client, fresh_org):
    org = fresh_org()
    other = fresh_org()
    content = (FIXTURES / "balance_sheet.csv").read_bytes()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    assert _upload(client, org["headers"], content, "balance_sheet.csv").status_code == 200
    theirs = client.get(UPLOAD, headers=other["headers"])
    assert theirs.status_code == 200
    assert theirs.json()["balance_sheet"] is None
    assert theirs.json()["provider_calls"] == 0
    with SessionLocal() as db:
        assert _portal_rows(db, other["org_id"]) == []


def test_hebrew_excel_encodings_and_explicit_kind(client, fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        _chart(db, org["org_id"])
    semicolon = "מפתח;שם חשבון;סעיף;יתרה\n1000;קופה;נכסים;5\n".encode("cp1255")
    response = _upload(client, org["headers"], semicolon, "מאזן.csv")
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "balance_sheet"
    assert response.json()["inserted"] == 1


def test_portal_import_does_not_call_sumit_or_enable_the_weekly_pull(client, fresh_org, monkeypatch):
    import inspect
    import cfo.integrations.sumit_integration as sumit_integration
    import cfo.services.dashboards.balance_sheet as sheet
    import cfo.services.sumit_portal_export as portal
    from cfo.config import Settings
    from cfo.services.sumit_request_budget import LIVE_ACCOUNT_REQUEST_HARD_CAP

    assert "SumitIntegration" not in inspect.getsource(portal)
    assert "SumitIntegration" not in inspect.getsource(sheet)
    monkeypatch.setattr(
        sumit_integration, "SumitIntegration",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SUMIT client constructed")),
    )
    org = fresh_org()
    content = (FIXTURES / "balance_sheet.csv").read_bytes()
    response = _upload(client, org["headers"], content, "balance_sheet.csv", kind="balance_sheet")
    assert response.status_code == 200, response.text
    loaded = Settings(_env_file=None)
    assert loaded.sumit_weekly_pull_enabled is False
    assert LIVE_ACCOUNT_REQUEST_HARD_CAP == 50
    assert loaded.sumit_live_monthly_request_limit <= 50


def test_upload_requires_an_authenticated_admin(client):
    response = client.post(UPLOAD, files={"file": ("a.csv", "מפתח\n".encode(), "text/csv")})
    assert response.status_code == 403
    assert response.json()["detail"] == "Not authenticated"


def test_dashboard_screen_names_the_balance_sheet_tab():
    page = Path("frontend/src/components/ClientDashboardPage.tsx").read_text(encoding="utf-8")
    tab = Path("frontend/src/components/balanceSheetTab.tsx").read_text(encoding="utf-8")
    assert "{ id: 'balance', label: 'מאזן' }" in page
    assert "money(" in tab


def test_combined_dashboard_does_not_add_balance_sheets(client, fresh_org):
    from cfo.services.dashboards.balance_sheet import unknown_balance_sheet

    sheet = unknown_balance_sheet("המאזן מוצג לכל ישות בנפרד. החיבור המאוחד אינו מחבר מאזנים.")
    assert sheet["assets"]["total"] is None
    assert sheet["status"] == "unknown"
    assert "אינו מחבר" in sheet["message"]
