"""Entity-sync priority order (25/08/2026).

**הממצא (בדיקה חיה על אליהב כהן, org2, פרוד).** הסנכרון היומי מ-SUMIT
לארגונים 1/2/5 מ-24/08 ואילך מסתיים PARTIAL: `accounts`+`vendors`
מצליחים, אבל `customers`/`invoices`/`bills`/`payments` — המסמכים
הפיננסיים שמושקו וכל שאר רצף תלויים בהם — נכשלים עם
"SUMIT global minute request budget exceeded" כי `all_types` (ב-
`sync_engine.py`) מריץ את `accounts`/`vendors` **לפני** המסמכים
הפיננסיים, וכשהמכסה-לדקה (מסלול-בדיקות: 10) נגמרת באמצע, מה שנשאר
מחוץ למכסה הוא בדיוק המידע החשוב ביותר.

התיקון: לא נוגע במכסה/ב-limiter עצמם (אין הקלה על ה-hard rule) —
רק בסדר-העדיפות בתוך אותה מכסה קיימת, כך שכשחלה חריגה, מה שנופל
הוא accounts/vendors (מידע איטי-שינוי, ולא-קריטי לדוחות) ולא
המסמכים הפיננסיים. `_upsert_invoice`/`_upsert_bill` כבר סובלים
`contact_id=None` בחן (contact_backfill רץ בסוף בכל מקרה) — אין
תלות-סדר אמיתית שדורשת customers/vendors לפני invoices/bills.
"""
import asyncio

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import Organization
from cfo.services.connector_base import FetchResult
from cfo.services.sync_engine import SyncEngine


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _make_org(db, name="Priority Co"):
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


class _OrderRecordingConnector:
    """Records the order entity types are actually fetched in."""

    def __init__(self):
        self.order = []

    async def _record(self, entity_type):
        self.order.append(entity_type)
        return FetchResult(items=[], has_more=False)

    async def fetch_accounts(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("accounts")

    async def fetch_customers(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("customers")

    async def fetch_vendors(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("vendors")

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("invoices")

    async def fetch_bills(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("bills")

    async def fetch_payments(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("payments")

    async def fetch_bank_transactions(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("bank_transactions")

    async def fetch_journal_entries(self, updated_since=None, cursor=None, page_size=100):
        return await self._record("journal_entries")


def test_financial_documents_sync_before_accounts_and_vendors():
    """invoices/bills/payments/customers must be attempted before
    accounts/vendors, so a mid-run budget cutoff drops the least-critical
    data first, never the financial documents."""
    db = SessionLocal()
    try:
        org_id = _make_org(db).id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _OrderRecordingConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        asyncio.run(engine.run_full_sync())
    finally:
        db.close()

    order = connector.order
    assert set(order) == {
        "accounts", "customers", "vendors", "invoices",
        "bills", "payments", "bank_transactions", "journal_entries",
    }
    financial = {"invoices", "bills", "payments", "customers"}
    administrative = {"accounts", "vendors"}
    last_financial_index = max(order.index(t) for t in financial)
    first_administrative_index = min(order.index(t) for t in administrative)
    assert last_financial_index < first_administrative_index, (
        f"order was {order} — accounts/vendors must not run before "
        "the financial documents"
    )
