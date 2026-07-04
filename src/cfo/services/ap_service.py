"""
Accounts Payable Service - Payment Management
שירות ניהול זכאים - תזמון תשלומים והתאמות
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models import Transaction, Account, Bill, Contact, Payment, BankTransaction
from ..database import SessionLocal


class PaymentPriority(str, Enum):
    """עדיפות תשלום"""
    CRITICAL = "critical"    # חובה לשלם היום
    HIGH = "high"            # עדיפות גבוהה
    MEDIUM = "medium"        # עדיפות בינונית
    LOW = "low"              # אפשר לדחות
    FLEXIBLE = "flexible"    # גמיש


class PaymentMethod(str, Enum):
    """אמצעי תשלום"""
    BANK_TRANSFER = "bank_transfer"
    CHECK = "check"
    CREDIT_CARD = "credit_card"
    CASH = "cash"
    STANDING_ORDER = "standing_order"


class ApprovalStatus(str, Enum):
    """סטטוס אישור"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


class ReconciliationStatus(str, Enum):
    """סטטוס התאמה"""
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PARTIAL = "partial"
    MANUAL_REVIEW = "manual_review"


@dataclass
class VendorPayment:
    """תשלום לספק"""
    payment_id: str
    vendor_id: str
    vendor_name: str
    invoice_number: str
    invoice_date: str
    due_date: str
    amount: float
    currency: str
    payment_terms: str
    days_until_due: int
    priority: PaymentPriority
    payment_method: PaymentMethod
    approval_status: ApprovalStatus
    scheduled_date: Optional[str]
    discount_available: bool
    discount_amount: float
    discount_deadline: Optional[str]


@dataclass
class PaymentSchedule:
    """לוח זמנים לתשלומים"""
    schedule_date: str
    total_payments: int
    total_amount: float
    payments: List[VendorPayment]
    cash_available: float
    cash_after_payments: float
    recommendations: List[str]


@dataclass
class BankReconciliationItem:
    """פריט התאמת בנק"""
    item_id: str
    bank_date: str
    bank_description: str
    bank_amount: float
    book_date: Optional[str]
    book_description: Optional[str]
    book_amount: Optional[float]
    status: ReconciliationStatus
    difference: float
    suggested_match: Optional[str]
    notes: str


@dataclass
class BankReconciliationReport:
    """דוח התאמת בנק"""
    reconciliation_date: str
    bank_balance: float
    book_balance: float
    difference: float
    matched_items: List[BankReconciliationItem]
    unmatched_bank_items: List[BankReconciliationItem]
    unmatched_book_items: List[BankReconciliationItem]
    reconciled_percentage: float
    adjustments_needed: List[Dict]
    # אין מקור אמיתי לשם הבנק/מספר החשבון בקלט הפונקציה (bank_statement מכיל
    # רק תאריך/תיאור/סכום) — לכן None, לא ניחוש שנראה אמיתי.
    bank_name: Optional[str] = None
    account_number: Optional[str] = None


@dataclass
class VendorAnalysis:
    """ניתוח ספק"""
    vendor_id: str
    vendor_name: str
    total_purchases_ytd: float
    total_paid_ytd: float
    outstanding_balance: float
    average_payment_days: float
    payment_terms: str
    discount_captured: float
    discount_missed: float
    on_time_payment_rate: float
    relationship_score: int
    category: str
    recommendations: List[str]


@dataclass
class CashOptimizationPlan:
    """תכנית אופטימיזציה של תשלומים"""
    plan_date: str
    current_cash: float
    total_payables: float
    recommended_payments: List[VendorPayment]
    deferred_payments: List[VendorPayment]
    total_recommended: float
    total_deferred: float
    expected_cash_after: float
    savings_from_discounts: float
    optimization_score: int
    notes: List[str]


