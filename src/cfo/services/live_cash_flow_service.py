"""
LiveCashFlowService — נתוני מסך "תזרים — מפורט" (`/cashflow-detail`) מבוססי
ספרים חיים, לא טבלת ``Transaction`` הקפואה (~127 שורות ₪0, קפואה מ-19/08/2026).

מקורות אמת:
  - ``bank_transactions_actual``: תנועות בנק אמיתיות (``BankTransaction``) —
    בסיס לתזרים חודשי/יומי ולקצב שריפה בפועל. amount חיובי=כניסה,
    שלילי=יציאה (אותה מוסכמה כמו ``LiveForecastService``).
  - ``invoices_open_ar`` / ``bills_open_ap``: חשבוניות/חשבונות-ספק פתוחים
    עם due_date בתוך 30 הימים הקרובים — צפי גבייה/תשלום קרוב, מסופק כתוספת
    ל"קצב שריפה" (לא מוזרם לתוך הסכומים בפועל).
  - יתרת מזומנים חיה: סכום ``Account.balance`` לכל חשבונות BANK ממקור
    Open Finance, רק כשכולם עוברים שער טריות. **בלי** נפילה חזרה לסכימת
    Transaction ובלי סכום ארגוני חלקי — היעדר/פסילת יתרה מדווחים כ-honest-null
    (``balance_basis`` / ``current_balance_available``), לא מוסתרים מאחורי 0
    או מספר חלקי שקרי-בביטחון.

פירוק גלוי + honest-null: כל תשובה נושאת ``as_of`` ו-``data_sources``,
ו-``message`` כשאין נתונים חיים לחלון המבוקש — אותה מוסכמה בדיוק כמו
``LiveForecastService`` (משימה 1). אין ML/החלקה — סכימה ישירה בלבד.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Account, AccountType, BankTransaction, Bill, BillStatus, Category,
    Invoice, InvoiceStatus,
)

EXPECTED_HORIZON_DAYS = 30

# חוזה המזומן (P0-B, 23/08/2026): "מזומן" = יתרה בנקאית טרייה, לא "כל
# נכס בטבלת Account". סף הטריות (48h) הוא אותו סף בדיוק כמו
# data_quality._STALE_AFTER — שני המקומות בודקים את אותה שאלה
# ("מתי סונכרנה היתרה הזו לאחרונה"), ואין סיבה לשני סֵפים שונים.
MAX_BALANCE_AGE = timedelta(hours=48)


def _naive(ts: Optional[datetime]) -> Optional[datetime]:
    """מנרמל DateTime(timezone=True) (aware בפרוד/Postgres, naive ב-SQLite
    של הטסטים) להשוואה אחידה מול datetime.utcnow() הנאיבי."""
    if ts is None:
        return None
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _add_months(d: date, months: int) -> date:
    """מחזיר את היום ה-1 של (d.month + months), עם גלישת שנה נכונה."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


