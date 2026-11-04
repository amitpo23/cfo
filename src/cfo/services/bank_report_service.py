"""
דוח מצב עסקי לבנק
Bank status report — composes real P&L, balance, cash position and AR/AP aging
into one banker-facing summary, with Excel export.
"""
from datetime import date, timedelta
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Bill, Organization
from .financial_control_service import FinancialControlService
from .ar_service import AccountsReceivableService


def _fraction(percent):
    """A percent (48.7) as the fraction Excel's 0.0% format expects (0.487). Missing stays empty."""
    return None if percent is None else round(percent / 100, 4)


def _cell_text(value):
    """Text from a provider (an account name) must not start an Excel formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class BankReportService:
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id

    def generate(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict:
        """הרכבת דוח מצב עסקי לבנק מנתונים אמיתיים."""
        today = end_date or date.today()
        period_start = start_date or today.replace(month=1, day=1)

        org = (
            self.db.query(Organization)
            .filter(Organization.id == self.organization_id)
            .first()
        )
        company_name = org.name if org else "העסק"

        # The same books figures /pnl shows for this range (cashflow.period).
        from .dashboards.period_compare import books_pnl_summary
        pl = books_pnl_summary(self.db, self.organization_id, period_start, today)
        # מקור אמת משותף עם מסך ה-KPI כדי שהמספרים יתאימו
        from .balance_snapshot import compute_balance_snapshot
        balance = compute_balance_snapshot(self.db, self.organization_id)

        control = FinancialControlService(
            self.db, organization_id=self.organization_id
        ).get_control_overview(period_start, today)

        aging = AccountsReceivableService(
            self.db, organization_id=self.organization_id
        ).get_aging_report(today)

        from .open_payables import confirmed_cover, remaining_of
        cover = confirmed_cover(self.db, self.organization_id)
        payables_total = float(sum(
            (remaining_of(bill, cover) or 0)
            for bill in self.db.query(Bill).filter(
                Bill.organization_id == self.organization_id,
                Bill.balance > 0,
            ).all()
        ))

        from .dashboards.money_screens import checking_and_loans
        checking = checking_and_loans(self.db, self.organization_id)

        return {
            "company_name": company_name,
            "credit_lines": checking["credit_lines"],
            "loans_total": checking["loans_total"],
            "partial_banner": checking["partial_banner"],
            "generated_at": date.today().isoformat(),
            "period": {"start": period_start.isoformat(), "end": today.isoformat()},
            "profit_loss": pl,
            "balance_sheet": {
                "total_assets": balance["total_assets"],
                "total_current_assets": balance["current_assets"],
                "total_liabilities": balance["total_liabilities"],
                "total_current_liabilities": balance["current_liabilities"],
                "total_equity": balance["equity"],
                "current_ratio": balance["current_ratio"],
            },
            "cash_position": control.get("cash", {}),
            "receivables": {
                "total": float(aging.total_receivables or 0),
                "current": float(aging.current_total or 0),
                "days_31_60": float(aging.days_31_60_total or 0),
                "days_61_90": float(aging.days_61_90_total or 0),
                "days_91_120": float(aging.days_91_120_total or 0),
                "over_120": float(aging.over_120_total or 0),
            },
            "payables": {"total": payables_total},
        }

    def to_excel(self, report: Dict) -> bytes:
        """ייצוא דוח הבנק ל-Excel."""
        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment, PatternFill
        except ImportError:
            raise ValueError("openpyxl required for Excel export")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "דוח מצב לבנק"
        ws.sheet_view.rightToLeft = True

        header_font = Font(bold=True, size=14)
        section_font = Font(bold=True, size=12, color="FFFFFF")
        section_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        currency = "₪#,##0"
        percent = "0.0%"

        ws.merge_cells("A1:B1")
        ws["A1"] = f"דוח מצב עסקי — {report['company_name']}"
        ws["A1"].font = header_font
        ws["A1"].alignment = Alignment(horizontal="center")
        ws.merge_cells("A2:B2")
        ws["A2"] = f"לתקופה {report['period']['start']} עד {report['period']['end']}"
        ws["A2"].alignment = Alignment(horizontal="center")

        row = 4

        def section(title: str):
            nonlocal row
            ws.merge_cells(f"A{row}:B{row}")
            c = ws.cell(row=row, column=1, value=title)
            c.font = section_font
            c.fill = section_fill
            row += 1

        def line(label: str, value, fmt: str = currency):
            nonlocal row
            ws.cell(row=row, column=1, value=_cell_text(label))
            cell = ws.cell(row=row, column=2, value="חסר" if value is None else _cell_text(value))
            if value is not None:
                cell.number_format = fmt
            row += 1

        pl = report["profit_loss"]
        section("רווח והפסד")
        line("סך הכנסות", pl["total_revenue"])
        line("סך הוצאות", pl["total_expenses"])
        line("רווח גולמי", pl["gross_profit"])
        line("שולי רווח גולמי", _fraction(pl["gross_margin"]), percent)
        line("רווח תפעולי", pl["operating_income"])
        line("רווח נקי", pl["net_income"])
        line("שולי רווח נקי", _fraction(pl["net_margin"]), percent)
        row += 1

        bs = report["balance_sheet"]
        section("מאזן")
        line("סך נכסים", bs["total_assets"])
        line("נכסים שוטפים", bs["total_current_assets"])
        line("סך התחייבויות", bs["total_liabilities"])
        line("התחייבויות שוטפות", bs["total_current_liabilities"])
        line("הון עצמי", bs["total_equity"])
        line("יחס שוטף", bs["current_ratio"], "0.00")
        row += 1

        cash = report["cash_position"] or {}
        section("עו״ש ומסגרות (יתרה סגורה אחרונה)")
        for account in (report.get("credit_lines") or {}).get("accounts") or []:
            name = account.get("name") or "חשבון עו״ש"
            line(f"{name}: יתרה", account.get("balance"))
            line(f"{name}: נכון ל-", account.get("as_of"), "@")
            line(f"{name}: מסגרת", account.get("limit"))
            line(f"{name}: ניצול", account.get("used"))
            line(f"{name}: חריגה", account.get("overrun"))
        line("הלוואות (יתרה)", report.get("loans_total"))
        line("תזרים בנק נטו בתקופה", cash.get("net_bank_flow"))
        row += 1

        ar = report["receivables"]
        section("חייבים (לקוחות)")
        line("סך חוב לקוחות", ar["total"])
        line("שוטף", ar["current"])
        line("31-60 יום", ar["days_31_60"])
        line("61-90 יום", ar["days_61_90"])
        line("91-120 יום", ar["days_91_120"])
        line("מעל 120 יום", ar["over_120"])
        row += 1

        section("זכאים (ספקים)")
        line("סך חוב לספקים", report["payables"]["total"])

        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 20

        import io
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
