"""
SUMIT (OfficeGuy) API Integration

Implements the real SUMIT API (https://api.sumit.co.il).
API conventions (per the official OpenAPI spec):
- Every endpoint is HTTP POST with a trailing slash: /<area>/<resource>/<action>/
- Authentication is sent in the request body on every call:
  {"Credentials": {"CompanyID": int, "APIKey": str}}
- Every response (except binary endpoints such as /accounting/documents/getpdf/)
  is wrapped in an envelope:
  {"Status": 0|1|2, "UserErrorMessage": ..., "TechnicalErrorDetails": ..., "Data": ...}
  Status == 0 means success. Business errors come back with HTTP 200.

Documentation: https://app.sumit.co.il/developers/api/
"""
from typing import Any, Dict, List, Optional
import httpx
import logging
from datetime import date, datetime
from decimal import Decimal

from .base import BaseIntegration
from .sumit_models import (
    # Customer models
    CustomerRequest, CustomerResponse, CustomerRemarkRequest,
    # Document models
    DocumentRequest, DocumentResponse, SendDocumentRequest,
    DocumentListRequest, ExpenseRequest, DebtReportRequest,
    # Payment models
    ChargeRequest, PaymentResponse, PaymentMethodResponse,
    # Transaction models
    TransactionRequest, TransactionResponse,
    # CRM models
    EntityRequest, EntityResponse, FolderResponse,
    # Income item models
    IncomeItemRequest, IncomeItemResponse,
    # Recurring payment models
    RecurringPaymentRequest, RecurringPaymentResponse,
    # Communication models
    SMSRequest, SMSResponse, EmailListRequest, FaxRequest,
    # Billing models
    BillingTransactionRequest, BillingTransaction,
    # Vault models
    TokenizeCardRequest, TokenResponse,
    # General models
    BankAccountVerification, ExchangeRateRequest, ExchangeRateResponse,
    SettingsUpdate, DocumentNumberRequest,
    # Ticket models
    TicketRequest, TicketResponse,
    # Company models
    CompanyRequest, CompanyResponse,
    # User models
    UserRequest, UserResponse, UserPermission,
    # Stock models
    StockItemResponse,
    # Base response
    SumitResponse
)

logger = logging.getLogger(__name__)


# Mapping from this codebase's document type names to SUMIT's
# Accounting_Typed_DocumentType enum names.
_DOCUMENT_TYPE_TO_SUMIT = {
    "invoice": "Invoice",
    "tax_invoice": "Invoice",
    "invoice_receipt": "InvoiceAndReceipt",
    "invoice_and_receipt": "InvoiceAndReceipt",
    "receipt": "Receipt",
    "proforma": "ProformaInvoice",
    "proforma_invoice": "ProformaInvoice",
    "donation_receipt": "DonationReceipt",
    "credit_note": "CreditInvoice",
    "credit_invoice": "CreditInvoice",
    "quote": "PriceQuotation",
    "price_quotation": "PriceQuotation",
    "order": "Order",
    # הזמנת רכש / הזמנת עבודה — SUMIT מייצג שתיהן כ-Order (הזמנה).
    "purchase_order": "Order",
    "work_order": "Order",
    "delivery_note": "DeliveryNote",
    "payment_request": "PaymentRequest",
    "expense": "ExpenseInvoice",
    "expense_invoice": "ExpenseInvoice",
    "expense_receipt": "ExpenseReceipt",
}

# Reverse mapping from SUMIT enum names to the names used by callers.
_DOCUMENT_TYPE_FROM_SUMIT = {
    "Invoice": "invoice",
    "InvoiceAndReceipt": "invoice_receipt",
    "Receipt": "receipt",
    "ProformaInvoice": "proforma",
    "DonationReceipt": "donation_receipt",
    "CreditInvoice": "credit_note",
    "PriceQuotation": "quote",
    "Order": "order",
    "DeliveryNote": "delivery_note",
    "PaymentRequest": "payment_request",
    "ExpenseInvoice": "expense_invoice",
    "ExpenseReceipt": "expense_receipt",
}

_LANGUAGE_TO_SUMIT = {
    "he": "Hebrew",
    "en": "English",
    "ar": "Arabic",
    "es": "Spanish",
}


