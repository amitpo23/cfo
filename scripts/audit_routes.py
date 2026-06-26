#!/usr/bin/env python3
"""
מיפוי מלא — audit של כל ה-GET routes במערכת מול נתונים אמיתיים.
מריץ TestClient בזיכרון, יוצר משתמש+נתוני דמה, ופונה לכל GET route, ומדווח סטטוס.

הרצה: python scripts/audit_routes.py
"""
import os
import sys
import tempfile
from collections import defaultdict

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='audit_')}/a.db"
os.environ["CRON_SECRET"] = "audit-cron"
os.environ.pop("REGISTRATION_SECRET", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, timedelta  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from cfo.api import app  # noqa: E402
from cfo.database import SessionLocal  # noqa: E402
from cfo.models import (  # noqa: E402
    Account, AccountType, Contact, ContactType, Invoice, InvoiceStatus,
    Bill, BillStatus, Transaction, TransactionType, InventoryItem, Expense,
)


def seed(org_id):
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=50000)
        db.add(acct); db.flush()
        today = date.today()
        db.add_all([
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.INCOME,
                        amount=100000, category="sales", transaction_date=today.replace(day=1)),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=40000, category="materials", transaction_date=today.replace(day=1)),
        ])
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח", tax_id="123456782")
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק", tax_id="987654321",
                       bank_code="12", bank_branch="345", bank_account_number="111")
        db.add_all([cust, vend]); db.flush()
        db.add_all([
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="INV1",
                    issue_date=today - timedelta(days=40), due_date=today - timedelta(days=10),
                    total=20000, paid_amount=0, balance=20000, status=InvoiceStatus.OVERDUE),
            Bill(organization_id=org_id, vendor_id=vend.id, bill_number="BILL1",
                 issue_date=today - timedelta(days=10), due_date=today + timedelta(days=5),
                 total=15000, paid_amount=0, balance=15000, status=BillStatus.APPROVED),
            InventoryItem(organization_id=org_id, name="פריט", quantity=5, unit_cost=100, reorder_level=2),
            Expense(organization_id=org_id, supplier_name="ספק", amount=500, vat_amount=90, total=590,
                    expense_date=today, category="materials", status="pending"),
        ])
        db.commit()
        ids = {
            "cust": cust.id, "vend": vend.id,
            "exp": db.query(Expense).first().id,
        }
        return ids
    finally:
        db.close()


PLACEHOLDERS = {
    "customer_id": "1", "product_id": "P1", "metric": "revenue", "expense_id": "{exp}",
    "id": "1", "schedule_id": "1", "template_id": "1", "invoice_id": "1",
    "report_id": "1", "year": "2026", "alert_id": "1", "task_id": "1",
    "run_id": "1", "account_id": "1", "contact_id": "1", "bill_id": "1",
}


def main():
    with TestClient(app) as c:
        reg = c.post("/api/admin/auth/register", json={
            "email": "audit@example.com", "password": "secret123", "full_name": "Audit",
        })
        token = reg.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ids = seed(reg.json()["user"]["organization_id"])

        results = defaultdict(list)
        seen = set()
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if "GET" not in methods or not path.startswith("/api/"):
                continue
            url = path
            skip = False
            for key, val in PLACEHOLDERS.items():
                token_ph = "{" + key + "}"
                if token_ph in url:
                    v = str(ids["exp"]) if val == "{exp}" else val
                    url = url.replace(token_ph, v)
            if "{" in url or url in seen:
                continue
            seen.add(url)
            # router group = first two path segments
            group = "/".join(path.split("/")[:3])
            try:
                r = c.get(url, headers=h)
                code = r.status_code
            except Exception as e:
                code = f"EXC:{type(e).__name__}"
            results[group].append((url, code))

        # report
        total = ok = warn = bad = 0
        print("=" * 70)
        print("מיפוי מלא — GET routes (על ארגון עם נתונים)")
        print("=" * 70)
        for group in sorted(results):
            print(f"\n## {group}")
            for url, code in sorted(results[group]):
                total += 1
                if code == 200:
                    mark = "OK  "; ok += 1
                elif isinstance(code, int) and code in (401, 403, 404, 422):
                    mark = "WARN"; warn += 1
                else:
                    mark = "FAIL"; bad += 1
                print(f"  [{mark}] {code} {url}")
        print("\n" + "=" * 70)
        print(f"סהכ: {total} | תקין(200): {ok} | אזהרה(4xx): {warn} | כשל(5xx/EXC): {bad}")
        print("=" * 70)
        return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
