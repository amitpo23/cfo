"""
LiveForecastService — תחזית תזרים חודשית מבוססת ספרים חיים.

מחליף את מקור הנתונים של מסך Forecasting מטבלת ``Transaction`` הקפואה
(~127 שורות ₪0, קפואה מ-19/08/2026) לספרים החיים בפועל — שלוש התחזית-קדימה
ומקור היסטוריה אחד:

  - ``invoices_open_ar`` / ``invoices_overdue_ar``: חשבוניות פתוחות (יתרה
    > 0) לפי ``due_date``. חשבונית שה-``due_date`` שלה כבר עבר (לפני תחילת
    חלון התחזית) לא נעלמת בשקט — היא מוצגת כרכיב ``*_overdue_*`` נפרד
    בחודש הראשון ("בפירעון שעבר, מוצג בחודש הנוכחי"), כי היא כסף שכבר
    אמור היה להיכנס/לצאת ורלוונטית לתמונה המיידית.
  - ``bills_open_ap`` / ``bills_overdue_ap``: חשבונות ספק פתוחים, אותה
    לוגיקה.
  - ``excluded_no_due_date``: חשבוניות/חשבונות פתוחים (אותם קריטריוני
    סטטוס/יתרה) שה-``due_date`` שלהם NULL — לא ניתן לשבץ אותם לאף חודש,
    ולכן הם לא נכללים בשום סכום למעלה. במקום להיעלם בשקט (follow-up,
    21/08/2026 review), הם נספרים ומדווחים בגלוי בכל תשובה.
  - ``expenses_recurring_avg``: ממוצע היסטורי (לא ניחוש/ML) של הוצאות
    שנרשמו בחודשים האחרונים — בסיס חוזר קבוע לכל חודש עתידי, לא תחזית-מגמה.
  - ``bank_transactions_actual``: תזרים בנק *בפועל* (לא תחזית) ב-90 הימים
    האחרונים — מוצג כ-``historical_context`` נפרד מהתחזית-קדימה, לצורך
    השוואה. לא מוזרם לתוך המספרים העתידיים (אין דרך לדעת אם תנועת עבר
    תחזור על עצמה בלי ML/ניחוש).

פירוק גלוי (intermediate-sums, כעקרון הפרויקט): כל חודש מוחזר עם צבר
in/out וגם שורת-מקור נפרדת לכל רכיב, כדי שאפשר יהיה לבדוק מאיפה כל מספר
הגיע. אין החלקה מעריכית/רגרסיה/אנסמבל — סכימה ישירה בלבד.

דה-דופ: הוצאה עם ``external_id`` שכבר מיוצג כ-Bill פתוח מדולגת מהבסיס
החוזר — אותה לוגיקה כמו ``DashboardService._month_expenses_accrual``,
כדי לא לספור את אותו מסמך פעמיים (פעם כ-AP עתידי, פעם כבסיס היסטורי).

honest-null: ארגון בלי חשבוניות/חשבונות-ספק פתוחים (כולל overdue) ובלי
הוצאות ב-90 הימים האחרונים מקבל ``months=[]`` + הודעה כנה, לא אפסים
בביטחון. אם יש בכל זאת היסטוריית תנועות בנק — היא כן מוחזרת
(``historical_context``), כדי לא להסתיר נתונים אמיתיים שקיימים רק כי אין
עליהם תחזית-קדימה אחראית.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import BankTransaction, Bill, BillStatus, Expense, Invoice, InvoiceStatus


def _add_months(d: date, months: int) -> date:
    """מחזיר את היום ה-1 של (d.month + months), עם גלישת שנה נכונה."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


