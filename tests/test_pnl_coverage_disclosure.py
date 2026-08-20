"""רו"ה חייב להצהיר כשצד ההכנסות מסונכרן פחות מצד ההוצאות.

**הממצא (18/08/2026), נמדד בפרוד.** ב-6 החודשים האחרונים:

    org1 עמית פורת    —  3 חשבוניות  מול  229 חשבונות ספק
    org5 עומר ועודד   — 27 חשבוניות  מול   81
    org2 שף אליהב     —  7 חשבוניות  מול   45

ורוחב התקופה מספר את אותו סיפור: חשבוניות org1 נעצרות ב-03/2026 בזמן
שחשבונות הספק ממשיכים ל-07/2026.

רו"ה עבור org1 יראה **הפסד** — אבל 3 מסמכי הכנסה מול 229 מסמכי הוצאה
אינם עדות להפסד, הם עדות לכך שצד ההכנסות אינו מסתנכרן. המספר נכון
אריתמטית וחסר משמעות כלכלית, והמערכת מסרה אותו בלי לומר זאת.

**זהו בדיוק הכשל שתוקן ב-parity:** דוח שאינו מסייג את עצמו מאמן את
הקורא להאמין לו. הכלל כאן זהה — לא להשתיק את המספר ולא להגיש אותו חשוף.

**מה זה לא עושה:** אינו מנחש הכנסה חסרה, אינו מתקן, ואינו חוסם. הוא
מצרף לדוח את יחס המסמכים ואת פער הכיסוי, כדי שההחלטה תהיה של הקורא.
"""
from datetime import date, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Invoice, InvoiceStatus
from cfo.services.financial_reports_service import FinancialReportsService


TODAY = date(2026, 8, 18)
START = TODAY - timedelta(days=180)


def _bill(db, org_id, when, amount):
    db.add(Bill(organization_id=org_id, bill_number=f"B{when}{amount}",
                issue_date=when, subtotal=amount, tax=0.0,
                status=BillStatus.RECEIVED))


def _invoice(db, org_id, when, amount):
    db.add(Invoice(organization_id=org_id, invoice_number=f"I{when}{amount}",
                   issue_date=when, subtotal=amount, tax=0.0,
                   status=InvoiceStatus.SENT))


def test_a_lopsided_org_is_flagged(client, fresh_org):
    """**התרחיש של org1.** מעט מסמכי הכנסה מול הרבה מסמכי הוצאה."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _invoice(db, org_id, TODAY - timedelta(days=150), 20000)
    for i in range(40):
        _bill(db, org_id, TODAY - timedelta(days=i * 4), 500)
    db.commit()

    rep = FinancialReportsService(db).generate_profit_loss(
        org_id, START, TODAY, compare_previous=False)

    assert rep.coverage["balanced"] is False
    assert rep.coverage["warning_he"], "אין הסבר — הקורא לא יידע מה לעשות"


def test_a_balanced_org_carries_no_warning(client, fresh_org):
    """שער נגדי: אזהרה שמופיעה תמיד היא אזהרה שאיש אינו קורא."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    for i in range(10):
        _invoice(db, org_id, TODAY - timedelta(days=i * 10), 3000)
        _bill(db, org_id, TODAY - timedelta(days=i * 10), 1000)
    db.commit()

    rep = FinancialReportsService(db).generate_profit_loss(
        org_id, START, TODAY, compare_previous=False)

    assert rep.coverage["balanced"] is True
    assert not rep.coverage.get("warning_he")


def test_a_revenue_side_that_stops_early_is_flagged(client, fresh_org):
    """הצד השני של אותה בעיה: מספר דומה של מסמכים, אבל ההכנסות נעצרו.
    חשבוניות org1 נעצרות ב-03/26 בזמן שהספקים ממשיכים ל-07/26."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    for i in range(8):
        _invoice(db, org_id, TODAY - timedelta(days=150 + i), 4000)
        _bill(db, org_id, TODAY - timedelta(days=i * 3), 1000)
    db.commit()

    rep = FinancialReportsService(db).generate_profit_loss(
        org_id, START, TODAY, compare_previous=False)

    assert rep.coverage["balanced"] is False
    assert rep.coverage["revenue_last_document"] is not None


def test_an_empty_period_is_unknown_not_balanced(client, fresh_org):
    """honest-null: אפס מסמכים בשני הצדדים אינו 'מאוזן'. זו אותה טעות
    שתוקנה ב-parity — אין נתונים אינו התאמה."""
    db = SessionLocal()

    rep = FinancialReportsService(db).generate_profit_loss(
        fresh_org()["org_id"], START, TODAY, compare_previous=False)

    assert rep.coverage["balanced"] is None


def test_the_numbers_are_still_reported(client, fresh_org):
    """שער נגדי חשוב: הסיוג אינו משתיק את הדוח. השתקה הייתה מחליפה
    תשובה מטעה בהיעדר תשובה — לא שיפור."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _invoice(db, org_id, TODAY - timedelta(days=100), 20000)
    for i in range(40):
        _bill(db, org_id, TODAY - timedelta(days=i * 4), 500)
    db.commit()

    rep = FinancialReportsService(db).generate_profit_loss(
        org_id, START, TODAY, compare_previous=False)

    assert rep.total_revenue > 0
    assert rep.total_expenses > 0


def test_moshko_receives_the_coverage_block(client, fresh_org):
    """שער חיווט: סיוג שאינו מגיע למושקו לא ימנע ממנו לומר 'העסק
    בהפסד'. זהו הכשל שחזר בסשן הזה — נבנה ולא חוּוט."""
    import asyncio

    from cfo.services.ai_chat_tools import TOOLS

    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _invoice(db, org_id, TODAY - timedelta(days=100), 20000)
    for i in range(40):
        _bill(db, org_id, TODAY - timedelta(days=i * 4), 500)
    db.commit()

    # asyncio.run ולא get_event_loop(): הדפוס הישן נשבר כשטסט קודם סגר
    # את לולאת ה-event הגלובלית (order-dependent flake).
    out = asyncio.run(TOOLS["get_pnl"].fn(db, org_id, months=6))

    assert "coverage" in out
