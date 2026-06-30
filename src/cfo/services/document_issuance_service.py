"""DB-backed document issuance for Rezef.

Creates local AR records and, when requested, issues/sends the document in
SUMIT using the active organization's credentials.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..integrations.sumit_models import DocumentItem, DocumentRequest, SendDocumentRequest
from ..models import Invoice, InvoiceStatus
from .sync_engine import get_connector_for_org


ISSUABLE_DOCUMENT_TYPES = {
    "invoice": "חשבונית מס",
    "receipt": "קבלה",
    "invoice_receipt": "חשבונית מס קבלה",
    "proforma": "חשבונית עסקה",
    "quote": "הצעת מחיר",
    "order": "הזמנה",
    "purchase_order": "הזמנת רכש",
    "work_order": "הזמנת עבודה",
    "delivery_note": "תעודת משלוח",
    "credit_note": "חשבונית זיכוי",
    "payment_request": "דרישת תשלום",
}


class DocumentIssuanceService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def list_types(self) -> list[dict[str, str]]:
        return [{"value": value, "label": label} for value, label in ISSUABLE_DOCUMENT_TYPES.items()]

    def list_documents(
        self,
        *,
        status: Optional[str] = None,
        document_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        q = self.db.query(Invoice).filter(Invoice.organization_id == self.organization_id)
        if status:
            q = q.filter(Invoice.status == InvoiceStatus(status))
        rows = q.order_by(Invoice.issue_date.desc().nullslast(), Invoice.id.desc()).limit(limit).all()
        docs = [self._serialize(row) for row in rows]
        if document_type:
            docs = [row for row in docs if row["document_type"] == document_type]
        return docs

    async def create_document(
        self,
        *,
        document_type: str,
        customer_id: str,
        customer_name: str,
        items: list[dict[str, Any]],
        issue_date: Optional[date] = None,
        due_date: Optional[date] = None,
        notes: Optional[str] = None,
        currency: str = "ILS",
        send_to_sumit: bool = True,
        send_email: bool = False,
        recipient_email: Optional[str] = None,
    ) -> dict[str, Any]:
        document_type = document_type.strip().lower()
        if document_type not in ISSUABLE_DOCUMENT_TYPES:
            raise ValueError(f"סוג מסמך לא נתמך: {document_type}")

        issue = issue_date or date.today()
        due = due_date or issue + timedelta(days=30)
        line_items = [self._line_item(item) for item in items]
        subtotal = sum(item["subtotal"] for item in line_items)
        tax = sum(item["tax"] for item in line_items)
        total = sum(item["total"] for item in line_items)
        stored_line_items = [
            {
                **item,
                "subtotal": float(item["subtotal"]),
                "tax": float(item["tax"]),
                "total": float(item["total"]),
            }
            for item in line_items
        ]

        invoice = Invoice(
            organization_id=self.organization_id,
            source="rezef",
            issue_date=issue,
            due_date=due,
            status=InvoiceStatus.DRAFT,
            currency=currency,
            subtotal=subtotal,
            tax=tax,
            total=total,
            balance=total,
            line_items=stored_line_items,
            notes=notes,
            raw_data={
                "document_type": document_type,
                "customer": {
                    "id": customer_id,
                    "name": customer_name,
                    "email": recipient_email,
                },
                "issued_by": "rezef",
            },
        )
        self.db.add(invoice)
        self.db.flush()

        sumit_response: dict[str, Any] | None = None
        sent_response: dict[str, Any] | None = None
        if send_to_sumit:
            connector, _conn_id, source = get_connector_for_org(
                self.db, self.organization_id, preferred_source="sumit"
            )
            if source != "sumit" or not hasattr(connector, "_get_client"):
                raise ValueError("SUMIT אינו מחובר עבור ארגון זה")

            request = DocumentRequest(
                customer_id=customer_id or customer_name,
                document_type=document_type,
                items=[
                    DocumentItem(
                        description=item["description"],
                        quantity=Decimal(str(item["quantity"])),
                        price=Decimal(str(item["unit_price"])),
                        vat_rate=Decimal(str(item["vat_rate"])),
                        discount=Decimal(str(item.get("discount", 0) or 0)) or None,
                    )
                    for item in line_items
                ],
                issue_date=issue,
                due_date=due,
                notes=notes,
                currency=currency,
            )
            client = await connector._get_client()
            async with client:
                response = await client.create_document(request)
                sumit_response = response.model_dump(mode="json")
                invoice.external_id = response.document_id
                invoice.invoice_number = response.document_number
                invoice.allocation_number = response.allocation_number
                invoice.source = "sumit"
                invoice.status = InvoiceStatus.SENT if send_email else InvoiceStatus.SENT
                invoice.raw_data = {
                    **(invoice.raw_data or {}),
                    "sumit": sumit_response,
                }
                if send_email:
                    sent_response = await client.send_document(
                        SendDocumentRequest(
                            document_id=response.document_id,
                            recipient_email=recipient_email,
                        )
                    )

        self.db.commit()
        self.db.refresh(invoice)
        return {
            "id": invoice.id,
            "organization_id": invoice.organization_id,
            "document_type": document_type,
            "document_label": ISSUABLE_DOCUMENT_TYPES[document_type],
            "external_id": invoice.external_id,
            "document_number": invoice.invoice_number,
            "allocation_number": invoice.allocation_number,
            "status": invoice.status.value if invoice.status else None,
            "subtotal": float(invoice.subtotal or 0),
            "tax": float(invoice.tax or 0),
            "total": float(invoice.total or 0),
            "balance": float(invoice.balance or 0),
            "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "sumit": sumit_response,
            "sent": sent_response,
        }

    async def send_document(
        self,
        invoice_id: int,
        *,
        recipient_email: Optional[str] = None,
        subject: Optional[str] = None,
        message: Optional[str] = None,
    ) -> dict[str, Any]:
        invoice = self._get_invoice(invoice_id)
        if not invoice.external_id:
            raise ValueError("המסמך עדיין לא הופק ב-SUMIT")
        connector, _conn_id, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit" or not hasattr(connector, "_get_client"):
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")
        client = await connector._get_client()
        async with client:
            response = await client.send_document(
                SendDocumentRequest(
                    document_id=invoice.external_id,
                    recipient_email=recipient_email,
                    subject=subject,
                    message=message,
                )
            )
        raw = dict(invoice.raw_data or {})
        raw["last_send"] = response
        invoice.raw_data = raw
        invoice.status = InvoiceStatus.SENT
        self.db.commit()
        self.db.refresh(invoice)
        return {"document": self._serialize(invoice), "sumit": response}

    async def cancel_document(self, invoice_id: int, reason: Optional[str] = None) -> dict[str, Any]:
        invoice = self._get_invoice(invoice_id)
        if not invoice.external_id:
            raise ValueError("המסמך עדיין לא הופק ב-SUMIT")
        connector, _conn_id, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit" or not hasattr(connector, "_get_client"):
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")
        client = await connector._get_client()
        async with client:
            response = await client.cancel_document(invoice.external_id)
        raw = dict(invoice.raw_data or {})
        raw["cancel_reason"] = reason
        raw["sumit_cancel"] = response
        invoice.raw_data = raw
        invoice.status = InvoiceStatus.CANCELLED
        self.db.commit()
        self.db.refresh(invoice)
        return {"document": self._serialize(invoice), "sumit": response}

    def _line_item(self, item: dict[str, Any]) -> dict[str, Any]:
        quantity = Decimal(str(item.get("quantity", 1)))
        unit_price = Decimal(str(item.get("unit_price", 0)))
        vat_rate = Decimal(str(item.get("vat_rate", 17)))
        discount = Decimal(str(item.get("discount", item.get("discount_percent", 0)) or 0))
        net = quantity * unit_price
        if discount:
            net = net * (Decimal("1") - (discount / Decimal("100")))
        tax = net * (vat_rate / Decimal("100"))
        return {
            "description": item["description"],
            "quantity": float(quantity),
            "unit_price": float(unit_price),
            "vat_rate": float(vat_rate),
            "discount": float(discount),
            "subtotal": net,
            "tax": tax,
            "total": net + tax,
        }

    def _get_invoice(self, invoice_id: int) -> Invoice:
        invoice = self.db.query(Invoice).filter(
            Invoice.organization_id == self.organization_id,
            Invoice.id == invoice_id,
        ).first()
        if not invoice:
            raise ValueError(f"מסמך {invoice_id} לא נמצא")
        return invoice

    def _serialize(self, invoice: Invoice) -> dict[str, Any]:
        raw = invoice.raw_data or {}
        document_type = raw.get("document_type") or "invoice"
        return {
            "id": invoice.id,
            "organization_id": invoice.organization_id,
            "document_type": document_type,
            "document_label": ISSUABLE_DOCUMENT_TYPES.get(document_type, document_type),
            "external_id": invoice.external_id,
            "document_number": invoice.invoice_number,
            "allocation_number": invoice.allocation_number,
            "status": invoice.status.value if invoice.status else None,
            "subtotal": float(invoice.subtotal or 0),
            "tax": float(invoice.tax or 0),
            "total": float(invoice.total or 0),
            "balance": float(invoice.balance or 0),
            "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "customer": raw.get("customer") or {},
            "line_items": invoice.line_items or [],
        }
