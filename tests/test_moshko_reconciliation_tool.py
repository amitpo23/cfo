"""מושקו יודע לענות על התאמות בנק.

**הפער (18/08/2026).** מיפוי 58 כלי מושקו מול מה שהבעלים ביקש ממנו
("מושקו יצטרך לבדוק התאמות ורישומים וכרטיסים") העלה שתי חסרות:

1. **סגירת מנה** — אין כלי, **וזה נכון**: `/books` של SUMIT חושף
   `createbatch` בלבד. סגירה היא פעולת דפדפן. כלי שהיה מתיימר לסגור
   היה משקר.
2. **התאמות בנק** — `bank_reconciliation.py` קיים ומשמש את מחזור
   הבוקר, אבל למושקו לא היה אליו כלי. כלומר היכולת קיימת במערכת ומנהל
   החשבונות שלה לא יכול היה להגיע אליה.

הקובץ הזה סוגר את השנייה.

**קריאה בלבד.** `persist=False` — התאמה היא רישום שמשנה נתונים, ולכן
היא אינה נעשית בתשובה לשאלה בצ'אט. מושקו מדווח מה מותאם ומה לא; שינוי
מצב עובר במסלול האישור, לא כתופעת-לוואי של שאלה.
"""
import pytest

from cfo.services.ai_chat_tools import TOOLS


def test_the_reconciliation_tool_is_registered():
    """הפער עצמו: בלי רישום, מושקו אינו יודע שהיכולת קיימת."""
    assert "get_bank_reconciliation" in TOOLS


def test_the_tool_is_read_only():
    """התאמה משנה נתונים. שאלה בצ'אט לא תשנה מצב — אחרת 'מה מצב
    ההתאמות?' היה מבצע התאמות."""
    tool = TOOLS["get_bank_reconciliation"]

    assert not getattr(tool, "policy_action", None), (
        "כלי קריאה לא אמור לשאת policy_action"
    )


@pytest.mark.asyncio
async def test_it_reports_matched_and_unmatched(client, fresh_org):
    """התשובה חייבת לכלול את שני הצדדים. 'X הותאמו' בלי 'Y לא' מסתיר
    בדיוק את מה שמנהל החשבונות מחפש."""
    org_id = fresh_org()["org_id"]
    from cfo.database import SessionLocal

    result = await TOOLS["get_bank_reconciliation"].fn(SessionLocal(), org_id)

    assert "matched" in result
    assert "unmatched" in result


@pytest.mark.asyncio
async def test_it_does_not_persist_matches(client, fresh_org):
    """שער נגדי מדיד: קריאה לכלי לא מסמנת תנועות כמותאמות ב-DB."""
    from datetime import date

    from cfo.database import SessionLocal
    from cfo.models import BankTransaction

    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    txn = BankTransaction(
        organization_id=org_id, amount=-100.0,
        transaction_date=date(2026, 5, 1), description="בדיקה",
    )
    db.add(txn)
    db.commit()
    txn_id = txn.id

    await TOOLS["get_bank_reconciliation"].fn(db, org_id)

    db.expire_all()
    after = db.query(BankTransaction).filter(BankTransaction.id == txn_id).one()
    assert not after.is_reconciled, "הכלי שינה מצב — הוא אמור להיות קריאה בלבד"


def test_batch_closing_is_deliberately_absent():
    """שער כנות: SUMIT אינה חושפת סגירת מנה ב-API. כלי בשם כזה היה
    מבטיח פעולה שאינה קיימת — וסגירת מנה היא רישום בלתי-הפיך."""
    forbidden = [n for n in TOOLS if "close_batch" in n or "batch_close" in n]

    assert not forbidden, (
        f"נוסף כלי לסגירת מנה: {forbidden}. אין endpoint כזה אצל הספק."
    )
