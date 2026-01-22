"""
Invoice Management Service
שירות ניהול חשבוניות - הפקה, קליטה ומעקב
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
    DocumentRequest, DocumentResponse, DocumentItem,
    SendDocumentRequest, DocumentListRequest, ExpenseRequest
)


class DocumentType(str, Enum):
    """סוג מסמך"""
    INVOICE = "invoice"  # חשבונית מס
    RECEIPT = "receipt"  # קבלה
    INVOICE_RECEIPT = "invoice_receipt"  # חשבונית מס קבלה
    QUOTE = "quote"  # הצעת מחיר
    PROFORMA = "proforma"  # חשבונית עסקה
    CREDIT_NOTE = "credit_note"  # חשבונית זיכוי
    DELIVERY_NOTE = "delivery_note"  # תעודת משלוח
    PURCHASE_ORDER = "purchase_order"  # הזמנת רכש


class InvoiceStatus(str, Enum):
    """סטטוס חשבונית"""
    DRAFT = "draft"  # טיוטה
    SENT = "sent"  # נשלחה
    VIEWED = "viewed"  # נצפתה
    PARTIAL_PAID = "partial_paid"  # שולמה חלקית
    PAID = "paid"  # שולמה
    OVERDUE = "overdue"  # באיחור
    CANCELLED = "cancelled"  # בוטלה
    DISPUTED = "disputed"  # במחלוקת


class ExpenseCategory(str, Enum):
    """קטגוריית הוצאה"""
    MATERIALS = "materials"  # חומרים
    SERVICES = "services"  # שירותים
    UTILITIES = "utilities"  # חשמל/מים/גז
    RENT = "rent"  # שכירות
    SALARY = "salary"  # משכורות
    MARKETING = "marketing"  # שיווק ופרסום
    TRAVEL = "travel"  # נסיעות
    EQUIPMENT = "equipment"  # ציוד
    INSURANCE = "insurance"  # ביטוח
    PROFESSIONAL = "professional"  # שירותים מקצועיים
    OTHER = "other"  # אחר


@dataclass
class InvoiceItem:
    """פריט בחשבונית"""
    description: str
    quantity: float
    unit_price: float
    vat_rate: float = 17.0
    discount_percent: float = 0.0
    item_code: Optional[str] = None
    unit: str = "יחידה"
    
    @property
    def subtotal(self) -> float:
        """סכום לפני מע"מ"""
        base = self.quantity * self.unit_price
        discount = base * (self.discount_percent / 100)
        return base - discount
    
    @property
    def vat_amount(self) -> float:
        """סכום מע"מ"""
        return self.subtotal * (self.vat_rate / 100)
    
    @property
    def total(self) -> float:
        """סכום כולל מע"מ"""
        return self.subtotal + self.vat_amount


@dataclass
class Invoice:
    """חשבונית"""
    invoice_id: str
    customer_id: str
    customer_name: str
    document_type: DocumentType
    items: List[InvoiceItem]
    issue_date: str
    due_date: str
    status: InvoiceStatus
    currency: str = "ILS"
    notes: Optional[str] = None
    internal_notes: Optional[str] = None
    po_number: Optional[str] = None  # מספר הזמנה
    document_number: Optional[str] = None
    pdf_url: Optional[str] = None
    sumit_id: Optional[str] = None
    
    @property
    def subtotal(self) -> float:
        """סה"כ לפני מע"מ"""
        return sum(item.subtotal for item in self.items)
    
    @property
    def total_vat(self) -> float:
        """סה"כ מע"מ"""
        return sum(item.vat_amount for item in self.items)
    
    @property
    def total(self) -> float:
        """סה"כ לתשלום"""
        return sum(item.total for item in self.items)


@dataclass
class ReceivedInvoice:
    """חשבונית ספק שהתקבלה"""
    invoice_id: str
    supplier_id: str
    supplier_name: str
    supplier_tax_id: Optional[str]
    original_invoice_number: str
    amount_before_vat: float
    vat_amount: float
    total_amount: float
    invoice_date: str
    received_date: str
    due_date: str
    category: ExpenseCategory
    status: InvoiceStatus
    payment_status: str
    notes: Optional[str] = None
    attachment_url: Optional[str] = None
    sumit_expense_id: Optional[str] = None


