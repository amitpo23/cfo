"""W6.4 — חיזוק סכימת הכסף ברמת ה-DB (SWOT: 0 אילוצים על כסף).

מה נאכף (בטוח מול נתוני אמת):
- עמודות כסף NOT NULL עם server_default=0 — INSERT שעוקף את ה-ORM
  (סנכרון bulk, SQL ידני) לא ישאיר עוד NULL שמאפס SUM בשקט.
- אינדקסים על השאילתות הכבדות: journal_entries(org, entry_date) —
  ‏15K שורות נסרקו בכל דוח תקופתי; payments לפי invoice/bill/תאריך.
- ייחודיות ל-expenses על (org, external_id, source) כשיש external_id
  (partial) — האינדקס הקיים לא היה unique בכלל.

מה **לא** נאכף בכוונה: אילוצי סימן (amount>0) — זיכוי ספק שלילי הוא
לגיטימי (ר' docstring של _bills_nonnegative); סימנים נבדקים רך
ב-data_quality.
"""
import pytest
from sqlalchemy import inspect

from cfo.database import engine


def _columns(table):
    return {c["name"]: c for c in inspect(engine).get_columns(table)}


def _index_names(table):
    return {ix["name"] for ix in inspect(engine).get_indexes(table)}


MONEY_COLUMNS = {
    "invoices": ("subtotal", "tax", "total", "paid_amount", "balance"),
    "bills": ("subtotal", "tax", "total", "paid_amount", "balance"),
}


def test_money_columns_are_not_nullable_with_default(client):
    for table, cols in MONEY_COLUMNS.items():
        actual = _columns(table)
        for col in cols:
            assert actual[col]["nullable"] is False, f"{table}.{col} nullable"
            assert actual[col]["default"] is not None, f"{table}.{col} no server default"


def test_heavy_query_indexes_exist(client):
    assert "ix_je_org_entry_date" in _index_names("journal_entries")
    payment_indexes = _index_names("payments")
    assert "ix_payment_invoice" in payment_indexes
    assert "ix_payment_bill" in payment_indexes
    assert "ix_payment_org_date" in payment_indexes
    assert "ix_transaction_org" in _index_names("transactions")


def test_expenses_external_id_is_unique_when_present(client):
    indexes = inspect(engine).get_indexes("expenses")
    target = next((ix for ix in indexes if ix["name"] == "ix_expense_org_ext"), None)
    assert target is not None
    assert bool(target["unique"]) is True  # sqlite מחזיר 1, פוסטגרס True