class SumitIntegration(BaseIntegration):
    """
    SUMIT (OfficeGuy) API Integration

    Implements the real SUMIT API endpoints for:
    - Accounting (Customers, Documents, Income Items, General)
    - Billing (Payments, Payment Methods, Recurring, Upay)
    - Credit Card Terminal (CreditGuy Gateway, Vault, Batch Billing)
    - CRM (Data, Schema, Views)
    - Communications (Email lists, SMS, Fax)
    - Customer Service (Tickets)
    - Website administration (Companies, Users, Permissions)
    """

    BASE_URL = "https://api.sumit.co.il"

    def __init__(self, api_key: str, company_id: Optional[str] = None, **kwargs):
        """
        Initialize SUMIT integration

        Args:
            api_key: SUMIT API key
            company_id: Optional company ID for multi-company accounts
            **kwargs: Additional configuration
        """
        super().__init__(api_key, **kwargs)
        self.company_id = company_id
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Content-Type": "application/json"
            },
            timeout=30.0
        )

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.client.aclose()

    # ==================== Request plumbing ====================

    def _credentials(self) -> Dict[str, Any]:
        """Build the Credentials object SUMIT expects in every request body."""
        credentials: Dict[str, Any] = {
            "APIKey": self.api_key,
        }
        if self.company_id:
            try:
                credentials["CompanyID"] = int(self.company_id)
            except (TypeError, ValueError):
                credentials["CompanyID"] = self.company_id
        return credentials

    def _with_credentials(self, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Inject Credentials into a request body (without overwriting)."""
        if data is None:
            data = {}
        # SUMIT authenticates via Credentials in the request body for
        # every endpoint — never skip injection or the request is sent
        # unauthenticated.
        data.setdefault("Credentials", self._credentials())
        return data

    async def _make_request(
        self,
        endpoint: str,
        method: str = "POST",
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP request to SUMIT API.

        All SUMIT endpoints are POST with a JSON body; the method parameter
        is kept for backwards compatibility but defaults to POST.

        Args:
            endpoint: API endpoint path (e.g. "/accounting/documents/list/")
            method: HTTP method (always POST for SUMIT)
            data: Request body data
            params: Query parameters (only used by a few endpoints,
                e.g. /customerservice/tickets/create/)

        Returns:
            Dict containing the full response envelope
            ({"Status": ..., "UserErrorMessage": ..., "Data": ...})
        """
        self._log_request(method, endpoint, data)

        try:
            data = self._with_credentials(data)

            response = await self.client.request(
                method=method,
                url=endpoint,
                json=data,
                params=params
            )

            self._log_response(response.status_code, response.text)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            self._log_error(e, f"HTTP error on {endpoint}")
            # כולל את קוד הסטטוס בהודעה — ל-403 (rate limit) התגובה לרוב ריקה,
            # וקוראים מסתמכים על זיהוי "403" בטקסט כדי לבצע backoff.
            raise Exception(
                f"SUMIT API error {e.response.status_code}: {e.response.text}"
            )
        except Exception as e:
            self._log_error(e, f"Request failed on {endpoint}")
            raise

    async def _post(
        self,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        POST to a SUMIT endpoint, validate the response envelope and
        return its "Data" member.

        Raises:
            Exception: if the envelope Status != 0, with the server's
                UserErrorMessage / TechnicalErrorDetails.
        """
        response = await self._make_request(endpoint, data=payload, params=params)
        if not isinstance(response, dict):
            raise Exception(f"SUMIT API error: unexpected response from {endpoint}")
        status = response.get("Status", 0)
        if status not in (0, "0", "Success"):
            message = (
                response.get("UserErrorMessage")
                or response.get("TechnicalErrorDetails")
                or f"Status={status}"
            )
            raise Exception(f"SUMIT API error: {message}")
        data = response.get("Data")
        return data if isinstance(data, dict) else ({} if data is None else data)

    async def _post_binary(
        self,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """
        POST to a SUMIT endpoint that returns raw binary content
        (e.g. /accounting/documents/getpdf/) and return the bytes.
        """
        data = self._with_credentials(payload or {})
        response = await self.client.post(endpoint, json=data)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            # An error envelope came back instead of the binary payload.
            try:
                body = response.json()
            except ValueError:
                return response.content
            if isinstance(body, dict) and body.get("Status", 0) not in (0, "0", "Success"):
                message = (
                    body.get("UserErrorMessage")
                    or body.get("TechnicalErrorDetails")
                    or f"Status={body.get('Status')}"
                )
                raise Exception(f"SUMIT API error: {message}")
        return response.content

    # ==================== Conversion helpers ====================

    @staticmethod
    def _to_int(value: Any) -> Any:
        """Convert an id-like value to int when possible (SUMIT ids are ints)."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        """Parse a SUMIT date string into a date (best effort)."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse a SUMIT date string into a datetime (best effort)."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _map_document_type(value: Any) -> str:
        """Map a local document type name to SUMIT's DocumentType enum name."""
        if value is None:
            return "Invoice"
        return _DOCUMENT_TYPE_TO_SUMIT.get(str(value).lower(), str(value))

    @staticmethod
    def _unmap_document_type(value: Any) -> str:
        """Map SUMIT's DocumentType enum name back to the local name."""
        if value is None:
            return "invoice"
        return _DOCUMENT_TYPE_FROM_SUMIT.get(str(value), str(value).lower())

    @staticmethod
    def _map_language(value: Optional[str]) -> str:
        return _LANGUAGE_TO_SUMIT.get((value or "he").lower(), "Hebrew")

    def _customer_ref(self, customer_id: Any) -> Dict[str, Any]:
        """
        Build the Accounting_Typed_Customer reference SUMIT expects.
        Numeric ids reference an existing customer; other values are
        searched/created by name.
        """
        customer_id_int = self._to_int(customer_id)
        if isinstance(customer_id_int, int):
            return {"ID": customer_id_int}
        return {"Name": str(customer_id), "SearchMode": "Automatic"}

    def _customer_details(self, customer: CustomerRequest) -> Dict[str, Any]:
        """Build SUMIT's Accounting_Typed_Customer from a CustomerRequest."""
        details: Dict[str, Any] = {"Name": customer.name, "SearchMode": "Automatic"}
        if customer.email:
            details["EmailAddress"] = str(customer.email)
        if customer.phone:
            details["Phone"] = customer.phone
        if customer.tax_id:
            details["CompanyNumber"] = customer.tax_id
        if customer.address:
            if customer.address.street:
                details["Address"] = customer.address.street
            if customer.address.city:
                details["City"] = customer.address.city
            if customer.address.zip_code:
                details["ZipCode"] = customer.address.zip_code
        return details

    def _customer_response(
        self,
        customer_id: Any,
        customer: CustomerRequest
    ) -> CustomerResponse:
        return CustomerResponse(
            customer_id=str(customer_id),
            name=customer.name,
            email=str(customer.email) if customer.email else None,
            phone=customer.phone,
            tax_id=customer.tax_id,
            created_at=datetime.now(),
        )

    @staticmethod
    def _extract_vat(doc: Dict[str, Any]) -> Optional[Decimal]:
        """Return an explicit VAT amount from a SUMIT list record, or None.

        SUMIT's list payload historically omits VAT, but guard for variants that
        expose it so a real value always wins over derivation.
        """
        for key in ("VAT", "Vat", "VATAmount", "VatAmount", "DocumentVAT",
                    "TotalVAT", "VAT_Amount"):
            if doc.get(key) is not None:
                try:
                    return Decimal(str(doc.get(key)))
                except (TypeError, ValueError):
                    continue
        return None

    def _document_response_from_list(self, doc: Dict[str, Any]) -> DocumentResponse:
        """Build a DocumentResponse from a /accounting/documents/list/ record."""
        total = Decimal(str(doc.get("DocumentValue") or 0))
        issue = self._parse_date(doc.get("Date")) or date.today()
        # SUMIT's list payload returns only the VAT-inclusive gross. Prefer an
        # explicit VAT field if the response ever carries one; otherwise recover the
        # split deterministically from the gross + date so downstream VAT isn't zeroed.
        vat_amount = self._extract_vat(doc)
        if vat_amount is None:
            from ..services.vat_utils import split_inclusive
            _subtotal, vat_amount = split_inclusive(total, issue)
        if doc.get("IsDraft"):
            status = "draft"
        elif doc.get("IsClosed"):
            status = "closed"
        else:
            status = "open"
        document_id = str(doc.get("DocumentID", ""))
        return DocumentResponse(
            document_id=document_id,
            document_number=str(doc.get("DocumentNumber") or ""),
            document_type=self._unmap_document_type(doc.get("Type")),
            customer_id=str(doc.get("CustomerID") or ""),
            total_amount=total,
            vat_amount=vat_amount,
            status=status,
            issue_date=issue,
            due_date=self._parse_date(doc.get("DueDate")),
            pdf_url=doc.get("DocumentDownloadURL"),
            # convenience aliases used by sync services
            id=document_id,
            total=total,
            date=issue,
            customer_name=doc.get("CustomerName"),
            currency=str(doc.get("Currency") or "ILS"),
            allocation_number=(str(doc.get("AssignmentNumber")).strip()
                               if doc.get("AssignmentNumber") else None),
        )

    def _payment_response(
        self,
        payment: Dict[str, Any],
        fallback_currency: str = "ILS"
    ) -> PaymentResponse:
        """Build a PaymentResponse from SUMIT's Billing Payment object."""
        method = payment.get("PaymentMethod") or {}
        payment_id = str(payment.get("ID", ""))
        when = self._parse_datetime(payment.get("Date"))
        return PaymentResponse(
            payment_id=payment_id,
            transaction_id=payment_id,
            amount=Decimal(str(payment.get("Amount") or 0)),
            currency=str(payment.get("Currency") or fallback_currency),
            status="completed" if payment.get("ValidPayment") else "failed",
            created_at=when or datetime.now(),
            authorization_number=payment.get("AuthNumber"),
            last_4_digits=method.get("CreditCard_LastDigits"),
            # convenience aliases used by sync services
            id=payment_id,
            customer_id=(
                str(payment.get("CustomerID"))
                if payment.get("CustomerID") is not None else None
            ),
            date=when,
            description=payment.get("StatusDescription") or payment.get("Status"),
            payment_method=(
                str(method.get("Type")) if method.get("Type") is not None else None
            ),
        )

    def _payment_method_payload(self, charge: ChargeRequest) -> Dict[str, Any]:
        """Build SUMIT's PaymentMethod / SingleUseToken fields from a ChargeRequest."""
        payload: Dict[str, Any] = {}
        if charge.card is not None:
            payload["PaymentMethod"] = {
                "CreditCard_Number": charge.card.card_number,
                "CreditCard_ExpirationMonth": self._to_int(charge.card.expiry_month),
                "CreditCard_ExpirationYear": self._to_int(charge.card.expiry_year),
                "CreditCard_CVV": charge.card.cvv,
                "Type": "CreditCard",
            }
        elif charge.payment_method:
            token = str(charge.payment_method)
            if token.isdigit():
                # Existing payment method id stored at SUMIT
                payload["PaymentMethod"] = {"ID": int(token), "Type": "CreditCard"}
            else:
                # Card token (vault) — single-use tokens also work here via
                # the dedicated SingleUseToken field.
                payload["PaymentMethod"] = {
                    "CreditCard_Token": token,
                    "Type": "CreditCard",
                }
        return payload

    @staticmethod
    def _charge_items(charge: ChargeRequest) -> List[Dict[str, Any]]:
        """Build SUMIT's ChargeItem list from a ChargeRequest."""
        description = charge.description or "General charge"
        return [{
            "Item": {"Name": description, "SearchMode": "Automatic"},
            "Quantity": 1,
            "UnitPrice": float(charge.amount),
            "Total": float(charge.amount),
            "Currency": charge.currency,
            "Description": description,
        }]

    # ==================== Base Integration Methods ====================

    async def test_connection(self) -> bool:
        """Test API connection"""
        try:
            result = await self._make_request("/website/companies/getdetails/")
            # SUMIT returns HTTP 200 with an error envelope on bad
            # credentials; Status == 0 is the only success signal.
            status = result.get("Status") if isinstance(result, dict) else None
            if status is not None:
                return status in (0, "0", "Success")
            return bool(result)
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False

    async def get_balance(self) -> Dict[str, Any]:
        """Get account balance information"""
        raise Exception(
            "SUMIT API does not expose an account balance endpoint; "
            "use get_debt_report() (/accounting/documents/getdebtreport/) for "
            "outstanding customer debt, or list_payments() for received payments."
        )

    # ==================== Accounting - Customers ====================

    async def create_customer(self, customer: CustomerRequest) -> CustomerResponse:
        """
        Create a new customer (POST /accounting/customers/create/)

        Args:
            customer: Customer details

        Returns:
            CustomerResponse with created customer details
        """
        data = await self._post(
            "/accounting/customers/create/",
            {"Details": self._customer_details(customer)}
        )
        return self._customer_response(data.get("CustomerID", ""), customer)

    async def update_customer(
        self,
        customer_id: str,
        customer: CustomerRequest
    ) -> CustomerResponse:
        """
        Update existing customer (POST /accounting/customers/update/)

        Args:
            customer_id: Customer ID to update
            customer: Updated customer details

        Returns:
            CustomerResponse with updated customer details
        """
        details = self._customer_details(customer)
        details["ID"] = self._to_int(customer_id)
        details["SearchMode"] = "None"
        data = await self._post(
            "/accounting/customers/update/",
            {"Details": details}
        )
        return self._customer_response(data.get("CustomerID", customer_id), customer)

    async def get_customer_details_url(self, customer_id: str) -> str:
        """
        Get URL to customer details page
        (POST /accounting/customers/getdetailsurl/)

        Args:
            customer_id: Customer ID

        Returns:
            URL string
        """
        data = await self._post(
            "/accounting/customers/getdetailsurl/",
            {"CustomerID": self._to_int(customer_id)}
        )
        return data.get("CustomerHistoryURL", "")

    async def create_customer_remark(
        self,
        remark: CustomerRemarkRequest
    ) -> Dict[str, Any]:
        """
        Add remark to customer (POST /accounting/customers/createremark/)

        Args:
            remark: Remark details

        Returns:
            Response dict (contains RemarkID)
        """
        return await self._post(
            "/accounting/customers/createremark/",
            {
                "CustomerID": self._to_int(remark.customer_id),
                "Content": remark.remark,
            }
        )

    # ==================== Accounting - Documents ====================

    async def send_document(
        self,
        request: SendDocumentRequest
    ) -> Dict[str, Any]:
        """
        Send document by email (POST /accounting/documents/send/)

        Args:
            request: Send document request details

        Returns:
            Response dict
        """
        payload: Dict[str, Any] = {
            "EntityID": self._to_int(request.document_id),
            "Original": True,
        }
        if request.recipient_email:
            payload["EmailAddress"] = str(request.recipient_email)
        # SUMIT supports a personal message; there is no separate subject field.
        message_parts = [p for p in (request.subject, request.message) if p]
        if message_parts:
            payload["PersonalMessage"] = "\n".join(message_parts)
        return await self._post("/accounting/documents/send/", payload)

    async def get_document_pdf(self, document_id: str) -> bytes:
        """
        Get document PDF (POST /accounting/documents/getpdf/ — binary response)

        Args:
            document_id: Document ID

        Returns:
            PDF content as bytes
        """
        return await self._post_binary(
            "/accounting/documents/getpdf/",
            {
                "DocumentID": self._to_int(document_id),
                "Original": True,
            }
        )

    async def get_document_details(self, document_id: str) -> DocumentResponse:
        """
        Get document details (POST /accounting/documents/getdetails/)

        Args:
            document_id: Document ID

        Returns:
            DocumentResponse with document details
        """
        data = await self._post(
            "/accounting/documents/getdetails/",
            {"DocumentID": self._to_int(document_id)}
        )
        document = data.get("Document") or {}
        items = data.get("Items") or []
        customer = document.get("Customer") or {}
        total = Decimal(str(document.get("DocumentValue") or 0))
        vat = Decimal("0")
        for item in items:
            vat += Decimal(str(item.get("VAT") or 0))
        issue = self._parse_date(document.get("Date")) or date.today()
        if document.get("IsDraft"):
            status = "draft"
        elif document.get("IsClosed"):
            status = "closed"
        else:
            status = "open"
        doc_id = str(data.get("DocumentID", document_id))
        return DocumentResponse(
            document_id=doc_id,
            document_number=str(data.get("DocumentNumber") or ""),
            document_type=self._unmap_document_type(document.get("Type")),
            customer_id=str(customer.get("ID") or ""),
            total_amount=total,
            vat_amount=vat,
            status=status,
            issue_date=issue,
            due_date=self._parse_date(document.get("DueDate")),
            pdf_url=data.get("DocumentDownloadURL"),
            id=doc_id,
            total=total,
            date=issue,
            customer_name=customer.get("Name"),
            currency=str(document.get("Currency") or "ILS"),
            allocation_number=(str(document.get("AssignmentNumber")).strip()
                               if document.get("AssignmentNumber") else None),
        )

    async def create_document(
        self,
        document: DocumentRequest
    ) -> DocumentResponse:
        """
        Create a new document — invoice, receipt, quote, etc.
        (POST /accounting/documents/create/)

        Args:
            document: Document details

        Returns:
            DocumentResponse with created document
        """
        details: Dict[str, Any] = {
            "Customer": self._customer_ref(document.customer_id),
            "Type": self._map_document_type(document.document_type),
            "Language": self._map_language(document.language),
            "Currency": document.currency or "ILS",
        }
        if document.issue_date:
            details["Date"] = document.issue_date.isoformat()
        if document.due_date:
            details["DueDate"] = document.due_date.isoformat()
        if document.notes:
            details["Description"] = document.notes

        items: List[Dict[str, Any]] = []
        total = Decimal("0")
        for item in document.items:
            quantity = item.quantity or Decimal("1")
            unit_price = item.price
            if item.discount:
                unit_price = unit_price * (Decimal("1") - item.discount / Decimal("100"))
            line_total = quantity * unit_price
            total += line_total
            sumit_item: Dict[str, Any] = {
                "Quantity": float(quantity),
                "UnitPrice": float(unit_price),
                "TotalPrice": float(line_total),
                "Description": item.description,
            }
            item_id = self._to_int(item.item_id) if item.item_id else None
            if isinstance(item_id, int):
                sumit_item["Item"] = {"ID": item_id}
            else:
                sumit_item["Item"] = {
                    "Name": item.description,
                    "SearchMode": "Automatic",
                }
            items.append(sumit_item)

        payload: Dict[str, Any] = {
            "Details": details,
            "Items": items,
            "VATIncluded": True,
        }

        data = await self._post("/accounting/documents/create/", payload)
        doc_id = str(data.get("DocumentID", ""))
        issue = document.issue_date or date.today()
        return DocumentResponse(
            document_id=doc_id,
            document_number=str(data.get("DocumentNumber") or ""),
            document_type=document.document_type,
            customer_id=str(data.get("CustomerID") or document.customer_id),
            total_amount=total,
            vat_amount=Decimal("0"),
            status="open",
            issue_date=issue,
            due_date=document.due_date,
            pdf_url=data.get("DocumentDownloadURL"),
            id=doc_id,
            total=total,
            date=issue,
            currency=document.currency or "ILS",
        )

    async def add_expense(self, expense: ExpenseRequest) -> Dict[str, Any]:
        """
        Add expense (POST /accounting/documents/addexpense/)

        Args:
            expense: Expense details

        Returns:
            Response dict (contains expense_id / DocumentID)
        """
        amount = expense.amount
        if expense.vat_amount:
            amount = amount + expense.vat_amount
        payload: Dict[str, Any] = {
            "Supplier": {
                "Name": expense.supplier_name,
                "SearchMode": "Automatic",
            },
            "Date": expense.expense_date.isoformat(),
            "Lines": [{
                "Item": {
                    "Name": expense.category or "General expense",
                    "SearchMode": "Automatic",
                },
                "Amount": float(amount),
            }],
        }
        if expense.notes:
            payload["Description"] = expense.notes
        if expense.receipt_file:
            payload["ExpenseFile"] = expense.receipt_file
            payload["ExpenseFilename"] = "receipt.pdf"
        data = await self._post("/accounting/documents/addexpense/", payload)
        document_id = data.get("DocumentID")
        result = dict(data)
        result["expense_id"] = str(document_id) if document_id is not None else None
        return result

    async def get_document_supplier(self, document_id: str) -> str:
        """Return the supplier/customer name on a document (from getdetails)."""
        details = await self.get_document_supplier_details(document_id)
        return details["name"]

    async def get_document_supplier_details(self, document_id: str) -> Dict[str, Any]:
        """Return supplier name + tax id (CompanyNumber) + VAT + total for a
        document — everything PCN874 needs, only reachable via getdetails.
        """
        data = await self._post(
            "/accounting/documents/getdetails/",
            {"DocumentID": self._to_int(document_id)}
        )
        document = data.get("Document") or {}
        customer = document.get("Customer") or {}
        items = data.get("Items") or []
        # מע"מ: קודם סכימת Items, ואז fallback לשדות ברמת מסמך שמכילים 'vat'
        vat = Decimal("0")
        for it in items:
            vat += Decimal(str(it.get("VAT") or 0))
        if vat == 0:
            for k, v in document.items():
                if "vat" in k.lower() and v:
                    try:
                        vat = abs(Decimal(str(v)))
                        break
                    except Exception:
                        pass
        total = abs(Decimal(str(document.get("DocumentValue") or 0)))
        # שם פריט ההוצאה ב-SUMIT (למשל "הוצאות נסיעה") — אות הסיווג האמין,
        # נבחר הפריט הראשון עם שם לא-ריק.
        item_name = ""
        for it in items:
            nm = ((it.get("Item") or {}).get("Name") or "").strip()
            if nm:
                item_name = nm
                break
        return {
            "name": (customer.get("Name") or "").strip(),
            "tax_id": str(customer.get("CompanyNumber") or "").strip(),
            "vat": float(vat),
            "total": float(total),
            "no_vat": bool(customer.get("NoVAT")),
            "item_name": item_name,
        }

    async def cancel_document(self, document_id: str) -> Dict[str, Any]:
        """
        Cancel a document (POST /accounting/documents/cancel/)

        Args:
            document_id: Document ID to cancel

        Returns:
            Response dict
        """
        return await self._post(
            "/accounting/documents/cancel/",
            {
                "DocumentID": self._to_int(document_id),
                # Description is required by the API.
                "Description": "Cancelled via API",
            }
        )

    async def move_document_to_books(self, document_id: str) -> Dict[str, Any]:
        """
        Move document to books — finalize a draft document
        (POST /accounting/documents/movetobooks/)

        Args:
            document_id: Document ID

        Returns:
            Response dict
        """
        return await self._post(
            "/accounting/documents/movetobooks/",
            {"DocumentID": self._to_int(document_id)}
        )

    async def get_debt(self, customer_id: str) -> Dict[str, Any]:
        """
        Get customer debt information (POST /accounting/documents/getdebt/)

        Args:
            customer_id: Customer ID

        Returns:
            Debt information dict (contains "Debt")
        """
        return await self._post(
            "/accounting/documents/getdebt/",
            {"CustomerID": self._to_int(customer_id)}
        )

    async def get_debt_report(
        self,
        request: DebtReportRequest
    ) -> List[Dict[str, Any]]:
        """
        Get customers debt report (POST /accounting/documents/getdebtreport/)

        Args:
            request: Debt report request parameters

        Returns:
            List of debt records
        """
        # DebitSource/CreditSource הם שדות-חובה (enum מספרי) שבוחרים אילו סוגי
        # מסמכים נספרים כחיוב/זיכוי (אחרת ה-API מחזיר "שדה חסר: DebitSource").
        # 2/1 מחזיר את רשומות החוב; ערכים אחרים (1/1, 2/2) החזירו 0 בבדיקה.
        payload: Dict[str, Any] = {"DebitSource": 2, "CreditSource": 1}
        if request.include_paid:
            payload["IncludeDraftDocuments"] = True
        data = await self._post("/accounting/documents/getdebtreport/", payload)
        debts = data.get("Debts") or []
        results: List[Dict[str, Any]] = []
        for debt in debts:
            customer_id = debt.get("CustomerID")
            if request.customer_id and str(customer_id) != str(request.customer_id):
                continue
            results.append({
                "CustomerID": customer_id,
                "Debt": debt.get("Debt"),
                # convenience aliases used by sync services
                "customer_id": str(customer_id) if customer_id is not None else "",
                "amount": debt.get("Debt", 0),
            })
        return results

    async def list_documents(
        self,
        request: DocumentListRequest
    ) -> List[DocumentResponse]:
        """
        List documents with filters (POST /accounting/documents/list/)

        Args:
            request: List request with filters

        Returns:
            List of DocumentResponse
        """
        payload: Dict[str, Any] = {"IncludeDrafts": True}
        type_names = request.document_types or (
            [request.document_type] if request.document_type else None
        )
        if type_names:
            # SUMIT's documents/list accepts the numeric Accounting_Typed_DocumentType
            # codes directly (e.g. 0=Invoice, 5=Receipt, 15=ExpenseInvoice). Filtering by
            # those numeric codes is reliable; the enum *name* filter is not (e.g.
            # "ExpenseInvoice" returns nothing). Pass an int through unchanged; map names.
            def _doc_type(t):
                if isinstance(t, int):
                    return t
                if isinstance(t, str) and t.lstrip("-").isdigit():
                    return int(t)
                return self._map_document_type(t)
            payload["DocumentTypes"] = [_doc_type(t) for t in type_names]
        if request.from_date:
            payload["DateFrom"] = request.from_date.isoformat()
        if request.to_date:
            payload["DateTo"] = request.to_date.isoformat()
        if request.limit or request.offset:
            payload["Paging"] = {
                "StartIndex": request.offset or 0,
                "PageSize": request.limit or 100,
            }
        data = await self._post("/accounting/documents/list/", payload)
        documents = data.get("Documents") or []
        results = [self._document_response_from_list(doc) for doc in documents]
        if request.status:
            results = [doc for doc in results if doc.status == request.status]
        return results

    # ==================== Accounting - General ====================

    async def verify_bank_account(
        self,
        verification: BankAccountVerification
    ) -> Dict[str, Any]:
        """
        Verify bank account details (POST /accounting/general/verifybankaccount/)

        Args:
            verification: Bank account details to verify

        Returns:
            Verification result (Result / ValidBranch / IsLimitedAccount)
        """
        return await self._post(
            "/accounting/general/verifybankaccount/",
            {
                "BankCode": self._to_int(verification.bank_number),
                "BranchCode": self._to_int(verification.branch_number),
                "AccountNumber": self._to_int(verification.account_number),
            }
        )

    async def get_vat_rate(self, date: Optional[date] = None) -> Decimal:
        """
        Get VAT rate for a specific date (POST /accounting/general/getvatrate/)

        Args:
            date: Date to get VAT rate for (default: today)

        Returns:
            VAT rate as Decimal
        """
        payload: Dict[str, Any] = {}
        if date:
            payload["Date"] = date.isoformat()
        data = await self._post("/accounting/general/getvatrate/", payload)
        return Decimal(str(data.get("Rate", "0")))

    async def get_exchange_rate(
        self,
        request: ExchangeRateRequest
    ) -> ExchangeRateResponse:
        """
        Get foreign currency exchange rate
        (POST /accounting/general/getexchangerate/)

        Args:
            request: Exchange rate request

        Returns:
            ExchangeRateResponse
        """
        payload: Dict[str, Any] = {
            "Currency_From": request.from_currency,
            "Currency_To": request.to_currency,
        }
        if request.date:
            payload["Date"] = request.date.isoformat()
        data = await self._post("/accounting/general/getexchangerate/", payload)
        return ExchangeRateResponse(
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            rate=Decimal(str(data.get("Rate", "0"))),
            date=request.date or date.today(),
        )

    async def update_settings(self, settings: SettingsUpdate) -> Dict[str, Any]:
        """
        Update accounting application settings
        (POST /accounting/general/updatesettings/)

        Args:
            settings: Settings to update — keys must match SUMIT's
                Accounting_General_UpdateSettings_Request fields
                (e.g. DocumentsEmailAddress, AccountantEmail, DocumentsTheme)

        Returns:
            Response dict
        """
        return await self._post(
            "/accounting/general/updatesettings/",
            dict(settings.settings)
        )

    async def get_next_document_number(self, document_type: str) -> int:
        """
        Get next document number for a document type
        (POST /accounting/general/getnextdocumentnumber/)

        Args:
            document_type: Type of document

        Returns:
            Next document number
        """
        data = await self._post(
            "/accounting/general/getnextdocumentnumber/",
            {"Type": self._map_document_type(document_type)}
        )
        return int(data.get("NextDocumentNumber", 1))

    async def set_next_document_number(
        self,
        request: DocumentNumberRequest
    ) -> Dict[str, Any]:
        """
        Set next document number (POST /accounting/general/setnextdocumentnumber/)

        Args:
            request: Document number request

        Returns:
            Response dict
        """
        return await self._post(
            "/accounting/general/setnextdocumentnumber/",
            {
                "Type": self._map_document_type(request.document_type),
                "NextDocumentNumber": request.next_number or 1,
            }
        )

    # ==================== Accounting - Income Items ====================

    async def create_income_item(
        self,
        item: IncomeItemRequest
    ) -> IncomeItemResponse:
        """
        Create income item (POST /accounting/incomeitems/create/)

        Args:
            item: Income item details

        Returns:
            IncomeItemResponse
        """
        income_item: Dict[str, Any] = {
            "Name": item.name,
            "Price": float(item.price),
            "Currency": item.currency or "ILS",
        }
        if item.description:
            income_item["Description"] = item.description
        data = await self._post(
            "/accounting/incomeitems/create/",
            {"IncomeItem": income_item}
        )
        entity_id = str(data.get("EntityID", ""))
        return IncomeItemResponse(
            item_id=entity_id,
            name=item.name,
            description=item.description,
            price=item.price,
            currency=item.currency or "ILS",
            vat_rate=item.vat_rate,
            id=entity_id,
        )

    async def list_income_items(self) -> List[IncomeItemResponse]:
        """
        List all income items (POST /accounting/incomeitems/list/)

        Returns:
            List of IncomeItemResponse
        """
        data = await self._post("/accounting/incomeitems/list/", {})
        items = data.get("IncomeItems") or []
        results = []
        for item in items:
            item_id = str(item.get("ID", ""))
            results.append(IncomeItemResponse(
                item_id=item_id,
                name=item.get("Name") or "",
                description=item.get("Description"),
                price=Decimal(str(item.get("Price") or 0)),
                currency="ILS",
                id=item_id,
            ))
        return results

    # ==================== Credit Card Terminal - Billing ====================

    async def load_billing_transactions(
        self,
        request: BillingTransactionRequest
    ) -> List[BillingTransaction]:
        """
        NOT SUPPORTED by the real SUMIT API as a date-range listing.

        /creditguy/billing/load/ exists but it SUBMITS a batch of card
        charges (requires card tokens and amounts) — it does not list
        historical terminal transactions for a date range.
        """
        raise Exception(
            "SUMIT API does not expose a listing of terminal transactions by "
            "date range; /creditguy/billing/load/ submits a batch of card "
            "charges. Use list_payments() (/billing/payments/list/) to fetch "
            "received payments instead."
        )

    async def process_billing_transactions(
        self,
        transaction_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Process loaded billing batches (POST /creditguy/billing/process/)

        The real API processes a batch by its BillingIdentifier (set when
        the batch was loaded), so each entry here is treated as a billing
        batch identifier.

        Args:
            transaction_ids: List of billing batch identifiers to process

        Returns:
            Processing result per identifier
        """
        results: Dict[str, Any] = {}
        for identifier in transaction_ids:
            data = await self._post(
                "/creditguy/billing/process/",
                {"BillingIdentifier": str(identifier)}
            )
            results[str(identifier)] = data
        return {"results": results}

    async def get_billing_status(self, transaction_id: str) -> Dict[str, Any]:
        """
        Get billing process status (POST /creditguy/billing/getstatus/)

        Args:
            transaction_id: Billing batch identifier (BillingIdentifier)

        Returns:
            Status dict
        """
        return await self._post(
            "/creditguy/billing/getstatus/",
            {
                "BillingIdentifier": str(transaction_id),
                "ListTransactions": True,
            }
        )

    # ==================== Credit Card Terminal - Gateway ====================

    async def create_card_transaction(
        self,
        transaction: TransactionRequest
    ) -> TransactionResponse:
        """
        Create credit card transaction (POST /creditguy/gateway/transaction/)

        Note: SUMIT recommends charge_customer() (/billing/payments/charge/)
        for common scenarios; the gateway requires card data or a token.

        Args:
            transaction: Transaction details

        Returns:
            TransactionResponse
        """
        payload: Dict[str, Any] = {
            "ParamJ": "Charge",
            "Amount": float(transaction.amount),
            "Currency": transaction.currency or "ILS",
        }
        if transaction.description:
            payload["CustomData_1"] = transaction.description
        data = await self._post("/creditguy/gateway/transaction/", payload)
        success = bool(data.get("Success"))
        return TransactionResponse(
            transaction_id=str(data.get("TransactionID", "")),
            status="completed" if success else "failed",
            amount=transaction.amount,
            currency=transaction.currency or "ILS",
            created_at=datetime.now(),
        )

    async def get_transaction(self, transaction_id: str) -> TransactionResponse:
        """
        Get transaction details (POST /creditguy/gateway/gettransaction/)

        Args:
            transaction_id: Transaction ID

        Returns:
            TransactionResponse
        """
        data = await self._post(
            "/creditguy/gateway/gettransaction/",
            {"ID": self._to_int(transaction_id)}
        )
        return TransactionResponse(
            transaction_id=str(transaction_id),
            status=str(data.get("Description") or data.get("Code") or "unknown"),
            amount=Decimal(str(data.get("Amount") or 0)),
            currency="ILS",
            created_at=datetime.now(),
        )

    async def begin_redirect(
        self,
        transaction_id: str,
        return_url: str
    ) -> str:
        """
        Begin redirect flow for transaction
        (POST /creditguy/gateway/beginredirect/)

        Args:
            transaction_id: Transaction identifier (sent as Identifier)
            return_url: URL to return to after payment

        Returns:
            Redirect URL
        """
        data = await self._post(
            "/creditguy/gateway/beginredirect/",
            {
                "Mode": "Charge",
                "Identifier": str(transaction_id),
                "RedirectURL": return_url,
            }
        )
        return data.get("RedirectURL", "")

    async def get_reference_numbers(
        self,
        transaction_ids: List[str]
    ) -> Dict[str, str]:
        """
        Get reference numbers for transactions
        (POST /creditguy/gateway/getreferencenumbers/)

        Args:
            transaction_ids: List of transaction IDs

        Returns:
            Dict mapping transaction_id to reference_number
        """
        data = await self._post(
            "/creditguy/gateway/getreferencenumbers/",
            {"IDs": [self._to_int(t) for t in transaction_ids]}
        )
        references = data.get("ReferenceNumbers_ByID") or []
        return {
            str(tx_id): str(ref)
            for tx_id, ref in zip(transaction_ids, references)
        }

    # ==================== Credit Card Terminal - Vault ====================

    async def tokenize_card(
        self,
        request: TokenizeCardRequest
    ) -> TokenResponse:
        """
        Tokenize credit card for future use (POST /creditguy/vault/tokenize/)

        Args:
            request: Card tokenization request

        Returns:
            TokenResponse with card token
        """
        data = await self._post(
            "/creditguy/vault/tokenize/",
            {
                "CardNumber": request.card_number,
                "ForceFormatPreservingToken": "",
            }
        )
        return TokenResponse(
            token=data.get("Token") or data.get("FormatPreservingToken") or "",
            last_4_digits=request.card_number[-4:],
            expiry_date=f"{request.expiry_month}/{request.expiry_year}",
            card_brand="Unknown",
        )

    async def tokenize_single_use(
        self,
        request: TokenizeCardRequest
    ) -> TokenResponse:
        """
        Tokenize card for single use
        (POST /creditguy/vault/tokenizesingleusejson/)

        Args:
            request: Card tokenization request

        Returns:
            TokenResponse with single-use token
        """
        payload: Dict[str, Any] = {
            "CardNumber": request.card_number,
            "ExpirationMonth": self._to_int(request.expiry_month),
            "ExpirationYear": self._to_int(request.expiry_year),
            "CVV": request.cvv,
        }
        data = await self._post("/creditguy/vault/tokenizesingleusejson/", payload)
        return TokenResponse(
            token=data.get("SingleUseToken") or "",
            last_4_digits=request.card_number[-4:],
            expiry_date=f"{request.expiry_month}/{request.expiry_year}",
            card_brand="Unknown",
        )

    async def tokenize_single_use_json(
        self,
        card_data: Dict[str, Any]
    ) -> TokenResponse:
        """
        Tokenize card for single use (JSON format)
        (POST /creditguy/vault/tokenizesingleusejson/)

        Args:
            card_data: Card data dict using SUMIT's field names
                (CardNumber, ExpirationMonth, ExpirationYear, CVV, CitizenID)

        Returns:
            TokenResponse
        """
        data = await self._post(
            "/creditguy/vault/tokenizesingleusejson/",
            dict(card_data)
        )
        card_number = str(card_data.get("CardNumber") or card_data.get("card_number") or "")
        month = card_data.get("ExpirationMonth") or card_data.get("expiry_month") or ""
        year = card_data.get("ExpirationYear") or card_data.get("expiry_year") or ""
        return TokenResponse(
            token=data.get("SingleUseToken") or "",
            last_4_digits=card_number[-4:] if card_number else "",
            expiry_date=f"{month}/{year}",
            card_brand="Unknown",
        )

    # ==================== CRM - Data ====================

    @staticmethod
    def _entity_properties(entity: EntityRequest) -> Dict[str, Any]:
        return {field.field_name: field.field_value for field in entity.fields}

    async def create_entity(self, entity: EntityRequest) -> EntityResponse:
        """
        Create CRM entity (POST /crm/data/createentity/)

        Args:
            entity: Entity details

        Returns:
            EntityResponse
        """
        data = await self._post(
            "/crm/data/createentity/",
            {
                "Entity": {
                    "Folder": entity.folder_id,
                    "Properties": self._entity_properties(entity),
                }
            }
        )
        now = datetime.now()
        return EntityResponse(
            entity_id=str(data.get("EntityID", "")),
            folder_id=entity.folder_id,
            fields=self._entity_properties(entity),
            created_at=now,
            updated_at=now,
        )

    async def update_entity(
        self,
        entity_id: str,
        entity: EntityRequest
    ) -> EntityResponse:
        """
        Update CRM entity (POST /crm/data/updateentity/)

        Args:
            entity_id: Entity ID
            entity: Updated entity details

        Returns:
            EntityResponse
        """
        data = await self._post(
            "/crm/data/updateentity/",
            {
                "Entity": {
                    "ID": self._to_int(entity_id),
                    "Folder": entity.folder_id,
                    "Properties": self._entity_properties(entity),
                }
            }
        )
        now = datetime.now()
        return EntityResponse(
            entity_id=str(data.get("EntityID", entity_id)),
            folder_id=entity.folder_id,
            fields=self._entity_properties(entity),
            created_at=now,
            updated_at=now,
        )

    async def archive_entity(self, entity_id: str) -> Dict[str, Any]:
        """
        Archive CRM entity (POST /crm/data/archiveentity/)

        Args:
            entity_id: Entity ID

        Returns:
            Response dict
        """
        return await self._post(
            "/crm/data/archiveentity/",
            {"EntityID": self._to_int(entity_id)}
        )

    async def delete_entity(self, entity_id: str) -> Dict[str, Any]:
        """
        Delete CRM entity (POST /crm/data/deleteentity/)

        Args:
            entity_id: Entity ID

        Returns:
            Response dict
        """
        return await self._post(
            "/crm/data/deleteentity/",
            {"EntityID": self._to_int(entity_id)}
        )

    @staticmethod
    def _entity_response(entity: Dict[str, Any]) -> EntityResponse:
        now = datetime.now()
        return EntityResponse(
            entity_id=str(entity.get("ID", "")),
            folder_id=str(entity.get("Folder") or ""),
            fields=entity.get("Properties") or {},
            created_at=now,
            updated_at=now,
        )

    async def list_entities(
        self,
        folder_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[EntityResponse]:
        """
        List CRM entities in folder (POST /crm/data/listentities/)

        Args:
            folder_id: Folder name/identifier
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of EntityResponse
        """
        data = await self._post(
            "/crm/data/listentities/",
            {
                "Folder": folder_id,
                "LoadProperties": True,
                "Paging": {
                    "StartIndex": offset,
                    "PageSize": limit,
                },
            }
        )
        entities = data.get("Entities") or []
        return [self._entity_response(entity) for entity in entities]

    async def get_entity(self, entity_id: str) -> EntityResponse:
        """
        Get CRM entity details (POST /crm/data/getentity/)

        Args:
            entity_id: Entity ID

        Returns:
            EntityResponse
        """
        data = await self._post(
            "/crm/data/getentity/",
            {
                "EntityID": self._to_int(entity_id),
                "IncludeFields": True,
            }
        )
        entity = data.get("Entity") or {}
        if not entity.get("ID"):
            entity["ID"] = entity_id
        return self._entity_response(entity)

    async def count_entity_usage(self, entity_id: str) -> int:
        """
        Count entity usage (POST /crm/data/countentityusage/)

        Args:
            entity_id: Entity ID

        Returns:
            Usage count
        """
        data = await self._post(
            "/crm/data/countentityusage/",
            {"EntityID": self._to_int(entity_id)}
        )
        if isinstance(data, dict):
            for key in ("Count", "UsageCount", "count"):
                if key in data:
                    return int(data[key] or 0)
        return 0

    async def get_entity_print_html(self, entity_id: str) -> str:
        """
        Get entity as printable HTML (POST /crm/data/getentityprinthtml/)

        The real API requires both SchemaID and EntityID, so the entity's
        folder schema is resolved first via getentity + getfolder.

        Args:
            entity_id: Entity ID

        Returns:
            HTML string
        """
        entity_data = await self._post(
            "/crm/data/getentity/",
            {"EntityID": self._to_int(entity_id)}
        )
        folder_name = (entity_data.get("Entity") or {}).get("Folder")
        if not folder_name:
            raise Exception(
                f"SUMIT API error: could not resolve folder for entity {entity_id}"
            )
        folder_data = await self._post(
            "/crm/schema/getfolder/",
            {"Folder": folder_name}
        )
        schema_id = (folder_data.get("Folder") or {}).get("ID")
        content = await self._post_binary(
            "/crm/data/getentityprinthtml/",
            {
                "SchemaID": schema_id,
                "EntityID": self._to_int(entity_id),
            }
        )
        return content.decode("utf-8", errors="replace")

    async def get_entities_html(
        self,
        folder_id: str,
        entity_ids: List[str]
    ) -> str:
        """
        NOT SUPPORTED as specified: the real endpoint
        /crm/data/getentitieshtml/ renders a saved view (SchemaID + ViewID)
        and cannot render an arbitrary list of entity IDs.
        """
        raise Exception(
            "SUMIT API does not expose rendering of an arbitrary entity list; "
            "/crm/data/getentitieshtml/ requires a SchemaID and a saved ViewID. "
            "Use get_entity_print_html() per entity instead."
        )

    # ==================== CRM - Schema ====================

    async def get_folder(self, folder_id: str) -> FolderResponse:
        """
        Get CRM folder details and schema (POST /crm/schema/getfolder/)

        Args:
            folder_id: Folder name/identifier

        Returns:
            FolderResponse
        """
        data = await self._post(
            "/crm/schema/getfolder/",
            {
                "Folder": folder_id,
                "IncludeProperties": True,
            }
        )
        folder = data.get("Folder") or {}
        return FolderResponse(
            folder_id=str(folder.get("ID") or folder_id),
            folder_name=folder.get("Name") or "",
            field_definitions=data.get("Properties") or [],
        )

    async def list_folders(self) -> List[FolderResponse]:
        """
        List all CRM folders (POST /crm/schema/listfolders/)

        Returns:
            List of FolderResponse
        """
        data = await self._post("/crm/schema/listfolders/", {})
        folders = data.get("Folders") or []
        return [
            FolderResponse(
                folder_id=str(folder.get("ID", "")),
                folder_name=folder.get("Name") or "",
                field_definitions=[],
            )
            for folder in folders
        ]

    # ==================== CRM - Views ====================

    async def list_views(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        List views for a folder (POST /crm/views/listviews/)

        Args:
            folder_id: Folder ID (numeric)

        Returns:
            List of view definitions
        """
        data = await self._post(
            "/crm/views/listviews/",
            {"FolderID": self._to_int(folder_id)}
        )
        return data.get("Views") or []

    # ==================== Customer Service ====================

    async def create_ticket(self, ticket: TicketRequest) -> TicketResponse:
        """
        Create customer service ticket (POST /customerservice/tickets/create/)

        Note: this endpoint takes its parameters as query string values
        (including credentials), unlike the rest of the API.

        Args:
            ticket: Ticket details

        Returns:
            TicketResponse
        """
        params: Dict[str, Any] = {
            "Subject": ticket.subject,
            "ContentsText": ticket.description,
        }
        if ticket.customer_id:
            customer_id = self._to_int(ticket.customer_id)
            if isinstance(customer_id, int):
                params["CustomerID"] = customer_id
            else:
                params["CustomerName"] = str(ticket.customer_id)
        credentials = self._credentials()
        params["Credentials.APIKey"] = credentials.get("APIKey")
        if "CompanyID" in credentials:
            params["Credentials.CompanyID"] = credentials["CompanyID"]
        data = await self._post(
            "/customerservice/tickets/create/",
            {},
            params=params
        )
        return TicketResponse(
            ticket_id=str(data.get("TicketID", "")),
            subject=ticket.subject,
            status="open",
            created_at=datetime.now(),
        )

    # ==================== Email Subscriptions ====================

    async def list_mailing_lists(self) -> List[Dict[str, Any]]:
        """
        List all email mailing lists
        (POST /emailsubscriptions/mailinglists/list/)

        Returns:
            List of mailing list dicts
        """
        data = await self._post("/emailsubscriptions/mailinglists/list/", {})
        return data.get("MailingLists") or []

    async def add_to_mailing_list(
        self,
        request: EmailListRequest
    ) -> Dict[str, Any]:
        """
        Add contact to email mailing list
        (POST /emailsubscriptions/mailinglists/add/)

        Args:
            request: Email list request

        Returns:
            Response dict
        """
        payload: Dict[str, Any] = {
            "MailingListID": self._to_int(request.list_id),
            "EmailAddress": str(request.email),
        }
        if request.name:
            payload["Name"] = request.name
        return await self._post("/emailsubscriptions/mailinglists/add/", payload)

    # ==================== SMS ====================

    async def send_sms(self, sms: SMSRequest) -> SMSResponse:
        """
        Send single SMS (POST /sms/sms/send/)

        Args:
            sms: SMS details

        Returns:
            SMSResponse
        """
        payload: Dict[str, Any] = {
            "Recipient": sms.phone_number,
            "Text": sms.message,
        }
        if sms.sender_name:
            payload["Sender"] = sms.sender_name
        data = await self._post("/sms/sms/send/", payload)
        return SMSResponse(
            message_id=str(data.get("EntityID", "")),
            status="sent",
            sent_at=datetime.now(),
        )

    async def send_multiple_sms(
        self,
        messages: List[SMSRequest]
    ) -> List[SMSResponse]:
        """
        Send multiple SMS messages.

        SUMIT's /sms/sms/sendmultiple/ sends ONE text to many recipients,
        so messages sharing the same text are batched together and the
        rest are sent individually via /sms/sms/send/.

        Args:
            messages: List of SMS requests

        Returns:
            List of SMSResponse
        """
        results: List[SMSResponse] = []
        if not messages:
            return results
        texts = {(m.message, m.sender_name) for m in messages}
        if len(texts) == 1:
            payload: Dict[str, Any] = {
                "Recipients": [m.phone_number for m in messages],
                "Text": messages[0].message,
            }
            if messages[0].sender_name:
                payload["Sender"] = messages[0].sender_name
            data = await self._post("/sms/sms/sendmultiple/", payload)
            sent_at = datetime.now()
            entity_id = str(data.get("EntityID", ""))
            return [
                SMSResponse(message_id=entity_id, status="sent", sent_at=sent_at)
                for _ in messages
            ]
        for message in messages:
            results.append(await self.send_sms(message))
        return results

    async def list_sms_senders(self) -> List[str]:
        """
        List available SMS sender names (POST /sms/sms/listsenders/)

        Returns:
            List of sender names
        """
        data = await self._post("/sms/sms/listsenders/", {})
        return data.get("Senders") or []

    async def list_sms_mailing_lists(self) -> List[Dict[str, Any]]:
        """
        List SMS mailing lists (POST /sms/mailinglists/list/)

        Returns:
            List of mailing list dicts
        """
        data = await self._post("/sms/mailinglists/list/", {})
        return data.get("MailingLists") or []

    async def add_to_sms_mailing_list(
        self,
        list_id: str,
        phone_number: str,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add contact to SMS mailing list (POST /sms/mailinglists/add/)

        Args:
            list_id: Mailing list ID
            phone_number: Phone number
            name: Optional contact name

        Returns:
            Response dict
        """
        payload: Dict[str, Any] = {
            "MailingListID": self._to_int(list_id),
            "PhoneNumber": phone_number,
        }
        if name:
            payload["Name"] = name
        return await self._post("/sms/mailinglists/add/", payload)

    # ==================== Payments ====================

    async def charge_customer(self, charge: ChargeRequest) -> PaymentResponse:
        """
        Charge customer (POST /billing/payments/charge/)

        Args:
            charge: Charge request details

        Returns:
            PaymentResponse
        """
        payload: Dict[str, Any] = {
            "Customer": self._customer_ref(charge.customer_id or "Customer"),
            "Items": self._charge_items(charge),
            "VATIncluded": True,
        }
        payload.update(self._payment_method_payload(charge))
        if charge.installments and charge.installments > 1:
            payload["Payments_Count"] = charge.installments
        if charge.description:
            payload["DocumentDescription"] = charge.description
        data = await self._post("/billing/payments/charge/", payload)
        payment = data.get("Payment") or {}
        response = self._payment_response(payment, charge.currency)
        if not payment.get("ValidPayment"):
            status_description = (
                payment.get("StatusDescription") or payment.get("Status")
            )
            if status_description:
                self.logger.warning(f"SUMIT charge declined: {status_description}")
        return response

    async def multivendor_charge(
        self,
        charge: ChargeRequest,
        vendor_splits: List[Dict[str, Any]]
    ) -> PaymentResponse:
        """
        Charge with multivendor split (POST /billing/payments/multivendorcharge/)

        Args:
            charge: Charge request
            vendor_splits: List of vendor split definitions; each may contain
                company_id / api_key (or CompanyID / APIKey), amount and
                description

        Returns:
            PaymentResponse (for the first vendor's charge)
        """
        items: List[Dict[str, Any]] = []
        for split in vendor_splits:
            amount = split.get("amount", split.get("Total", charge.amount))
            description = (
                split.get("description")
                or split.get("Description")
                or charge.description
                or "General charge"
            )
            item: Dict[str, Any] = {
                "Item": {"Name": description, "SearchMode": "Automatic"},
                "Quantity": 1,
                "UnitPrice": float(amount),
                "Total": float(amount),
                "Currency": charge.currency,
                "Description": description,
            }
            company_id = split.get("company_id", split.get("CompanyID"))
            if company_id is not None:
                item["CompanyID"] = self._to_int(company_id)
            api_key = split.get("api_key", split.get("APIKey"))
            if api_key:
                item["APIKey"] = api_key
            items.append(item)
        payload: Dict[str, Any] = {
            "Customer": self._customer_ref(charge.customer_id or "Customer"),
            "Items": items or self._charge_items(charge),
            "VATIncluded": True,
        }
        payload.update(self._payment_method_payload(charge))
        if charge.installments and charge.installments > 1:
            payload["Payments_Count"] = charge.installments
        data = await self._post("/billing/payments/multivendorcharge/", payload)
        vendors = data.get("Vendors") or []
        payment = (vendors[0].get("Payment") if vendors else None) or {}
        return self._payment_response(payment, charge.currency)

    async def get_payment(self, payment_id: str) -> PaymentResponse:
        """
        Get payment details (POST /billing/payments/get/)

        Args:
            payment_id: Payment ID

        Returns:
            PaymentResponse
        """
        data = await self._post(
            "/billing/payments/get/",
            {"PaymentID": self._to_int(payment_id)}
        )
        return self._payment_response(data.get("Payment") or {})

    async def list_payments(
        self,
        customer_id: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[PaymentResponse]:
        """
        List payments with filters (POST /billing/payments/list/)

        Args:
            customer_id: Filter by customer (applied client-side; the API
                filters by date range only)
            from_date: Start date filter (required by the API; defaults to
                one year back)
            to_date: End date filter (defaults to today)
            limit: Maximum results
            offset: Pagination offset (StartIndex)

        Returns:
            List of PaymentResponse
        """
        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = date(to_date.year - 1, to_date.month, 1)
        data = await self._post(
            "/billing/payments/list/",
            {
                "Date_From": from_date.isoformat(),
                "Date_To": to_date.isoformat(),
                "StartIndex": offset,
            }
        )
        payments = data.get("Payments") or []
        results: List[PaymentResponse] = []
        for payment in payments:
            if customer_id is not None and str(payment.get("CustomerID")) != str(customer_id):
                continue
            results.append(self._payment_response(payment))
            if len(results) >= limit:
                break
        return results

    async def begin_payment_redirect(
        self,
        amount: Decimal,
        description: str,
        return_url: str,
        customer_id: Optional[str] = None
    ) -> str:
        """
        Begin payment redirect flow (POST /billing/payments/beginredirect/)

        Args:
            amount: Payment amount
            description: Payment description
            return_url: URL to return after payment
            customer_id: Optional customer ID

        Returns:
            Redirect URL
        """
        data = await self._post(
            "/billing/payments/beginredirect/",
            {
                "Customer": self._customer_ref(customer_id or "Customer"),
                "Items": [{
                    "Item": {"Name": description or "Payment", "SearchMode": "Automatic"},
                    "Quantity": 1,
                    "UnitPrice": float(amount),
                    "Total": float(amount),
                    "Description": description,
                }],
                "VATIncluded": True,
                "RedirectURL": return_url,
            }
        )
        return data.get("RedirectURL", "")

    @staticmethod
    def _payment_method_response(
        method: Dict[str, Any],
        is_default: bool
    ) -> PaymentMethodResponse:
        expiry = None
        month = method.get("CreditCard_ExpirationMonth")
        year = method.get("CreditCard_ExpirationYear")
        if month and year:
            expiry = f"{int(month):02d}/{year}"
        return PaymentMethodResponse(
            payment_method_id=str(method.get("ID", "")),
            type=str(method.get("Type") or "Other"),
            last_4_digits=method.get("CreditCard_LastDigits"),
            expiry_date=expiry,
            is_default=is_default,
        )

    async def get_payment_methods(
        self,
        customer_id: str
    ) -> List[PaymentMethodResponse]:
        """
        Get customer payment methods
        (POST /billing/paymentmethods/getforcustomer/)

        Args:
            customer_id: Customer ID

        Returns:
            List of PaymentMethodResponse (active method first)
        """
        data = await self._post(
            "/billing/paymentmethods/getforcustomer/",
            {
                "Customer": self._customer_ref(customer_id),
                "IncludeInactive": True,
            }
        )
        results: List[PaymentMethodResponse] = []
        active = data.get("PaymentMethod")
        if active:
            results.append(self._payment_method_response(active, True))
        for method in data.get("InactivePaymentMethods") or []:
            results.append(self._payment_method_response(method, False))
        return results

    async def set_payment_methods(
        self,
        customer_id: str,
        payment_method_id: str,
        is_default: bool = False
    ) -> Dict[str, Any]:
        """
        Set customer payment method
        (POST /billing/paymentmethods/setforcustomer/)

        Args:
            customer_id: Customer ID
            payment_method_id: Payment method ID, card token, or single-use
                token (from payments.js)
            is_default: Kept for compatibility (SUMIT keeps one active
                payment method per customer)

        Returns:
            Response dict
        """
        payload: Dict[str, Any] = {
            "Customer": self._customer_ref(customer_id),
        }
        token = str(payment_method_id)
        if token.isdigit():
            payload["PaymentMethod"] = {"ID": int(token), "Type": "CreditCard"}
        else:
            payload["SingleUseToken"] = token
        return await self._post("/billing/paymentmethods/setforcustomer/", payload)

    async def remove_payment_method(
        self,
        customer_id: str,
        payment_method_id: str
    ) -> Dict[str, Any]:
        """
        Remove customer payment method (POST /billing/paymentmethods/remove/)

        Note: SUMIT removes the customer's stored payment method; the
        payment_method_id parameter is kept for compatibility.

        Args:
            customer_id: Customer ID
            payment_method_id: Payment method ID (unused by the API)

        Returns:
            Response dict
        """
        return await self._post(
            "/billing/paymentmethods/remove/",
            {"Customer": self._customer_ref(customer_id)}
        )

    async def open_upay_terminal(
        self,
        amount: Decimal,
        description: str
    ) -> Dict[str, Any]:
        """
        NOT SUPPORTED as specified: SUMIT's
        /billing/generalbilling/openupayterminal/ onboards a NEW Upay
        merchant terminal (requires bank account details), it does not open
        a payment session for an amount.
        """
        raise Exception(
            "SUMIT API does not expose opening a Upay payment session for an "
            "amount; /billing/generalbilling/openupayterminal/ onboards a new "
            "Upay merchant terminal (requires BankCode/BranchCode/AccountNumber). "
            "Use charge_customer() or begin_payment_redirect() to take a payment."
        )

    async def setup_upay_credentials(
        self,
        credentials: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Setup existing Upay account credentials
        (POST /billing/generalbilling/setupaycredentials/)

        Args:
            credentials: Dict with email/password
                (EmailAddress/Password or email/password keys)

        Returns:
            Response dict
        """
        email = credentials.get("EmailAddress") or credentials.get("email")
        password = credentials.get("Password") or credentials.get("password")
        return await self._post(
            "/billing/generalbilling/setupaycredentials/",
            {
                "EmailAddress": email,
                "Password": password,
            }
        )

    # ==================== Recurring Payments ====================

    async def list_customer_recurring(
        self,
        customer_id: str
    ) -> List[RecurringPaymentResponse]:
        """
        List customer recurring items (POST /billing/recurring/listforcustomer/)

        Args:
            customer_id: Customer ID

        Returns:
            List of RecurringPaymentResponse
        """
        data = await self._post(
            "/billing/recurring/listforcustomer/",
            {
                "Customer": self._customer_ref(customer_id),
                "IncludeInactive": True,
            }
        )
        items = data.get("RecurringItems") or []
        results: List[RecurringPaymentResponse] = []
        for item in items:
            quantity = Decimal(str(item.get("Quantity") or 1))
            unit_price = Decimal(str(item.get("UnitPrice") or 0))
            results.append(RecurringPaymentResponse(
                recurring_id=str(item.get("ID", "")),
                customer_id=str(customer_id),
                amount=quantity * unit_price,
                currency="ILS",
                frequency="monthly",
                status=str(item.get("Status") or "unknown"),
                next_charge_date=self._parse_date(item.get("Date_NextBilling")),
            ))
        return results

    async def cancel_recurring(
        self,
        recurring_id: str,
        customer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cancel recurring payment item (POST /billing/recurring/cancel/)

        Args:
            recurring_id: Recurring customer item ID
            customer_id: Optional customer ID (the API expects the owning
                customer alongside the item id)

        Returns:
            Response dict
        """
        payload: Dict[str, Any] = {
            "RecurringCustomerItemID": self._to_int(recurring_id),
        }
        if customer_id is not None:
            payload["Customer"] = self._customer_ref(customer_id)
        return await self._post("/billing/recurring/cancel/", payload)

    async def charge_recurring(self, recurring_id: str) -> PaymentResponse:
        """
        NOT SUPPORTED as specified: SUMIT's /billing/recurring/charge/
        creates a NEW recurring charge (requires Customer, PaymentMethod
        and Items); there is no API to immediately charge an existing
        recurring item by its ID — SUMIT bills those automatically.
        """
        raise Exception(
            "SUMIT API does not expose charging an existing recurring item by "
            "ID; /billing/recurring/charge/ creates a new recurring charge "
            "(Customer + Items required) and SUMIT bills active recurring "
            "items automatically. Use charge_customer() for a one-off charge."
        )

    async def update_recurring(
        self,
        recurring_id: str,
        updates: RecurringPaymentRequest
    ) -> RecurringPaymentResponse:
        """
        Update customer recurring item (POST /billing/recurring/update/)

        Args:
            recurring_id: Recurring customer item ID
            updates: Updated details

        Returns:
            RecurringPaymentResponse
        """
        payload: Dict[str, Any] = {
            "Customer": self._customer_ref(updates.customer_id),
            "RecurringCustomerItemID": self._to_int(recurring_id),
            "UnitPrice": float(updates.amount),
        }
        if updates.start_date:
            payload["NextPaymentDate"] = updates.start_date.isoformat()
        if updates.end_date:
            payload["LastPaymentDate"] = updates.end_date.isoformat()
        await self._post("/billing/recurring/update/", payload)
        return RecurringPaymentResponse(
            recurring_id=str(recurring_id),
            customer_id=updates.customer_id,
            amount=updates.amount,
            currency=updates.currency,
            frequency=updates.frequency,
            status="active",
            next_charge_date=updates.start_date,
        )

    async def update_recurring_settings(
        self,
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update recurring billing application settings
        (POST /billing/recurring/updatesettings/)

        Args:
            settings: Settings dict — keys must match SUMIT's
                Recurring_UpdateSettings_Request fields (e.g.
                AutomaticBilling_CreditCard, AutomaticBilling_ChargeDocument)

        Returns:
            Response dict
        """
        return await self._post(
            "/billing/recurring/updatesettings/",
            dict(settings)
        )

    # ==================== Other Services ====================

    async def send_fax(self, fax: FaxRequest) -> Dict[str, Any]:
        """
        Send fax (POST /fax/fax/send/)

        Args:
            fax: Fax details (document_content must be base64 file bytes;
                document_url is not supported by the API)

        Returns:
            Response dict with fax entity ID
        """
        if not fax.document_content:
            raise Exception(
                "SUMIT API error: /fax/fax/send/ requires the file contents "
                "(base64) in document_content; sending by URL is not supported."
            )
        data = await self._post(
            "/fax/fax/send/",
            {
                "FaxNumber": fax.fax_number,
                "FileBytes": fax.document_content,
                "Filename": "document.pdf",
            }
        )
        result = dict(data)
        entity_id = data.get("EntityID")
        result["fax_id"] = str(entity_id) if entity_id is not None else None
        return result

    async def send_letter_by_click(
        self,
        recipient: Dict[str, str],
        content: str
    ) -> Dict[str, Any]:
        """
        NOT SUPPORTED: the SUMIT API does not expose a postal letter /
        mail service.
        """
        raise Exception(
            "SUMIT API does not expose a postal letter service; "
            "use send_fax() (/fax/fax/send/) or send_document() "
            "(/accounting/documents/send/) for delivering documents."
        )

    async def get_letter_tracking_code(self, letter_id: str) -> str:
        """
        NOT SUPPORTED: the SUMIT API does not expose a postal letter /
        mail service.
        """
        raise Exception(
            "SUMIT API does not expose a postal letter service or letter "
            "tracking codes."
        )

    async def create_scheduled_document(
        self,
        document: DocumentRequest,
        schedule_date: date
    ) -> Dict[str, Any]:
        """
        NOT SUPPORTED as specified: SUMIT's
        /scheduleddocuments/documents/createfromdocument/ schedules future
        documents from an EXISTING document (DocumentID), not from raw
        document details and a date.
        """
        raise Exception(
            "SUMIT API does not expose scheduling a document from raw details; "
            "/scheduleddocuments/documents/createfromdocument/ requires an "
            "existing DocumentID. Create the document with create_document() "
            "first, then schedule from it."
        )

    async def list_stock(self) -> List[StockItemResponse]:
        """
        List stock items (POST /stock/stock/list/)

        Returns:
            List of StockItemResponse
        """
        data = await self._post("/stock/stock/list/", {})
        items = data.get("Stock") or []
        now = datetime.now()
        return [
            StockItemResponse(
                item_id=str(item.get("ID", "")),
                name=item.get("Name") or "",
                quantity=Decimal(str(item.get("Stock") or 0)),
                unit="unit",
                last_updated=now,
            )
            for item in items
        ]

    async def subscribe_trigger(
        self,
        trigger_type: str,
        webhook_url: str
    ) -> Dict[str, Any]:
        """
        Subscribe to webhook trigger (POST /triggers/triggers/subscribe/)

        Args:
            trigger_type: Type of trigger to subscribe to
            webhook_url: Webhook URL to call

        Returns:
            Subscription dict
        """
        return await self._post(
            "/triggers/triggers/subscribe/",
            {
                "URL": webhook_url,
                "TriggerType": trigger_type,
            }
        )

    async def unsubscribe_trigger(self, subscription_id: str) -> Dict[str, Any]:
        """
        Unsubscribe from webhook trigger (POST /triggers/triggers/unsubscribe/)

        Note: SUMIT unsubscribes by the webhook URL, so subscription_id must
        be the URL that was subscribed.

        Args:
            subscription_id: The subscribed webhook URL

        Returns:
            Response dict
        """
        return await self._post(
            "/triggers/triggers/unsubscribe/",
            {"URL": subscription_id}
        )

    @staticmethod
    def _company_payload(company: CompanyRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "Name": company.name,
            "CorporateNumber": company.tax_id,
        }
        if company.email:
            payload["EmailAddress"] = str(company.email)
        if company.phone:
            payload["Phone"] = company.phone
        if company.address:
            parts = [
                p for p in (
                    company.address.street,
                    company.address.city,
                    company.address.zip_code,
                    company.address.country,
                ) if p
            ]
            if parts:
                payload["Address"] = ", ".join(parts)
        return payload

    async def create_company(self, company: CompanyRequest) -> CompanyResponse:
        """
        Create new organization (POST /website/companies/create/)

        Args:
            company: Company details

        Returns:
            CompanyResponse
        """
        data = await self._post(
            "/website/companies/create/",
            {"Company": self._company_payload(company)}
        )
        return CompanyResponse(
            company_id=str(data.get("CompanyID", "")),
            name=company.name,
            tax_id=company.tax_id,
            created_at=datetime.now(),
        )

    async def update_company(
        self,
        company_id: str,
        company: CompanyRequest
    ) -> CompanyResponse:
        """
        Update organization details (POST /website/companies/update/)

        The API updates the company identified by Credentials.CompanyID,
        so the credentials are overridden with the requested company id.

        Args:
            company_id: Company ID
            company: Updated company details

        Returns:
            CompanyResponse
        """
        credentials = self._credentials()
        credentials["CompanyID"] = self._to_int(company_id)
        await self._post(
            "/website/companies/update/",
            {
                "Credentials": credentials,
                "Company": self._company_payload(company),
            }
        )
        return CompanyResponse(
            company_id=str(company_id),
            name=company.name,
            tax_id=company.tax_id,
            created_at=datetime.now(),
        )

    async def get_company_details(self, company_id: str) -> CompanyResponse:
        """
        Get company details (POST /website/companies/getdetails/)

        The API returns the company identified by Credentials.CompanyID,
        so the credentials are overridden with the requested company id.

        Args:
            company_id: Company ID

        Returns:
            CompanyResponse
        """
        credentials = self._credentials()
        credentials["CompanyID"] = self._to_int(company_id)
        data = await self._post(
            "/website/companies/getdetails/",
            {"Credentials": credentials}
        )
        company = data.get("Company") or {}
        return CompanyResponse(
            company_id=str(company_id),
            name=company.get("Name") or "",
            tax_id=company.get("CorporateNumber") or "",
            created_at=datetime.now(),
        )

    async def list_quotas(self) -> Dict[str, Any]:
        """
        List API quotas and usage (POST /website/companies/listquotas/)

        Returns:
            Quotas dict
        """
        return await self._post("/website/companies/listquotas/", {})

    async def install_applications(
        self,
        application_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Install applications (POST /website/companies/installapplications/)

        Args:
            application_ids: List of application names from SUMIT's
                Website_Typed_Application enum (e.g. "Accounting", "CRM",
                "CreditCard", "SMS")

        Returns:
            Installation result dict
        """
        return await self._post(
            "/website/companies/installapplications/",
            {"Applications": list(application_ids)}
        )

    async def set_user_permissions(
        self,
        user_id: str,
        permissions: List[UserPermission]
    ) -> Dict[str, Any]:
        """
        Grant user permission (POST /website/permissions/set/)

        SUMIT assigns a single company role per user
        (Shared/ReadOnly/None/Accountant/Manager/Owner); the first granted
        permission name is used as the role.

        Args:
            user_id: User ID
            permissions: List of permissions (permission_name = role)

        Returns:
            Response dict
        """
        role = None
        for permission in permissions:
            if permission.granted:
                role = permission.permission_name
                break
        if role is None:
            raise Exception(
                "SUMIT API error: /website/permissions/set/ requires a granted "
                "role (Shared/ReadOnly/None/Accountant/Manager/Owner)."
            )
        return await self._post(
            "/website/permissions/set/",
            {
                "UserID": self._to_int(user_id),
                "Role": role,
            }
        )

    async def remove_user_permissions(
        self,
        user_id: str,
        permission_names: List[str]
    ) -> Dict[str, Any]:
        """
        Remove user permission (POST /website/permissions/remove/)

        Note: SUMIT removes the user's company role entirely; the
        permission_names parameter is kept for compatibility.

        Args:
            user_id: User ID
            permission_names: Unused by the API

        Returns:
            Response dict
        """
        return await self._post(
            "/website/permissions/remove/",
            {"UserID": self._to_int(user_id)}
        )

    async def create_user(self, user: UserRequest) -> UserResponse:
        """
        Create user and grant permissions (POST /website/users/create/)

        Args:
            user: User details (role must be one of SUMIT's roles:
                Shared/ReadOnly/None/Accountant/Manager/Owner)

        Returns:
            UserResponse
        """
        data = await self._post(
            "/website/users/create/",
            {
                "User": {
                    "Name": user.name,
                    "EmailAddress": str(user.email),
                },
                "Role": user.role,
            }
        )
        return UserResponse(
            user_id=str(data.get("UserID", "")),
            email=str(user.email),
            name=user.name,
            role=user.role,
            created_at=datetime.now(),
        )

    async def user_login_redirect(
        self,
        user_id: str,
        return_url: Optional[str] = None
    ) -> str:
        """
        Get user login redirect URL (POST /website/users/loginredirect/)

        Note: the real API identifies the user by email address, so user_id
        must be the user's email. Per SUMIT's docs the credentials are not
        validated when creating the redirect token.

        Args:
            user_id: User email address
            return_url: Kept for compatibility (not supported by the API)

        Returns:
            Login redirect URL
        """
        data = await self._post(
            "/website/users/loginredirect/",
            {
                "EmailAddress": str(user_id),
                "Password": "",
            }
        )
        return data.get("RedirectURL", "")
