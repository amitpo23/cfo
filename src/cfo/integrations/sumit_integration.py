"""
SUMIT API Integration
Complete implementation of SUMIT API endpoints
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


class SumitIntegration(BaseIntegration):
    """
    Complete SUMIT API Integration
    
    Implements all SUMIT API endpoints for:
    - Accounting (Customers, Documents, General)
    - Credit Card Terminal (Billing, Gateway, Vault)
    - CRM (Data, Schema, Views)
    - Payments (Standard and Recurring)
    - Communications (Email, SMS, Fax)
    - Customer Service
    - Company Management
    """
    
    BASE_URL = "https://api.sumit.co.il/v1"
    
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
                "Authorization": f"Bearer {api_key}",
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
    
    async def _make_request(
        self,
        endpoint: str,
        method: str = "POST",
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP request to SUMIT API
        
        Args:
            endpoint: API endpoint path
            method: HTTP method (default: POST as per SUMIT docs)
            data: Request body data
            params: Query parameters
            
        Returns:
            Dict containing response data
        """
        self._log_request(method, endpoint, data)
        
        try:
            # Add company_id to data if set
            if data is None:
                data = {}
            if self.company_id:
                data["company_id"] = self.company_id
            
            response = await self.client.request(
                method=method,
                url=endpoint,
                json=data if method in ["POST", "PUT", "PATCH"] else None,
                params=params
            )
            
            self._log_response(response.status_code, response.text)
            response.raise_for_status()
            
            return response.json()
            
        except httpx.HTTPStatusError as e:
            self._log_error(e, f"HTTP error on {endpoint}")
            raise Exception(f"SUMIT API error: {e.response.text}")
        except Exception as e:
            self._log_error(e, f"Request failed on {endpoint}")
            raise
    
    # ==================== Base Integration Methods ====================
    
    async def test_connection(self) -> bool:
        """Test API connection"""
        try:
            await self._make_request("/ping", method="GET")
            return True
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False
    
    async def get_balance(self) -> Dict[str, Any]:
        """Get account balance information"""
        response = await self._make_request("/accounting/balance", method="GET")
        return response
    
    # ==================== Accounting - Customers ====================
    
    async def create_customer(self, customer: CustomerRequest) -> CustomerResponse:
        """
        Create a new customer
        
        Args:
            customer: Customer details
            
        Returns:
            CustomerResponse with created customer details
        """
        response = await self._make_request(
            "/accounting/customers",
            method="POST",
            data=customer.model_dump(exclude_none=True)
        )
        return CustomerResponse(**response)
    
    async def update_customer(
        self,
        customer_id: str,
        customer: CustomerRequest
    ) -> CustomerResponse:
        """
        Update existing customer
        
        Args:
            customer_id: Customer ID to update
            customer: Updated customer details
            
        Returns:
            CustomerResponse with updated customer details
        """
        response = await self._make_request(
            f"/accounting/customers/{customer_id}",
            method="PUT",
            data=customer.model_dump(exclude_none=True)
        )
        return CustomerResponse(**response)
    
    async def get_customer_details_url(self, customer_id: str) -> str:
        """
        Get URL to customer details page
        
        Args:
            customer_id: Customer ID
            
        Returns:
            URL string
        """
        response = await self._make_request(
            f"/accounting/customers/{customer_id}/url",
            method="GET"
        )
        return response.get("url", "")
    
    async def create_customer_remark(
        self,
        remark: CustomerRemarkRequest
    ) -> Dict[str, Any]:
        """
        Add remark to customer
        
        Args:
            remark: Remark details
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/accounting/customers/remarks",
            method="POST",
            data=remark.model_dump()
        )
    
    # ==================== Accounting - Documents ====================
    
    async def send_document(
        self,
        request: SendDocumentRequest
    ) -> Dict[str, Any]:
        """
        Send document by email
        
        Args:
            request: Send document request details
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/accounting/documents/send",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
    
    async def get_document_pdf(self, document_id: str) -> bytes:
        """
        Get document PDF
        
        Args:
            document_id: Document ID
            
        Returns:
            PDF content as bytes
        """
        response = await self.client.get(
            f"/accounting/documents/{document_id}/pdf"
        )
        response.raise_for_status()
        return response.content
    
    async def get_document_details(self, document_id: str) -> DocumentResponse:
        """
        Get document details
        
        Args:
            document_id: Document ID
            
        Returns:
            DocumentResponse with document details
        """
        response = await self._make_request(
            f"/accounting/documents/{document_id}",
            method="GET"
        )
        return DocumentResponse(**response)
    
    async def create_document(
        self,
        document: DocumentRequest
    ) -> DocumentResponse:
        """
        Create a new document (invoice, receipt, etc.)
        
        Args:
            document: Document details
            
        Returns:
            DocumentResponse with created document
        """
        response = await self._make_request(
            "/accounting/documents",
            method="POST",
            data=document.model_dump(exclude_none=True)
        )
        return DocumentResponse(**response)
    
    async def add_expense(self, expense: ExpenseRequest) -> Dict[str, Any]:
        """
        Add expense transaction
        
        Args:
            expense: Expense details
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/accounting/expenses",
            method="POST",
            data=expense.model_dump(exclude_none=True)
        )
    
    async def cancel_document(self, document_id: str) -> Dict[str, Any]:
        """
        Cancel a document
        
        Args:
            document_id: Document ID to cancel
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/accounting/documents/{document_id}/cancel",
            method="POST"
        )
    
    async def move_document_to_books(self, document_id: str) -> Dict[str, Any]:
        """
        Move document to accounting books
        
        Args:
            document_id: Document ID
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/accounting/documents/{document_id}/move-to-books",
            method="POST"
        )
    
    async def get_debt(self, customer_id: str) -> Dict[str, Any]:
        """
        Get customer debt information
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Debt information dict
        """
        return await self._make_request(
            f"/accounting/customers/{customer_id}/debt",
            method="GET"
        )
    
    async def get_debt_report(
        self,
        request: DebtReportRequest
    ) -> List[Dict[str, Any]]:
        """
        Get debt report
        
        Args:
            request: Debt report request parameters
            
        Returns:
            List of debt records
        """
        response = await self._make_request(
            "/accounting/reports/debt",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
        return response.get("items", [])
    
    async def list_documents(
        self,
        request: DocumentListRequest
    ) -> List[DocumentResponse]:
        """
        List documents with filters
        
        Args:
            request: List request with filters
            
        Returns:
            List of DocumentResponse
        """
        response = await self._make_request(
            "/accounting/documents",
            method="GET",
            params=request.model_dump(exclude_none=True)
        )
        return [DocumentResponse(**doc) for doc in response.get("items", [])]
    
    # ==================== Accounting - General ====================
    
    async def verify_bank_account(
        self,
        verification: BankAccountVerification
    ) -> Dict[str, Any]:
        """
        Verify bank account details
        
        Args:
            verification: Bank account details to verify
            
        Returns:
            Verification result
        """
        return await self._make_request(
            "/accounting/verify-bank-account",
            method="POST",
            data=verification.model_dump()
        )
    
    async def get_vat_rate(self, date: Optional[date] = None) -> Decimal:
        """
        Get VAT rate for a specific date
        
        Args:
            date: Date to get VAT rate for (default: today)
            
        Returns:
            VAT rate as Decimal
        """
        params = {"date": date.isoformat()} if date else {}
        response = await self._make_request(
            "/accounting/vat-rate",
            method="GET",
            params=params
        )
        return Decimal(str(response.get("vat_rate", "0")))
    
    async def get_exchange_rate(
        self,
        request: ExchangeRateRequest
    ) -> ExchangeRateResponse:
        """
        Get exchange rate
        
        Args:
            request: Exchange rate request
            
        Returns:
            ExchangeRateResponse
        """
        response = await self._make_request(
            "/accounting/exchange-rate",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
        return ExchangeRateResponse(**response)
    
    async def update_settings(self, settings: SettingsUpdate) -> Dict[str, Any]:
        """
        Update system settings
        
        Args:
            settings: Settings to update
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/accounting/settings",
            method="PUT",
            data=settings.model_dump()
        )
    
    async def get_next_document_number(self, document_type: str) -> int:
        """
        Get next document number for a document type
        
        Args:
            document_type: Type of document
            
        Returns:
            Next document number
        """
        response = await self._make_request(
            f"/accounting/documents/next-number/{document_type}",
            method="GET"
        )
        return response.get("next_number", 1)
    
    async def set_next_document_number(
        self,
        request: DocumentNumberRequest
    ) -> Dict[str, Any]:
        """
        Set next document number
        
        Args:
            request: Document number request
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/accounting/documents/next-number",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
    
    # ==================== Accounting - Income Items ====================
    
    async def create_income_item(
        self,
        item: IncomeItemRequest
    ) -> IncomeItemResponse:
        """
        Create income item
        
        Args:
            item: Income item details
            
        Returns:
            IncomeItemResponse
        """
        response = await self._make_request(
            "/accounting/income-items",
            method="POST",
            data=item.model_dump(exclude_none=True)
        )
        return IncomeItemResponse(**response)
    
    async def list_income_items(self) -> List[IncomeItemResponse]:
        """
        List all income items
        
        Returns:
            List of IncomeItemResponse
        """
        response = await self._make_request(
            "/accounting/income-items",
            method="GET"
        )
        return [IncomeItemResponse(**item) for item in response.get("items", [])]
    
    # ==================== Credit Card Terminal - Billing ====================
    
    async def load_billing_transactions(
        self,
        request: BillingTransactionRequest
    ) -> List[BillingTransaction]:
        """
        Load billing transactions from credit card terminal
        
        Args:
            request: Billing transaction request
            
        Returns:
            List of BillingTransaction
        """
        response = await self._make_request(
            "/terminal/billing/load",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
        return [BillingTransaction(**t) for t in response.get("transactions", [])]
    
    async def process_billing_transactions(
        self,
        transaction_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Process billing transactions
        
        Args:
            transaction_ids: List of transaction IDs to process
            
        Returns:
            Processing result
        """
        return await self._make_request(
            "/terminal/billing/process",
            method="POST",
            data={"transaction_ids": transaction_ids}
        )
    
    async def get_billing_status(self, transaction_id: str) -> Dict[str, Any]:
        """
        Get billing transaction status
        
        Args:
            transaction_id: Transaction ID
            
        Returns:
            Status dict
        """
        return await self._make_request(
            f"/terminal/billing/{transaction_id}/status",
            method="GET"
        )
    
    # ==================== Credit Card Terminal - Gateway ====================
    
    async def create_card_transaction(
        self,
        transaction: TransactionRequest
    ) -> TransactionResponse:
        """
        Create credit card transaction
        
        Args:
            transaction: Transaction details
            
        Returns:
            TransactionResponse
        """
        response = await self._make_request(
            "/terminal/gateway/transaction",
            method="POST",
            data=transaction.model_dump(exclude_none=True)
        )
        return TransactionResponse(**response)
    
    async def get_transaction(self, transaction_id: str) -> TransactionResponse:
        """
        Get transaction details
        
        Args:
            transaction_id: Transaction ID
            
        Returns:
            TransactionResponse
        """
        response = await self._make_request(
            f"/terminal/gateway/transaction/{transaction_id}",
            method="GET"
        )
        return TransactionResponse(**response)
    
    async def begin_redirect(
        self,
        transaction_id: str,
        return_url: str
    ) -> str:
        """
        Begin redirect flow for transaction
        
        Args:
            transaction_id: Transaction ID
            return_url: URL to return to after payment
            
        Returns:
            Redirect URL
        """
        response = await self._make_request(
            "/terminal/gateway/redirect",
            method="POST",
            data={
                "transaction_id": transaction_id,
                "return_url": return_url
            }
        )
        return response.get("redirect_url", "")
    
    async def get_reference_numbers(
        self,
        transaction_ids: List[str]
    ) -> Dict[str, str]:
        """
        Get reference numbers for transactions
        
        Args:
            transaction_ids: List of transaction IDs
            
        Returns:
            Dict mapping transaction_id to reference_number
        """
        response = await self._make_request(
            "/terminal/gateway/reference-numbers",
            method="POST",
            data={"transaction_ids": transaction_ids}
        )
        return response.get("reference_numbers", {})
    
    # ==================== Credit Card Terminal - Vault ====================
    
    async def tokenize_card(
        self,
        request: TokenizeCardRequest
    ) -> TokenResponse:
        """
        Tokenize credit card for future use
        
        Args:
            request: Card tokenization request
            
        Returns:
            TokenResponse with card token
        """
        response = await self._make_request(
            "/terminal/vault/tokenize",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
        return TokenResponse(**response)
    
    async def tokenize_single_use(
        self,
        request: TokenizeCardRequest
    ) -> TokenResponse:
        """
        Tokenize card for single use
        
        Args:
            request: Card tokenization request
            
        Returns:
            TokenResponse with single-use token
        """
        response = await self._make_request(
            "/terminal/vault/tokenize-single-use",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
        return TokenResponse(**response)
    
    async def tokenize_single_use_json(
        self,
        card_data: Dict[str, Any]
    ) -> TokenResponse:
        """
        Tokenize card for single use (JSON format)
        
        Args:
            card_data: Card data dict
            
        Returns:
            TokenResponse
        """
        response = await self._make_request(
            "/terminal/vault/tokenize-single-use-json",
            method="POST",
            data=card_data
        )
        return TokenResponse(**response)
    
    # ==================== CRM - Data ====================
    
    async def create_entity(self, entity: EntityRequest) -> EntityResponse:
        """
        Create CRM entity
        
        Args:
            entity: Entity details
            
        Returns:
            EntityResponse
        """
        response = await self._make_request(
            "/crm/entities",
            method="POST",
            data=entity.model_dump(exclude_none=True)
        )
        return EntityResponse(**response)
    
    async def update_entity(
        self,
        entity_id: str,
        entity: EntityRequest
    ) -> EntityResponse:
        """
        Update CRM entity
        
        Args:
            entity_id: Entity ID
            entity: Updated entity details
            
        Returns:
            EntityResponse
        """
        response = await self._make_request(
            f"/crm/entities/{entity_id}",
            method="PUT",
            data=entity.model_dump(exclude_none=True)
        )
        return EntityResponse(**response)
    
    async def archive_entity(self, entity_id: str) -> Dict[str, Any]:
        """
        Archive CRM entity
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/crm/entities/{entity_id}/archive",
            method="POST"
        )
    
    async def delete_entity(self, entity_id: str) -> Dict[str, Any]:
        """
        Delete CRM entity
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/crm/entities/{entity_id}",
            method="DELETE"
        )
    
    async def list_entities(
        self,
        folder_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[EntityResponse]:
        """
        List CRM entities in folder
        
        Args:
            folder_id: Folder ID
            limit: Maximum number of results
            offset: Pagination offset
            
        Returns:
            List of EntityResponse
        """
        response = await self._make_request(
            "/crm/entities",
            method="GET",
            params={
                "folder_id": folder_id,
                "limit": limit,
                "offset": offset
            }
        )
        return [EntityResponse(**e) for e in response.get("items", [])]
    
    async def get_entity(self, entity_id: str) -> EntityResponse:
        """
        Get CRM entity details
        
        Args:
            entity_id: Entity ID
            
        Returns:
            EntityResponse
        """
        response = await self._make_request(
            f"/crm/entities/{entity_id}",
            method="GET"
        )
        return EntityResponse(**response)
    
    async def count_entity_usage(self, entity_id: str) -> int:
        """
        Count entity usage in system
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Usage count
        """
        response = await self._make_request(
            f"/crm/entities/{entity_id}/usage-count",
            method="GET"
        )
        return response.get("count", 0)
    
    async def get_entity_print_html(self, entity_id: str) -> str:
        """
        Get entity as printable HTML
        
        Args:
            entity_id: Entity ID
            
        Returns:
            HTML string
        """
        response = await self._make_request(
            f"/crm/entities/{entity_id}/print",
            method="GET"
        )
        return response.get("html", "")
    
    async def get_entities_html(
        self,
        folder_id: str,
        entity_ids: List[str]
    ) -> str:
        """
        Get multiple entities as HTML
        
        Args:
            folder_id: Folder ID
            entity_ids: List of entity IDs
            
        Returns:
            HTML string
        """
        response = await self._make_request(
            "/crm/entities/html",
            method="POST",
            data={
                "folder_id": folder_id,
                "entity_ids": entity_ids
            }
        )
        return response.get("html", "")
    
    # ==================== CRM - Schema ====================
    
    async def get_folder(self, folder_id: str) -> FolderResponse:
        """
        Get CRM folder details and schema
        
        Args:
            folder_id: Folder ID
            
        Returns:
            FolderResponse
        """
        response = await self._make_request(
            f"/crm/folders/{folder_id}",
            method="GET"
        )
        return FolderResponse(**response)
    
    async def list_folders(self) -> List[FolderResponse]:
        """
        List all CRM folders
        
        Returns:
            List of FolderResponse
        """
        response = await self._make_request(
            "/crm/folders",
            method="GET"
        )
        return [FolderResponse(**f) for f in response.get("items", [])]
    
    # ==================== CRM - Views ====================
    
    async def list_views(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        List views for a folder
        
        Args:
            folder_id: Folder ID
            
        Returns:
            List of view definitions
        """
        response = await self._make_request(
            f"/crm/folders/{folder_id}/views",
            method="GET"
        )
        return response.get("views", [])
    
    # ==================== Customer Service ====================
    
    async def create_ticket(self, ticket: TicketRequest) -> TicketResponse:
        """
        Create customer service ticket
        
        Args:
            ticket: Ticket details
            
        Returns:
            TicketResponse
        """
        response = await self._make_request(
            "/customer-service/tickets",
            method="POST",
            data=ticket.model_dump(exclude_none=True)
        )
        return TicketResponse(**response)
    
    # ==================== Email Subscriptions ====================
    
    async def list_mailing_lists(self) -> List[Dict[str, Any]]:
        """
        List all mailing lists
        
        Returns:
            List of mailing list dicts
        """
        response = await self._make_request(
            "/email/mailing-lists",
            method="GET"
        )
        return response.get("lists", [])
    
    async def add_to_mailing_list(
        self,
        request: EmailListRequest
    ) -> Dict[str, Any]:
        """
        Add contact to mailing list
        
        Args:
            request: Email list request
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/email/mailing-lists/add",
            method="POST",
            data=request.model_dump(exclude_none=True)
        )
    
    # ==================== SMS ====================
    
    async def send_sms(self, sms: SMSRequest) -> SMSResponse:
        """
        Send single SMS
        
        Args:
            sms: SMS details
            
        Returns:
            SMSResponse
        """
        response = await self._make_request(
            "/sms/send",
            method="POST",
            data=sms.model_dump(exclude_none=True)
        )
        return SMSResponse(**response)
    
    async def send_multiple_sms(
        self,
        messages: List[SMSRequest]
    ) -> List[SMSResponse]:
        """
        Send multiple SMS messages
        
        Args:
            messages: List of SMS requests
            
        Returns:
            List of SMSResponse
        """
        response = await self._make_request(
            "/sms/send-multiple",
            method="POST",
            data={
                "messages": [m.model_dump(exclude_none=True) for m in messages]
            }
        )
        return [SMSResponse(**s) for s in response.get("results", [])]
    
    async def list_sms_senders(self) -> List[str]:
        """
        List available SMS sender names
        
        Returns:
            List of sender names
        """
        response = await self._make_request(
            "/sms/senders",
            method="GET"
        )
        return response.get("senders", [])
    
    async def list_sms_mailing_lists(self) -> List[Dict[str, Any]]:
        """
        List SMS mailing lists
        
        Returns:
            List of mailing list dicts
        """
        response = await self._make_request(
            "/sms/mailing-lists",
            method="GET"
        )
        return response.get("lists", [])
    
    async def add_to_sms_mailing_list(
        self,
        list_id: str,
        phone_number: str,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add contact to SMS mailing list
        
        Args:
            list_id: Mailing list ID
            phone_number: Phone number
            name: Optional contact name
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/sms/mailing-lists/add",
            method="POST",
            data={
                "list_id": list_id,
                "phone_number": phone_number,
                "name": name
            }
        )
    
    # ==================== Payments ====================
    
    async def charge_customer(self, charge: ChargeRequest) -> PaymentResponse:
        """
        Charge customer
        
        Args:
            charge: Charge request details
            
        Returns:
            PaymentResponse
        """
        response = await self._make_request(
            "/payments/charge",
            method="POST",
            data=charge.model_dump(exclude_none=True)
        )
        return PaymentResponse(**response)
    
    async def multivendor_charge(
        self,
        charge: ChargeRequest,
        vendor_splits: List[Dict[str, Any]]
    ) -> PaymentResponse:
        """
        Charge with multivendor split
        
        Args:
            charge: Charge request
            vendor_splits: List of vendor split definitions
            
        Returns:
            PaymentResponse
        """
        data = charge.model_dump(exclude_none=True)
        data["vendor_splits"] = vendor_splits
        
        response = await self._make_request(
            "/payments/multivendor-charge",
            method="POST",
            data=data
        )
        return PaymentResponse(**response)
    
    async def get_payment(self, payment_id: str) -> PaymentResponse:
        """
        Get payment details
        
        Args:
            payment_id: Payment ID
            
        Returns:
            PaymentResponse
        """
        response = await self._make_request(
            f"/payments/{payment_id}",
            method="GET"
        )
        return PaymentResponse(**response)
    
    async def list_payments(
        self,
        customer_id: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[PaymentResponse]:
        """
        List payments with filters
        
        Args:
            customer_id: Filter by customer
            from_date: Start date filter
            to_date: End date filter
            limit: Maximum results
            offset: Pagination offset
            
        Returns:
            List of PaymentResponse
        """
        params = {"limit": limit, "offset": offset}
        if customer_id:
            params["customer_id"] = customer_id
        if from_date:
            params["from_date"] = from_date.isoformat()
        if to_date:
            params["to_date"] = to_date.isoformat()
        
        response = await self._make_request(
            "/payments",
            method="GET",
            params=params
        )
        return [PaymentResponse(**p) for p in response.get("items", [])]
    
    async def begin_payment_redirect(
        self,
        amount: Decimal,
        description: str,
        return_url: str,
        customer_id: Optional[str] = None
    ) -> str:
        """
        Begin payment redirect flow
        
        Args:
            amount: Payment amount
            description: Payment description
            return_url: URL to return after payment
            customer_id: Optional customer ID
            
        Returns:
            Redirect URL
        """
        response = await self._make_request(
            "/payments/redirect/begin",
            method="POST",
            data={
                "amount": str(amount),
                "description": description,
                "return_url": return_url,
                "customer_id": customer_id
            }
        )
        return response.get("redirect_url", "")
    
    async def get_payment_methods(
        self,
        customer_id: str
    ) -> List[PaymentMethodResponse]:
        """
        Get customer payment methods
        
        Args:
            customer_id: Customer ID
            
        Returns:
            List of PaymentMethodResponse
        """
        response = await self._make_request(
            f"/payments/methods/{customer_id}",
            method="GET"
        )
        return [PaymentMethodResponse(**pm) for pm in response.get("methods", [])]
    
    async def set_payment_methods(
        self,
        customer_id: str,
        payment_method_id: str,
        is_default: bool = False
    ) -> Dict[str, Any]:
        """
        Set customer payment method
        
        Args:
            customer_id: Customer ID
            payment_method_id: Payment method ID
            is_default: Set as default payment method
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/payments/methods/set",
            method="POST",
            data={
                "customer_id": customer_id,
                "payment_method_id": payment_method_id,
                "is_default": is_default
            }
        )
    
    async def remove_payment_method(
        self,
        customer_id: str,
        payment_method_id: str
    ) -> Dict[str, Any]:
        """
        Remove customer payment method
        
        Args:
            customer_id: Customer ID
            payment_method_id: Payment method ID to remove
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/payments/methods/remove",
            method="POST",
            data={
                "customer_id": customer_id,
                "payment_method_id": payment_method_id
            }
        )
    
    async def open_upay_terminal(
        self,
        amount: Decimal,
        description: str
    ) -> Dict[str, Any]:
        """
        Open Upay terminal for payment
        
        Args:
            amount: Payment amount
            description: Payment description
            
        Returns:
            Terminal session dict
        """
        return await self._make_request(
            "/payments/upay/open-terminal",
            method="POST",
            data={
                "amount": str(amount),
                "description": description
            }
        )
    
    async def setup_upay_credentials(
        self,
        credentials: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Setup Upay credentials
        
        Args:
            credentials: Upay credentials dict
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/payments/upay/setup",
            method="POST",
            data=credentials
        )
    
    # ==================== Recurring Payments ====================
    
    async def list_customer_recurring(
        self,
        customer_id: str
    ) -> List[RecurringPaymentResponse]:
        """
        List customer recurring payments
        
        Args:
            customer_id: Customer ID
            
        Returns:
            List of RecurringPaymentResponse
        """
        response = await self._make_request(
            f"/payments/recurring/customer/{customer_id}",
            method="GET"
        )
        return [RecurringPaymentResponse(**r) for r in response.get("items", [])]
    
    async def cancel_recurring(self, recurring_id: str) -> Dict[str, Any]:
        """
        Cancel recurring payment
        
        Args:
            recurring_id: Recurring payment ID
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/payments/recurring/{recurring_id}/cancel",
            method="POST"
        )
    
    async def charge_recurring(self, recurring_id: str) -> PaymentResponse:
        """
        Manually charge recurring payment
        
        Args:
            recurring_id: Recurring payment ID
            
        Returns:
            PaymentResponse
        """
        response = await self._make_request(
            f"/payments/recurring/{recurring_id}/charge",
            method="POST"
        )
        return PaymentResponse(**response)
    
    async def update_recurring(
        self,
        recurring_id: str,
        updates: RecurringPaymentRequest
    ) -> RecurringPaymentResponse:
        """
        Update recurring payment details
        
        Args:
            recurring_id: Recurring payment ID
            updates: Updated details
            
        Returns:
            RecurringPaymentResponse
        """
        response = await self._make_request(
            f"/payments/recurring/{recurring_id}",
            method="PUT",
            data=updates.model_dump(exclude_none=True)
        )
        return RecurringPaymentResponse(**response)
    
    async def update_recurring_settings(
        self,
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update recurring payment settings
        
        Args:
            settings: Settings dict
            
        Returns:
            Response dict
        """
        return await self._make_request(
            "/payments/recurring/settings",
            method="PUT",
            data=settings
        )
    
    # ==================== Other Services ====================
    
    async def send_fax(self, fax: FaxRequest) -> Dict[str, Any]:
        """
        Send fax
        
        Args:
            fax: Fax details
            
        Returns:
            Response dict with fax ID
        """
        return await self._make_request(
            "/fax/send",
            method="POST",
            data=fax.model_dump(exclude_none=True)
        )
    
    async def send_letter_by_click(
        self,
        recipient: Dict[str, str],
        content: str
    ) -> Dict[str, Any]:
        """
        Send letter via mail service
        
        Args:
            recipient: Recipient details dict
            content: Letter content (HTML or PDF base64)
            
        Returns:
            Response dict with letter ID
        """
        return await self._make_request(
            "/mail/send-letter",
            method="POST",
            data={
                "recipient": recipient,
                "content": content
            }
        )
    
    async def get_letter_tracking_code(self, letter_id: str) -> str:
        """
        Get letter tracking code
        
        Args:
            letter_id: Letter ID
            
        Returns:
            Tracking code
        """
        response = await self._make_request(
            f"/mail/letters/{letter_id}/tracking",
            method="GET"
        )
        return response.get("tracking_code", "")
    
    async def create_scheduled_document(
        self,
        document: DocumentRequest,
        schedule_date: date
    ) -> Dict[str, Any]:
        """
        Create scheduled document
        
        Args:
            document: Document details
            schedule_date: Date to create document
            
        Returns:
            Scheduled document dict
        """
        data = document.model_dump(exclude_none=True)
        data["schedule_date"] = schedule_date.isoformat()
        
        return await self._make_request(
            "/accounting/documents/scheduled",
            method="POST",
            data=data
        )
    
    async def list_stock(self) -> List[StockItemResponse]:
        """
        List stock items
        
        Returns:
            List of StockItemResponse
        """
        response = await self._make_request(
            "/stock/items",
            method="GET"
        )
        return [StockItemResponse(**item) for item in response.get("items", [])]
    
    async def subscribe_trigger(
        self,
        trigger_type: str,
        webhook_url: str
    ) -> Dict[str, Any]:
        """
        Subscribe to webhook trigger
        
        Args:
            trigger_type: Type of trigger to subscribe to
            webhook_url: Webhook URL to call
            
        Returns:
            Subscription dict
        """
        return await self._make_request(
            "/webhooks/subscribe",
            method="POST",
            data={
                "trigger_type": trigger_type,
                "webhook_url": webhook_url
            }
        )
    
    async def unsubscribe_trigger(self, subscription_id: str) -> Dict[str, Any]:
        """
        Unsubscribe from webhook trigger
        
        Args:
            subscription_id: Subscription ID
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/webhooks/unsubscribe/{subscription_id}",
            method="POST"
        )
    
    async def create_company(self, company: CompanyRequest) -> CompanyResponse:
        """
        Create new company
        
        Args:
            company: Company details
            
        Returns:
            CompanyResponse
        """
        response = await self._make_request(
            "/companies",
            method="POST",
            data=company.model_dump(exclude_none=True)
        )
        return CompanyResponse(**response)
    
    async def update_company(
        self,
        company_id: str,
        company: CompanyRequest
    ) -> CompanyResponse:
        """
        Update company details
        
        Args:
            company_id: Company ID
            company: Updated company details
            
        Returns:
            CompanyResponse
        """
        response = await self._make_request(
            f"/companies/{company_id}",
            method="PUT",
            data=company.model_dump(exclude_none=True)
        )
        return CompanyResponse(**response)
    
    async def get_company_details(self, company_id: str) -> CompanyResponse:
        """
        Get company details
        
        Args:
            company_id: Company ID
            
        Returns:
            CompanyResponse
        """
        response = await self._make_request(
            f"/companies/{company_id}",
            method="GET"
        )
        return CompanyResponse(**response)
    
    async def list_quotas(self) -> Dict[str, Any]:
        """
        List API quotas and usage
        
        Returns:
            Quotas dict
        """
        return await self._make_request(
            "/quotas",
            method="GET"
        )
    
    async def install_applications(
        self,
        application_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Install applications
        
        Args:
            application_ids: List of application IDs to install
            
        Returns:
            Installation result dict
        """
        return await self._make_request(
            "/applications/install",
            method="POST",
            data={"application_ids": application_ids}
        )
    
    async def set_user_permissions(
        self,
        user_id: str,
        permissions: List[UserPermission]
    ) -> Dict[str, Any]:
        """
        Set user permissions
        
        Args:
            user_id: User ID
            permissions: List of permissions
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/users/{user_id}/permissions",
            method="POST",
            data={
                "permissions": [p.model_dump() for p in permissions]
            }
        )
    
    async def remove_user_permissions(
        self,
        user_id: str,
        permission_names: List[str]
    ) -> Dict[str, Any]:
        """
        Remove user permissions
        
        Args:
            user_id: User ID
            permission_names: List of permission names to remove
            
        Returns:
            Response dict
        """
        return await self._make_request(
            f"/users/{user_id}/permissions/remove",
            method="POST",
            data={"permission_names": permission_names}
        )
    
    async def create_user(self, user: UserRequest) -> UserResponse:
        """
        Create new user
        
        Args:
            user: User details
            
        Returns:
            UserResponse
        """
        response = await self._make_request(
            "/users",
            method="POST",
            data=user.model_dump(exclude_none=True)
        )
        return UserResponse(**response)
    
    async def user_login_redirect(
        self,
        user_id: str,
        return_url: Optional[str] = None
    ) -> str:
        """
        Get user login redirect URL
        
        Args:
            user_id: User ID
            return_url: Optional URL to return to after login
            
        Returns:
            Login redirect URL
        """
        data = {"user_id": user_id}
        if return_url:
            data["return_url"] = return_url
        
        response = await self._make_request(
            "/users/login-redirect",
            method="POST",
            data=data
        )
        return response.get("redirect_url", "")
