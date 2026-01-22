"""
Agreement-based Cash Flow Service
שירות תזרים מזומנים מבוסס הסכמים
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
from sqlalchemy.orm import Session
import numpy as np

from ..database import SessionLocal
from ..config import settings
from ..integrations.sumit_integration import SumitIntegration


class AgreementType(str, Enum):
    """סוג הסכם"""
    SUBSCRIPTION = "subscription"  # מנוי
    RETAINER = "retainer"  # ריטיינר
    PROJECT = "project"  # פרויקט
    SERVICE = "service"  # שירות
    LICENSE = "license"  # רישיון
    MAINTENANCE = "maintenance"  # תחזוקה
    LEASE = "lease"  # השכרה
    CONSULTING = "consulting"  # ייעוץ


class AgreementStatus(str, Enum):
    """סטטוס הסכם"""
    DRAFT = "draft"  # טיוטה
    PENDING = "pending"  # ממתין לאישור
    ACTIVE = "active"  # פעיל
    PAUSED = "paused"  # מושהה
    COMPLETED = "completed"  # הושלם
    CANCELLED = "cancelled"  # בוטל
    EXPIRED = "expired"  # פג תוקף


class BillingCycle(str, Enum):
    """מחזור חיוב"""
    ONE_TIME = "one_time"  # חד-פעמי
    WEEKLY = "weekly"  # שבועי
    BI_WEEKLY = "bi_weekly"  # דו-שבועי
    MONTHLY = "monthly"  # חודשי
    QUARTERLY = "quarterly"  # רבעוני
    SEMI_ANNUAL = "semi_annual"  # חצי-שנתי
    ANNUAL = "annual"  # שנתי


class CashFlowType(str, Enum):
    """סוג תזרים"""
    INFLOW = "inflow"  # כניסה
    OUTFLOW = "outflow"  # יציאה


@dataclass
class AgreementMilestone:
    """אבן דרך בהסכם"""
    milestone_id: str
    name: str
    amount: float
    due_date: str
    status: str  # pending, invoiced, paid
    invoice_id: Optional[str] = None
    payment_date: Optional[str] = None


@dataclass
class Agreement:
    """הסכם"""
    agreement_id: str
    customer_id: str
    customer_name: str
    agreement_type: AgreementType
    title: str
    description: str
    total_value: float
    currency: str
    billing_cycle: BillingCycle
    billing_amount: float
    start_date: str
    end_date: Optional[str]
    status: AgreementStatus
    created_at: str
    updated_at: str
    auto_renew: bool = False
    payment_terms_days: int = 30
    milestones: List[AgreementMilestone] = field(default_factory=list)
    invoiced_total: float = 0.0
    paid_total: float = 0.0
    notes: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class CashFlowEntry:
    """רשומת תזרים מזומנים"""
    entry_id: str
    date: str
    flow_type: CashFlowType
    amount: float
    currency: str
    category: str
    source: str  # agreement, invoice, forecast, etc.
    source_id: Optional[str]
    description: str
    is_actual: bool  # True = בפועל, False = צפי
    probability: float = 1.0  # הסתברות (לצפי)
    actual_date: Optional[str] = None
    actual_amount: Optional[float] = None


@dataclass
class CashFlowProjection:
    """תחזית תזרים מזומנים"""
    period: str  # YYYY-MM
    inflows: List[CashFlowEntry]
    outflows: List[CashFlowEntry]
    total_inflows: float
    total_outflows: float
    net_flow: float
    opening_balance: float
    closing_balance: float
    weighted_inflows: float  # משוקלל בהסתברות
    weighted_outflows: float


@dataclass
class CashFlowSummary:
    """סיכום תזרים מזומנים"""
    period_start: str
    period_end: str
    total_periods: int
    
    # סיכומים
    total_inflows: float
    total_outflows: float
    net_change: float
    
    # ממוצעים
    avg_monthly_inflow: float
    avg_monthly_outflow: float
    avg_monthly_net: float
    
    # מקורות הכנסה
    income_by_source: Dict[str, float]
    income_by_agreement_type: Dict[str, float]
    
    # יציאות
    outflows_by_category: Dict[str, float]
    
    # תחזיות
    projections: List[CashFlowProjection]
    
    # ניתוח
    min_balance: float
    max_balance: float
    low_balance_months: List[str]
    
    # חשבוניות פתוחות
    outstanding_invoices_total: float
    outstanding_invoices_count: int
    overdue_invoices_total: float
    overdue_invoices_count: int


class AgreementCashFlowService:
    """
    שירות תזרים מזומנים מבוסס הסכמים
    Agreement-based Cash Flow Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # אחסון זמני (בפרודקשן - database)
        self._agreements: Dict[str, Agreement] = {}
        self._cash_flow_entries: List[CashFlowEntry] = []
    
    # ==================== Agreement Management ====================
    
    async def create_agreement(
        self,
        customer_id: str,
        customer_name: str,
        agreement_type: AgreementType,
        title: str,
        total_value: float,
        billing_cycle: BillingCycle,
        start_date: date,
        end_date: Optional[date] = None,
        description: str = "",
        auto_renew: bool = False,
        payment_terms_days: int = 30,
        milestones: Optional[List[Dict]] = None
    ) -> Agreement:
        """
        יצירת הסכם
        Create Agreement
        """
        agreement_id = f"AGR-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now()
        
        # חישוב סכום חיוב לפי מחזור
        billing_amount = self._calculate_billing_amount(
            total_value, billing_cycle, start_date, end_date
        )
        
        agreement = Agreement(
            agreement_id=agreement_id,
            customer_id=customer_id,
            customer_name=customer_name,
            agreement_type=agreement_type,
            title=title,
            description=description,
            total_value=total_value,
            currency="ILS",
            billing_cycle=billing_cycle,
            billing_amount=billing_amount,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat() if end_date else None,
            status=AgreementStatus.ACTIVE,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            auto_renew=auto_renew,
            payment_terms_days=payment_terms_days
        )
        
        # הוספת אבני דרך
        if milestones:
            for m in milestones:
                milestone = AgreementMilestone(
                    milestone_id=f"MS-{uuid.uuid4().hex[:8].upper()}",
                    name=m['name'],
                    amount=m['amount'],
                    due_date=m['due_date'],
                    status='pending'
                )
                agreement.milestones.append(milestone)
        
        self._agreements[agreement_id] = agreement
        
        # יצירת רשומות תזרים עתידיות
        await self._generate_cash_flow_entries(agreement)
        
        return agreement
    
    async def update_agreement(
        self,
        agreement_id: str,
        **updates
    ) -> Agreement:
        """
        עדכון הסכם
        Update Agreement
        """
        agreement = self._agreements.get(agreement_id)
        if not agreement:
            raise ValueError(f"הסכם {agreement_id} לא נמצא")
        
        for key, value in updates.items():
            if hasattr(agreement, key):
                setattr(agreement, key, value)
        
        agreement.updated_at = datetime.now().isoformat()
        
        # עדכון תזרים
        await self._regenerate_cash_flow_entries(agreement)
        
        return agreement
    
    async def cancel_agreement(
        self,
        agreement_id: str,
        reason: str = ""
    ) -> Agreement:
        """
        ביטול הסכם
        Cancel Agreement
        """
        agreement = self._agreements.get(agreement_id)
        if not agreement:
            raise ValueError(f"הסכם {agreement_id} לא נמצא")
        
        agreement.status = AgreementStatus.CANCELLED
        agreement.updated_at = datetime.now().isoformat()
        
        # הסרת רשומות תזרים עתידיות
        self._cash_flow_entries = [
            e for e in self._cash_flow_entries
            if not (e.source_id == agreement_id and not e.is_actual)
        ]
        
        return agreement
    
    async def list_agreements(
        self,
        customer_id: Optional[str] = None,
        agreement_type: Optional[AgreementType] = None,
        status: Optional[AgreementStatus] = None
    ) -> List[Agreement]:
        """רשימת הסכמים"""
        agreements = list(self._agreements.values())
        
        if customer_id:
            agreements = [a for a in agreements if a.customer_id == customer_id]
        if agreement_type:
            agreements = [a for a in agreements if a.agreement_type == agreement_type]
        if status:
            agreements = [a for a in agreements if a.status == status]
        
        return sorted(agreements, key=lambda x: x.start_date, reverse=True)
    
    def _calculate_billing_amount(
        self,
        total_value: float,
        billing_cycle: BillingCycle,
        start_date: date,
        end_date: Optional[date]
    ) -> float:
        """חישוב סכום חיוב"""
        if billing_cycle == BillingCycle.ONE_TIME:
            return total_value
        
        if not end_date:
            # הסכם ללא תאריך סיום - חישוב לפי סוג מחזור
            cycles_per_year = {
                BillingCycle.WEEKLY: 52,
                BillingCycle.BI_WEEKLY: 26,
                BillingCycle.MONTHLY: 12,
                BillingCycle.QUARTERLY: 4,
                BillingCycle.SEMI_ANNUAL: 2,
                BillingCycle.ANNUAL: 1
            }
            return total_value / cycles_per_year.get(billing_cycle, 12)
        
        # חישוב מספר מחזורים
        days = (end_date - start_date).days
        
        cycle_days = {
            BillingCycle.WEEKLY: 7,
            BillingCycle.BI_WEEKLY: 14,
            BillingCycle.MONTHLY: 30,
            BillingCycle.QUARTERLY: 90,
            BillingCycle.SEMI_ANNUAL: 180,
            BillingCycle.ANNUAL: 365
        }
        
        num_cycles = max(1, days // cycle_days.get(billing_cycle, 30))
        return total_value / num_cycles
    
    async def _generate_cash_flow_entries(self, agreement: Agreement):
        """יצירת רשומות תזרים מהסכם"""
        if agreement.billing_cycle == BillingCycle.ONE_TIME:
            # חיוב חד-פעמי
            entry = CashFlowEntry(
                entry_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
                date=agreement.start_date,
                flow_type=CashFlowType.INFLOW,
                amount=agreement.total_value,
                currency=agreement.currency,
                category=agreement.agreement_type.value,
                source='agreement',
                source_id=agreement.agreement_id,
                description=f"{agreement.title} - {agreement.customer_name}",
                is_actual=False,
                probability=0.95
            )
            self._cash_flow_entries.append(entry)
        else:
            # חיובים חוזרים
            billing_dates = self._get_billing_dates(
                date.fromisoformat(agreement.start_date),
                date.fromisoformat(agreement.end_date) if agreement.end_date else date.today() + timedelta(days=365),
                agreement.billing_cycle
            )
            
            for billing_date in billing_dates:
                # הוספת ימי אשראי
                expected_payment_date = billing_date + timedelta(days=agreement.payment_terms_days)
                
                entry = CashFlowEntry(
                    entry_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
                    date=expected_payment_date.isoformat(),
                    flow_type=CashFlowType.INFLOW,
                    amount=agreement.billing_amount,
                    currency=agreement.currency,
                    category=agreement.agreement_type.value,
                    source='agreement',
                    source_id=agreement.agreement_id,
                    description=f"{agreement.title} - {agreement.customer_name}",
                    is_actual=False,
                    probability=0.9
                )
                self._cash_flow_entries.append(entry)
        
        # אבני דרך
        for milestone in agreement.milestones:
            entry = CashFlowEntry(
                entry_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
                date=milestone.due_date,
                flow_type=CashFlowType.INFLOW,
                amount=milestone.amount,
                currency=agreement.currency,
                category='milestone',
                source='milestone',
                source_id=milestone.milestone_id,
                description=f"{milestone.name} - {agreement.customer_name}",
                is_actual=False,
                probability=0.85
            )
            self._cash_flow_entries.append(entry)
    
    async def _regenerate_cash_flow_entries(self, agreement: Agreement):
        """רענון רשומות תזרים"""
        # הסרת רשומות ישנות (לא בפועל)
        self._cash_flow_entries = [
            e for e in self._cash_flow_entries
            if not (e.source_id == agreement.agreement_id and not e.is_actual)
        ]
        
        # יצירת חדשות
        if agreement.status == AgreementStatus.ACTIVE:
            await self._generate_cash_flow_entries(agreement)
    
    def _get_billing_dates(
        self,
        start: date,
        end: date,
        cycle: BillingCycle
    ) -> List[date]:
        """קבלת תאריכי חיוב"""
        dates = []
        current = start
        
        while current <= end:
            dates.append(current)
            
            if cycle == BillingCycle.WEEKLY:
                current += timedelta(weeks=1)
            elif cycle == BillingCycle.BI_WEEKLY:
                current += timedelta(weeks=2)
            elif cycle == BillingCycle.MONTHLY:
                current = self._add_months(current, 1)
            elif cycle == BillingCycle.QUARTERLY:
                current = self._add_months(current, 3)
            elif cycle == BillingCycle.SEMI_ANNUAL:
                current = self._add_months(current, 6)
            elif cycle == BillingCycle.ANNUAL:
                current = self._add_months(current, 12)
            else:
                break
        
        return dates
    
    def _add_months(self, d: date, months: int) -> date:
        """הוספת חודשים לתאריך"""
        month = d.month + months
        year = d.year
        while month > 12:
            month -= 12
            year += 1
        day = min(d.day, 28)
        return date(year, month, day)
    
    # ==================== Outstanding Invoices ====================
    
    async def sync_outstanding_invoices(self) -> List[CashFlowEntry]:
        """
        סנכרון חשבוניות פתוחות מ-SUMIT
        Sync Outstanding Invoices from SUMIT
        """
        entries = []
        
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                # קבלת חשבוניות פתוחות
                documents = await sumit.list_documents(
                    type_filter="invoice",
                    status_filter="open",
                    from_date=date.today() - timedelta(days=365),
                    to_date=date.today()
                )
                
                for doc in documents:
                    # חישוב תאריך תשלום צפוי
                    issue_date = date.fromisoformat(doc.date)
                    expected_payment = issue_date + timedelta(days=30)
                    
                    # הערכת הסתברות לפי גיל
                    days_old = (date.today() - issue_date).days
                    if days_old <= 30:
                        probability = 0.95
                    elif days_old <= 60:
                        probability = 0.80
                    elif days_old <= 90:
                        probability = 0.60
                    else:
                        probability = 0.40
                    
                    entry = CashFlowEntry(
                        entry_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
                        date=expected_payment.isoformat(),
                        flow_type=CashFlowType.INFLOW,
                        amount=float(doc.balance) if hasattr(doc, 'balance') else float(doc.total),
                        currency=doc.currency,
                        category='invoice',
                        source='sumit_invoice',
                        source_id=doc.document_id,
                        description=f"חשבונית {doc.document_number} - {doc.customer_name}",
                        is_actual=False,
                        probability=probability
                    )
                    entries.append(entry)
                    self._cash_flow_entries.append(entry)
                    
        except Exception as e:
            # במקרה של שגיאה, נחזיר רשימה ריקה
            pass
        
        return entries
    
    async def add_expected_expense(
        self,
        amount: float,
        date: date,
        category: str,
        description: str,
        probability: float = 1.0
    ) -> CashFlowEntry:
        """
        הוספת הוצאה צפויה
        Add Expected Expense
        """
        entry = CashFlowEntry(
            entry_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
            date=date.isoformat(),
            flow_type=CashFlowType.OUTFLOW,
            amount=amount,
            currency="ILS",
            category=category,
            source='manual',
            source_id=None,
            description=description,
            is_actual=False,
            probability=probability
        )
        
        self._cash_flow_entries.append(entry)
        return entry
    
    async def record_actual_transaction(
        self,
        amount: float,
        date: date,
        flow_type: CashFlowType,
        category: str,
        description: str,
        source_id: Optional[str] = None
    ) -> CashFlowEntry:
        """
        רישום עסקה בפועל
        Record Actual Transaction
        """
        entry = CashFlowEntry(
            entry_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
            date=date.isoformat(),
            flow_type=flow_type,
            amount=amount,
            currency="ILS",
            category=category,
            source='actual',
            source_id=source_id,
            description=description,
            is_actual=True,
            probability=1.0,
            actual_date=date.isoformat(),
            actual_amount=amount
        )
        
        self._cash_flow_entries.append(entry)
        return entry
    
    # ==================== Cash Flow Analysis ====================
    
    async def get_cash_flow_projection(
        self,
        start_date: date,
        periods: int = 12,  # חודשים
        opening_balance: float = 0.0
    ) -> List[CashFlowProjection]:
        """
        תחזית תזרים מזומנים
        Cash Flow Projection
        """
        projections = []
        balance = opening_balance
        
        for i in range(periods):
            period_start = self._add_months(start_date, i)
            period_end = self._add_months(start_date, i + 1) - timedelta(days=1)
            period_key = period_start.strftime("%Y-%m")
            
            # סינון רשומות לתקופה
            period_entries = [
                e for e in self._cash_flow_entries
                if period_start.isoformat() <= e.date <= period_end.isoformat()
            ]
            
            inflows = [e for e in period_entries if e.flow_type == CashFlowType.INFLOW]
            outflows = [e for e in period_entries if e.flow_type == CashFlowType.OUTFLOW]
            
            total_inflows = sum(e.amount for e in inflows)
            total_outflows = sum(e.amount for e in outflows)
            
            # סכומים משוקללים בהסתברות
            weighted_inflows = sum(e.amount * e.probability for e in inflows)
            weighted_outflows = sum(e.amount * e.probability for e in outflows)
            
            net_flow = total_inflows - total_outflows
            closing_balance = balance + (weighted_inflows - weighted_outflows)
            
            projection = CashFlowProjection(
                period=period_key,
                inflows=inflows,
                outflows=outflows,
                total_inflows=total_inflows,
                total_outflows=total_outflows,
                net_flow=net_flow,
                opening_balance=balance,
                closing_balance=closing_balance,
                weighted_inflows=weighted_inflows,
                weighted_outflows=weighted_outflows
            )
            
            projections.append(projection)
            balance = closing_balance
        
        return projections
    
    async def get_cash_flow_summary(
        self,
        start_date: date,
        periods: int = 12,
        opening_balance: float = 0.0
    ) -> CashFlowSummary:
        """
        סיכום תזרים מזומנים
        Cash Flow Summary
        """
        projections = await self.get_cash_flow_projection(start_date, periods, opening_balance)
        
        total_inflows = sum(p.total_inflows for p in projections)
        total_outflows = sum(p.total_outflows for p in projections)
        
        # הכנסות לפי מקור
        income_by_source: Dict[str, float] = {}
        income_by_type: Dict[str, float] = {}
        outflows_by_category: Dict[str, float] = {}
        
        for p in projections:
            for entry in p.inflows:
                income_by_source[entry.source] = income_by_source.get(entry.source, 0) + entry.amount
                income_by_type[entry.category] = income_by_type.get(entry.category, 0) + entry.amount
            
            for entry in p.outflows:
                outflows_by_category[entry.category] = outflows_by_category.get(entry.category, 0) + entry.amount
        
        # איתור חודשים עם יתרה נמוכה
        balances = [p.closing_balance for p in projections]
        min_balance = min(balances) if balances else 0
        max_balance = max(balances) if balances else 0
        
        # חודשים עם יתרה נמוכה (פחות מ-0 או מתחת לסף)
        low_balance_months = [
            p.period for p in projections
            if p.closing_balance < 0
        ]
        
        # חשבוניות פתוחות
        outstanding_entries = [
            e for e in self._cash_flow_entries
            if e.source == 'sumit_invoice' and not e.is_actual
        ]
        
        today = date.today().isoformat()
        overdue_entries = [
            e for e in outstanding_entries
            if e.date < today
        ]
        
        return CashFlowSummary(
            period_start=start_date.isoformat(),
            period_end=self._add_months(start_date, periods).isoformat(),
            total_periods=periods,
            total_inflows=total_inflows,
            total_outflows=total_outflows,
            net_change=total_inflows - total_outflows,
            avg_monthly_inflow=total_inflows / periods if periods > 0 else 0,
            avg_monthly_outflow=total_outflows / periods if periods > 0 else 0,
            avg_monthly_net=(total_inflows - total_outflows) / periods if periods > 0 else 0,
            income_by_source=income_by_source,
            income_by_agreement_type=income_by_type,
            outflows_by_category=outflows_by_category,
            projections=projections,
            min_balance=min_balance,
            max_balance=max_balance,
            low_balance_months=low_balance_months,
            outstanding_invoices_total=sum(e.amount for e in outstanding_entries),
            outstanding_invoices_count=len(outstanding_entries),
            overdue_invoices_total=sum(e.amount for e in overdue_entries),
            overdue_invoices_count=len(overdue_entries)
        )
    
    # ==================== Forecasting ====================
    
    async def forecast_cash_flow(
        self,
        historical_months: int = 12,
        forecast_months: int = 6,
        method: str = 'exponential_smoothing'
    ) -> Dict[str, Any]:
        """
        חיזוי תזרים מזומנים
        Forecast Cash Flow
        """
        # איסוף נתונים היסטוריים
        historical = await self._get_historical_data(historical_months)
        
        if len(historical['monthly_inflows']) < 3:
            return {
                'error': 'לא מספיק נתונים היסטוריים לחיזוי',
                'required_months': 3,
                'available_months': len(historical['monthly_inflows'])
            }
        
        # חיזוי
        inflow_forecast = self._forecast_series(
            historical['monthly_inflows'],
            forecast_months,
            method
        )
        
        outflow_forecast = self._forecast_series(
            historical['monthly_outflows'],
            forecast_months,
            method
        )
        
        # חישוב תזרים נטו
        net_forecast = [
            inflow_forecast[i] - outflow_forecast[i]
            for i in range(forecast_months)
        ]
        
        # תאריכים
        start = date.today().replace(day=1)
        forecast_dates = [
            self._add_months(start, i).strftime("%Y-%m")
            for i in range(1, forecast_months + 1)
        ]
        
        return {
            'method': method,
            'historical_months': historical_months,
            'forecast_months': forecast_months,
            'dates': forecast_dates,
            'inflows': {
                'forecast': inflow_forecast,
                'confidence_lower': [v * 0.85 for v in inflow_forecast],
                'confidence_upper': [v * 1.15 for v in inflow_forecast]
            },
            'outflows': {
                'forecast': outflow_forecast,
                'confidence_lower': [v * 0.90 for v in outflow_forecast],
                'confidence_upper': [v * 1.10 for v in outflow_forecast]
            },
            'net_cash_flow': {
                'forecast': net_forecast,
                'trend': 'up' if net_forecast[-1] > net_forecast[0] else 'down'
            },
            'metrics': {
                'total_forecast_inflow': sum(inflow_forecast),
                'total_forecast_outflow': sum(outflow_forecast),
                'avg_monthly_net': sum(net_forecast) / forecast_months,
                'best_month': forecast_dates[net_forecast.index(max(net_forecast))],
                'worst_month': forecast_dates[net_forecast.index(min(net_forecast))]
            }
        }
    
    async def _get_historical_data(self, months: int) -> Dict:
        """קבלת נתונים היסטוריים"""
        monthly_inflows: List[float] = []
        monthly_outflows: List[float] = []
        
        today = date.today()
        
        for i in range(months, 0, -1):
            period_start = self._add_months(today, -i)
            period_end = self._add_months(today, -i + 1) - timedelta(days=1)
            
            period_entries = [
                e for e in self._cash_flow_entries
                if period_start.isoformat() <= e.date <= period_end.isoformat()
                and e.is_actual
            ]
            
            inflows = sum(e.amount for e in period_entries if e.flow_type == CashFlowType.INFLOW)
            outflows = sum(e.amount for e in period_entries if e.flow_type == CashFlowType.OUTFLOW)
            
            monthly_inflows.append(inflows)
            monthly_outflows.append(outflows)
        
        return {
            'monthly_inflows': monthly_inflows,
            'monthly_outflows': monthly_outflows
        }
    
    def _forecast_series(
        self,
        data: List[float],
        periods: int,
        method: str
    ) -> List[float]:
        """חיזוי סדרה"""
        if method == 'exponential_smoothing':
            return self._exponential_smoothing(data, periods)
        elif method == 'moving_average':
            return self._moving_average(data, periods)
        elif method == 'linear_regression':
            return self._linear_regression(data, periods)
        else:
            return self._exponential_smoothing(data, periods)
    
    def _exponential_smoothing(
        self,
        data: List[float],
        periods: int,
        alpha: float = 0.3
    ) -> List[float]:
        """החלקה אקספוננציאלית"""
        if not data:
            return [0.0] * periods
        
        forecast = []
        smoothed = data[0]
        
        for value in data[1:]:
            smoothed = alpha * value + (1 - alpha) * smoothed
        
        for _ in range(periods):
            forecast.append(smoothed)
        
        return forecast
    
    def _moving_average(
        self,
        data: List[float],
        periods: int,
        window: int = 3
    ) -> List[float]:
        """ממוצע נע"""
        if not data:
            return [0.0] * periods
        
        if len(data) < window:
            window = len(data)
        
        avg = sum(data[-window:]) / window
        return [avg] * periods
    
    def _linear_regression(
        self,
        data: List[float],
        periods: int
    ) -> List[float]:
        """רגרסיה ליניארית"""
        if len(data) < 2:
            return [data[0] if data else 0.0] * periods
        
        n = len(data)
        x = list(range(n))
        
        x_mean = sum(x) / n
        y_mean = sum(data) / n
        
        numerator = sum((x[i] - x_mean) * (data[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return [y_mean] * periods
        
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        
        forecast = []
        for i in range(n, n + periods):
            forecast.append(intercept + slope * i)
        
        return forecast
    
    # ==================== Analysis ====================
    
    async def analyze_payment_patterns(
        self,
        customer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        ניתוח דפוסי תשלום
        Analyze Payment Patterns
        """
        # סינון רשומות
        entries = [
            e for e in self._cash_flow_entries
            if e.is_actual and e.flow_type == CashFlowType.INFLOW
        ]
        
        if customer_id:
            # נצטרך לשלוף את הלקוח מההסכמים
            customer_agreements = [
                a.agreement_id for a in self._agreements.values()
                if a.customer_id == customer_id
            ]
            entries = [e for e in entries if e.source_id in customer_agreements]
        
        if not entries:
            return {'message': 'אין מספיק נתונים לניתוח'}
        
        # ניתוח
        amounts = [e.amount for e in entries]
        
        return {
            'total_payments': len(entries),
            'total_amount': sum(amounts),
            'avg_payment': sum(amounts) / len(amounts),
            'min_payment': min(amounts),
            'max_payment': max(amounts),
            'by_category': self._group_by_category(entries),
            'by_source': self._group_by_source(entries),
            'monthly_trend': self._calculate_monthly_trend(entries)
        }
    
    def _group_by_category(self, entries: List[CashFlowEntry]) -> Dict[str, float]:
        """קיבוץ לפי קטגוריה"""
        result: Dict[str, float] = {}
        for e in entries:
            result[e.category] = result.get(e.category, 0) + e.amount
        return result
    
    def _group_by_source(self, entries: List[CashFlowEntry]) -> Dict[str, float]:
        """קיבוץ לפי מקור"""
        result: Dict[str, float] = {}
        for e in entries:
            result[e.source] = result.get(e.source, 0) + e.amount
        return result
    
    def _calculate_monthly_trend(self, entries: List[CashFlowEntry]) -> List[Dict]:
        """חישוב מגמה חודשית"""
        monthly: Dict[str, float] = {}
        
        for e in entries:
            month = e.date[:7]  # YYYY-MM
            monthly[month] = monthly.get(month, 0) + e.amount
        
        return [
            {'month': month, 'total': total}
            for month, total in sorted(monthly.items())
        ]
    
    async def get_agreement_revenue_summary(self) -> Dict[str, Any]:
        """
        סיכום הכנסות מהסכמים
        Agreement Revenue Summary
        """
        active = [a for a in self._agreements.values() if a.status == AgreementStatus.ACTIVE]
        
        by_type: Dict[str, Dict] = {}
        for a in active:
            atype = a.agreement_type.value
            if atype not in by_type:
                by_type[atype] = {'count': 0, 'value': 0, 'monthly': 0}
            
            by_type[atype]['count'] += 1
            by_type[atype]['value'] += a.total_value
            by_type[atype]['monthly'] += a.billing_amount if a.billing_cycle != BillingCycle.ONE_TIME else 0
        
        return {
            'total_agreements': len(active),
            'total_value': sum(a.total_value for a in active),
            'monthly_recurring': sum(
                a.billing_amount for a in active
                if a.billing_cycle not in [BillingCycle.ONE_TIME]
            ),
            'by_type': by_type,
            'by_customer': self._group_agreements_by_customer(active),
            'expiring_soon': [
                {
                    'agreement_id': a.agreement_id,
                    'title': a.title,
                    'customer_name': a.customer_name,
                    'end_date': a.end_date,
                    'value': a.total_value
                }
                for a in active
                if a.end_date and date.fromisoformat(a.end_date) <= date.today() + timedelta(days=60)
            ]
        }
    
    def _group_agreements_by_customer(self, agreements: List[Agreement]) -> List[Dict]:
        """קיבוץ הסכמים לפי לקוח"""
        by_customer: Dict[str, Dict] = {}
        
        for a in agreements:
            if a.customer_id not in by_customer:
                by_customer[a.customer_id] = {
                    'customer_id': a.customer_id,
                    'customer_name': a.customer_name,
                    'count': 0,
                    'total_value': 0
                }
            
            by_customer[a.customer_id]['count'] += 1
            by_customer[a.customer_id]['total_value'] += a.total_value
        
        return sorted(
            list(by_customer.values()),
            key=lambda x: x['total_value'],
            reverse=True
        )
