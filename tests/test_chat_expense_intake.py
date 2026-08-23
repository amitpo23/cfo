"""חבילה A (תכנית מושקו, 2026-07-27) — קליטת קבלה בשיחה → הוצאה, בלי לעבור
דרך טיוטת SUMIT. שום קריאת רשת אמיתית — vision_extractor.extract_receipt
תמיד מדומה (monkeypatch) בקובץ הזה."""
import asyncio
import os
import time
from datetime import date, datetime

import pytest

import cfo.services.vision_extractor as ve
from cfo import config as config_module
from cfo.database import SessionLocal
from cfo.models import Expense
from cfo.services.chat_expense_intake import count_receipts_today, intake_receipt_bytes
from cfo.services.vision_extractor import VisionExtractionError

FAKE_RECEIPT_BYTES = b"%PDF-1.4 fake receipt bytes"


def _good_extract(**overrides):
    base = {
        "supplier_name": "שופרסל",
        "supplier_tax_id": "520022732",
        "amount_total": 118.0,
        "vat_amount": 18.0,
        "net_amount": 100.0,
        "invoice_number": "INV-9001",
        "expense_date": date.today().isoformat(),
        "currency": "ILS",
        "document_type": "invoice",
        "confidence": 0.92,
        "is_readable": True,
        "notes": None,
    }
    base.update(overrides)
    return base


def _mock_extract(monkeypatch, result=None, exc=None):
    calls = {"n": 0}

    async def fake_extract_receipt(content, media_type=None, *, user_initiated=False, **_context):
        calls["n"] += 1
        if exc is not None:
            raise exc
        return result

    # chat_expense_intake imports extract_receipt locally inside the
    # function body (`from .vision_extractor import extract_receipt`), so
    # patching the attribute on vision_extractor itself is what the local
    # import actually resolves at call time.
    monkeypatch.setattr(ve, "extract_receipt", fake_extract_receipt)
    return calls


@pytest.fixture(autouse=True)
def _reset_intake_settings(monkeypatch):
    monkeypatch.setattr(config_module.settings, "chat_receipt_intake_enabled", True)
    monkeypatch.setattr(config_module.settings, "chat_receipt_daily_limit", 20)


