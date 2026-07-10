"""
Accounts Receivable Service - Aging & Collection
שירות ניהול חייבים - גיול חובות וגבייה
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models import Transaction, Account, Invoice, Contact, Payment
from ..database import SessionLocal


class AgingBucket(str, Enum):
    """קטגוריות גיול"""
    CURRENT = "current"      # 0-30 יום
    DAYS_31_60 = "31-60"     # 31-60 יום
    DAYS_61_90 = "61-90"     # 61-90 יום
    DAYS_91_120 = "91-120"   # 91-120 יום
    OVER_120 = "120+"        # מעל 120 יום


class CollectionStatus(str, Enum):
    """סטטוס גבייה"""
    NOT_STARTED = "not_started"
    REMINDER_SENT = "reminder_sent"
    SECOND_REMINDER = "second_reminder"
    PHONE_CONTACT = "phone_contact"
    PAYMENT_PLAN = "payment_plan"
    LEGAL_ACTION = "legal_action"
    WRITTEN_OFF = "written_off"
    COLLECTED = "collected"


class CreditRisk(str, Enum):
    """רמת סיכון אשראי"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CustomerAging:
    """גיול חובות לקוח"""
    customer_id: str
    customer_name: str
    current: float
    days_31_60: float
    days_61_90: float
    days_91_120: float
    over_120: float
    total_outstanding: float
    credit_limit: float
    credit_used_percentage: float
    credit_risk: CreditRisk
    oldest_invoice_date: str
    oldest_invoice_days: int
    last_payment_date: Optional[str]
    collection_status: CollectionStatus
    invoices: List[Dict] = field(default_factory=list)


@dataclass
class AgingReport:
    """דוח גיול חובות"""
    report_date: str
    total_receivables: float
    current_total: float
    days_31_60_total: float
    days_61_90_total: float
    days_91_120_total: float
    over_120_total: float
    weighted_average_days: float
    customers: List[CustomerAging]
    risk_summary: Dict
    collection_summary: Dict


@dataclass
class CollectionAction:
    """פעולת גבייה"""
    action_id: str
    customer_id: str
    customer_name: str
    action_type: str
    action_date: str
    due_date: Optional[str]
    amount: float
    status: str
    notes: str
    assigned_to: Optional[str]


@dataclass
class PaymentReminder:
    """תזכורת תשלום"""
    reminder_id: str
    customer_id: str
    customer_name: str
    customer_email: str
    invoice_numbers: List[str]
    total_amount: float
    days_overdue: int
    reminder_type: str  # first, second, final
    message: str
    scheduled_date: str
    sent_date: Optional[str]
    status: str


@dataclass
class CustomerCreditScore:
    """ניקוד אשראי לקוח"""
    customer_id: str
    customer_name: str
    credit_score: int  # 0-100
    credit_risk: CreditRisk
    credit_limit_recommended: float
    payment_history_score: int
    aging_score: int
    volume_score: int
    relationship_length_months: int
    average_days_to_pay: float
    on_time_payment_rate: float
    factors: Dict


class AccountsReceivableService:
    """
    שירות ניהול חייבים
    Accounts Receivable Management Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # תבניות הודעות
        self.reminder_templates = {
            'first': """
שלום {customer_name},

ברצוננו להזכירך כי חשבונית מספר {invoice_numbers} על סך ₪{amount:,.0f} טרם שולמה.
מועד הפירעון היה בתאריך {due_date}.

נשמח לקבל את התשלום בהקדם.

בברכה,
{company_name}
            """,
            'second': """
שלום {customer_name},

זוהי תזכורת שנייה בנוגע לחוב פתוח על סך ₪{amount:,.0f}.
החוב באיחור של {days_overdue} ימים.

חשבוניות: {invoice_numbers}

נא להסדיר את התשלום בהקדם האפשרי.

בברכה,
{company_name}
            """,
            'final': """
שלום {customer_name},

