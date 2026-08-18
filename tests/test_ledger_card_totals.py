"""כרטיס הלקוח מחשב את הסכומים — כדי שמושקו לא יחשב אותם בעצמו.

**כשל חי, נמדד בפרודקשיין 18/08/2026** (שיחה
`sess-1783112110407-body0s`, org1, על הלקוח "אליהב כהן"):

    האמת ב-DB:  23 חשבוניות · ₪306,251 · תשלומים ₪168,600
                יתרה = ₪137,651

    מושקו 16:03:08:  יתרה ₪137,651 ✓  ·  "סך חשבוניות ₪637,851" ✗
    מושקו 16:03:50:  יתרה ₪137,651 ✓  ·  "סך חשבוניות ₪512,651" ✗
                     "עברתי על כל 26 התנועות"          ✗ (23)

**היתרה הייתה נכונה כי `contact_card` החזיר `closing_balance` מוכן.
הפירוט הומצא כי הכלי החזיר `movements` בלבד — ומושקו סכם אותן בעצמו.**

שני סכומים שונים לאותה שאלה, בהפרש 42 שניות. מנהל חשבונות שמצטט
₪637,851 חשבוניות כשיש ₪306,251 יפיק דיווח מע"מ שגוי.

**הכלל:** מודל שפה אינו כלי חישוב. כל סכום שהמודל עשוי לצטט חייב להגיע
מחושב מהכלי. זה אינו שיפור נוחות — זה מונע מספרים מומצאים בדוח לרשויות.
"""
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import (BankTransaction, Contact, ContactType, Invoice,
                        InvoiceStatus, Payment)
from cfo.services.ledger_service import contact_card


@pytest.fixture
def contact_with_history(client, fresh_org):
    """שלוש חשבוניות ושני תשלומים — מספיק כדי שסכימה ידנית תשתבש."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    c = Contact(organization_id=org_id, name="לקוח בדיקה",
                contact_type=ContactType.CUSTOMER)
    db.add(c); db.flush()

    # זיכוי שלילי בכוונה: הגרסה הראשונה של התיקון השתמשה ב-abs() וספרה
    # זיכויים כחיוב. על נתוני פרוד זה ניפח סך חשבוניות ב-₪193,600.
    for n, amt in ((1, 100_000.0), (2, 150_000.0), (3, 76_251.0), (4, -20_000.0)):
        db.add(Invoice(organization_id=org_id, contact_id=c.id,
                       invoice_number=f"INV-{n}", issue_date=date(2026, n, 1),
                       subtotal=amt, tax=0.0, total=amt,
                       status=InvoiceStatus.SENT))
    db.flush()
    invs = db.query(Invoice).filter(Invoice.contact_id == c.id).all()
    db.add(Payment(organization_id=org_id, invoice_id=invs[0].id,
                   amount=100_000.0, payment_date=date(2026, 4, 1)))
    db.add(Payment(organization_id=org_id, invoice_id=invs[1].id,
                   amount=68_600.0, payment_date=date(2026, 5, 1)))
    db.commit()
    return org_id, c.id


def test_the_card_reports_the_invoice_total(contact_with_history):
    """**הלב.** מושקו ציטט ₪637,851 ו-₪512,651 כשהאמת ₪306,251 — כי
    הסכום לא הגיע מהכלי."""
    org_id, cid = contact_with_history

    card = contact_card(SessionLocal(), org_id, cid)

    assert card["totals"]["invoices"] == 306251.0  # 100k+150k+76,251−20k


def test_the_card_reports_the_payment_total(contact_with_history):
    org_id, cid = contact_with_history

    card = contact_card(SessionLocal(), org_id, cid)

    assert card["totals"]["payments"] == 168600.0


def test_the_card_reports_the_movement_count(contact_with_history):
    """מושקו אמר "26 תנועות" כשהיו 23. ספירה היא חישוב, ולכן היא באה
    מהכלי."""
    org_id, cid = contact_with_history

    card = contact_card(SessionLocal(), org_id, cid)

    assert card["totals"]["movement_count"] == len(card["movements"]) == 6


def test_the_totals_reconcile_to_the_closing_balance(contact_with_history):
    """שער עצמי: חשבוניות פחות תשלומים חייב לתת את היתרה. אם השניים
    יתפצלו, נחזיר שני מספרים שסותרים זה את זה — בדיוק מה שקרה."""
    org_id, cid = contact_with_history

    card = contact_card(SessionLocal(), org_id, cid)
    t = card["totals"]
    derived = round(t["invoices"] + t["bills"] - t["payments"], 2)

    assert derived == round(card["closing_balance"], 2)


def test_an_empty_contact_reports_zeros_not_missing_keys(client, fresh_org):
    """honest-null בכיוון הנכון: אפס הוא עובדה מדידה כשאין תנועות.
    מפתח חסר היה מחזיר את מושקו לנחש."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    c = Contact(organization_id=org_id, name="ללא תנועות",
                contact_type=ContactType.CUSTOMER)
    db.add(c); db.commit()

    card = contact_card(db, org_id, c.id)

    assert card["totals"] == {
        "invoices": 0.0, "bills": 0.0, "payments": 0.0, "movement_count": 0,
    }


@pytest.mark.asyncio
async def test_moshko_receives_the_totals(contact_with_history):
    """שער חיווט: סכום שאינו מגיע לכלי של מושקו לא ימנע ממנו להמציא
    אותו. זהו הכשל שחזר בסשן הזה — נבנה ולא חוּוט.

    `@pytest.mark.asyncio` ולא `asyncio.get_event_loop()` ידני — הראשונה
    התנגשה עם ניהול ה-loop של pytest-asyncio כשהטסט רץ אחרי טסטים
    אסינכרוניים אחרים בחבילה המלאה (RuntimeError: Event loop is closed).
    """
    from cfo.services.ai_chat_tools import TOOLS

    org_id, cid = contact_with_history
    out = await TOOLS["get_ledger_card"].fn(SessionLocal(), org_id, contact_id=cid)

    assert "totals" in out
