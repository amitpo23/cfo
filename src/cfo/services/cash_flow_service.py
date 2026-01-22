"""
Cash Flow Management Service
שירות ניהול תזרים מזומנים
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, extract

from ..models import (
    Account, Transaction, AccountType, TransactionType
)


class CashFlowCategory(str, Enum):
    """קטגוריות תזרים מזומנים"""
    OPERATING = "operating"  # פעילות שוטפת
    INVESTING = "investing"  # פעילות השקעה
    FINANCING = "financing"  # פעילות מימון


@dataclass
class CashFlowItem:
    """פריט תזרים מזומנים"""
    category: CashFlowCategory
    name: str
    name_he: str
    amount: Decimal
    is_inflow: bool  # True = כניסה, False = יציאה


@dataclass
class CashFlowStatement:
    """דוח תזרים מזומנים"""
    period_start: datetime
    period_end: datetime
    opening_balance: Decimal
    closing_balance: Decimal
    
    # פעילות שוטפת
    operating_items: List[CashFlowItem]
    operating_total: Decimal
    
    # פעילות השקעה
    investing_items: List[CashFlowItem]
    investing_total: Decimal
    
    # פעילות מימון
    financing_items: List[CashFlowItem]
    financing_total: Decimal
    
    # סה"כ
    net_cash_flow: Decimal


@dataclass
class CashFlowProjection:
    """תחזית תזרים מזומנים"""
    date: datetime
    projected_inflows: Decimal
    projected_outflows: Decimal
    projected_balance: Decimal
    confidence_level: float  # 0-1


class CashFlowService:
    """
    שירות ניהול תזרים מזומנים
    מספק ניתוח, דיווח ותחזית תזרים
    """
    
    # מיפוי קטגוריות עסקאות לקטגוריות תזרים
    CATEGORY_MAPPING = {
        # פעילות שוטפת
        'sales': CashFlowCategory.OPERATING,
        'services': CashFlowCategory.OPERATING,
        'salaries': CashFlowCategory.OPERATING,
        'rent': CashFlowCategory.OPERATING,
        'utilities': CashFlowCategory.OPERATING,
        'supplies': CashFlowCategory.OPERATING,
        'marketing': CashFlowCategory.OPERATING,
        'insurance': CashFlowCategory.OPERATING,
        'taxes': CashFlowCategory.OPERATING,
        'interest_expense': CashFlowCategory.OPERATING,
        'interest_income': CashFlowCategory.OPERATING,
        
        # פעילות השקעה
        'equipment': CashFlowCategory.INVESTING,
        'property': CashFlowCategory.INVESTING,
        'investments': CashFlowCategory.INVESTING,
        'asset_sale': CashFlowCategory.INVESTING,
        
        # פעילות מימון
        'loan': CashFlowCategory.FINANCING,
        'loan_repayment': CashFlowCategory.FINANCING,
        'equity': CashFlowCategory.FINANCING,
        'dividends': CashFlowCategory.FINANCING,
        'owner_withdrawal': CashFlowCategory.FINANCING,
        'owner_investment': CashFlowCategory.FINANCING,
    }
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_cash_flow_statement(
        self,
        organization_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> CashFlowStatement:
        """
        יצירת דוח תזרים מזומנים לתקופה
        Cash Flow Statement generation
        """
        # חישוב יתרת פתיחה
        opening_balance = self._get_opening_balance(organization_id, start_date)
        
        # שליפת כל העסקאות בתקופה
        transactions = self.db.query(Transaction).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).all()
        
        # מיון לפי קטגוריות
        operating_items = []
        investing_items = []
        financing_items = []
        
        category_totals: Dict[str, Decimal] = {}
        
        for tx in transactions:
            category = tx.category or 'other'
            cf_category = self.CATEGORY_MAPPING.get(category, CashFlowCategory.OPERATING)
            
            # צבירה לפי קטגוריה
            if category not in category_totals:
                category_totals[category] = Decimal("0")
            
            if tx.transaction_type == TransactionType.INCOME:
                category_totals[category] += tx.amount
            else:
                category_totals[category] -= tx.amount
        
        # יצירת פריטים
        for category, amount in category_totals.items():
            cf_category = self.CATEGORY_MAPPING.get(category, CashFlowCategory.OPERATING)
            item = CashFlowItem(
                category=cf_category,
                name=category,
                name_he=self._get_hebrew_name(category),
                amount=abs(amount),
                is_inflow=amount > 0
            )
            
            if cf_category == CashFlowCategory.OPERATING:
                operating_items.append(item)
            elif cf_category == CashFlowCategory.INVESTING:
                investing_items.append(item)
            else:
                financing_items.append(item)
        
        # חישוב סכומים
        operating_total = self._calculate_category_total(operating_items)
        investing_total = self._calculate_category_total(investing_items)
        financing_total = self._calculate_category_total(financing_items)
        
        net_cash_flow = operating_total + investing_total + financing_total
        closing_balance = opening_balance + net_cash_flow
        
        return CashFlowStatement(
            period_start=start_date,
            period_end=end_date,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            operating_items=operating_items,
            operating_total=operating_total,
            investing_items=investing_items,
            investing_total=investing_total,
            financing_items=financing_items,
            financing_total=financing_total,
            net_cash_flow=net_cash_flow
        )
    
    def get_monthly_cash_flow(
        self,
        organization_id: int,
        months: int = 12
    ) -> List[Dict[str, Any]]:
        """
        תזרים מזומנים חודשי
        Monthly cash flow analysis
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)
        
        results = []
        current_date = start_date
        
        while current_date < end_date:
            month_start = current_date.replace(day=1)
            if current_date.month == 12:
                month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)
            
            # הכנסות בחודש
            income = self.db.query(func.sum(Transaction.amount)).filter(
                and_(
                    Transaction.organization_id == organization_id,
                    Transaction.transaction_type == TransactionType.INCOME,
                    Transaction.transaction_date >= month_start,
                    Transaction.transaction_date <= month_end
                )
            ).scalar() or Decimal("0")
            
            # הוצאות בחודש
            expenses = self.db.query(func.sum(Transaction.amount)).filter(
                and_(
                    Transaction.organization_id == organization_id,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.transaction_date >= month_start,
                    Transaction.transaction_date <= month_end
                )
            ).scalar() or Decimal("0")
            
            results.append({
                'month': month_start.strftime('%Y-%m'),
                'month_name': month_start.strftime('%B %Y'),
                'inflows': float(income),
                'outflows': float(expenses),
                'net_flow': float(income - expenses),
                'cumulative': float(sum(r['net_flow'] for r in results) + float(income - expenses))
            })
            
            # מעבר לחודש הבא
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1, day=1)
        
        return results
    
    def get_cash_flow_by_category(
        self,
        organization_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Dict[str, Decimal]]:
        """
        ניתוח תזרים לפי קטגוריות
        Cash flow breakdown by category
        """
        transactions = self.db.query(
            Transaction.category,
            Transaction.transaction_type,
            func.sum(Transaction.amount).label('total')
        ).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).group_by(Transaction.category, Transaction.transaction_type).all()
        
        result = {
            'operating': {'inflows': Decimal("0"), 'outflows': Decimal("0")},
            'investing': {'inflows': Decimal("0"), 'outflows': Decimal("0")},
            'financing': {'inflows': Decimal("0"), 'outflows': Decimal("0")},
        }
        
        for tx in transactions:
            category = tx.category or 'other'
            cf_category = self.CATEGORY_MAPPING.get(category, CashFlowCategory.OPERATING).value
            
            if tx.transaction_type == TransactionType.INCOME:
                result[cf_category]['inflows'] += tx.total
            else:
                result[cf_category]['outflows'] += tx.total
        
        return result
    
    def get_daily_cash_position(
        self,
        organization_id: int,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        מצב מזומנים יומי
        Daily cash position tracking
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # יתרת פתיחה
        opening_balance = self._get_opening_balance(organization_id, start_date)
        
        results = []
        current_balance = opening_balance
        current_date = start_date
        
        while current_date <= end_date:
            day_start = current_date.replace(hour=0, minute=0, second=0)
            day_end = current_date.replace(hour=23, minute=59, second=59)
            
            # הכנסות ביום
            income = self.db.query(func.sum(Transaction.amount)).filter(
                and_(
                    Transaction.organization_id == organization_id,
                    Transaction.transaction_type == TransactionType.INCOME,
                    Transaction.transaction_date >= day_start,
                    Transaction.transaction_date <= day_end
                )
            ).scalar() or Decimal("0")
            
            # הוצאות ביום
            expenses = self.db.query(func.sum(Transaction.amount)).filter(
                and_(
                    Transaction.organization_id == organization_id,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.transaction_date >= day_start,
                    Transaction.transaction_date <= day_end
                )
            ).scalar() or Decimal("0")
            
            current_balance += income - expenses
            
            results.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'inflows': float(income),
                'outflows': float(expenses),
                'net_flow': float(income - expenses),
                'closing_balance': float(current_balance)
            })
            
            current_date += timedelta(days=1)
        
        return results
    
    def get_cash_burn_rate(
        self,
        organization_id: int,
        months: int = 3
    ) -> Dict[str, Any]:
        """
        חישוב קצב שריפת מזומנים
        Calculate cash burn rate
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)
        
        # סך הוצאות בתקופה
        total_expenses = self.db.query(func.sum(Transaction.amount)).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).scalar() or Decimal("0")
        
        # סך הכנסות בתקופה
        total_income = self.db.query(func.sum(Transaction.amount)).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).scalar() or Decimal("0")
        
        # יתרה נוכחית
        current_balance = self._get_current_balance(organization_id)
        
        # חישובים
        monthly_burn = total_expenses / months if months > 0 else Decimal("0")
        monthly_income = total_income / months if months > 0 else Decimal("0")
        net_burn = monthly_burn - monthly_income
        
        # חישוב runway - כמה חודשים נשארו
        if net_burn > 0:
            runway_months = float(current_balance / net_burn)
        else:
            runway_months = float('inf')  # אין שריפת מזומנים
        
        return {
            'monthly_burn_rate': float(monthly_burn),
            'monthly_income': float(monthly_income),
            'net_monthly_burn': float(net_burn),
            'current_balance': float(current_balance),
            'runway_months': runway_months,
            'analysis_period_months': months
        }
    
    def get_receivables_aging(
        self,
        organization_id: int
    ) -> Dict[str, Any]:
        """
        גיול חובות לקוחות
        Accounts receivable aging report
        """
        # TODO: לממש עם נתוני חשבוניות מ-SUMIT
        today = datetime.now()
        
        return {
            'current': {'amount': 0, 'count': 0, 'label': '0-30 ימים'},
            'days_30_60': {'amount': 0, 'count': 0, 'label': '31-60 ימים'},
            'days_60_90': {'amount': 0, 'count': 0, 'label': '61-90 ימים'},
            'over_90': {'amount': 0, 'count': 0, 'label': 'מעל 90 ימים'},
            'total': {'amount': 0, 'count': 0}
        }
    
    def get_payables_aging(
        self,
        organization_id: int
    ) -> Dict[str, Any]:
        """
        גיול חובות לספקים
        Accounts payable aging report
        """
        # TODO: לממש עם נתוני הוצאות מ-SUMIT
        return {
            'current': {'amount': 0, 'count': 0, 'label': '0-30 ימים'},
            'days_30_60': {'amount': 0, 'count': 0, 'label': '31-60 ימים'},
            'days_60_90': {'amount': 0, 'count': 0, 'label': '61-90 ימים'},
            'over_90': {'amount': 0, 'count': 0, 'label': 'מעל 90 ימים'},
            'total': {'amount': 0, 'count': 0}
        }
    
    def get_liquidity_ratios(
        self,
        organization_id: int
    ) -> Dict[str, float]:
        """
        חישוב יחסי נזילות
        Calculate liquidity ratios
        """
        # נכסים שוטפים
        current_assets = self.db.query(func.sum(Account.balance)).filter(
            and_(
                Account.organization_id == organization_id,
                Account.account_type == AccountType.ASSET
            )
        ).scalar() or Decimal("0")
        
        # התחייבויות שוטפות
        current_liabilities = self.db.query(func.sum(Account.balance)).filter(
            and_(
                Account.organization_id == organization_id,
                Account.account_type == AccountType.LIABILITY
            )
        ).scalar() or Decimal("0")
        
        # יחס שוטף
        current_ratio = float(current_assets / current_liabilities) if current_liabilities > 0 else float('inf')
        
        # יחס מהיר (בהנחה ש-80% מהנכסים נזילים)
        quick_ratio = float((current_assets * Decimal("0.8")) / current_liabilities) if current_liabilities > 0 else float('inf')
        
        # יחס מזומנים
        cash_ratio = float((current_assets * Decimal("0.5")) / current_liabilities) if current_liabilities > 0 else float('inf')
        
        return {
            'current_ratio': current_ratio,
            'quick_ratio': quick_ratio,
            'cash_ratio': cash_ratio,
            'working_capital': float(current_assets - current_liabilities),
            'current_assets': float(current_assets),
            'current_liabilities': float(current_liabilities)
        }
    
    # ============= Private Methods =============
    
    def _get_opening_balance(
        self,
        organization_id: int,
        as_of_date: datetime
    ) -> Decimal:
        """חישוב יתרת פתיחה"""
        # סכום כל העסקאות עד לתאריך
        income = self.db.query(func.sum(Transaction.amount)).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date < as_of_date
            )
        ).scalar() or Decimal("0")
        
        expenses = self.db.query(func.sum(Transaction.amount)).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date < as_of_date
            )
        ).scalar() or Decimal("0")
        
        return income - expenses
    
    def _get_current_balance(self, organization_id: int) -> Decimal:
        """יתרה נוכחית"""
        return self._get_opening_balance(organization_id, datetime.now() + timedelta(days=1))
    
    def _calculate_category_total(self, items: List[CashFlowItem]) -> Decimal:
        """חישוב סה״כ לקטגוריה"""
        total = Decimal("0")
        for item in items:
            if item.is_inflow:
                total += item.amount
            else:
                total -= item.amount
        return total
    
    def _get_hebrew_name(self, category: str) -> str:
        """תרגום שם קטגוריה לעברית"""
        translations = {
            'sales': 'מכירות',
            'services': 'שירותים',
            'salaries': 'משכורות',
            'rent': 'שכירות',
            'utilities': 'חשבונות',
            'supplies': 'ציוד',
            'marketing': 'שיווק',
            'insurance': 'ביטוח',
            'taxes': 'מסים',
            'interest_expense': 'הוצאות ריבית',
            'interest_income': 'הכנסות ריבית',
            'equipment': 'ציוד',
            'property': 'נדל"ן',
            'investments': 'השקעות',
            'asset_sale': 'מכירת נכסים',
            'loan': 'הלוואה',
            'loan_repayment': 'החזר הלוואה',
            'equity': 'הון',
            'dividends': 'דיבידנדים',
            'owner_withdrawal': 'משיכת בעלים',
            'owner_investment': 'השקעת בעלים',
            'other': 'אחר',
        }
        return translations.get(category, category)