def test_disabled_flag_blocks_before_any_llm_call(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(config_module.settings, "chat_receipt_intake_enabled", False)
    calls = _mock_extract(monkeypatch, result=_good_extract())

    db = SessionLocal()
    try:
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "disabled"
        assert calls["n"] == 0
    finally:
        db.close()


def test_daily_limit_zero_is_treated_as_disabled(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(config_module.settings, "chat_receipt_daily_limit", 0)
    calls = _mock_extract(monkeypatch, result=_good_extract())

    db = SessionLocal()
    try:
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "disabled"
        assert calls["n"] == 0
    finally:
        db.close()


def test_daily_limit_reached_blocks_before_llm_call(monkeypatch, fresh_org):
    """מעבר לתקרה -> status=limit_reached, ו-extract_receipt לא נקרא כלל."""
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(config_module.settings, "chat_receipt_daily_limit", 2)
    calls = _mock_extract(monkeypatch, result=_good_extract())

    db = SessionLocal()
    try:
        from cfo.services.expense_filing_service import ExpenseFilingService
        service = ExpenseFilingService(db, organization_id=org_id)
        for _ in range(2):
            service.create_expense({
                "source": "telegram", "supplier_name": "ספק קודם",
                "amount": 10, "vat_amount": 1.8, "expense_date": date.today(),
            })

        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "limit_reached"
        assert calls["n"] == 0
    finally:
        db.close()


def test_llm_extraction_error_is_returned_as_status_error_not_raised(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    _mock_extract(monkeypatch, exc=VisionExtractionError("קריאת Anthropic נכשלה: boom"))

    db = SessionLocal()
    try:
        before = db.query(Expense).filter(Expense.organization_id == org_id).count()
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "error"
        after = db.query(Expense).filter(Expense.organization_id == org_id).count()
        assert after == before
    finally:
        db.close()


def test_unreadable_receipt_does_not_create_an_expense(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    _mock_extract(monkeypatch, result=_good_extract(is_readable=False, confidence=0.1))

    db = SessionLocal()
    try:
        before = db.query(Expense).filter(Expense.organization_id == org_id).count()
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "unreadable"
        assert "extracted" in result
        after = db.query(Expense).filter(Expense.organization_id == org_id).count()
        assert after == before
    finally:
        db.close()


def test_low_confidence_receipt_does_not_create_an_expense(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    _mock_extract(monkeypatch, result=_good_extract(is_readable=True, confidence=0.2))

    db = SessionLocal()
    try:
        before = db.query(Expense).filter(Expense.organization_id == org_id).count()
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "unreadable"
        after = db.query(Expense).filter(Expense.organization_id == org_id).count()
        assert after == before
    finally:
        db.close()


def test_high_confidence_duplicate_does_not_create_an_expense(monkeypatch, fresh_org):
    """כפילות HIGH (ח.פ+אסמכתא זהים למסמך קיים) -> status=duplicate, ולא
    נוצרת הוצאה חדשה."""
    org_id = fresh_org()["org_id"]
    extract = _good_extract()
    _mock_extract(monkeypatch, result=extract)

    db = SessionLocal()
    try:
        from cfo.services.expense_filing_service import ExpenseFilingService
        service = ExpenseFilingService(db, organization_id=org_id)
        existing = service.create_expense({
            "source": "sumit", "supplier_name": extract["supplier_name"],
            "amount": 100, "vat_amount": 18, "expense_date": date.today(),
            "invoice_number": extract["invoice_number"],
        })
        db.query(Expense).filter(Expense.id == existing["id"]).update(
            {"supplier_tax_id": extract["supplier_tax_id"]}
        )
        db.commit()

        before = db.query(Expense).filter(Expense.organization_id == org_id).count()
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "duplicate"
        assert result["candidates"]
        after = db.query(Expense).filter(Expense.organization_id == org_id).count()
        assert after == before
    finally:
        db.close()


def test_successful_intake_creates_expense_with_source_and_receipt_file(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    extract = _good_extract()
    _mock_extract(monkeypatch, result=extract)

    db = SessionLocal()
    try:
        result = asyncio.run(
            intake_receipt_bytes(
                db, org_id, FAKE_RECEIPT_BYTES, source="telegram", uploaded_by_user_id=7,
            )
        )
        assert result["status"] == "created"
        assert extract["supplier_name"] in result["message"]
        assert "118" in result["message"] or "118.00" in result["message"]

        exp = db.query(Expense).filter(Expense.id == result["expense_id"]).first()
        assert exp is not None
        assert exp.source == "telegram"
        assert exp.receipt_file
        assert exp.supplier_tax_id == extract["supplier_tax_id"]
        assert exp.status == "pending"  # טיוטה — לא תויקה אוטומטית
    finally:
        db.close()


def test_missing_amount_is_treated_as_unreadable_not_a_crash(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    _mock_extract(monkeypatch, result=_good_extract(amount_total=None, vat_amount=None, net_amount=None))

    db = SessionLocal()
    try:
        before = db.query(Expense).filter(Expense.organization_id == org_id).count()
        result = asyncio.run(intake_receipt_bytes(db, org_id, FAKE_RECEIPT_BYTES))
        assert result["status"] == "unreadable"
        after = db.query(Expense).filter(Expense.organization_id == org_id).count()
        assert after == before
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# vision_extractor.extract_receipt — user_initiated gate (real function,
# not mocked here — proving the two cost gates are actually independent).
# ---------------------------------------------------------------------- #

def test_extract_receipt_background_default_still_gated_by_ocr_llm_enabled(monkeypatch):
    """שמירת ההתנהגות הקיימת: user_initiated=False (ברירת מחדל) נחסם ע"י
    ocr_llm_enabled כמו קודם, גם כש-chat_receipt_intake_enabled פעיל."""
    monkeypatch.setattr(config_module.settings, "ocr_llm_enabled", False)
    monkeypatch.setattr(config_module.settings, "chat_receipt_intake_enabled", True)
    monkeypatch.setattr(config_module.settings, "anthropic_api_key", "test-key")

    with pytest.raises(VisionExtractionError, match="כבוי"):
        asyncio.run(ve.extract_receipt(FAKE_RECEIPT_BYTES))


def test_extract_receipt_user_initiated_gated_by_chat_receipt_intake_enabled(monkeypatch):
    """user_initiated=True נבדק מול chat_receipt_intake_enabled, לא מול
    ocr_llm_enabled — גם אם ocr_llm_enabled=True, דגל הצ'אט הכבוי חוסם."""
    monkeypatch.setattr(config_module.settings, "ocr_llm_enabled", True)
    monkeypatch.setattr(config_module.settings, "chat_receipt_intake_enabled", False)
    monkeypatch.setattr(config_module.settings, "anthropic_api_key", "test-key")

    with pytest.raises(VisionExtractionError, match="כבוי"):
        asyncio.run(ve.extract_receipt(FAKE_RECEIPT_BYTES, user_initiated=True))


# --------------------------------------------------------------------- #
# Regression (21/08/2026 review, follow-up #2): midnight-window TZ flake.
#
# Root cause: `_today_bounds()` used to derive "today" from `date.today()`
# (the server process's LOCAL calendar date), while `Expense.created_at`
# defaults to `datetime.utcnow()` (naive UTC). Those two are the same
# calendar day almost always — except during the server's local
# 00:00-03:00 window under IDT (UTC+3): local "today" has already rolled
# over to day D while UTC is still on day D-1, so a row created seconds ago
# with `created_at` in UTC day D-1 falls outside a bounds window computed
# for local day D, and the daily-limit counter silently reports 0 for a
# receipt that was just filed.
#
# This test freezes "now" to exactly such an instant (2026-08-21 22:00 UTC
# == 2026-08-22 01:00 in Asia/Jerusalem, i.e. the middle of the buggy
# window) and flips the process's local timezone across the run, proving
# the count is TZ-independent — i.e. derived from UTC like `created_at`,
# not from local wall-clock date. `time.tzset()` is POSIX-only (fine: this
# repo targets macOS/Linux, not Windows).
# --------------------------------------------------------------------- #
def test_count_receipts_today_is_timezone_independent_across_utc_midnight(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # created_at pinned to 22:00 UTC on day D-1 — this is the instant a
        # receipt filed "just now" would actually carry, if "now" (UTC) is
        # 2026-08-21 22:00, i.e. 2026-08-22 01:00 local time in
        # Asia/Jerusalem (IDT, UTC+3) — the middle of the buggy window.
        fixed_now = datetime(2026, 8, 21, 22, 0, 0)
        db.add(Expense(
            organization_id=org_id, source="telegram", supplier_name="ספק",
            amount=10, vat_amount=0, total=10,
            expense_date=fixed_now.date(), status="pending",
            created_at=fixed_now,
        ))
        db.commit()

        class _FrozenDatetime(datetime):
            @classmethod
            def utcnow(cls):
                return fixed_now

        import cfo.services.chat_expense_intake as intake_module
        monkeypatch.setattr(intake_module, "datetime", _FrozenDatetime)

        old_tz = os.environ.get("TZ")
        try:
            counts = {}
            for tz_name in ("UTC", "Asia/Jerusalem"):
                os.environ["TZ"] = tz_name
                time.tzset()
                counts[tz_name] = count_receipts_today(db, org_id, "telegram")
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

        assert counts["UTC"] == 1
        assert counts["Asia/Jerusalem"] == 1
        assert counts["UTC"] == counts["Asia/Jerusalem"]
    finally:
        db.close()