@dataclass 
class InvoiceSummary:
    """סיכום חשבוניות"""
    period: str
    total_issued: int
    total_received: int
    issued_amount: float
    received_amount: float
    collected_amount: float
    outstanding_amount: float
    overdue_amount: float
    by_status: Dict[str, int]
    by_customer: List[Dict]
    aging_breakdown: Dict[str, float]


class InvoiceService:
    """
    שירות ניהול חשבוניות
    Invoice Management Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # אחסון זמני (בפרודקשן - database)
        self._invoices: Dict[str, Invoice] = {}
        self._received_invoices: Dict[str, ReceivedInvoice] = {}
    
    # ==================== Invoice Creation ====================
    
    async def create_invoice(
        self,
        customer_id: str,
        customer_name: str,
        items: List[Dict],
        document_type: DocumentType = DocumentType.INVOICE,
        due_days: int = 30,
        notes: Optional[str] = None,
        po_number: Optional[str] = None,
        send_immediately: bool = False
    ) -> Invoice:
        """
        יצירת חשבונית חדשה
        Create New Invoice
        """
        invoice_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
        issue_date = date.today()
        due_date = issue_date + timedelta(days=due_days)
        
        # המרת פריטים
        invoice_items = [
            InvoiceItem(
                description=item['description'],
                quantity=item.get('quantity', 1),
                unit_price=item['unit_price'],
                vat_rate=item.get('vat_rate', 17.0),
                discount_percent=item.get('discount_percent', 0),
                item_code=item.get('item_code'),
                unit=item.get('unit', 'יחידה')
            )
            for item in items
        ]
        
        invoice = Invoice(
            invoice_id=invoice_id,
            customer_id=customer_id,
            customer_name=customer_name,
            document_type=document_type,
            items=invoice_items,
            issue_date=issue_date.isoformat(),
            due_date=due_date.isoformat(),
            status=InvoiceStatus.DRAFT,
            notes=notes,
            po_number=po_number
        )
        
        self._invoices[invoice_id] = invoice
        
        return invoice
    
    async def issue_invoice_to_sumit(
        self,
        invoice_id: str,
        send_to_customer: bool = True
    ) -> Invoice:
        """
        הפקת חשבונית ב-SUMIT
        Issue Invoice via SUMIT API
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            raise ValueError(f"חשבונית {invoice_id} לא נמצאה")
        
        # יצירת בקשה ל-SUMIT
        sumit_items = [
            DocumentItem(
                description=item.description,
                quantity=Decimal(str(item.quantity)),
                price=Decimal(str(item.unit_price)),
                vat_rate=Decimal(str(item.vat_rate)) if item.vat_rate else None,
                discount=Decimal(str(item.discount_percent)) if item.discount_percent else None
            )
            for item in invoice.items
        ]
        
        document_request = DocumentRequest(
            customer_id=invoice.customer_id,
            document_type=invoice.document_type.value,
            items=sumit_items,
            issue_date=date.fromisoformat(invoice.issue_date),
            due_date=date.fromisoformat(invoice.due_date),
            notes=invoice.notes,
            currency=invoice.currency
        )
        
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                # יצירת המסמך
                response = await sumit.create_document(document_request)
                
                # עדכון החשבונית
                invoice.sumit_id = response.document_id
                invoice.document_number = response.document_number
                invoice.pdf_url = response.pdf_url
                invoice.status = InvoiceStatus.SENT if send_to_customer else InvoiceStatus.DRAFT
                
                # שליחה ללקוח
                if send_to_customer:
                    send_request = SendDocumentRequest(
                        document_id=response.document_id
                    )
                    await sumit.send_document(send_request)
                
                return invoice
                
        except Exception as e:
            raise Exception(f"שגיאה בהפקת חשבונית: {str(e)}")
    
    async def create_and_issue_invoice(
        self,
        customer_id: str,
        customer_name: str,
        items: List[Dict],
        document_type: DocumentType = DocumentType.INVOICE,
        due_days: int = 30,
        notes: Optional[str] = None,
        send_to_customer: bool = True
    ) -> Invoice:
        """
        יצירה והפקה בפעולה אחת
        Create and Issue in One Step
        """
        invoice = await self.create_invoice(
            customer_id=customer_id,
            customer_name=customer_name,
            items=items,
            document_type=document_type,
            due_days=due_days,
            notes=notes
        )
        
        return await self.issue_invoice_to_sumit(
            invoice_id=invoice.invoice_id,
            send_to_customer=send_to_customer
        )
    
    # ==================== Invoice Reception ====================
    
    async def receive_supplier_invoice(
        self,
        supplier_name: str,
        original_invoice_number: str,
        amount_before_vat: float,
        vat_amount: float,
        invoice_date: date,
        due_date: date,
        category: ExpenseCategory,
        supplier_id: Optional[str] = None,
        supplier_tax_id: Optional[str] = None,
        notes: Optional[str] = None,
        attachment_base64: Optional[str] = None
    ) -> ReceivedInvoice:
        """
        קליטת חשבונית ספק
        Receive Supplier Invoice
        """
        invoice_id = f"RINV-{uuid.uuid4().hex[:8].upper()}"
        
        received_invoice = ReceivedInvoice(
            invoice_id=invoice_id,
            supplier_id=supplier_id or f"SUP-{uuid.uuid4().hex[:6].upper()}",
            supplier_name=supplier_name,
            supplier_tax_id=supplier_tax_id,
            original_invoice_number=original_invoice_number,
            amount_before_vat=amount_before_vat,
            vat_amount=vat_amount,
            total_amount=amount_before_vat + vat_amount,
            invoice_date=invoice_date.isoformat(),
            received_date=date.today().isoformat(),
            due_date=due_date.isoformat(),
            category=category,
            status=InvoiceStatus.DRAFT,
            payment_status='pending',
            notes=notes
        )
        
        self._received_invoices[invoice_id] = received_invoice
        
        return received_invoice
    
    async def record_expense_to_sumit(
        self,
        received_invoice_id: str
    ) -> ReceivedInvoice:
        """
        רישום הוצאה ב-SUMIT
        Record Expense in SUMIT
        """
        invoice = self._received_invoices.get(received_invoice_id)
        if not invoice:
            raise ValueError(f"חשבונית {received_invoice_id} לא נמצאה")
        
        expense_request = ExpenseRequest(
            supplier_name=invoice.supplier_name,
            amount=Decimal(str(invoice.amount_before_vat)),
            vat_amount=Decimal(str(invoice.vat_amount)),
            expense_date=date.fromisoformat(invoice.invoice_date),
            category=invoice.category.value,
            notes=f"חשבונית מקור: {invoice.original_invoice_number}"
        )
        
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                response = await sumit.add_expense(expense_request)
                invoice.sumit_expense_id = response.get('expense_id')
                invoice.status = InvoiceStatus.SENT
                return invoice
                
        except Exception as e:
            raise Exception(f"שגיאה ברישום הוצאה: {str(e)}")
    
    # ==================== Invoice Management ====================
    
    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """קבלת חשבונית"""
        return self._invoices.get(invoice_id)
    
    async def get_received_invoice(self, invoice_id: str) -> Optional[ReceivedInvoice]:
        """קבלת חשבונית ספק"""
        return self._received_invoices.get(invoice_id)
    
    async def list_invoices(
        self,
        customer_id: Optional[str] = None,
        status: Optional[InvoiceStatus] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        document_type: Optional[DocumentType] = None
    ) -> List[Invoice]:
        """
        רשימת חשבוניות
        List Invoices
        """
        invoices = list(self._invoices.values())
        
        if customer_id:
            invoices = [i for i in invoices if i.customer_id == customer_id]
        if status:
            invoices = [i for i in invoices if i.status == status]
        if document_type:
            invoices = [i for i in invoices if i.document_type == document_type]
        if from_date:
            invoices = [i for i in invoices if i.issue_date >= from_date.isoformat()]
        if to_date:
            invoices = [i for i in invoices if i.issue_date <= to_date.isoformat()]
        
        return sorted(invoices, key=lambda x: x.issue_date, reverse=True)
    
    async def list_received_invoices(
        self,
        supplier_id: Optional[str] = None,
        category: Optional[ExpenseCategory] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[ReceivedInvoice]:
        """
        רשימת חשבוניות ספק
        List Received Invoices
        """
        invoices = list(self._received_invoices.values())
        
        if supplier_id:
            invoices = [i for i in invoices if i.supplier_id == supplier_id]
        if category:
            invoices = [i for i in invoices if i.category == category]
        if from_date:
            invoices = [i for i in invoices if i.invoice_date >= from_date.isoformat()]
        if to_date:
            invoices = [i for i in invoices if i.invoice_date <= to_date.isoformat()]
        
        return sorted(invoices, key=lambda x: x.invoice_date, reverse=True)
    
    async def update_invoice_status(
        self,
        invoice_id: str,
        new_status: InvoiceStatus
    ) -> Invoice:
        """עדכון סטטוס חשבונית"""
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            raise ValueError(f"חשבונית {invoice_id} לא נמצאה")
        
        invoice.status = new_status
        return invoice
    
    async def cancel_invoice(self, invoice_id: str, reason: str) -> Invoice:
        """
        ביטול חשבונית
        Cancel Invoice
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            raise ValueError(f"חשבונית {invoice_id} לא נמצאה")
        
        if invoice.sumit_id:
            try:
                async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                    await sumit.cancel_document(invoice.sumit_id)
            except Exception as e:
                raise Exception(f"שגיאה בביטול חשבונית ב-SUMIT: {str(e)}")
        
        invoice.status = InvoiceStatus.CANCELLED
        invoice.internal_notes = f"בוטלה: {reason}"
        return invoice
    
    async def create_credit_note(
        self,
        original_invoice_id: str,
        items: Optional[List[Dict]] = None,
        reason: str = ""
    ) -> Invoice:
        """
        יצירת חשבונית זיכוי
        Create Credit Note
        """
        original = self._invoices.get(original_invoice_id)
        if not original:
            raise ValueError(f"חשבונית מקור {original_invoice_id} לא נמצאה")
        
        # אם לא צוינו פריטים, זיכוי מלא
        credit_items = items or [
            {
                'description': f"זיכוי: {item.description}",
                'quantity': item.quantity,
                'unit_price': -item.unit_price,  # סכום שלילי
                'vat_rate': item.vat_rate
            }
            for item in original.items
        ]
        
        credit_note = await self.create_invoice(
            customer_id=original.customer_id,
            customer_name=original.customer_name,
            items=credit_items,
            document_type=DocumentType.CREDIT_NOTE,
            notes=f"זיכוי לחשבונית {original.document_number or original.invoice_id}. {reason}"
        )
        
        return credit_note
    
    # ==================== Sync with SUMIT ====================
    
    async def sync_invoices_from_sumit(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Invoice]:
        """
        סנכרון חשבוניות מ-SUMIT
        Sync Invoices from SUMIT
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        try:
            async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                request = DocumentListRequest(
                    from_date=from_date,
                    to_date=to_date,
                    document_type='invoice'
                )
                documents = await sumit.list_documents(request)
                
                synced_invoices = []
                for doc in documents:
                    invoice = Invoice(
                        invoice_id=f"SUMIT-{doc.document_id}",
                        customer_id=doc.customer_id,
                        customer_name="",  # נצטרך לשלוף מ-SUMIT
                        document_type=DocumentType(doc.document_type),
                        items=[],  # נצטרך לשלוף פירוט
                        issue_date=doc.issue_date.isoformat(),
                        due_date=doc.due_date.isoformat() if doc.due_date else doc.issue_date.isoformat(),
                        status=InvoiceStatus.SENT if doc.status == 'sent' else InvoiceStatus.DRAFT,
                        document_number=doc.document_number,
                        pdf_url=doc.pdf_url,
                        sumit_id=doc.document_id
                    )
                    self._invoices[invoice.invoice_id] = invoice
                    synced_invoices.append(invoice)
                
                return synced_invoices
                
        except Exception as e:
            raise Exception(f"שגיאה בסנכרון מ-SUMIT: {str(e)}")
    
    # ==================== Reports ====================
    
    async def get_invoice_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> InvoiceSummary:
        """
        סיכום חשבוניות
        Invoice Summary
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date.replace(day=1)
        
        # חשבוניות שהופקו
        issued = [i for i in self._invoices.values() 
                  if start_date.isoformat() <= i.issue_date <= end_date.isoformat()]
        
        # חשבוניות שהתקבלו
        received = [i for i in self._received_invoices.values()
                    if start_date.isoformat() <= i.invoice_date <= end_date.isoformat()]
        
        # חישובים
        issued_amount = sum(i.total for i in issued)
        received_amount = sum(i.total_amount for i in received)
        
        # סטטוס
        paid = [i for i in issued if i.status == InvoiceStatus.PAID]
        collected_amount = sum(i.total for i in paid)
        outstanding_amount = issued_amount - collected_amount
        
        # גיול
        today = date.today()
        overdue = [i for i in issued 
                   if i.status not in [InvoiceStatus.PAID, InvoiceStatus.CANCELLED] 
                   and i.due_date < today.isoformat()]
        overdue_amount = sum(i.total for i in overdue)
        
        # לפי סטטוס
        by_status = {}
        for status in InvoiceStatus:
            count = len([i for i in issued if i.status == status])
            if count > 0:
                by_status[status.value] = count
        
        # לפי לקוח
        customer_totals: Dict[str, float] = {}
        for i in issued:
            customer_totals[i.customer_name] = customer_totals.get(i.customer_name, 0) + i.total
        
        by_customer = [
            {'customer_name': name, 'total': total}
            for name, total in sorted(customer_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        # גיול
        aging = {'current': 0.0, '31-60': 0.0, '61-90': 0.0, '91-120': 0.0, '120+': 0.0}
        for i in issued:
            if i.status in [InvoiceStatus.PAID, InvoiceStatus.CANCELLED]:
                continue
            
            due = date.fromisoformat(i.due_date)
            days_overdue = (today - due).days
            
            if days_overdue <= 0:
                aging['current'] += i.total
            elif days_overdue <= 60:
                aging['31-60'] += i.total
            elif days_overdue <= 90:
                aging['61-90'] += i.total
            elif days_overdue <= 120:
                aging['91-120'] += i.total
            else:
                aging['120+'] += i.total
        
        return InvoiceSummary(
            period=f"{start_date.isoformat()} - {end_date.isoformat()}",
            total_issued=len(issued),
            total_received=len(received),
            issued_amount=issued_amount,
            received_amount=received_amount,
            collected_amount=collected_amount,
            outstanding_amount=outstanding_amount,
            overdue_amount=overdue_amount,
            by_status=by_status,
            by_customer=by_customer,
            aging_breakdown=aging
        )
    
    # ==================== Bulk Operations ====================
    
    async def bulk_create_invoices(
        self,
        invoice_data: List[Dict]
    ) -> List[Invoice]:
        """
        יצירת חשבוניות מרובות
        Bulk Create Invoices
        """
        created = []
        for data in invoice_data:
            invoice = await self.create_invoice(
                customer_id=data['customer_id'],
                customer_name=data['customer_name'],
                items=data['items'],
                document_type=data.get('document_type', DocumentType.INVOICE),
                due_days=data.get('due_days', 30),
                notes=data.get('notes')
            )
            created.append(invoice)
        
        return created
    
    async def send_payment_reminders(
        self,
        min_days_overdue: int = 7
    ) -> List[Dict]:
        """
        שליחת תזכורות תשלום
        Send Payment Reminders
        """
        today = date.today()
        reminders_sent = []
        
        for invoice in self._invoices.values():
            if invoice.status in [InvoiceStatus.PAID, InvoiceStatus.CANCELLED]:
                continue
            
            due = date.fromisoformat(invoice.due_date)
            days_overdue = (today - due).days
            
            if days_overdue >= min_days_overdue and invoice.sumit_id:
                try:
                    async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
                        await sumit.send_document(SendDocumentRequest(
                            document_id=invoice.sumit_id,
                            subject=f"תזכורת תשלום - חשבונית {invoice.document_number}",
                            message=f"שלום,\n\nזוהי תזכורת לתשלום חשבונית מספר {invoice.document_number} על סך ₪{invoice.total:,.2f}.\nהחשבונית באיחור של {days_overdue} ימים.\n\nנודה לטיפולכם."
                        ))
                        
                        reminders_sent.append({
                            'invoice_id': invoice.invoice_id,
                            'customer_name': invoice.customer_name,
                            'amount': invoice.total,
                            'days_overdue': days_overdue
                        })
                except:
                    pass
        
        return reminders_sent