class LiveCashFlowService:
    """נתוני תזרים חי (BankTransaction + Account) עבור CashFlowDashboard."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    # ------------------------------------------------------------------ #
    # תזרים חודשי
    # ------------------------------------------------------------------ #
    def monthly_cash_flow(
        self, months: int = 12, as_of_date: Optional[date] = None
    ) -> dict[str, Any]:
        as_of = as_of_date or date.today()
        month_anchor = as_of.replace(day=1)
        first_month = _add_months(month_anchor, -(months - 1))
        window_start = first_month
        window_end = as_of

        rows = self._bank_rows(window_start, window_end)

        if not rows:
            return {
                "as_of": as_of.isoformat(),
                "data_sources": [],
                "months": [],
                "message": (
                    f"אין תנועות בנק בין {window_start.isoformat()} ל-"
                    f"{window_end.isoformat()} — אין נתוני תזרים חודשי חי לארגון "
                    "זה בחלון הזה."
                ),
            }

        months_out: list[dict[str, Any]] = []
        cumulative = 0.0
        for i in range(months):
            m_start = _add_months(first_month, i)
            m_end = _add_months(m_start, 1) - timedelta(days=1)
            inflow, outflow = self._sum_flows(rows, m_start, m_end)
            net = round(inflow - outflow, 2)
            cumulative = round(cumulative + net, 2)
            months_out.append({
                "month": m_start.strftime("%Y-%m"),
                "month_name": m_start.strftime("%B %Y"),
                "inflows": inflow,
                "outflows": outflow,
                "net_flow": net,
                "cumulative": cumulative,
            })

        return {
            "as_of": as_of.isoformat(),
            "data_sources": ["bank_transactions_actual"],
            "months": months_out,
            "message": None,
        }

    # ------------------------------------------------------------------ #
    # מצב מזומנים יומי
    # ------------------------------------------------------------------ #
    def daily_cash_position(
        self, days: int = 30, as_of_date: Optional[date] = None
    ) -> dict[str, Any]:
        as_of = as_of_date or date.today()
        window_start = as_of - timedelta(days=days)

        rows = self._bank_rows(window_start, as_of)

        if not rows:
            return {
                "as_of": as_of.isoformat(),
                "data_sources": [],
                "days": [],
                "balance_basis": "no_bank_data",
                "message": (
                    f"אין תנועות בנק בין {window_start.isoformat()} ל-"
                    f"{as_of.isoformat()} — אין נתוני מזומנים יומיים חיים לארגון "
                    "זה בחלון הזה."
                ),
            }

        day_dates: list[date] = []
        d = window_start
        while d <= as_of:
            day_dates.append(d)
            d += timedelta(days=1)

        daily_flows = [self._sum_flows(rows, dd, dd) for dd in day_dates]
        total_net = sum(inflow - outflow for inflow, outflow in daily_flows)

        live_balance, balance_reason = self._live_cash_balance()
        balance_available = live_balance is not None
        running = float(live_balance) - total_net if live_balance is not None else 0.0

        days_out: list[dict[str, Any]] = []
        for dd, (inflow, outflow) in zip(day_dates, daily_flows):
            net = round(inflow - outflow, 2)
            running = round(running + net, 2)
            days_out.append({
                "date": dd.isoformat(),
                "inflows": inflow,
                "outflows": outflow,
                "net_flow": net,
                "closing_balance": running if balance_available else None,
            })

        return {
            "as_of": as_of.isoformat(),
            "data_sources": ["bank_transactions_actual"],
            "days": days_out,
            "balance_basis": "account_balance" if balance_available else "unavailable",
            "balance_reason": balance_reason,
            "message": None,
        }

    # ------------------------------------------------------------------ #
    # קצב שריפה + תוספת AR/AP פתוחים
    # ------------------------------------------------------------------ #
    def burn_rate(
        self, months: int = 3, as_of_date: Optional[date] = None
    ) -> dict[str, Any]:
        as_of = as_of_date or date.today()
        window_start = as_of - timedelta(days=months * 30)

        rows = self._bank_rows(window_start, as_of)
        has_bank_data = bool(rows)
        total_inflow, total_outflow = self._sum_flows(rows, window_start, as_of)

        live_balance, balance_reason = self._live_cash_balance()
        current_balance = float(live_balance) if live_balance is not None else None

        monthly_burn = round(total_outflow / months, 2) if months > 0 else 0.0
        monthly_income = round(total_inflow / months, 2) if months > 0 else 0.0
        net_burn = round(monthly_burn - monthly_income, 2)

        # honest-null (תיקון-ביקורת 23/08/2026, P0-B): אין יותר סנטינל
        # 999.0 — הוא הוצג ב-frontend/API כמספר-אמת בכל שלושת המצבים למטה,
        # שאין ביניהם שום קשר מספרי. runway_months הוא None בכל מצב שאינו
        # "computed" בפועל; runway_status מבחין בין המצבים בקוד-מכונה
        # (לא בטקסט עברי חופשי שה-frontend היה צריך לפרש), ו-runway_reason
        # נותן את ההסבר האנושי.
        if live_balance is None:
            runway_status = "unavailable"
            runway_months: Optional[float] = None
            runway_reason: Optional[str] = balance_reason or (
                "אין יתרת מזומנים חיה זמינה — לא ניתן לחשב כמה זמן הכסף יספיק."
            )
        elif current_balance <= 0:
            # סדר ה-state machine מכוון: יתרה לא-חיובית גוברת על קצב
            # השריפה. גם אם net_burn<=0 בתקופה, מינוס/אפס אינם runway
            # אינסופי ואסור לצבוע אותם בירוק.
            runway_status = "not_positive"
            runway_months = None
            runway_reason = "יתרת המזומנים הידועה אינה חיובית — אין runway לחשב."
        elif net_burn <= 0:
            # לא בשריפה נטו (הכנסות מכסות/עולות על ההוצאות) עם יתרה ידועה
            # וחיובית — runway "אינסופי" הוא עובדה אמיתית כאן, לא סנטינל.
            runway_status = "infinite"
            runway_months = None
            runway_reason = (
                "אין שריפת מזומנים נטו בתקופה הנבדקת (ההכנסות מכסות את "
                "ההוצאות) — מושג ה-runway אינו רלוונטי."
            )
        else:
            runway_status = "computed"
            runway_months = round(current_balance / net_burn, 2)
            runway_reason = None

        ar_amount, ar_count = self._expected_open_amount(
            Invoice, [InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED], as_of
        )
        ap_amount, ap_count = self._expected_open_amount(
            Bill, [BillStatus.DRAFT, BillStatus.VOID], as_of
        )

        data_sources: list[str] = []
        if has_bank_data:
            data_sources.append("bank_transactions_actual")
        if ar_count:
            data_sources.append("invoices_open_ar")
        if ap_count:
            data_sources.append("bills_open_ap")

        message = None
        if not has_bank_data and live_balance is None and not ar_count and not ap_count:
            message = (
                "אין תנועות בנק, יתרת חשבון חיה, חשבוניות פתוחות או חשבונות "
                "ספק פתוחים — אין נתוני קצב שריפה חיים לארגון זה."
            )

        return {
            "as_of": as_of.isoformat(),
            "data_sources": data_sources,
            "monthly_burn_rate": monthly_burn,
            "monthly_income": monthly_income,
            "net_monthly_burn": net_burn,
            "current_balance": round(current_balance, 2) if current_balance is not None else None,
            "current_balance_available": live_balance is not None,
            "current_balance_reason": balance_reason,
            "runway_months": runway_months,
            "runway_status": runway_status,
            "runway_reason": runway_reason,
            "analysis_period_months": months,
            "expected_receivables_30d": ar_amount,
            "expected_receivables_30d_count": ar_count,
            "expected_payables_30d": ap_amount,
            "expected_payables_30d_count": ap_count,
            "message": message,
        }

    # ------------------------------------------------------------------ #
    # פירוק לפי קטגוריה
    # ------------------------------------------------------------------ #
    # מתחת לסף הזה (חלק מהתנועות המסווגות מכלל התנועות בחלון) הפירוק
    # מוצג עדיין (אין למה להחביא נתון אמיתי), אבל עם הודעת-כיסוי מפורשת —
    # אחרת "לא מסווג" שולט בעוגה ומוצג כמו כל פרוסה רגילה אחרת, ב-message
    # None, כאילו הפירוק אמין באותה מידה. ר' CRITICAL 1 בביקורת המשימה
    # (21/08/2026): 1 תנועה מסווגת מול 200 לא-מסווגות עדיין נתן message=None.
    CATEGORY_COVERAGE_DISCLOSURE_THRESHOLD = 0.5

    def by_category(
        self, start_date: date, end_date: date, as_of_date: Optional[date] = None
    ) -> dict[str, Any]:
        as_of = as_of_date or date.today()
        rows = (
            self.db.query(BankTransaction.amount, BankTransaction.category_id, Category.name)
            .outerjoin(Category, Category.id == BankTransaction.category_id)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.transaction_date >= start_date,
                BankTransaction.transaction_date <= end_date,
            )
            .all()
        )
        total_count = len(rows)
        categorized_count = sum(1 for r in rows if r[1] is not None)

        if categorized_count == 0:
            # honest-null: לא בונים "עוגה" של פרוסה אחת "לא מסווג" — זה
            # מטעה יותר מהודעה כנה. BankTransaction.category_id כמעט אף
            # פעם אינו מאוכלס בפועל (אין כותב שממלא אותו כרגע).
            message = (
                "תנועות הבנק בטווח זה אינן מסווגות לקטגוריה — אין פירוק חי "
                "לפי קטגוריה לארגון זה."
                if rows else
                f"אין תנועות בנק בין {start_date.isoformat()} ל-{end_date.isoformat()}."
            )
            return {
                "as_of": as_of.isoformat(), "data_sources": [], "categories": {},
                "coverage": {
                    "categorized_count": 0, "total_count": total_count, "categorized_share": 0.0,
                },
                "message": message,
            }

        categories: dict[str, dict[str, float]] = {}
        for amount, cat_id, cat_name in rows:
            key = cat_name if cat_id is not None else "לא מסווג"
            bucket = categories.setdefault(key, {"inflows": 0.0, "outflows": 0.0})
            amt = float(amount or 0)
            if amt > 0:
                bucket["inflows"] += amt
            else:
                bucket["outflows"] += abs(amt)
        for bucket in categories.values():
            bucket["inflows"] = round(bucket["inflows"], 2)
            bucket["outflows"] = round(bucket["outflows"], 2)
            bucket["net"] = round(bucket["inflows"] - bucket["outflows"], 2)

        categorized_share = round(categorized_count / total_count, 4) if total_count else 0.0
        message = None
        if categorized_share < self.CATEGORY_COVERAGE_DISCLOSURE_THRESHOLD:
            # רוב התנועות בחלון אינן מסווגות — הפירוק המוצג הוא אמיתי (לא
            # מומצא), אבל חלקי. "אפס אמון מוצג בביטחון" אסור: מגלים את
            # הכיסוי במפורש במקום להשתיק אותו מאחורי message=None.
            message = (
                f"רק {categorized_count} מתוך {total_count} תנועות בטווח זה "
                'מסווגות לקטגוריה (השאר תחת "לא מסווג") — ההתפלגות שלהלן '
                "חלקית ואינה מייצגת את מלוא התזרים."
            )

        return {
            "as_of": as_of.isoformat(),
            "data_sources": ["bank_transactions_actual"],
            "categories": categories,
            "coverage": {
                "categorized_count": categorized_count,
                "total_count": total_count,
                "categorized_share": categorized_share,
            },
            "message": message,
        }

    # ------------------------------------------------------------------ #
    # פנימי
    # ------------------------------------------------------------------ #
    def _bank_rows(self, start: date, end: date) -> list[tuple[date, Decimal]]:
        return (
            self.db.query(BankTransaction.transaction_date, BankTransaction.amount)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.transaction_date >= start,
                BankTransaction.transaction_date <= end,
            )
            .all()
        )

    @staticmethod
    def _sum_flows(
        rows: list[tuple[date, Decimal]], start: date, end: date
    ) -> tuple[float, float]:
        inflow = 0.0
        outflow = 0.0
        for d, amount in rows:
            if not (start <= d <= end):
                continue
            amt = float(amount or 0)
            if amt > 0:
                inflow += amt
            elif amt < 0:
                outflow += abs(amt)
        return round(inflow, 2), round(outflow, 2)

    def _live_cash_balance(self) -> tuple[Optional[Decimal], Optional[str]]:
        """יתרת מזומנים חיה = Σ Account.balance לחשבונות BANK ממקור Open
        Finance בלבד, עם דרישת טריות. אותה הגדרה בדיוק כמו
        ``DashboardService._get_of_cash_summary`` (dashboard_service.py:109),
        עם חיזוק אחד: כאן גם נדרשת חותמת-זמן טרייה (48h — ר' MAX_BALANCE_AGE
        למעלה). לכן שני המסכים עלולים להציג "מזומן" שונה באופן לגיטימי —
        /dashboard/overview לא בודק טריות, /cashflow* כן; זה לא באג, וההבדל
        לא אמור להיסגר ע"י מחיקת בדיקת הטריות כאן.

        **מה לא נספר כ"מזומן" (ותיקון-ביקורת 23/08/2026, P0-B):**
          - ASSET (חסכונות/נכסים ידניים) — נכס אינו מזומן זמין למחזור.
          - חשבון שאינו ``source == "open_finance"`` (SUMIT-מסונתז/ידני) —
            אין מקור-אמת חיצוני שמאמת את היתרה.
          - חשבון בלי חותמת-זמן טרייה: ``balance_as_of`` היא הראיה הראשית.
            רק כשהיא חסרה מותר fallback ל-``synced_at``, משום שסנכרון
            החשבון עדכן את היתרה באותה פעימה. ``observed_at`` לבדה היא
            תצפית כללית ברשומה ואינה מעידה שהיתרה עודכנה — לכן אינה fallback.

        שלמות ארגונית היא שער קשיח: אם אפילו חשבון OF/BANK אחד נפסל, מוחזר
        ``balance=None`` עם פירוט החשבונות שנפסלו. אין להציג סכום של החשבונות
        הטריים כמספר ארגוני שלם, גם אם מצרפים אליו אזהרת coverage.

        מחזיר (balance, reason): balance קיים רק כשכל חשבונות OF/BANK של
        הארגון כשירים וטריים; reason מסביר כל פסילה (None כשהכול טרי ומלא)."""
        accounts = self.db.query(Account).filter(
            Account.organization_id == self.organization_id,
            Account.account_type == AccountType.BANK,
            Account.source == "open_finance",
        ).all()
        if not accounts:
            return None, (
                "אין חשבון בנק ממקור Open Finance מחובר לארגון זה — "
                "לא ניתן לחשב יתרת מזומנים חיה."
            )

        now = datetime.utcnow()
        fresh: list[Account] = []
        rejected: list[str] = []
        max_age_hours = int(MAX_BALANCE_AGE.total_seconds() // 3600)
        for a in accounts:
            balance_as_of = _naive(a.balance_as_of)
            synced_at = _naive(a.synced_at)
            account_label = f"{a.name} (id={a.id})"

            # Policy: a provider balance timestamp wins whenever present.
            # A fresh account sync is acceptable only when balance_as_of is
            # absent; observed_at never proves that the balance was refreshed.
            ts = balance_as_of if balance_as_of is not None else synced_at
            if ts is not None and (now - ts) <= MAX_BALANCE_AGE:
                fresh.append(a)
            else:
                if ts is not None:
                    timestamp_name = "balance_as_of" if balance_as_of is not None else "synced_at"
                    rejected.append(
                        f"{account_label}: {timestamp_name} ישנה מ-{max_age_hours} שעות"
                    )
                elif a.observed_at is not None:
                    rejected.append(
                        f"{account_label}: קיים observed_at בלבד, שאינו מעיד על עדכניות היתרה"
                    )
                else:
                    rejected.append(
                        f"{account_label}: חסרות חותמות balance_as_of ו-synced_at"
                    )

        if rejected:
            return None, (
                "יתרת המזומנים הארגונית אינה שלמה ולכן נפסלה (fail-closed). "
                "החשבונות שנפסלו: " + "; ".join(rejected) + "."
            )

        total = sum((a.balance or Decimal("0")) for a in fresh)
        return Decimal(total), None

    def _expected_open_amount(
        self, model, skip_statuses: list, as_of: date
    ) -> tuple[float, int]:
        horizon = as_of + timedelta(days=EXPECTED_HORIZON_DAYS)
        rows = (
            self.db.query(model)
            .filter(
                model.organization_id == self.organization_id,
                model.status.notin_(skip_statuses),
                model.balance > 0,
                model.due_date.isnot(None),
                model.due_date >= as_of,
                model.due_date <= horizon,
            )
            .all()
        )
        amount = round(float(sum((r.balance for r in rows), Decimal("0"))), 2)
        return amount, len(rows)
