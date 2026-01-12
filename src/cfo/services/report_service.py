"""
Report generation service
שירות ליצירת דוחות
"""
from typing import Optional
from datetime import datetime
from pathlib import Path
import pandas as pd
from decimal import Decimal

from ..config import settings
from .financial_service import FinancialService


class ReportService:
    """שירות ליצירת דוחות פיננסיים"""
    
    def __init__(self, financial_service: FinancialService):
        self.financial_service = financial_service
        self.output_dir = Path(settings.reports_output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def generate_balance_sheet_report(
        self,
        output_file: Optional[str] = None
    ) -> str:
        """יצירת דוח מאזן"""
        accounts = self.financial_service.get_all_accounts()
        
        # הכנת הנתונים
        data = []
        for account in accounts:
            data.append({
                "שם חשבון": account.name,
                "סוג": account.account_type.value,
                "יתרה": float(account.balance),
                "מטבע": account.currency
            })
        
        df = pd.DataFrame(data)
        
        # שמירת הקובץ
        if not output_file:
            output_file = f"balance_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        output_path = self.output_dir / output_file
        df.to_excel(output_path, index=False, engine='openpyxl')
        
        return str(output_path)
    
    def generate_transactions_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        output_file: Optional[str] = None
    ) -> str:
        """יצירת דוח עסקאות"""
        transactions = self.financial_service.get_transactions(
            start_date=start_date,
            end_date=end_date,
            limit=10000
        )
        
        # הכנת הנתונים
        data = []
        for trans in transactions:
            account = self.financial_service.get_account(trans.account_id)
            data.append({
                "תאריך": trans.transaction_date.strftime("%Y-%m-%d %H:%M"),
                "חשבון": account.name if account else "לא ידוע",
                "סוג": trans.transaction_type.value,
                "סכום": float(trans.amount),
                "תיאור": trans.description or "",
                "קטגוריה": trans.category or ""
            })
        
        df = pd.DataFrame(data)
        
        # שמירת הקובץ
        if not output_file:
            output_file = f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        output_path = self.output_dir / output_file
        df.to_excel(output_path, index=False, engine='openpyxl')
        
        return str(output_path)
    
    def generate_profit_loss_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        output_file: Optional[str] = None
    ) -> str:
        """יצירת דוח רווח והפסד"""
        summary = self.financial_service.get_financial_summary(
            start_date=start_date,
            end_date=end_date
        )
        
        # הכנת הנתונים
        data = [
            {"פריט": "הכנסות", "סכום": float(summary.total_income)},
            {"פריט": "הוצאות", "סכום": float(summary.total_expenses)},
            {"פריט": "רווח/הפסד נקי", "סכום": float(summary.net_income)},
        ]
        
        df = pd.DataFrame(data)
        
        # שמירת הקובץ
        if not output_file:
            output_file = f"profit_loss_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        output_path = self.output_dir / output_file
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='רווח והפסד', index=False)
            
            # הוספת סיכום
            summary_data = pd.DataFrame([{
                "תקופה מ-": summary.period_start.strftime("%Y-%m-%d"),
                "תקופה עד": summary.period_end.strftime("%Y-%m-%d"),
                "סך נכסים": float(summary.total_assets),
                "סך התחייבויות": float(summary.total_liabilities),
                "הון עצמי": float(summary.net_worth)
            }])
            summary_data.to_excel(writer, sheet_name='סיכום', index=False)
        
        return str(output_path)
