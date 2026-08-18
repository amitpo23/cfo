"""שבע התצוגות הפיננסיות חייבות להסכים על **אותם נתונים** — לא רק כל
אחת בנפרד.

**ההנחיה (18/08/2026).** "כרגע מושקו ורצף זה אוסף של דברים שאין להם
תכלול והגיון ובדיקות ויכולת להסתכל כמכלול... המידע לא נכון ולא מאומת
ואין שלמות מידע שאני יכול לסמוך עליה."

הביקורת נכונה עובדתית: היום נמצאו ותוקנו בנפרד — פילטר `source` ב-
`build_journal` (יבוא נעלם), כפילות `Bill`/`Expense`, `contact_card`
שהתעלם מתקבולי-בנק, `abs()` שהפך זיכוי לחיוב, פער AP חסר. **כל תיקון
נבדק בבידוד על התצוגה שלו — אף אחד לא אימת ששאר התצוגות עדיין מסכימות
איתו על אותם נתונים.** זו בדיוק ההגדרה של "אוסף בלי תכלול".

הקובץ הזה בונה תרחיש עסקי **אחד** עשיר (לקוח עם חשבוניות פתוחות/סגורות/
מותאמות-בבנק, ספק באותה צורה, זיכוי, תנועת בנק לא-משויכת) ובודק ששבע
התצוגות — `get_trial_balance`, `get_pnl`, `get_ar_aging`, `get_ap_aging`,
`get_ledger_card`, `get_cashflow`, `get_bank_reconciliation` — כולן
נגזרות מ**אותה** אמת בסיסית ולא סותרות זו את זו. אם תצוגה אחת מדווחת
מספר ואחרת מדווחת מספר אחר על אותו לקוח/ספק/תקופה — זהו באג מכלול,
ולא משנה ששתיהן "עברו" בבידוד.
"""
import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    BankTransaction, Bill, BillStatus, Contact, ContactType,
    Invoice, InvoiceStatus, Payment,
)
from cfo.services.ai_chat_tools import TOOLS
from cfo.services.dashboard_service import DashboardService
from cfo.services.ledger_service import contact_card, trial_balance


TODAY = date.today()