class AccountsPayableService:
    """
    שירות ניהול זכאים
    Accounts Payable Management Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # הגדרות ברירת מחדל
        self.cash_reserve_minimum = 50000  # מינימום מזומן לשמור
        self.approval_threshold = 10000    # סף לאישור
    
    def get_pending_payments(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        vendor_id: Optional[str] = None,
        priority: Optional[PaymentPriority] = None
    ) -> List[VendorPayment]:
        """
        קבלת תשלומים ממתינים
        Get Pending Payments
        """
        if not from_date:
            from_date = date.today()
        if not to_date:
            to_date = from_date + timedelta(days=30)
        
        # שליפת חשבוניות לתשלום
        invoices = self._get_pending_invoices()
        
        payments = []
        for inv in invoices:
            due = datetime.strptime(inv['due_date'], '%Y-%m-%d').date()
            days_until = (due - date.today()).days
            
            # קביעת עדיפות
            if days_until < 0:
                prio = PaymentPriority.CRITICAL
            elif days_until <= 3:
                prio = PaymentPriority.HIGH
            elif days_until <= 14:
                prio = PaymentPriority.MEDIUM
            elif days_until <= 30:
                prio = PaymentPriority.LOW
            else:
                prio = PaymentPriority.FLEXIBLE
            
            if priority and prio != priority:
                continue
            
            if vendor_id and inv['vendor_id'] != vendor_id:
                continue
            
            # בדיקת הנחה
            discount_available = inv.get('discount_percent', 0) > 0
            discount_deadline = inv.get('discount_deadline')
            discount_amount = inv['amount'] * inv.get('discount_percent', 0) / 100
            
            payment = VendorPayment(
                payment_id=f"PAY-{inv['number']}",
                vendor_id=inv['vendor_id'],
                vendor_name=inv['vendor_name'],
                invoice_number=inv['number'],
                invoice_date=inv['date'],
                due_date=inv['due_date'],
                amount=inv['amount'],
                currency='ILS',
                payment_terms=inv.get('terms', 'שוטף+30'),
                days_until_due=days_until,
                priority=prio,
                payment_method=PaymentMethod.BANK_TRANSFER,
                approval_status=ApprovalStatus.PENDING if inv['amount'] > self.approval_threshold else ApprovalStatus.APPROVED,
                scheduled_date=None,
                discount_available=discount_available,
                discount_amount=discount_amount,
                discount_deadline=discount_deadline
            )
            payments.append(payment)
        
        # מיון לפי עדיפות ותאריך
        priority_order = {
            PaymentPriority.CRITICAL: 0,
            PaymentPriority.HIGH: 1,
            PaymentPriority.MEDIUM: 2,
            PaymentPriority.LOW: 3,
            PaymentPriority.FLEXIBLE: 4
        }
        payments.sort(key=lambda x: (priority_order[x.priority], x.days_until_due))
        
        return payments
    
    def create_payment_schedule(
        self,
        schedule_date: date,
        available_cash: float,
        prioritize_discounts: bool = True
    ) -> PaymentSchedule:
        """
        יצירת לוח תשלומים אופטימלי
        Create Optimal Payment Schedule
        """
        pending = self.get_pending_payments(to_date=schedule_date + timedelta(days=7))
        
        # מיון לפי אופטימיזציה
        if prioritize_discounts:
            # קודם כל תשלומים עם הנחות שעומדים לפוג
            pending.sort(key=lambda x: (
                not x.discount_available,
                x.days_until_due
            ))
        
        scheduled_payments = []
        deferred_payments = []
        remaining_cash = available_cash - self.cash_reserve_minimum
        
        recommendations = []
        
        for payment in pending:
            # חובה לשלם?
            if payment.priority == PaymentPriority.CRITICAL:
                scheduled_payments.append(payment)
                remaining_cash -= payment.amount
                if remaining_cash < 0:
                    recommendations.append(f"⚠️ אזהרה: גירעון צפוי של ₪{abs(remaining_cash):,.0f}")
            
            # יש מספיק מזומן?
            elif remaining_cash >= payment.amount:
                # כדאי לשלם מוקדם בגלל הנחה?
                if payment.discount_available:
                    scheduled_payments.append(payment)
                    remaining_cash -= (payment.amount - payment.discount_amount)
                    recommendations.append(
                        f"💰 הנחה של ₪{payment.discount_amount:,.0f} מ{payment.vendor_name}"
                    )
                elif payment.priority in [PaymentPriority.HIGH, PaymentPriority.MEDIUM]:
                    scheduled_payments.append(payment)
                    remaining_cash -= payment.amount
                else:
                    deferred_payments.append(payment)
            else:
                deferred_payments.append(payment)
        
        # סיכום
        total_scheduled = sum(p.amount for p in scheduled_payments)
        total_deferred = sum(p.amount for p in deferred_payments)
        
        return PaymentSchedule(
            schedule_date=schedule_date.isoformat(),
            total_payments=len(scheduled_payments),
            total_amount=total_scheduled,
            payments=scheduled_payments,
            cash_available=available_cash,
            cash_after_payments=available_cash - total_scheduled,
            recommendations=recommendations
        )
    
    def run_bank_reconciliation(
        self,
        bank_statement: List[Dict],
        book_transactions: Optional[List[Dict]] = None
    ) -> BankReconciliationReport:
        """
        התאמת בנק אוטומטית
        Automatic Bank Reconciliation
        """
        if not book_transactions:
            book_transactions = self._get_book_transactions()
        
        matched = []
        unmatched_bank = []
        unmatched_book = book_transactions.copy()
        
        for bank_item in bank_statement:
            match_found = False
            
            for book_item in unmatched_book:
                # התאמה לפי סכום ותאריך
                amount_match = abs(bank_item['amount'] - book_item['amount']) < 0.01
                date_diff = abs((datetime.strptime(bank_item['date'], '%Y-%m-%d') - 
                               datetime.strptime(book_item['date'], '%Y-%m-%d')).days)
                date_match = date_diff <= 3
                
                if amount_match and date_match:
                    matched.append(BankReconciliationItem(
                        item_id=f"REC-{len(matched)+1}",
                        bank_date=bank_item['date'],
                        bank_description=bank_item['description'],
                        bank_amount=bank_item['amount'],
                        book_date=book_item['date'],
                        book_description=book_item['description'],
                        book_amount=book_item['amount'],
                        status=ReconciliationStatus.MATCHED,
                        difference=0,
                        suggested_match=None,
                        notes=""
                    ))
                    unmatched_book.remove(book_item)
                    match_found = True
                    break
            
            if not match_found:
                # חיפוש התאמה חלקית
                suggested = self._find_suggested_match(bank_item, unmatched_book)
                
                unmatched_bank.append(BankReconciliationItem(
                    item_id=f"BANK-{len(unmatched_bank)+1}",
                    bank_date=bank_item['date'],
                    bank_description=bank_item['description'],
                    bank_amount=bank_item['amount'],
                    book_date=None,
                    book_description=None,
                    book_amount=None,
                    status=ReconciliationStatus.UNMATCHED,
                    difference=bank_item['amount'],
                    suggested_match=suggested,
                    notes="לא נמצאה התאמה בספרים"
                ))
        
        # פריטים שנשארו בספרים
        unmatched_book_items = [
            BankReconciliationItem(
                item_id=f"BOOK-{i}",
                bank_date=None,
                bank_description=None,
                bank_amount=None,
                book_date=item['date'],
                book_description=item['description'],
                book_amount=item['amount'],
                status=ReconciliationStatus.UNMATCHED,
                difference=item['amount'],
                suggested_match=None,
                notes="לא נמצאה התאמה בבנק"
            )
            for i, item in enumerate(unmatched_book)
        ]
        
        # חישובים
        bank_balance = sum(item['amount'] for item in bank_statement)
        book_balance = sum(item['amount'] for item in book_transactions)
        
        total_items = len(bank_statement) + len(book_transactions)
        matched_items = len(matched) * 2  # כל התאמה = 2 פריטים
        reconciled_pct = (matched_items / total_items * 100) if total_items else 100
        
        # התאמות נדרשות
        adjustments = []
        if unmatched_bank:
            adjustments.append({
                'type': 'bank_to_book',
                'description': 'פריטים בבנק שלא נרשמו בספרים',
                'count': len(unmatched_bank),
                'total': sum(item.bank_amount for item in unmatched_bank)
            })
        if unmatched_book_items:
            adjustments.append({
                'type': 'book_to_bank',
                'description': 'פריטים בספרים שלא הופיעו בבנק',
                'count': len(unmatched_book_items),
                'total': sum(item.book_amount or 0 for item in unmatched_book_items)
            })
        
        return BankReconciliationReport(
            reconciliation_date=date.today().isoformat(),
            bank_balance=bank_balance,
            book_balance=book_balance,
            difference=bank_balance - book_balance,
            matched_items=matched,
            unmatched_bank_items=unmatched_bank,
            unmatched_book_items=unmatched_book_items,
            reconciled_percentage=reconciled_pct,
            adjustments_needed=adjustments
        )
    
    def analyze_vendor(self, vendor_id: str) -> VendorAnalysis:
        """
        ניתוח ספק
        Vendor Analysis
        """
        # נתוני ספק (בפרודקשן - מDB)
        vendor_data = self._get_vendor_data(vendor_id)
        
        recommendations = []
        
        # ניתוח הנחות
        if vendor_data['discount_missed'] > vendor_data['discount_captured']:
            recommendations.append("💡 מומלץ לנצל יותר הנחות מוקדמות מספק זה")
        
        # ניתוח תנאי תשלום
        if vendor_data['average_payment_days'] < 25:
            recommendations.append("⏰ משלמים מוקדם מדי - אפשר לשפר את התזרים")
        
        # ניתוח נפח
        if vendor_data['total_purchases_ytd'] > 100000:
            recommendations.append("🤝 ספק משמעותי - כדאי לנהל מו\"מ על תנאים")
        
        return VendorAnalysis(
            vendor_id=vendor_id,
            vendor_name=vendor_data['name'],
            total_purchases_ytd=vendor_data['total_purchases_ytd'],
            total_paid_ytd=vendor_data['total_paid_ytd'],
            outstanding_balance=vendor_data['outstanding'],
            average_payment_days=vendor_data['average_payment_days'],
            payment_terms=vendor_data['terms'],
            discount_captured=vendor_data['discount_captured'],
            discount_missed=vendor_data['discount_missed'],
            on_time_payment_rate=vendor_data['on_time_rate'],
            relationship_score=vendor_data['score'],
            category=vendor_data['category'],
            recommendations=recommendations
        )
    
    def optimize_cash_flow(
        self,
        current_cash: float,
        forecast_days: int = 30
    ) -> CashOptimizationPlan:
        """
        אופטימיזציית תשלומים לתזרים
        Cash Flow Optimization
        """
        pending = self.get_pending_payments(
            to_date=date.today() + timedelta(days=forecast_days)
        )
        
        # מיון לפי ROI - הנחות גדולות קודם
        pending.sort(key=lambda x: (
            -x.discount_amount if x.discount_available else 0,
            x.days_until_due
        ))
        
        recommended = []
        deferred = []
        remaining = current_cash - self.cash_reserve_minimum
        total_savings = 0
        
        notes = []
        
        for payment in pending:
            # חייבים לשלם
            if payment.priority == PaymentPriority.CRITICAL:
                recommended.append(payment)
                remaining -= payment.amount
                continue
            
            # יש הנחה וכדאי?
            if payment.discount_available and remaining >= payment.amount:
                recommended.append(payment)
                remaining -= (payment.amount - payment.discount_amount)
                total_savings += payment.discount_amount
                continue
            
            # עדיפות גבוהה ויש מזומן
            if payment.priority in [PaymentPriority.HIGH] and remaining >= payment.amount:
                recommended.append(payment)
                remaining -= payment.amount
                continue
            
            # השאר - לדחות
            deferred.append(payment)
        
        # ציון אופטימיזציה
        total_pending = sum(p.amount for p in pending)
        paid_on_time = sum(p.amount for p in recommended if p.priority != PaymentPriority.CRITICAL)
        score = int((paid_on_time / total_pending * 100) if total_pending else 100)
        
        if total_savings > 0:
            notes.append(f"💰 חיסכון מהנחות: ₪{total_savings:,.0f}")
        
        if len(deferred) > 0:
            notes.append(f"⏳ {len(deferred)} תשלומים נדחו לשיפור התזרים")
        
        return CashOptimizationPlan(
            plan_date=date.today().isoformat(),
            current_cash=current_cash,
            total_payables=total_pending,
            recommended_payments=recommended,
            deferred_payments=deferred,
            total_recommended=sum(p.amount for p in recommended),
            total_deferred=sum(p.amount for p in deferred),
            expected_cash_after=remaining + self.cash_reserve_minimum,
            savings_from_discounts=total_savings,
            optimization_score=score,
            notes=notes
        )
    
    def _get_pending_invoices(self) -> List[Dict]:
        """שליפת חשבוניות ספק פתוחות מהדאטאבייס (יתרה > 0)."""
        rows = (
            self.db.query(Bill, Contact)
            .outerjoin(Contact, Bill.vendor_id == Contact.id)
            .filter(
                Bill.organization_id == self.organization_id,
                Bill.balance > 0,
            )
            .all()
        )
        invoices: List[Dict] = []
        for bill, vendor in rows:
            ref_date = bill.issue_date or bill.due_date or date.today()
            due_date = bill.due_date or ref_date
            invoices.append({
                'number': bill.bill_number or bill.external_id or f'BILL-{bill.id}',
                'vendor_id': str(bill.vendor_id) if bill.vendor_id else f'bill-{bill.id}',
                'vendor_name': (vendor.name if vendor else None) or 'ספק לא ידוע',
                'date': ref_date.isoformat(),
                'due_date': due_date.isoformat(),
                'amount': float(bill.balance or 0),
                'terms': 'שוטף+30',
                'discount_percent': 0,
                'discount_deadline': None,
            })
        return invoices

    def _get_book_transactions(self) -> List[Dict]:
        """תנועות תשלום אמיתיות מהספרים (תשלומים יוצאים לספקים)."""
        payments = (
            self.db.query(Payment)
            .filter(
                Payment.organization_id == self.organization_id,
                Payment.bill_id.isnot(None),
            )
            .all()
        )
        transactions: List[Dict] = []
        for p in payments:
            transactions.append({
                'date': p.payment_date.isoformat(),
                'description': p.reference or f'תשלום ספק {p.bill_id}',
                'amount': -float(p.amount or 0),  # תשלום יוצא = שלילי
                'reference': p.reference or f'PAY-{p.id}',
            })
        return transactions

    def _find_suggested_match(self, bank_item: Dict, book_items: List[Dict]) -> Optional[str]:
        """מציאת התאמה מוצעת"""
        for book in book_items:
            # התאמה קרובה בסכום
            if abs(bank_item['amount'] - book['amount']) < bank_item['amount'] * 0.05:
                return f"התאמה אפשרית: {book['description']} (₪{book['amount']})"
        return None
    
    def _get_vendor_data(self, vendor_id: str) -> Dict:
        """נתוני ספק אמיתיים מתוך חשבוניות הספק והתשלומים."""
        try:
            vid = int(vendor_id)
        except (TypeError, ValueError):
            vid = -1

        vendor = (
            self.db.query(Contact)
            .filter(
                Contact.organization_id == self.organization_id,
                Contact.id == vid,
            )
            .first()
        )
        bills = (
            self.db.query(Bill)
            .filter(
                Bill.organization_id == self.organization_id,
                Bill.vendor_id == vid,
            )
            .all()
        )
        total_purchases = float(sum((b.total or 0) for b in bills))
        total_paid = float(sum((b.paid_amount or 0) for b in bills))
        outstanding = float(sum((b.balance or 0) for b in bills))

        # זמן תשלום ושיעור תשלום בזמן
        days_to_pay: List[int] = []
        on_time = 0
        considered = 0
        for b in bills:
            if not b.due_date:
                continue
            pay = (
                self.db.query(Payment)
                .filter(
                    Payment.organization_id == self.organization_id,
                    Payment.bill_id == b.id,
                )
                .order_by(Payment.payment_date.desc())
                .first()
            )
            if not pay:
                continue
            considered += 1
            if b.issue_date:
                days_to_pay.append((pay.payment_date - b.issue_date).days)
            if pay.payment_date <= b.due_date:
                on_time += 1

        avg_days = sum(days_to_pay) / len(days_to_pay) if days_to_pay else 30
        on_time_rate = (on_time / considered) if considered else 0.8
        score = int(min(100, on_time_rate * 100))

        return {
            'name': vendor.name if vendor else f'ספק {vendor_id}',
            'total_purchases_ytd': total_purchases,
            'total_paid_ytd': total_paid,
            'outstanding': outstanding,
            'average_payment_days': avg_days,
            'terms': 'שוטף+30',
            'discount_captured': 0,
            'discount_missed': 0,
            'on_time_rate': on_time_rate,
            'score': score,
            'category': 'ספקים',
        }
