"""get_tax_calendar() החזיר עד כה 'estimated_amount' קבוע (15000/8000/25000)
לכל תקופה, ללא קשר לנתונים האמיתיים -- וגרוע מכך, ה-route העביר את פרמטר
ה-'year' (למשל 2026) כארגומנט הפוזיציוני months_ahead, מה שיצר 2027
איטרציות (6081 פריטים) בכל קריאה. שני הבאגים נמצאים באותו קוד ותוקנו יחד:
הסכומים נגזרים כעת מהמתודות האמיתיות הקיימות (generate_vat_report,
calculate_tax_advance, generate_withholding_report), וה-route כבר לא
מזין year לתוך months_ahead.
"""
from datetime import date

import pytest


@pytest.fixture(scope="module")
def tax_org(client):
    from cfo.database import SessionLocal
    from cfo.models import (
        Contact, ContactType, Invoice, InvoiceStatus, Expense,
        Employee, Payslip,
    )

    reg = client.post("/api/admin/auth/register", json={
        "email": "taxcalendar@example.com", "password": "secret123", "full_name": "Tax Calendar",
    })
    assert reg.status_code == 201, reg.text
    payload = reg.json()
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    org_id = payload["user"]["organization_id"]

    today = date.today()
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח מעמ")
        db.add(cust); db.flush()
        # חשבונית עם מע"מ אמיתי לחודש הנוכחי: נטו 200000 + מע"מ 36000
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="TC-VAT-1",
                       issue_date=today, due_date=today,
                       subtotal=200000, tax=36000, total=236000,
                       paid_amount=0, balance=236000, status=InvoiceStatus.SENT))
        # הוצאה עם מע"מ תשומות אמיתי: נטו 100000 + מע"מ 18000
        db.add(Expense(organization_id=org_id, supplier_name="ספק מעמ",
                       amount=100000, vat_amount=18000, total=118000,
                       expense_date=today, status="filed"))

        emp = Employee(organization_id=org_id, name="עובד בדיקה", gross_salary=15000)
        db.add(emp); db.flush()
        db.add(Payslip(organization_id=org_id, employee_id=emp.id, year=today.year, month=today.month,
                       gross=15000, income_tax=2200, ni_employee=550, health_tax=800,
                       pension_employee=900, net=11550, employer_ni=650,
                       employer_pension=1050, employer_severance=500, employer_cost=17200))
        db.commit()
        return {"org_id": org_id, "headers": headers}
    finally:
        db.close()


def _find_vat_item(calendar_data, period):
    for item in calendar_data["upcoming_deadlines"] + calendar_data["overdue_items"]:
        if item["type"] == "VAT" and item["period"] == period:
            return item
    return None


def test_tax_calendar_vat_amount_is_real_not_hardcoded(client, tax_org):
    today = date.today()
    period = f"{today.year}-{today.month:02d}"
    r = client.get("/api/financial/tax/calendar", headers=tax_org["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    item = _find_vat_item(data, period)
    assert item is not None, data
    # מע"מ עסקאות אמיתי 36000 פחות תשומות אמיתיות 18000 = 18000, לא 15000 הקבוע הישן
    assert item["estimated_amount"] == 18000
    assert item["estimated_amount"] != 15000


def test_tax_calendar_withholding_amount_reflects_real_payslip(client, tax_org):
    today = date.today()
    period = f"{today.year}-{today.month:02d}"
    r = client.get("/api/financial/tax/calendar", headers=tax_org["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    items = [i for i in data["upcoming_deadlines"] + data["overdue_items"]
             if i["type"] == "WITHHOLDING_102" and i["period"] == period]
    assert items, data
    # 2200 (מס הכנסה) + 550 (בל אישי) + 800 (בריאות) = 3550, לא 25000 הקבוע הישן
    assert items[0]["estimated_amount"] == 3550
    assert items[0]["estimated_amount"] != 25000


def test_tax_calendar_response_size_is_bounded(client, tax_org):
    """לפני התיקון: ה-route העביר year (למשל 2026) כ-months_ahead, מה שיצר
    2027 איטרציות (6081 פריטים) בכל קריאה. אחרי התיקון, ברירת המחדל
    months_ahead=3 אמורה להישמר ללא קשר לשנה הנוכחית."""
    r = client.get("/api/financial/tax/calendar", headers=tax_org["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    total_items = len(data["upcoming_deadlines"]) + len(data["overdue_items"]) + len(data["completed_items"])
    assert total_items < 20, total_items