למרות פניותינו הקודמות, חשבונך על סך ₪{amount:,.0f} טרם הוסדר.
החוב באיחור של {days_overdue} ימים.

אנא שים לב: אם התשלום לא יתקבל תוך 7 ימים, נאלץ לנקוט בצעדים נוספים.

בברכה,
{company_name}
            """
        }
    
    def get_aging_report(
        self,
        as_of_date: Optional[date] = None,
        min_amount: float = 0
    ) -> AgingReport:
        """
        הפקת דוח גיול חובות
        Generate Aging Report
        """
        if not as_of_date:
            as_of_date = date.today()
        
        # שליפת חשבוניות פתוחות
        invoices = self._get_open_invoices()
        
        # חישוב גיול לכל לקוח
        customers_data = {}
        
        for inv in invoices:
            customer_id = inv['customer_id']
            if customer_id not in customers_data:
                customers_data[customer_id] = {
                    'customer_id': customer_id,
                    'customer_name': inv['customer_name'],
                    'invoices': [],
                    'current': 0,
                    'days_31_60': 0,
                    'days_61_90': 0,
                    'days_91_120': 0,
                    'over_120': 0
                }
            
            # חישוב ימי איחור
            invoice_date = datetime.strptime(inv['date'], '%Y-%m-%d').date()
            days_outstanding = (as_of_date - invoice_date).days
            amount = inv['amount']
            
            # שיוך לקטגוריית גיול
            if days_outstanding <= 30:
                customers_data[customer_id]['current'] += amount
                bucket = AgingBucket.CURRENT
            elif days_outstanding <= 60:
                customers_data[customer_id]['days_31_60'] += amount
                bucket = AgingBucket.DAYS_31_60
            elif days_outstanding <= 90:
                customers_data[customer_id]['days_61_90'] += amount
                bucket = AgingBucket.DAYS_61_90
            elif days_outstanding <= 120:
                customers_data[customer_id]['days_91_120'] += amount
                bucket = AgingBucket.DAYS_91_120
            else:
                customers_data[customer_id]['over_120'] += amount
                bucket = AgingBucket.OVER_120
            
            inv['days_outstanding'] = days_outstanding
            inv['aging_bucket'] = bucket.value
            customers_data[customer_id]['invoices'].append(inv)
        
        # בניית רשימת לקוחות
        customers = []
        for cust_id, data in customers_data.items():
            total = (data['current'] + data['days_31_60'] + 
                    data['days_61_90'] + data['days_91_120'] + data['over_120'])
            
            if total < min_amount:
                continue
            
            # חישוב סיכון אשראי
            if data['over_120'] > 0:
                risk = CreditRisk.CRITICAL
            elif data['days_91_120'] > 0:
                risk = CreditRisk.HIGH
            elif data['days_61_90'] > 0:
                risk = CreditRisk.MEDIUM
            else:
                risk = CreditRisk.LOW
            
            # מציאת חשבונית עתיקה ביותר
            oldest = min(data['invoices'], key=lambda x: x['date'])
            oldest_date = oldest['date']
            oldest_days = oldest['days_outstanding']
            
            # סטטוס גבייה
            if oldest_days > 90:
                collection_status = CollectionStatus.LEGAL_ACTION
            elif oldest_days > 60:
                collection_status = CollectionStatus.PHONE_CONTACT
            elif oldest_days > 30:
                collection_status = CollectionStatus.REMINDER_SENT
            else:
                collection_status = CollectionStatus.NOT_STARTED
            
            # מסגרת אשראי נגזרת מהתנהגות (לא מספר קבוע מזויף) + תאריך תשלום אחרון אמיתי.
            credit_limit = self._behavioral_credit_limit(cust_id)
            credit_used_pct = (total / credit_limit * 100) if credit_limit > 0 else 0.0
            customer = CustomerAging(
                customer_id=cust_id,
                customer_name=data['customer_name'],
                current=data['current'],
                days_31_60=data['days_31_60'],
                days_61_90=data['days_61_90'],
                days_91_120=data['days_91_120'],
                over_120=data['over_120'],
                total_outstanding=total,
                credit_limit=credit_limit,
                credit_used_percentage=round(credit_used_pct, 1),
                credit_risk=risk,
                oldest_invoice_date=oldest_date,
                oldest_invoice_days=oldest_days,
                last_payment_date=self._last_payment_date(cust_id),
                collection_status=collection_status,
                invoices=data['invoices']
            )
            customers.append(customer)
        
        # מיון לפי סכום יורד
        customers.sort(key=lambda x: x.total_outstanding, reverse=True)
        
        # סיכומים
        total_receivables = sum(c.total_outstanding for c in customers)
        current_total = sum(c.current for c in customers)
        days_31_60_total = sum(c.days_31_60 for c in customers)
        days_61_90_total = sum(c.days_61_90 for c in customers)
        days_91_120_total = sum(c.days_91_120 for c in customers)
        over_120_total = sum(c.over_120 for c in customers)
        
        # ממוצע ימי גיול משוקלל
        total_weighted_days = 0
        for c in customers:
            total_weighted_days += (
                c.current * 15 +
                c.days_31_60 * 45 +
                c.days_61_90 * 75 +
                c.days_91_120 * 105 +
                c.over_120 * 150
            )
        weighted_avg = total_weighted_days / total_receivables if total_receivables else 0
        
        # סיכום סיכונים
        risk_summary = {
            'low': len([c for c in customers if c.credit_risk == CreditRisk.LOW]),
            'medium': len([c for c in customers if c.credit_risk == CreditRisk.MEDIUM]),
            'high': len([c for c in customers if c.credit_risk == CreditRisk.HIGH]),
            'critical': len([c for c in customers if c.credit_risk == CreditRisk.CRITICAL]),
            'total_at_risk': sum(c.total_outstanding for c in customers if c.credit_risk in [CreditRisk.HIGH, CreditRisk.CRITICAL])
        }
        
        # סיכום גבייה
        collection_summary = {
            'not_started': len([c for c in customers if c.collection_status == CollectionStatus.NOT_STARTED]),
            'in_progress': len([c for c in customers if c.collection_status in [CollectionStatus.REMINDER_SENT, CollectionStatus.SECOND_REMINDER, CollectionStatus.PHONE_CONTACT]]),
            'escalated': len([c for c in customers if c.collection_status in [CollectionStatus.LEGAL_ACTION, CollectionStatus.PAYMENT_PLAN]]),
            'total_in_collection': sum(c.total_outstanding for c in customers if c.collection_status != CollectionStatus.NOT_STARTED)
        }
        
        return AgingReport(
            report_date=as_of_date.isoformat(),
            total_receivables=total_receivables,
            current_total=current_total,
            days_31_60_total=days_31_60_total,
            days_61_90_total=days_61_90_total,
            days_91_120_total=days_91_120_total,
            over_120_total=over_120_total,
            weighted_average_days=weighted_avg,
            customers=customers,
            risk_summary=risk_summary,
            collection_summary=collection_summary
        )
    
    def get_customer_credit_score(
        self,
        customer_id: str
    ) -> CustomerCreditScore:
        """
        חישוב ניקוד אשראי לקוח
        Calculate Customer Credit Score
        """
        # נתוני לקוח (בפרודקשן - מהDB)
        payment_history = self._get_payment_history(customer_id)
        
        # חישוב ציונים
        # 1. ציון היסטוריית תשלומים (40%)
        on_time_rate = payment_history.get('on_time_rate', 0.7)
        payment_score = int(on_time_rate * 100)
        
        # 2. ציון גיול (30%)
        aging = self._get_customer_aging_data(customer_id)
        if aging['over_120'] > 0:
            aging_score = 20
        elif aging['days_91_120'] > 0:
            aging_score = 40
        elif aging['days_61_90'] > 0:
            aging_score = 60
        elif aging['days_31_60'] > 0:
            aging_score = 80
        else:
            aging_score = 100
        
        # 3. ציון נפח עסקאות (20%)
        volume = payment_history.get('total_volume', 0)
        if volume > 500000:
            volume_score = 100
        elif volume > 200000:
            volume_score = 80
        elif volume > 50000:
            volume_score = 60
        else:
            volume_score = 40
        
        # 4. אורך הקשר (10%)
        months = payment_history.get('relationship_months', 6)
        relationship_score = min(100, months * 2)
        
        # ציון כולל
        total_score = int(
            payment_score * 0.4 +
            aging_score * 0.3 +
            volume_score * 0.2 +
            relationship_score * 0.1
        )
        
        # קביעת רמת סיכון
        if total_score >= 80:
            risk = CreditRisk.LOW
            credit_limit = 200000
        elif total_score >= 60:
            risk = CreditRisk.MEDIUM
            credit_limit = 100000
        elif total_score >= 40:
            risk = CreditRisk.HIGH
            credit_limit = 50000
        else:
            risk = CreditRisk.CRITICAL
            credit_limit = 0
        
        return CustomerCreditScore(
            customer_id=customer_id,
            customer_name=payment_history.get('customer_name', 'לקוח'),
            credit_score=total_score,
            credit_risk=risk,
            credit_limit_recommended=credit_limit,
            payment_history_score=payment_score,
            aging_score=aging_score,
            volume_score=volume_score,
            relationship_length_months=months,
            average_days_to_pay=payment_history.get('avg_days_to_pay', 30),
            on_time_payment_rate=on_time_rate,
            factors={
                'payment_history': f"{payment_score}/100 (משקל 40%)",
                'aging': f"{aging_score}/100 (משקל 30%)",
                'volume': f"{volume_score}/100 (משקל 20%)",
                'relationship': f"{relationship_score}/100 (משקל 10%)"
            }
        )
    
    def generate_payment_reminders(
        self,
        min_days_overdue: int = 7,
        reminder_type: str = 'auto'
    ) -> List[PaymentReminder]:
        """
        יצירת תזכורות תשלום
        Generate Payment Reminders
        """
        aging_report = self.get_aging_report()
        reminders = []
        
        for customer in aging_report.customers:
            if customer.oldest_invoice_days < min_days_overdue:
                continue
            
            # קביעת סוג תזכורת
            if reminder_type == 'auto':
                if customer.oldest_invoice_days > 60:
                    r_type = 'final'
                elif customer.oldest_invoice_days > 30:
                    r_type = 'second'
                else:
                    r_type = 'first'
            else:
                r_type = reminder_type
            
            # יצירת הודעה
            invoice_numbers = [inv['number'] for inv in customer.invoices]
            template = self.reminder_templates[r_type]
            message = template.format(
                customer_name=customer.customer_name,
                invoice_numbers=', '.join(invoice_numbers),
                amount=customer.total_outstanding,
                due_date=customer.oldest_invoice_date,
                days_overdue=customer.oldest_invoice_days,
                company_name='החברה שלי'
            )
            
            reminder = PaymentReminder(
                reminder_id=f"REM-{customer.customer_id}-{datetime.now().strftime('%Y%m%d')}",
                customer_id=customer.customer_id,
                customer_name=customer.customer_name,
                customer_email=(lambda c: c.email if c else None)(self._contact(customer.customer_id)),
                invoice_numbers=invoice_numbers,
                total_amount=customer.total_outstanding,
                days_overdue=customer.oldest_invoice_days,
                reminder_type=r_type,
                message=message.strip(),
                scheduled_date=date.today().isoformat(),
                sent_date=None,
                status='pending'
            )
            reminders.append(reminder)
        
        return reminders
    
    def get_collection_actions(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[CollectionAction]:
        """
        קבלת פעולות גבייה
        Get Collection Actions
        """
        aging_report = self.get_aging_report()
        actions = []
        
        for customer in aging_report.customers:
            if customer_id and customer.customer_id != customer_id:
                continue
            
            if customer.oldest_invoice_days <= 30:
                continue
            
            # קביעת פעולה נדרשת
            if customer.oldest_invoice_days > 90:
                action_type = 'legal_notice'
                action_status = 'urgent'
            elif customer.oldest_invoice_days > 60:
                action_type = 'phone_call'
                action_status = 'high_priority'
            else:
                action_type = 'email_reminder'
                action_status = 'pending'
            
            if status and action_status != status:
                continue
            
            action = CollectionAction(
                action_id=f"COL-{customer.customer_id}-{datetime.now().strftime('%Y%m%d')}",
                customer_id=customer.customer_id,
                customer_name=customer.customer_name,
                action_type=action_type,
                action_date=date.today().isoformat(),
                due_date=(date.today() + timedelta(days=7)).isoformat(),
                amount=customer.total_outstanding,
                status=action_status,
                notes=f"חוב באיחור של {customer.oldest_invoice_days} ימים",
                assigned_to=None
            )
            actions.append(action)
        
        return actions
    
    def get_dso_trend(self, months: int = 12, target_dso: int = 30) -> List[Dict]:
        """מגמת DSO אמיתית — ממוצע ימי-תשלום של חשבוניות ששולמו בכל חודש.

        DSO_m = ממוצע (תאריך תשלום − תאריך הפקה) על התשלומים שהתקבלו באותו חודש.
        חודש ללא תשלומים נושא את ה-DSO הידוע האחרון (carry-forward), ברירת מחדל היעד.
        """
        from calendar import monthrange
        today = date.today()
        trend: List[Dict] = []
        last_known = float(target_dso)

        # רשימת (חודש ראשון בחודש) אחורה מהיום.
        year, month = today.year, today.month
        periods: List[date] = []
        for _ in range(months):
            periods.append(date(year, month, 1))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods.reverse()

        for first in periods:
            last_day = date(first.year, first.month, monthrange(first.year, first.month)[1])
            rows = (
                self.db.query(Payment, Invoice)
                .join(Invoice, Payment.invoice_id == Invoice.id)
                .filter(
                    Payment.organization_id == self.organization_id,
                    Payment.payment_date >= first,
                    Payment.payment_date <= last_day,
                )
                .all()
            )
            days = [
                (pay.payment_date - inv.issue_date).days
                for pay, inv in rows
                if pay.payment_date and inv.issue_date
            ]
            if days:
                last_known = round(sum(days) / len(days), 1)
            dso = last_known
            trend.append({
                'month': first.strftime('%Y-%m'),
                'dso': dso,
                'target_dso': target_dso,
                'variance': round(dso - target_dso, 1),
                'sample': len(days),
            })

        return trend
    
    def _get_open_invoices(self) -> List[Dict]:
        """שליפת חשבוניות פתוחות מהדאטאבייס (יתרה > 0)."""
        rows = (
            self.db.query(Invoice, Contact)
            .outerjoin(Contact, Invoice.contact_id == Contact.id)
            .filter(
                Invoice.organization_id == self.organization_id,
                Invoice.balance > 0,
            )
            .all()
        )

        invoices: List[Dict] = []
        for inv, contact in rows:
            ref_date = inv.issue_date or inv.due_date or date.today()
            due_date = inv.due_date or ref_date
            invoices.append({
                'number': inv.invoice_number or inv.external_id or f'INV-{inv.id}',
                # חשבוניות ללא ספק משויך מקובצות תחת מזהה אחד כדי לא לפצל את הדוח
                'customer_id': str(inv.contact_id) if inv.contact_id else '0',
                'customer_name': (contact.name if contact else None) or 'לקוח לא ידוע',
                'date': ref_date.isoformat(),
                'due_date': due_date.isoformat(),
                'amount': float(inv.balance or 0),
            })
        return invoices

    def _get_payment_history(self, customer_id: str) -> Dict:
        """היסטוריית תשלומים אמיתית של לקוח מתוך החשבוניות והתשלומים."""
        contact = self._contact(customer_id)
        name = contact.name if contact else f'לקוח {customer_id}'

        invoices = (
            self.db.query(Invoice)
            .filter(
                Invoice.organization_id == self.organization_id,
                Invoice.contact_id == self._contact_id(customer_id),
            )
            .all()
        )
        total_volume = float(sum((inv.total or 0) for inv in invoices))

        # אורך הקשר בחודשים מאז החשבונית הראשונה
        issue_dates = [inv.issue_date for inv in invoices if inv.issue_date]
        if issue_dates:
            first = min(issue_dates)
            relationship_months = max(1, (date.today() - first).days // 30)
        else:
            relationship_months = 0

        # זמן תשלום בפועל ושיעור תשלום בזמן (מתוך חשבוניות ששולמו)
        days_to_pay: List[int] = []
        on_time = 0
        considered = 0
        for inv in invoices:
            if not inv.due_date:
                continue
            pay = (
                self.db.query(Payment)
                .filter(
                    Payment.organization_id == self.organization_id,
                    Payment.invoice_id == inv.id,
                )
                .order_by(Payment.payment_date.desc())
                .first()
            )
            if not pay:
                continue
            considered += 1
            if inv.issue_date:
                days_to_pay.append((pay.payment_date - inv.issue_date).days)
            if pay.payment_date <= inv.due_date:
                on_time += 1

        avg_days_to_pay = sum(days_to_pay) / len(days_to_pay) if days_to_pay else 30
        on_time_rate = (on_time / considered) if considered else 0.7

        return {
            'customer_name': name,
            'on_time_rate': on_time_rate,
            'total_volume': total_volume,
            'relationship_months': relationship_months,
            'avg_days_to_pay': avg_days_to_pay,
        }

    def _last_payment_date(self, customer_id: str) -> Optional[str]:
        """תאריך התשלום האחרון של הלקוח בפועל (מתוך רשומות התשלומים)."""
        cid = self._contact_id(customer_id)
        if not cid:
            return None
        pay = (
            self.db.query(Payment)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .filter(
                Payment.organization_id == self.organization_id,
                Invoice.contact_id == cid,
            )
            .order_by(Payment.payment_date.desc())
            .first()
        )
        return pay.payment_date.isoformat() if pay and pay.payment_date else None

    def _behavioral_credit_limit(self, customer_id: str) -> float:
        """מסגרת אשראי נגזרת מהתנהגות אמיתית: ~חודשיים מחזור, מתואם לשיעור תשלום בזמן.

        אין מסגרת מוגדרת במערכת, ולכן זו המלצה מבוססת-נתונים (לא מספר קבוע מזויף).
        """
        hist = self._get_payment_history(customer_id)
        months = max(1, hist.get('relationship_months') or 1)
        monthly_volume = (hist.get('total_volume') or 0) / months
        on_time = hist.get('on_time_rate', 0.7)
        # שני חודשי חשיפה, מתואם להתנהגות תשלום (0.5–1.0).
        limit = monthly_volume * 2 * (0.5 + 0.5 * on_time)
        return round(limit, 2)

    def _get_customer_aging_data(self, customer_id: str) -> Dict:
        """נתוני גיול אמיתיים ללקוח בודד מתוך חשבוניות פתוחות."""
        buckets = {
            'current': 0.0,
            'days_31_60': 0.0,
            'days_61_90': 0.0,
            'days_91_120': 0.0,
            'over_120': 0.0,
        }
        today = date.today()
        invoices = (
            self.db.query(Invoice)
            .filter(
                Invoice.organization_id == self.organization_id,
                Invoice.contact_id == self._contact_id(customer_id),
                Invoice.balance > 0,
            )
            .all()
        )
        for inv in invoices:
            ref_date = inv.issue_date or inv.due_date or today
            days = (today - ref_date).days
            amount = float(inv.balance or 0)
            if days <= 30:
                buckets['current'] += amount
            elif days <= 60:
                buckets['days_31_60'] += amount
            elif days <= 90:
                buckets['days_61_90'] += amount
            elif days <= 120:
                buckets['days_91_120'] += amount
            else:
                buckets['over_120'] += amount
        return buckets

    def _contact_id(self, customer_id: str):
        try:
            cid = int(customer_id)
            return None if cid == 0 else cid  # '0' is the sentinel for NULL-contact invoices
        except (TypeError, ValueError):
            return -1

    def _contact(self, customer_id: str) -> Optional[Contact]:
        return (
            self.db.query(Contact)
            .filter(
                Contact.organization_id == self.organization_id,
                Contact.id == self._contact_id(customer_id),
            )
            .first()
        )

    def get_invoices_status_report(self) -> Dict:
        """דוח סטטוס חשבוניות אמיתי מה-DB: שולם / חלקי / לא שולם."""
        invoices = (
            self.db.query(Invoice)
            .filter(Invoice.organization_id == self.organization_id)
            .all()
        )
        buckets = {
            "paid": {"count": 0, "total": 0.0, "balance": 0.0},
            "partial": {"count": 0, "total": 0.0, "balance": 0.0},
            "unpaid": {"count": 0, "total": 0.0, "balance": 0.0},
        }
        for inv in invoices:
            total = float(inv.total or 0)
            balance = float(inv.balance if inv.balance is not None else total)
            paid = float(inv.paid_amount or 0)
            if balance <= 0 and total > 0:
                key = "paid"
            elif paid > 0 and balance > 0:
                key = "partial"
            else:
                key = "unpaid"
            buckets[key]["count"] += 1
            buckets[key]["total"] += total
            buckets[key]["balance"] += balance
        for b in buckets.values():
            b["total"] = round(b["total"], 2)
            b["balance"] = round(b["balance"], 2)
        return {
            "invoice_count": len(invoices),
            "total_billed": round(sum(b["total"] for b in buckets.values()), 2),
            "total_outstanding": round(
                buckets["partial"]["balance"] + buckets["unpaid"]["balance"], 2
            ),
            "total_collected": round(
                sum(float(i.paid_amount or 0) for i in invoices), 2
            ),
            "by_status": buckets,
        }

    def get_collection_forecast(self, days: int = 90) -> Dict:
        """תחזית גבייה — סכום צפוי להיגבות לפי הסתברות גבייה לכל קטגוריית גיול."""
        report = self.get_aging_report()
        # הסתברות גבייה משוערת לפי ותק החוב
        probabilities = {
            'current': 0.95,
            'days_31_60': 0.85,
            'days_61_90': 0.70,
            'days_91_120': 0.50,
            'over_120': 0.25,
        }
        expected = (
            report.current_total * probabilities['current']
            + report.days_31_60_total * probabilities['days_31_60']
            + report.days_61_90_total * probabilities['days_61_90']
            + report.days_91_120_total * probabilities['days_91_120']
            + report.over_120_total * probabilities['over_120']
        )
        return {
            'forecast_days': days,
            'total_outstanding': report.total_receivables,
            'expected_collection': round(expected, 2),
            'expected_collection_rate': (
                round(expected / report.total_receivables, 4)
                if report.total_receivables else 0
            ),
            'at_risk_amount': round(report.total_receivables - expected, 2),
            'by_bucket': {
                'current': round(report.current_total * probabilities['current'], 2),
                'days_31_60': round(report.days_31_60_total * probabilities['days_31_60'], 2),
                'days_61_90': round(report.days_61_90_total * probabilities['days_61_90'], 2),
                'days_91_120': round(report.days_91_120_total * probabilities['days_91_120'], 2),
                'over_120': round(report.over_120_total * probabilities['over_120'], 2),
            },
        }