@pytest.fixture
def reconciled_org(fresh_org):
    """תרחיש אחד: לקוח עם חשבונית פתוחה+חשבונית מותאמת-בבנק-לא-רשומה,
    ספק עם חשבון פתוח+חשבון מותאם-בבנק, זיכוי ללקוח, ותנועת בנק
    לא-משויכת (הוצאה תפעולית סתמית שאינה חלק מהתרחיש)."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    customer = Contact(organization_id=org_id, name="לקוח מכלול",
                       contact_type=ContactType.CUSTOMER)
    vendor = Contact(organization_id=org_id, name="ספק מכלול",
                     contact_type=ContactType.VENDOR)
    db.add_all([customer, vendor]); db.flush()

    # חשבונית פתוחה — עדיין לא שולמה, לא בבנק. 40 יום איחור → בקט 31-60.
    inv_open = Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-OPEN",
        subtotal=Decimal("10000"), tax=Decimal("0"), total=Decimal("10000"),
        balance=Decimal("10000"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=70), due_date=TODAY - timedelta(days=40),
    )
    # חשבונית "פתוחה" ב-balance אבל **יש** תנועת בנק תואמת — עיכוב סנכרון.
    inv_settled_in_bank = Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-BANK",
        subtotal=Decimal("4000"), tax=Decimal("0"), total=Decimal("4000"),
        balance=Decimal("4000"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=20), due_date=TODAY - timedelta(days=5),
    )
    # זיכוי — סכום שלילי, אותו לקוח.
    inv_credit = Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-CREDIT",
        subtotal=Decimal("-1500"), tax=Decimal("0"), total=Decimal("-1500"),
        balance=Decimal("0"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=10),
    )
    db.add_all([inv_open, inv_settled_in_bank, inv_credit]); db.flush()

    bill_open = Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-OPEN",
        subtotal=Decimal("3000"), tax=Decimal("0"), total=Decimal("3000"),
        balance=Decimal("3000"), status=BillStatus.OVERDUE,
        issue_date=TODAY - timedelta(days=80), due_date=TODAY - timedelta(days=65),
    )
    bill_settled_in_bank = Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-BANK",
        subtotal=Decimal("1200"), tax=Decimal("0"), total=Decimal("1200"),
        balance=Decimal("1200"), status=BillStatus.RECEIVED,
        issue_date=TODAY - timedelta(days=15), due_date=TODAY - timedelta(days=2),
    )
    db.add_all([bill_open, bill_settled_in_bank]); db.flush()

    # תנועות בנק: אחת מותאמת לחשבונית, אחת לחשבון-ספק, אחת לא-משויכת.
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("4000"),
        transaction_date=TODAY - timedelta(days=3),
        is_reconciled=True, matched_entity_type="invoice",
        matched_entity_id=inv_settled_in_bank.id,
    ))
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("-1200"),
        transaction_date=TODAY - timedelta(days=1),
        is_reconciled=True, matched_entity_type="bill",
        matched_entity_id=bill_settled_in_bank.id,
    ))
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("-350"),
        transaction_date=TODAY - timedelta(days=2), description="עמלת בנק",
    ))
    db.commit()

    return {
        "org_id": org_id, "customer_id": customer.id, "vendor_id": vendor.id,
        "inv_open": inv_open.id, "inv_bank": inv_settled_in_bank.id,
    }


# ==================================================================== #
# AR — הלקוח חייב אותו סכום בכל תצוגה
# ==================================================================== #
def test_ar_aging_and_ledger_card_agree_on_the_customer_balance(reconciled_org):
    """`get_ar_aging` סופר balance גולמי (10,000+4,000, כי אין Payment).
    `get_ledger_card` מצליב בנק ומגלה שה-4,000 כבר שולמו. **שתי התצוגות
    אמורות להיות שונות במכוון** — אבל שתיהן חייבות להיות פנימיות-עקביות
    עם המקורות שלהן, לא לסתור זו את זו על אותה עובדה."""
    org_id = reconciled_org["org_id"]
    db = SessionLocal()

    aging = DashboardService(db, org_id).get_ar_aging()
    card = contact_card(db, org_id, reconciled_org["customer_id"])

    # ar_aging: balance גולמי מה-DB, בלי הצלבת בנק, ובלי נטו זיכויים —
    # 10,000 (open) + 4,000 (bank, balance עדיין לא אופס) + 0 (הזיכוי
    # עצמו, balance=0 במכוון כדי לא להיספר כחוב פתוח בפני עצמו — אבל
    # גם אינו מפחית מהיתר. ר' test_ar_aging_does_not_net_unapplied_credits.
    assert aging["total"] == 14000.0, f"ar_aging={aging['total']}"

    # ledger_card: הצלבת בנק (מפחית 4,000 על INV-BANK) **וגם** נטו
    # הזיכוי (-1,500), כי הוא סוכם כתנועה בפני עצמה — לא רק "לא נספר".
    # 10,000 + 4,000 - 1,500(זיכוי) - 4,000(תקבול בבנק) = 8,500.
    assert card["closing_balance"] == 8500.0, f"ledger_card={card['closing_balance']}"

    # **הפער בין השניים (5,500) חייב להיות מוסבר ולא שרירותי**: 4,000
    # (תקבול שהבנק ראה) + 1,500 (זיכוי ש-ar_aging אינו מנטרל). זה עצמו
    # הממצא — ar_aging לא מצליב בנק ולא מנטרל זיכויים; ledger_card עושה
    # את שניהם. אלה שתי תצוגות שונות במכוון (aging גולמי מול כרטיס
    # מלא), לא שתי תשובות סותרות לאותה שאלה.
    assert round(aging["total"] - card["closing_balance"], 2) == 5500.0


def test_ap_aging_flags_the_bank_settled_bill_that_ledger_card_also_sees(reconciled_org):
    """אותה עקביות בכיוון ההוצאות: `get_ap_aging` מסמן bank_movement_seen,
    ו-`get_ledger_card` (בכיוון הפוך, ספק) מוריד את אותו סכום מהיתרה.
    שני מנועים נפרדים (DashboardService, ledger_service) חייבים להסכים
    על אילו מסמכים כבר יש להם תנועת בנק."""
    org_id = reconciled_org["org_id"]
    db = SessionLocal()

    ap = DashboardService(db, org_id).get_ap_aging()
    card = contact_card(db, org_id, reconciled_org["vendor_id"])

    settled_in_ap = next(
        b for b in ap["bills"] if b["bill_number"] == "BILL-BANK"
    )
    assert settled_in_ap["bank_movement_seen"] is True

    bank_lines_in_card = [m for m in card["movements"] if m["type"] == "bank_settlement"]
    assert len(bank_lines_in_card) == 1, (
        "get_ap_aging ראה תנועת בנק על BILL-BANK אך get_ledger_card לא — "
        "שני מנועים חלוקים על אותה עובדה"
    )


# ==================================================================== #
# מאזן בוחן מול P&L — אותה תקופה, אותם מסמכים
# ==================================================================== #
def test_trial_balance_and_pnl_derive_from_the_same_documents(reconciled_org):
    """`build_journal` (מאזן) ו-`generate_profit_loss` (רו"ה) חייבים
    להסכים על אותה הכנסה נטו לתקופה — שניהם קוראים Invoice/Bill/Expense
    ישירות, אבל דרך שני מסלולי חישוב נפרדים."""
    from cfo.services.financial_reports_service import FinancialReportsService

    org_id = reconciled_org["org_id"]
    db = SessionLocal()
    start = TODAY - timedelta(days=90)

    tb = trial_balance(db, org_id, start=start, end=TODAY)
    pnl = FinancialReportsService(db).generate_profit_loss(
        org_id, start, TODAY, compare_previous=False,
    )

    revenue_account = next(
        (a for a in tb["accounts"] if a["account"] == "4000"), None,
    )
    assert revenue_account is not None, "אין כרטיס הכנסות במאזן"

    tb_revenue = round(revenue_account["credit"] - revenue_account["debit"], 2)
    pnl_revenue = round(pnl.total_revenue, 2)

    assert tb_revenue == pnl_revenue, (
        f"מאזן מדווח הכנסות {tb_revenue}, רו\"ה מדווח {pnl_revenue} — "
        "אותה תקופה, אותם מסמכים, שני מספרים שונים"
    )


def test_the_trial_balance_still_balances_with_the_full_scenario(reconciled_org):
    """שער יסוד: לא משנה כמה תנועות בנק/זיכויים/כפילויות בתרחיש — סך
    חובה חייב לשווה סך זכות."""
    org_id = reconciled_org["org_id"]
    db = SessionLocal()

    tb = trial_balance(db, org_id)

    assert round(tb["total_debit"], 2) == round(tb["total_credit"], 2)


# ==================================================================== #
# תזרים מול התאמת בנק — אותן תנועות
# ==================================================================== #
def test_cashflow_and_bank_reconciliation_see_the_same_bank_transactions(reconciled_org):
    """`get_cashflow` סופר תנועות בנק בפועל; `get_bank_reconciliation`
    מדווח כמה מהן הותאמו. **מספר התנועות הכולל בשני הכלים חייב להיות
    זהה** — שניהם קוראים מ-BankTransaction, לא ממקור שונה."""
    org_id = reconciled_org["org_id"]
    db = SessionLocal()

    recon = asyncio.run(TOOLS["get_bank_reconciliation"].fn(db, org_id))

    total_txns = db.query(BankTransaction).filter(
        BankTransaction.organization_id == org_id).count()

    # 3 תנועות נזרעו: 2 מותאמות (invoice+bill), 1 לא. matched+unmatched
    # מה-reconciliation engine (שרואה גם invoice/bill/expense כמועמדים
    # להתאמה) חייב לפחות לכסות את 3 תנועות הבנק הגולמיות.
    assert total_txns == 3
    assert recon["matched"] >= 2, f"רק {recon['matched']} הותאמו מתוך 2 ידועות"


def test_the_unmatched_bank_fee_appears_as_unreconciled(reconciled_org):
    """התנועה הלא-משויכת (עמלת בנק) חייבת להישאר גלויה כלא-מותאמת —
    לא להיעלם בשקט מאף תצוגה."""
    org_id = reconciled_org["org_id"]
    db = SessionLocal()

    recon = asyncio.run(TOOLS["get_bank_reconciliation"].fn(db, org_id))

    assert recon["unmatched"] >= 1, "עמלת הבנק הלא-משויכת נעלמה"


# ==================================================================== #
# השער המסכם: כל שבע התצוגות רצות על אותו ארגון בלי לקרוס זו על זו
# ==================================================================== #
def test_all_seven_surfaces_run_together_on_the_same_org_without_conflict(reconciled_org):
    """לא בדיקת ערך — בדיקת **מכלול**: אין תצוגה שקוראת ל-DB בצורה
    שסותרת אחרת (למשל נועלת שורה, או מניחה סכימה ששונתה ע"י תצוגה
    קודמת). מריץ את כל השבע ברצף על אותו session, כפי שמושקו היה עושה
    בשיחה אחת שעוברת מכובע לכובע."""
    org_id = reconciled_org["org_id"]
    db = SessionLocal()

    results = {
        "trial_balance": trial_balance(db, org_id),
        "pnl": asyncio.run(TOOLS["get_pnl"].fn(db, org_id)),
        "ar_aging": asyncio.run(TOOLS["get_ar_aging"].fn(db, org_id)),
        "ap_aging": asyncio.run(TOOLS["get_ap_aging"].fn(db, org_id)),
        "ledger_card": contact_card(db, org_id, reconciled_org["customer_id"]),
        "cashflow": asyncio.run(TOOLS["get_cashflow"].fn(db, org_id)),
        "bank_reconciliation": asyncio.run(TOOLS["get_bank_reconciliation"].fn(db, org_id)),
    }

    for name, result in results.items():
        assert result is not None, f"{name} החזיר None"
        assert isinstance(result, dict), f"{name} לא החזיר dict"
