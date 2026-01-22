"""
Payment Request Service
שירות בקשות תשלום והוראות קבע
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import json
import uuid
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..config import settings
from ..integrations.sumit_integration import SumitIntegration
from ..integrations.sumit_models import (
    ChargeRequest, PaymentResponse, PaymentMethodCard,
    RecurringPaymentRequest, RecurringPaymentResponse,
    TransactionRequest, TokenizeCardRequest
)


class PaymentRequestStatus(str, Enum):
    """סטטוס בקשת תשלום"""
    DRAFT = "draft"  # טיוטה
    SENT = "sent"  # נשלחה
    OPENED = "opened"  # נפתחה
    PARTIAL = "partial"  # שולמה חלקית
    COMPLETED = "completed"  # שולמה
    CANCELLED = "cancelled"  # בוטלה
    EXPIRED = "expired"  # פג תוקף
    FAILED = "failed"  # נכשלה


class PaymentMethod(str, Enum):
    """אמצעי תשלום"""
    CREDIT_CARD = "credit_card"  # כרטיס אשראי
    BANK_TRANSFER = "bank_transfer"  # העברה בנקאית
    CHECK = "check"  # המחאה
    CASH = "cash"  # מזומן
    BIT = "bit"  # ביט
    PAYPAL = "paypal"  # PayPal
    STANDING_ORDER = "standing_order"  # הוראת קבע


class RecurringFrequency(str, Enum):
    """תדירות הוראת קבע"""
    WEEKLY = "weekly"  # שבועי
    BI_WEEKLY = "bi_weekly"  # דו-שבועי
    MONTHLY = "monthly"  # חודשי
    QUARTERLY = "quarterly"  # רבעוני
    YEARLY = "yearly"  # שנתי


@dataclass
class PaymentLink:
    """קישור לתשלום"""
    link_id: str
    url: str
    amount: float
    currency: str
    description: str
    created_at: str
    expires_at: str
    status: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    invoice_id: Optional[str] = None


@dataclass
class PaymentRequest:
    """בקשת תשלום"""
    request_id: str
    customer_id: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str]
    amount: float
    currency: str
    description: str
    status: PaymentRequestStatus
    created_at: str
    expires_at: str
    allowed_methods: List[PaymentMethod]
    payment_link: Optional[PaymentLink] = None
    invoice_id: Optional[str] = None
    payments_received: List[Dict] = field(default_factory=list)
    notes: Optional[str] = None
    installments_allowed: bool = False
    max_installments: int = 12


@dataclass
class StandingOrder:
    """הוראת קבע"""
    order_id: str
    customer_id: str
    customer_name: str
    amount: float
    currency: str
    frequency: RecurringFrequency
    start_date: str
    end_date: Optional[str]
    next_charge_date: str
    status: str
    payment_method_token: str
    last_4_digits: str
    description: str
    total_charged: float
    charge_count: int
    failed_count: int
    sumit_recurring_id: Optional[str] = None
    charges_history: List[Dict] = field(default_factory=list)


@dataclass
class PaymentDemand:
    """דרישת תשלום"""
    demand_id: str
    customer_id: str
    customer_name: str
    amount: float
    currency: str
    due_date: str
    description: str
    status: str
    payment_methods: List[Dict]  # אמצעי תשלום אפשריים
    created_at: str
    sent_at: Optional[str]
    paid_at: Optional[str]
    payment_link: Optional[str]
    related_invoices: List[str]
    reminder_count: int = 0
    last_reminder_at: Optional[str] = None


@dataclass
class ChargeResult:
    """תוצאת חיוב"""
    success: bool
    charge_id: Optional[str]
    amount: float
    currency: str
    status: str
    authorization_number: Optional[str]
    last_4_digits: Optional[str]
    error_message: Optional[str]
    timestamp: str


class PaymentRequestService:
    """
    שירות בקשות תשלום והוראות קבע
    Payment Request & Standing Order Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # אחסון זמני (בפרודקשן - database)
        self._payment_requests: Dict[str, PaymentRequest] = {}
        self._standing_orders: Dict[str, StandingOrder] = {}
        self._payment_demands: Dict[str, PaymentDemand] = {}
        self._payment_links: Dict[str, PaymentLink] = {}
    
    # ==================== Payment Requests ====================
    
    async def create_payment_request(
        self,
        customer_id: str,
        customer_name: str,
        customer_email: str,
        amount: float,
        description: str,
        customer_phone: Optional[str] = None,
        invoice_id: Optional[str] = None,
        allowed_methods: Optional[List[PaymentMethod]] = None,
        expires_in_days: int = 30,
        installments_allowed: bool = False,
        max_installments: int = 12,
        notes: Optional[str] = None
    ) -> PaymentRequest:
        """
        יצירת בקשת תשלום
        Create Payment Request
        """
        request_id = f"PR-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now()
        
        if allowed_methods is None:
            allowed_methods = [PaymentMethod.CREDIT_CARD, PaymentMethod.BANK_TRANSFER]
        
        payment_request = PaymentRequest(
            request_id=request_id,
            customer_id=customer_id,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            amount=amount,
            currency="ILS",
            description=description,
            status=PaymentRequestStatus.DRAFT,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(days=expires_in_days)).isoformat(),
            allowed_methods=allowed_methods,
            invoice_id=invoice_id,
            installments_allowed=installments_allowed,
            max_installments=max_installments,
            notes=notes
        )
        
        self._payment_requests[request_id] = payment_request
        return payment_request
    
    async def send_payment_request(
        self,
        request_id: str,
        send_email: bool = True,
        send_sms: bool = False
    ) -> PaymentRequest:
        """
        שליחת בקשת תשלום ללקוח
        Send Payment Request to Customer
        """
        request = self._payment_requests.get(request_id)
        if not request:
            raise ValueError(f"בקשת תשלום {request_id} לא נמצאה")
        
        # יצירת קישור תשלום ב-SUMIT
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                # יצירת טרנזקציה לתשלום
                transaction = TransactionRequest(
                    amount=Decimal(str(request.amount)),
                    currency=request.currency,
                    description=request.description,
                    customer_id=request.customer_id,
                    success_url=f"{settings.app_url}/payment/success/{request_id}",
                    failure_url=f"{settings.app_url}/payment/failure/{request_id}"
                )
                
                tx_response = await sumit.create_card_transaction(transaction)
                
                # קבלת URL להפניה
                redirect_url = await sumit.begin_redirect(
                    tx_response.transaction_id,
                    f"{settings.app_url}/payment/callback/{request_id}"
                )
                
                # יצירת Payment Link
                payment_link = PaymentLink(
                    link_id=f"PL-{uuid.uuid4().hex[:8].upper()}",
                    url=redirect_url,
                    amount=request.amount,
                    currency=request.currency,
                    description=request.description,
                    created_at=datetime.now().isoformat(),
                    expires_at=request.expires_at,
                    status='active',
                    customer_id=request.customer_id,
                    customer_name=request.customer_name,
                    invoice_id=request.invoice_id
                )
                
                request.payment_link = payment_link
                request.status = PaymentRequestStatus.SENT
                self._payment_links[payment_link.link_id] = payment_link
                
                # שליחת התראות
                if send_email:
                    await self._send_payment_email(request, payment_link)
                if send_sms and request.customer_phone:
                    await self._send_payment_sms(request, payment_link)
                
                return request
                
        except Exception as e:
            # fallback - יצירת קישור לוקלי
            payment_link = PaymentLink(
                link_id=f"PL-{uuid.uuid4().hex[:8].upper()}",
                url=f"{settings.app_url or 'http://localhost:8000'}/pay/{request_id}",
                amount=request.amount,
                currency=request.currency,
                description=request.description,
                created_at=datetime.now().isoformat(),
                expires_at=request.expires_at,
                status='active',
                customer_id=request.customer_id
            )
            
            request.payment_link = payment_link
            request.status = PaymentRequestStatus.SENT
            return request
    
    async def process_payment(
        self,
        request_id: str,
        payment_method: PaymentMethod,
        card_details: Optional[Dict] = None,
        installments: int = 1
    ) -> ChargeResult:
        """
        עיבוד תשלום
        Process Payment
        """
        request = self._payment_requests.get(request_id)
        if not request:
            raise ValueError(f"בקשת תשלום {request_id} לא נמצאה")
        
        if payment_method not in request.allowed_methods:
            raise ValueError(f"אמצעי תשלום {payment_method} אינו מותר")
        
        if payment_method == PaymentMethod.CREDIT_CARD:
            return await self._charge_credit_card(request, card_details, installments)
        elif payment_method == PaymentMethod.BANK_TRANSFER:
            return await self._process_bank_transfer(request)
        else:
            # עבור אמצעי תשלום אחרים - רישום ידני
            return ChargeResult(
                success=True,
                charge_id=f"CHG-{uuid.uuid4().hex[:8].upper()}",
                amount=request.amount,
                currency=request.currency,
                status='pending_confirmation',
                authorization_number=None,
                last_4_digits=None,
                error_message=None,
                timestamp=datetime.now().isoformat()
            )
    
    async def _charge_credit_card(
        self,
        request: PaymentRequest,
        card_details: Dict,
        installments: int
    ) -> ChargeResult:
        """חיוב כרטיס אשראי"""
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                # Tokenize כרטיס לשימוש חד-פעמי
                token_request = TokenizeCardRequest(
                    card_number=card_details['card_number'],
                    expiry_month=card_details['expiry_month'],
                    expiry_year=card_details['expiry_year'],
                    cvv=card_details['cvv'],
                    holder_name=card_details['holder_name'],
                    customer_id=request.customer_id
                )
                
                token = await sumit.tokenize_single_use(token_request)
                
                # חיוב
                charge_request = ChargeRequest(
                    customer_id=request.customer_id,
                    amount=Decimal(str(request.amount)),
                    currency=request.currency,
                    description=request.description,
                    payment_method=token.token,
                    installments=installments,
                    document_id=request.invoice_id
                )
                
                payment = await sumit.charge_customer(charge_request)
                
                # עדכון הבקשה
                request.status = PaymentRequestStatus.COMPLETED
                request.payments_received.append({
                    'payment_id': payment.payment_id,
                    'amount': float(payment.amount),
                    'method': PaymentMethod.CREDIT_CARD.value,
                    'timestamp': datetime.now().isoformat()
                })
                
                return ChargeResult(
                    success=True,
                    charge_id=payment.payment_id,
                    amount=float(payment.amount),
                    currency=payment.currency,
                    status=payment.status,
                    authorization_number=payment.authorization_number,
                    last_4_digits=payment.last_4_digits,
                    error_message=None,
                    timestamp=datetime.now().isoformat()
                )
                
        except Exception as e:
            return ChargeResult(
                success=False,
                charge_id=None,
                amount=request.amount,
                currency=request.currency,
                status='failed',
                authorization_number=None,
                last_4_digits=None,
                error_message=str(e),
                timestamp=datetime.now().isoformat()
            )
    
    async def _process_bank_transfer(self, request: PaymentRequest) -> ChargeResult:
        """עיבוד העברה בנקאית"""
        # פרטי החשבון לתשלום
        return ChargeResult(
            success=True,
            charge_id=f"BT-{uuid.uuid4().hex[:8].upper()}",
            amount=request.amount,
            currency=request.currency,
            status='awaiting_transfer',
            authorization_number=None,
            last_4_digits=None,
            error_message=None,
            timestamp=datetime.now().isoformat()
        )
    
    # ==================== Standing Orders ====================
    
    async def create_standing_order(
        self,
        customer_id: str,
        customer_name: str,
        amount: float,
        frequency: RecurringFrequency,
        card_details: Dict,
        description: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> StandingOrder:
        """
        יצירת הוראת קבע
        Create Standing Order
        """
        order_id = f"SO-{uuid.uuid4().hex[:8].upper()}"
        
        if start_date is None:
            start_date = date.today()
        
        # חישוב תאריך החיוב הבא
        next_charge = self._calculate_next_charge_date(start_date, frequency)
        
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                # Tokenize כרטיס לשימוש חוזר
                token_request = TokenizeCardRequest(
                    card_number=card_details['card_number'],
                    expiry_month=card_details['expiry_month'],
                    expiry_year=card_details['expiry_year'],
                    cvv=card_details['cvv'],
                    holder_name=card_details['holder_name'],
                    customer_id=customer_id
                )
                
                token = await sumit.tokenize_card(token_request)
                
                # יצירת הוראת קבע ב-SUMIT
                sumit_frequency = {
                    RecurringFrequency.WEEKLY: 'weekly',
                    RecurringFrequency.BI_WEEKLY: 'weekly',  # נטפל בזה בנפרד
                    RecurringFrequency.MONTHLY: 'monthly',
                    RecurringFrequency.QUARTERLY: 'monthly',
                    RecurringFrequency.YEARLY: 'yearly'
                }[frequency]
                
                recurring_request = RecurringPaymentRequest(
                    customer_id=customer_id,
                    amount=Decimal(str(amount)),
                    currency="ILS",
                    frequency=sumit_frequency,
                    start_date=start_date,
                    end_date=end_date,
                    payment_method_id=token.token,
                    description=description
                )
                
                recurring = await sumit.update_recurring(order_id, recurring_request)
                sumit_recurring_id = recurring.recurring_id if hasattr(recurring, 'recurring_id') else None
                
                standing_order = StandingOrder(
                    order_id=order_id,
                    customer_id=customer_id,
                    customer_name=customer_name,
                    amount=amount,
                    currency="ILS",
                    frequency=frequency,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat() if end_date else None,
                    next_charge_date=next_charge.isoformat(),
                    status='active',
                    payment_method_token=token.token,
                    last_4_digits=token.last_4_digits,
                    description=description,
                    total_charged=0.0,
                    charge_count=0,
                    failed_count=0,
                    sumit_recurring_id=sumit_recurring_id
                )
                
        except Exception as e:
            # יצירה לוקלית ללא SUMIT
            standing_order = StandingOrder(
                order_id=order_id,
                customer_id=customer_id,
                customer_name=customer_name,
                amount=amount,
                currency="ILS",
                frequency=frequency,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat() if end_date else None,
                next_charge_date=next_charge.isoformat(),
                status='active',
                payment_method_token='local_token',
                last_4_digits=card_details['card_number'][-4:],
                description=description,
                total_charged=0.0,
                charge_count=0,
                failed_count=0
            )
        
        self._standing_orders[order_id] = standing_order
        return standing_order
    
    async def charge_standing_order(self, order_id: str) -> ChargeResult:
        """
        חיוב הוראת קבע
        Charge Standing Order
        """
        order = self._standing_orders.get(order_id)
        if not order:
            raise ValueError(f"הוראת קבע {order_id} לא נמצאה")
        
        if order.status != 'active':
            raise ValueError(f"הוראת קבע אינה פעילה")
        
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                if order.sumit_recurring_id:
                    payment = await sumit.charge_recurring(order.sumit_recurring_id)
                else:
                    # חיוב ידני
                    charge_request = ChargeRequest(
                        customer_id=order.customer_id,
                        amount=Decimal(str(order.amount)),
                        currency=order.currency,
                        description=order.description,
                        payment_method=order.payment_method_token
                    )
                    payment = await sumit.charge_customer(charge_request)
                
                # עדכון ההוראה
                order.total_charged += order.amount
                order.charge_count += 1
                order.next_charge_date = self._calculate_next_charge_date(
                    date.fromisoformat(order.next_charge_date),
                    order.frequency
                ).isoformat()
                
                order.charges_history.append({
                    'date': datetime.now().isoformat(),
                    'amount': order.amount,
                    'status': 'success',
                    'payment_id': payment.payment_id
                })
                
                return ChargeResult(
                    success=True,
                    charge_id=payment.payment_id,
                    amount=float(payment.amount),
                    currency=payment.currency,
                    status=payment.status,
                    authorization_number=payment.authorization_number,
                    last_4_digits=payment.last_4_digits,
                    error_message=None,
                    timestamp=datetime.now().isoformat()
                )
                
        except Exception as e:
            order.failed_count += 1
            order.charges_history.append({
                'date': datetime.now().isoformat(),
                'amount': order.amount,
                'status': 'failed',
                'error': str(e)
            })
            
            if order.failed_count >= 3:
                order.status = 'suspended'
            
            return ChargeResult(
                success=False,
                charge_id=None,
                amount=order.amount,
                currency=order.currency,
                status='failed',
                authorization_number=None,
                last_4_digits=order.last_4_digits,
                error_message=str(e),
                timestamp=datetime.now().isoformat()
            )
    
    async def cancel_standing_order(self, order_id: str, reason: str = "") -> StandingOrder:
        """
        ביטול הוראת קבע
        Cancel Standing Order
        """
        order = self._standing_orders.get(order_id)
        if not order:
            raise ValueError(f"הוראת קבע {order_id} לא נמצאה")
        
        try:
            if order.sumit_recurring_id:
                async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                    await sumit.cancel_recurring(order.sumit_recurring_id)
        except:
            pass
        
        order.status = 'cancelled'
        return order
    
    async def update_standing_order(
        self,
        order_id: str,
        amount: Optional[float] = None,
        frequency: Optional[RecurringFrequency] = None,
        end_date: Optional[date] = None
    ) -> StandingOrder:
        """
        עדכון הוראת קבע
        Update Standing Order
        """
        order = self._standing_orders.get(order_id)
        if not order:
            raise ValueError(f"הוראת קבע {order_id} לא נמצאה")
        
        if amount is not None:
            order.amount = amount
        if frequency is not None:
            order.frequency = frequency
            order.next_charge_date = self._calculate_next_charge_date(
                date.today(), frequency
            ).isoformat()
        if end_date is not None:
            order.end_date = end_date.isoformat()
        
        return order
    
    def _calculate_next_charge_date(
        self,
        from_date: date,
        frequency: RecurringFrequency
    ) -> date:
        """חישוב תאריך חיוב הבא"""
        if frequency == RecurringFrequency.WEEKLY:
            return from_date + timedelta(weeks=1)
        elif frequency == RecurringFrequency.BI_WEEKLY:
            return from_date + timedelta(weeks=2)
        elif frequency == RecurringFrequency.MONTHLY:
            month = from_date.month + 1
            year = from_date.year
            if month > 12:
                month = 1
                year += 1
            day = min(from_date.day, 28)  # למניעת בעיות בחודשים קצרים
            return date(year, month, day)
        elif frequency == RecurringFrequency.QUARTERLY:
            month = from_date.month + 3
            year = from_date.year
            while month > 12:
                month -= 12
                year += 1
            day = min(from_date.day, 28)
            return date(year, month, day)
        elif frequency == RecurringFrequency.YEARLY:
            return date(from_date.year + 1, from_date.month, from_date.day)
        
        return from_date + timedelta(days=30)
    
    # ==================== Payment Demands ====================
    
    async def create_payment_demand(
        self,
        customer_id: str,
        customer_name: str,
        amount: float,
        due_date: date,
        description: str,
        related_invoices: Optional[List[str]] = None,
        payment_methods: Optional[List[Dict]] = None
    ) -> PaymentDemand:
        """
        יצירת דרישת תשלום
        Create Payment Demand
        """
        demand_id = f"PD-{uuid.uuid4().hex[:8].upper()}"
        
        if payment_methods is None:
            payment_methods = [
                {
                    'method': PaymentMethod.CREDIT_CARD.value,
                    'name': 'כרטיס אשראי',
                    'enabled': True
                },
                {
                    'method': PaymentMethod.BANK_TRANSFER.value,
                    'name': 'העברה בנקאית',
                    'enabled': True,
                    'details': {
                        'bank': 'בנק לאומי',
                        'branch': '123',
                        'account': '456789'
                    }
                },
                {
                    'method': PaymentMethod.BIT.value,
                    'name': 'ביט',
                    'enabled': True,
                    'phone': '050-1234567'
                }
            ]
        
        demand = PaymentDemand(
            demand_id=demand_id,
            customer_id=customer_id,
            customer_name=customer_name,
            amount=amount,
            currency="ILS",
            due_date=due_date.isoformat(),
            description=description,
            status='draft',
            payment_methods=payment_methods,
            created_at=datetime.now().isoformat(),
            sent_at=None,
            paid_at=None,
            payment_link=None,
            related_invoices=related_invoices or []
        )
        
        self._payment_demands[demand_id] = demand
        return demand
    
    async def send_payment_demand(
        self,
        demand_id: str,
        send_email: bool = True,
        send_sms: bool = False
    ) -> PaymentDemand:
        """
        שליחת דרישת תשלום
        Send Payment Demand
        """
        demand = self._payment_demands.get(demand_id)
        if not demand:
            raise ValueError(f"דרישת תשלום {demand_id} לא נמצאה")
        
        # יצירת קישור תשלום
        demand.payment_link = f"{settings.app_url or 'http://localhost:8000'}/demand/{demand_id}"
        demand.status = 'sent'
        demand.sent_at = datetime.now().isoformat()
        
        return demand
    
    async def mark_demand_paid(
        self,
        demand_id: str,
        payment_method: PaymentMethod,
        payment_reference: Optional[str] = None
    ) -> PaymentDemand:
        """
        סימון דרישה כשולמה
        Mark Demand as Paid
        """
        demand = self._payment_demands.get(demand_id)
        if not demand:
            raise ValueError(f"דרישת תשלום {demand_id} לא נמצאה")
        
        demand.status = 'paid'
        demand.paid_at = datetime.now().isoformat()
        
        return demand
    
    async def send_demand_reminder(self, demand_id: str) -> PaymentDemand:
        """
        שליחת תזכורת לדרישת תשלום
        Send Demand Reminder
        """
        demand = self._payment_demands.get(demand_id)
        if not demand:
            raise ValueError(f"דרישת תשלום {demand_id} לא נמצאה")
        
        demand.reminder_count += 1
        demand.last_reminder_at = datetime.now().isoformat()
        
        return demand
    
    # ==================== Helpers ====================
    
    async def _send_payment_email(
        self,
        request: PaymentRequest,
        link: PaymentLink
    ):
        """שליחת מייל בקשת תשלום"""
        # בפרודקשן - שילוב עם SUMIT או שירות מייל
        pass
    
    async def _send_payment_sms(
        self,
        request: PaymentRequest,
        link: PaymentLink
    ):
        """שליחת SMS בקשת תשלום"""
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                from ..integrations.sumit_models import SMSRequest
                sms = SMSRequest(
                    phone_number=request.customer_phone,
                    message=f"בקשת תשלום על סך ₪{request.amount:,.2f}\nלתשלום: {link.url}"
                )
                await sumit.send_sms(sms)
        except:
            pass
    
    # ==================== Listings ====================
    
    async def list_payment_requests(
        self,
        customer_id: Optional[str] = None,
        status: Optional[PaymentRequestStatus] = None
    ) -> List[PaymentRequest]:
        """רשימת בקשות תשלום"""
        requests = list(self._payment_requests.values())
        
        if customer_id:
            requests = [r for r in requests if r.customer_id == customer_id]
        if status:
            requests = [r for r in requests if r.status == status]
        
        return sorted(requests, key=lambda x: x.created_at, reverse=True)
    
    async def list_standing_orders(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[StandingOrder]:
        """רשימת הוראות קבע"""
        orders = list(self._standing_orders.values())
        
        if customer_id:
            orders = [o for o in orders if o.customer_id == customer_id]
        if status:
            orders = [o for o in orders if o.status == status]
        
        return sorted(orders, key=lambda x: x.start_date, reverse=True)
    
    async def list_payment_demands(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[PaymentDemand]:
        """רשימת דרישות תשלום"""
        demands = list(self._payment_demands.values())
        
        if customer_id:
            demands = [d for d in demands if d.customer_id == customer_id]
        if status:
            demands = [d for d in demands if d.status == status]
        
        return sorted(demands, key=lambda x: x.created_at, reverse=True)
    
    async def get_pending_charges(self) -> List[StandingOrder]:
        """הוראות קבע שמגיע להן חיוב"""
        today = date.today().isoformat()
        return [
            o for o in self._standing_orders.values()
            if o.status == 'active' and o.next_charge_date <= today
        ]
    
    async def run_scheduled_charges(self) -> List[ChargeResult]:
        """הרצת חיובים מתוזמנים"""
        pending = await self.get_pending_charges()
        results = []
        
        for order in pending:
            result = await self.charge_standing_order(order.order_id)
            results.append(result)
        
        return results