class LiveForecastService:
    """תחזית תזרים חודשית מבוססת ספרים חיים, לצריכת ForecastingDashboard."""

    RECURRING_LOOKBACK_DAYS = 90

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def monthly_forecast(
        self, periods: int = 6, as_of_date: Optional[date] = None
    ) -> dict[str, Any]:
        as_of_date = as_of_date or date.today()
        month_anchor = as_of_date.replace(day=1)

        open_invoices = (
            self.db.query(Invoice)
            .filter(
                Invoice.organization_id == self.organization_id,
                Invoice.status.notin_(
                    [InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED]
                ),
                Invoice.balance > 0,
                Invoice.due_date.isnot(None),
            )
            .all()
        )
        open_bills = (
            self.db.query(Bill)
            .filter(
                Bill.organization_id == self.organization_id,
                Bill.status.notin_([BillStatus.DRAFT, BillStatus.VOID]),
                Bill.balance > 0,
                Bill.due_date.isnot(None),
            )
            .all()
        )

        # חשבוניות/חשבונות פתוחים (אותם קריטריוני סטטוס/יתרה) שה-due_date
        # שלהם NULL: לא ניתן לשבץ אותם לאף חודש בתחזית (אין לפי-מה), ועד
        # כה הם נעלמו בשקט. במקום להסתיר, סופרים ומגלים בפלט
        # (`excluded_no_due_date`) — honest-null גם על מה שלא נכלל, לא רק
        # על מה שכן.
        excluded_invoices_no_due_date = (
            self.db.query(Invoice)
            .filter(
                Invoice.organization_id == self.organization_id,
                Invoice.status.notin_(
                    [InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED]
                ),
                Invoice.balance > 0,
                Invoice.due_date.is_(None),
            )
            .count()
        )
        excluded_bills_no_due_date = (
            self.db.query(Bill)
            .filter(
                Bill.organization_id == self.organization_id,
                Bill.status.notin_([BillStatus.DRAFT, BillStatus.VOID]),
                Bill.balance > 0,
                Bill.due_date.is_(None),
            )
            .count()
        )
        excluded_no_due_date = {
            "invoices": excluded_invoices_no_due_date,
            "bills": excluded_bills_no_due_date,
        }

        # חשבוניות/חשבונות שה-due_date שלהם כבר לפני תחילת החלון: לא
        # ייכנסו לאף בקצת-חודש רגיל (כולם נבדקים כ-m_start<=due<=m_end
        # מ-month_anchor והלאה) — בלי הטיפול הזה הם היו נעלמים בשקט.
        overdue_invoices = [inv for inv in open_invoices if inv.due_date < month_anchor]
        overdue_ar_total = float(sum((inv.balance for inv in overdue_invoices), Decimal("0")))
        overdue_bills = [b for b in open_bills if b.due_date < month_anchor]
        overdue_ap_total = float(sum((b.balance for b in overdue_bills), Decimal("0")))

        recurring_rows, recurring_months_count = self._recurring_expense_rows(as_of_date)
        recurring_sum = sum((r[0] for r in recurring_rows), Decimal("0"))
        recurring_monthly_avg = (
            recurring_sum / recurring_months_count if recurring_months_count else Decimal("0")
        )

        bank_context = self._bank_actual_context(as_of_date)

        has_forward_data = bool(open_invoices or open_bills or recurring_rows)

        if not has_forward_data:
            if bank_context["available"]:
                data_sources = ["bank_transactions_actual"]
                message = (
                    "אין חשבוניות פתוחות, חשבונות ספק פתוחים או הוצאות חוזרות לבניית "
                    "תחזית קדימה עבור ארגון זה — אך יש היסטוריית תנועות בנק בפועל "
                    "(ר' historical_context)."
                )
            else:
                data_sources = []
                message = (
                    "אין נתונים חיים (חשבוניות פתוחות, חשבונות ספק פתוחים, הוצאות "
                    f"ב-{self.RECURRING_LOOKBACK_DAYS} הימים האחרונים, או תנועות בנק) "
                    "לתחזית עבור ארגון זה."
                )
            return {
                "as_of": as_of_date.isoformat(),
                "data_sources": data_sources,
                "months": [],
                "historical_context": bank_context,
                "excluded_no_due_date": excluded_no_due_date,
                "message": message,
            }

        data_sources: list[str] = []
        if open_invoices:
            data_sources.append("invoices_open_ar")
        if overdue_invoices:
            data_sources.append("invoices_overdue_ar")
        if open_bills:
            data_sources.append("bills_open_ap")
        if overdue_bills:
            data_sources.append("bills_overdue_ap")
        if recurring_rows:
            data_sources.append("expenses_recurring_avg")
        if bank_context["available"]:
            data_sources.append("bank_transactions_actual")

        months: list[dict[str, Any]] = []
        for i in range(periods):
            m_start = _add_months(month_anchor, i)
            m_end = _add_months(m_start, 1) - timedelta(days=1)
            is_first_month = i == 0

            ar_matches = [inv for inv in open_invoices if m_start <= inv.due_date <= m_end]
            ar_amount = float(sum((inv.balance for inv in ar_matches), Decimal("0")))

            ap_matches = [b for b in open_bills if m_start <= b.due_date <= m_end]
            ap_amount = float(sum((b.balance for b in ap_matches), Decimal("0")))

            month_overdue_ar = overdue_ar_total if is_first_month else 0.0
            month_overdue_ar_count = len(overdue_invoices) if is_first_month else 0
            month_overdue_ap = overdue_ap_total if is_first_month else 0.0
            month_overdue_ap_count = len(overdue_bills) if is_first_month else 0

            recurring_amount = float(recurring_monthly_avg)

            inflow_total = round(ar_amount + month_overdue_ar, 2)
            outflow_total = round(ap_amount + month_overdue_ap + recurring_amount, 2)

            months.append({
                "month": m_start.strftime("%Y-%m"),
                "inflow_total": inflow_total,
                "outflow_total": outflow_total,
                "net_flow": round(inflow_total - outflow_total, 2),
                "components": [
                    {
                        "source": "invoices_open_ar",
                        "label": "חשבוניות פתוחות (לקוחות) לפי תאריך פירעון",
                        "direction": "inflow",
                        "amount": round(ar_amount, 2),
                        "count": len(ar_matches),
                    },
                    {
                        "source": "invoices_overdue_ar",
                        "label": "חשבוניות פתוחות בפירעון שעבר (overdue) — מוצג בחודש הנוכחי",
                        "direction": "inflow",
                        "amount": round(month_overdue_ar, 2),
                        "count": month_overdue_ar_count,
                    },
                    {
                        "source": "bills_open_ap",
                        "label": "חשבונות ספק פתוחים לפי תאריך פירעון",
                        "direction": "outflow",
                        "amount": round(ap_amount, 2),
                        "count": len(ap_matches),
                    },
                    {
                        "source": "bills_overdue_ap",
                        "label": "חשבונות ספק פתוחים בפירעון שעבר (overdue) — מוצג בחודש הנוכחי",
                        "direction": "outflow",
                        "amount": round(month_overdue_ap, 2),
                        "count": month_overdue_ap_count,
                    },
                    {
                        "source": "expenses_recurring_avg",
                        "label": (
                            f"הוצאות חוזרות — ממוצע {recurring_months_count} חודשים "
                            "אחרונים עם נתונים (בסיס חוזר, לא תחזית-מגמה)"
                        ),
                        "direction": "outflow",
                        "amount": round(recurring_amount, 2),
                        "count": len(recurring_rows),
                    },
                ],
            })

        return {
            "as_of": as_of_date.isoformat(),
            "data_sources": data_sources,
            "months": months,
            "historical_context": bank_context,
            "excluded_no_due_date": excluded_no_due_date,
            "message": None,
        }

    def _recurring_expense_rows(
        self, as_of_date: date
    ) -> tuple[list[tuple[Decimal, date]], int]:
        """הוצאות ב-90 הימים האחרונים, בניכוי כאלה שכבר מיוצגות כ-Bill
        (אותו external_id) כדי לא לכפול את אותו מסמך, ובניכוי הוצאות
        שנכשלו (status="error" — OCR/סיווג כושל) — אותו פילטר בדיוק כמו
        ב-DashboardService._month_expenses_accrual, כדי שהוצאות כושלות
        לא יזהמו את בסיס ההוצאות החוזרות המוצג למשתמש. מחזיר את השורות
        (סכום, תאריך) ואת מספר החודשים הקלנדריים השונים שיש בהם נתונים."""
        bill_ext_ids = {
            r[0]
            for r in self.db.query(Bill.external_id).filter(
                Bill.organization_id == self.organization_id,
                Bill.external_id.isnot(None),
            ).all()
        }

        lookback_start = as_of_date - timedelta(days=self.RECURRING_LOOKBACK_DAYS)
        raw_rows = (
            self.db.query(Expense.total, Expense.amount, Expense.external_id, Expense.expense_date)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.expense_date >= lookback_start,
                Expense.expense_date <= as_of_date,
                func.lower(Expense.status) != "error",
            )
            .all()
        )

        rows: list[tuple[Decimal, date]] = []
        for total, amount, ext_id, expense_date in raw_rows:
            if ext_id and str(ext_id) in bill_ext_ids:
                continue
            rows.append(((total if total else amount) or Decimal("0"), expense_date))

        months_with_data = {(d.year, d.month) for _, d in rows}
        return rows, len(months_with_data)

    def _bank_actual_context(self, as_of_date: date) -> dict[str, Any]:
        """תזרים בנק בפועל (לא תחזית) ב-90 הימים האחרונים — מוצג בנפרד
        מהתחזית-קדימה, להשוואה בלבד. לא מוזרם למספרים העתידיים כדי לא
        להמציא הנחת-המשך (זה יהיה ML/ניחוש, לא סכימה ישירה)."""
        lookback_start = as_of_date - timedelta(days=self.RECURRING_LOOKBACK_DAYS)
        rows = (
            self.db.query(BankTransaction.amount)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.transaction_date >= lookback_start,
                BankTransaction.transaction_date <= as_of_date,
            )
            .all()
        )
        if not rows:
            return {"available": False}

        inflow = sum(float(amount) for (amount,) in rows if amount and amount > 0)
        outflow = sum(abs(float(amount)) for (amount,) in rows if amount and amount < 0)
        return {
            "available": True,
            "source": "bank_transactions_actual",
            "window_days": self.RECURRING_LOOKBACK_DAYS,
            "inflow": round(inflow, 2),
            "outflow": round(outflow, 2),
            "net": round(inflow - outflow, 2),
            "count": len(rows),
            "label": (
                f"תזרים בנק בפועל — {self.RECURRING_LOOKBACK_DAYS} הימים האחרונים "
                "(היסטוריה, לא תחזית)"
            ),
        }
