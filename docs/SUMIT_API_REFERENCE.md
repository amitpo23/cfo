# SUMIT API Reference — `SumitIntegration` Client

> **Auto-derived from source code as of 2026-06-28.**  
> Source of truth: `src/cfo/integrations/sumit_integration.py` (class `SumitIntegration`) and `src/cfo/integrations/sumit_models.py`.  
> This document is the authoritative per-method reference for every public method on the client. Do not edit manually — regenerate from the source.

---

## Table of Contents

1. [Transport & Authentication](#transport--authentication)
2. [Connection / Misc](#connection--misc)
3. [Accounting — Customers](#accounting--customers)
4. [Accounting — Documents & Invoices](#accounting--documents--invoices)
5. [Accounting — Expenses](#accounting--expenses)
6. [Accounting — General](#accounting--general)
7. [Accounting — Income Items](#accounting--income-items)
8. [Billing — Payments](#billing--payments)
9. [Billing — Payment Methods](#billing--payment-methods)
10. [Billing — Recurring Payments](#billing--recurring-payments)
11. [Credit Card Terminal — Gateway](#credit-card-terminal--gateway)
12. [Credit Card Terminal — Billing Batch](#credit-card-terminal--billing-batch)
13. [Credit Card Terminal — Vault (Tokenization)](#credit-card-terminal--vault-tokenization)
14. [CRM — Data](#crm--data)
15. [CRM — Schema](#crm--schema)
16. [CRM — Views](#crm--views)
17. [Customer Service — Tickets](#customer-service--tickets)
18. [Email Subscriptions](#email-subscriptions)
19. [SMS](#sms)
20. [Fax](#fax)
21. [Stock](#stock)
22. [Triggers / Webhooks](#triggers--webhooks)
23. [Website — Companies](#website--companies)
24. [Website — Permissions](#website--permissions)
25. [Website — Users](#website--users)
26. [Not-Supported Stubs](#not-supported-stubs)

---

## Transport & Authentication

**Base URL:** `https://api.sumit.co.il`  
**Protocol:** Every endpoint is HTTP **POST** with a JSON body and a trailing slash (e.g. `/accounting/documents/list/`).  
**Authentication:** Credentials are injected into **every** request body automatically:

```json
{
  "Credentials": {
    "APIKey": "<api_key>",
    "CompanyID": 12345
  },
  "<other fields>": "..."
}
```

`CompanyID` is omitted when the client is constructed without one.

**Response envelope (all non-binary endpoints):**

```json
{
  "Status": 0,
  "UserErrorMessage": null,
  "TechnicalErrorDetails": null,
  "Data": { ... }
}
```

`Status == 0` is success. The internal `_post()` helper unwraps `Data` and raises `SumitAPIError` on any non-zero status. Binary endpoints (`/accounting/documents/getpdf/`, `/crm/data/getentityprinthtml/`) skip the envelope and return raw bytes.

**Error:** `SumitAPIError` (exception subclass) is raised for HTTP 4xx/5xx and for business-level envelope errors.  
**Rate limiting:** SUMIT returns HTTP 403 (no body) under rapid calls. Callers should detect `"403"` in the error message and implement exponential back-off.

---

## Connection / Misc

### `test_connection() -> bool`

| Field | Value |
|---|---|
| Endpoint | `POST /website/companies/getdetails/` |
| Purpose | Validates that credentials are accepted by the API |
| Request body | Credentials only (no extra fields) |
| Returns | `True` if `Status == 0`, `False` otherwise (never raises) |

---

### `get_balance() -> ...`

Always raises `Exception`. SUMIT has no account-balance endpoint. Use `get_debt_report()` or `list_payments()` instead.

---

## Accounting — Customers

### `create_customer(customer: CustomerRequest) -> CustomerResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/customers/create/` |
| Purpose | Create a new customer in SUMIT's accounting module |
| Request body | `{"Details": {"Name", "EmailAddress"?, "Phone"?, "CompanyNumber"?, "Address"?, "City"?, "ZipCode"?, "SearchMode": "Automatic"}}` |
| Returns | `CustomerResponse` (customer_id, name, email, phone, tax_id, created_at) |

**`CustomerRequest` fields:**

| Field | Type | Required |
|---|---|---|
| `name` | `str` | Yes |
| `email` | `EmailStr` | No |
| `phone` | `str` | No |
| `tax_id` | `str` | No |
| `address` | `CustomerAddress` | No |
| `notes` | `str` | No |
| `customer_type` | `"individual"` \| `"company"` | No (default `"individual"`) |

---

### `update_customer(customer_id: str, customer: CustomerRequest) -> CustomerResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/customers/update/` |
| Purpose | Update an existing customer by ID |
| Request body | Same as create, plus `{"Details": {"ID": <int>, "SearchMode": "None", ...}}` |
| Returns | `CustomerResponse` |

---

### `get_customer_details_url(customer_id: str) -> str`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/customers/getdetailsurl/` |
| Purpose | Get the SUMIT web-app URL for a customer's history page |
| Request body | `{"CustomerID": <int>}` |
| Returns | URL string (`CustomerHistoryURL`) |

---

### `create_customer_remark(remark: CustomerRemarkRequest) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/customers/createremark/` |
| Purpose | Add a free-text remark to a customer record |
| Request body | `{"CustomerID": <int>, "Content": "<remark text>"}` |
| Returns | Dict containing `RemarkID` |

**`CustomerRemarkRequest` fields:**

| Field | Type | Required |
|---|---|---|
| `customer_id` | `str` | Yes |
| `remark` | `str` | Yes |

---

## Accounting — Documents & Invoices

### `create_document(document: DocumentRequest) -> DocumentResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/create/` |
| Purpose | Create any document type (invoice, receipt, quote, credit note, proforma, etc.) |
| Request body | `{"Details": {"Customer", "Type", "Language", "Currency", "Date"?, "DueDate"?, "Description"?}, "Items": [...], "VATIncluded": true}` |
| Returns | `DocumentResponse` (document_id, document_number, document_type, customer_id, total_amount, vat_amount, status, issue_date, due_date, pdf_url) |

**`DocumentRequest` fields:**

| Field | Type | Required |
|---|---|---|
| `customer_id` | `str` | Yes |
| `document_type` | `"invoice"` \| `"receipt"` \| `"quote"` \| `"credit_note"` \| `"proforma"` | Yes |
| `items` | `List[DocumentItem]` | Yes |
| `issue_date` | `date` | No |
| `due_date` | `date` | No |
| `notes` | `str` | No |
| `currency` | `str` | No (default `"ILS"`) |
| `language` | `str` | No (default `"he"`) |

**`DocumentItem` fields:**

| Field | Type | Required |
|---|---|---|
| `description` | `str` | Yes |
| `quantity` | `Decimal` | No (default `1`) |
| `price` | `Decimal` | Yes |
| `vat_rate` | `Decimal` | No |
| `discount` | `Decimal` | No (% discount applied to unit price) |
| `item_id` | `str` | No (numeric → `{"Item": {"ID": ...}}`, else by name) |

**Document type mapping** (local name → SUMIT enum):

| Local name | SUMIT enum |
|---|---|
| `invoice` / `tax_invoice` | `Invoice` |
| `invoice_receipt` / `invoice_and_receipt` | `InvoiceAndReceipt` |
| `receipt` | `Receipt` |
| `proforma` / `proforma_invoice` | `ProformaInvoice` |
| `donation_receipt` | `DonationReceipt` |
| `credit_note` / `credit_invoice` | `CreditInvoice` |
| `quote` / `price_quotation` | `PriceQuotation` |
| `order` / `purchase_order` / `work_order` | `Order` |
| `delivery_note` | `DeliveryNote` |
| `payment_request` | `PaymentRequest` |
| `expense` / `expense_invoice` | `ExpenseInvoice` |
| `expense_receipt` | `ExpenseReceipt` |

---

### `get_document_details(document_id: str) -> DocumentResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/getdetails/` |
| Purpose | Fetch full details of a single document |
| Request body | `{"DocumentID": <int>}` |
| Returns | `DocumentResponse` — VAT is summed from line `Items[].VAT`; if zero, falls back to document-level VAT fields |

---

### `list_documents(request: DocumentListRequest) -> List[DocumentResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/list/` |
| Purpose | List documents with optional type/date/status filters |
| Request body | `{"IncludeDrafts": true, "DocumentTypes"?: [...], "DateFrom"?: "...", "DateTo"?: "...", "Paging"?: {"StartIndex": ..., "PageSize": ...}}` |
| Returns | `List[DocumentResponse]` |

**`DocumentListRequest` fields:**

| Field | Type | Notes |
|---|---|---|
| `customer_id` | `str` | Not sent to API (no server-side filter) |
| `document_type` | `str` | Single type filter (alternative to `document_types`) |
| `document_types` | `List[str]` | Preferred; numeric codes or local names; numeric codes are reliable |
| `from_date` | `date` | Maps to `DateFrom` |
| `to_date` | `date` | Maps to `DateTo` |
| `status` | `str` | Applied **client-side** after the API call |
| `limit` | `int` | Default 100 — maps to `Paging.PageSize` |
| `offset` | `int` | Default 0 — maps to `Paging.StartIndex` |

**Note on VAT:** SUMIT's list payload historically omits VAT. The client falls back to `vat_utils.split_inclusive()` to recover VAT from the gross total and document date.

---

### `send_document(request: SendDocumentRequest) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/send/` |
| Purpose | Send an existing document to the customer by email |
| Request body | `{"EntityID": <int>, "Original": true, "EmailAddress"?, "PersonalMessage"?}` |
| Returns | Response dict |

**`SendDocumentRequest` fields:**

| Field | Type | Notes |
|---|---|---|
| `document_id` | `str` | Yes |
| `recipient_email` | `EmailStr` | No |
| `subject` | `str` | No (concatenated into `PersonalMessage`) |
| `message` | `str` | No |
| `cc_emails` | `List[EmailStr]` | No (not sent — SUMIT has no CC field) |

---

### `get_document_pdf(document_id: str) -> bytes`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/getpdf/` |
| Purpose | Download the PDF of a document |
| Request body | `{"DocumentID": <int>, "Original": true}` |
| Returns | Raw PDF bytes (binary response — no JSON envelope) |

---

### `cancel_document(document_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/cancel/` |
| Purpose | Cancel (void) a document |
| Request body | `{"DocumentID": <int>, "Description": "Cancelled via API"}` |
| Returns | Response dict |

---

### `move_document_to_books(document_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/movetobooks/` |
| Purpose | Finalize a draft document (move it to the accounting books) |
| Request body | `{"DocumentID": <int>}` |
| Returns | Response dict |

---

### `get_debt(customer_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/getdebt/` |
| Purpose | Get the outstanding debt for a single customer |
| Request body | `{"CustomerID": <int>}` |
| Returns | Dict containing `"Debt"` (numeric balance) |

---

### `get_debt_report(request: DebtReportRequest) -> List[Dict[str, Any]]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/getdebtreport/` |
| Purpose | Get outstanding debt across all customers (with optional single-customer filter) |
| Request body | `{"DebitSource": 2, "CreditSource": 1, "IncludeDraftDocuments"?: true}` |
| Returns | `List[{"CustomerID", "Debt", "customer_id", "amount"}]` |

**`DebtReportRequest` fields:**

| Field | Type | Notes |
|---|---|---|
| `customer_id` | `str` | Optional; filter applied client-side |
| `as_of_date` | `date` | Not sent (not supported by endpoint) |
| `include_paid` | `bool` | If true, sends `IncludeDraftDocuments: true` |

---

### `get_document_supplier(document_id: str) -> str`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/getdetails/` (via `get_document_supplier_details`) |
| Purpose | Return the supplier/customer name on a document |
| Returns | Name string |

---

### `get_document_supplier_details(document_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/getdetails/` |
| Purpose | Return all fields needed for PCN874 VAT filing: supplier name, tax ID, VAT, total, and item name |
| Request body | `{"DocumentID": <int>}` |
| Returns | `{"name", "tax_id", "vat", "total", "no_vat", "item_name"}` |

---

## Accounting — Expenses

### `add_expense(expense: ExpenseRequest) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/documents/addexpense/` |
| Purpose | Record a supplier expense (purchase invoice / expense receipt) |
| Request body | `{"Supplier": {"Name", "SearchMode": "Automatic"}, "Date": "...", "Lines": [{"Item": {"Name", "SearchMode"}, "Amount": ...}], "Description"?, "ExpenseFile"? (base64), "ExpenseFilename"?}` |
| Returns | Dict with `expense_id` alias added (mirrors `DocumentID`) |

**`ExpenseRequest` fields:**

| Field | Type | Required |
|---|---|---|
| `supplier_name` | `str` | Yes |
| `amount` | `Decimal` | Yes (net amount; VAT is added if `vat_amount` provided) |
| `vat_amount` | `Decimal` | No |
| `expense_date` | `date` | Yes |
| `category` | `str` | No (sent as item name) |
| `notes` | `str` | No (sent as `Description`) |
| `receipt_file` | `str` | No (base64 PDF; sent as `ExpenseFile`) |

---

## Accounting — General

### `verify_bank_account(verification: BankAccountVerification) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/general/verifybankaccount/` |
| Purpose | Validate Israeli bank account (bank/branch/account number combination) |
| Request body | `{"BankCode": <int>, "BranchCode": <int>, "AccountNumber": <int>}` |
| Returns | Dict with `Result`, `ValidBranch`, `IsLimitedAccount` |

**`BankAccountVerification` fields:** `account_number`, `branch_number`, `bank_number` (all `str`, converted to `int` on send).

---

### `get_vat_rate(date: Optional[date] = None) -> Decimal`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/general/getvatrate/` |
| Purpose | Get the Israeli VAT rate for a given date (or today) |
| Request body | `{"Date"?: "YYYY-MM-DD"}` |
| Returns | `Decimal` rate (e.g. `Decimal("0.18")`) from `Data.Rate` |

---

### `get_exchange_rate(request: ExchangeRateRequest) -> ExchangeRateResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/general/getexchangerate/` |
| Purpose | Get foreign currency exchange rate between two currencies |
| Request body | `{"Currency_From": "...", "Currency_To": "...", "Date"?: "..."}` |
| Returns | `ExchangeRateResponse` (from_currency, to_currency, rate, date) |

**`ExchangeRateRequest` fields:** `from_currency: str`, `to_currency: str`, `date: Optional[date]`.

---

### `update_settings(settings: SettingsUpdate) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/general/updatesettings/` |
| Purpose | Update accounting application settings (document theme, email addresses, etc.) |
| Request body | The `settings.settings` dict is merged with credentials and POSTed as-is. Keys must match SUMIT's `Accounting_General_UpdateSettings_Request` fields (e.g. `DocumentsEmailAddress`, `AccountantEmail`, `DocumentsTheme`). |
| Returns | Response dict |

---

### `get_next_document_number(document_type: str) -> int`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/general/getnextdocumentnumber/` |
| Purpose | Get the next auto-assigned document number for a given document type |
| Request body | `{"Type": "<SUMIT enum>"}` (local type name is mapped) |
| Returns | `int` (`NextDocumentNumber`) |

---

### `set_next_document_number(request: DocumentNumberRequest) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/general/setnextdocumentnumber/` |
| Purpose | Override the next document number for a given type |
| Request body | `{"Type": "<SUMIT enum>", "NextDocumentNumber": <int>}` |
| Returns | Response dict |

**`DocumentNumberRequest` fields:** `document_type: str`, `next_number: Optional[int]` (default 1).

---

## Accounting — Income Items

### `create_income_item(item: IncomeItemRequest) -> IncomeItemResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/incomeitems/create/` |
| Purpose | Create a catalogue income item (product/service) |
| Request body | `{"IncomeItem": {"Name", "Price", "Currency", "Description"?}}` |
| Returns | `IncomeItemResponse` (item_id, name, description, price, currency, vat_rate) |

**`IncomeItemRequest` fields:** `name: str`, `description: Optional[str]`, `price: Decimal`, `currency: str` (default `"ILS"`), `vat_rate: Optional[Decimal]`, `category: Optional[str]`.

---

### `list_income_items() -> List[IncomeItemResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /accounting/incomeitems/list/` |
| Purpose | List all catalogue income items |
| Request body | Empty (credentials only) |
| Returns | `List[IncomeItemResponse]` — each with `item_id`, `name`, `description`, `price`, `currency` |

---

## Billing — Payments

### `charge_customer(charge: ChargeRequest) -> PaymentResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/payments/charge/` |
| Purpose | Charge a customer immediately via credit card (card data, token, or stored payment method) |
| Request body | `{"Customer": {...}, "Items": [...], "VATIncluded": true, "PaymentMethod": {...}?, "Payments_Count"?: <int>, "DocumentDescription"?: "..."}` |
| Returns | `PaymentResponse` (payment_id, amount, currency, status, authorization_number, last_4_digits) |

**`ChargeRequest` fields:**

| Field | Type | Notes |
|---|---|---|
| `customer_id` | `str` | Optional (defaults to `"Customer"`) |
| `amount` | `Decimal` | Yes |
| `currency` | `str` | Default `"ILS"` |
| `description` | `str` | No |
| `payment_method` | `str` | Token or numeric ID of stored method |
| `card` | `PaymentMethodCard` | Inline card data (number, expiry, CVV, holder name) |
| `installments` | `int` | Default 1 |
| `document_id` | `str` | No |

---

### `multivendor_charge(charge: ChargeRequest, vendor_splits: List[Dict[str, Any]]) -> PaymentResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/payments/multivendorcharge/` |
| Purpose | Charge a customer with proceeds split across multiple vendors |
| Request body | Same as `charge_customer` but each item in `Items` may carry `CompanyID` and `APIKey` |
| Returns | `PaymentResponse` for the first vendor's payment |

**`vendor_splits` list items:** `{"company_id"/"CompanyID"?, "api_key"/"APIKey"?, "amount"/"Total"?, "description"/"Description"?}`.

---

### `get_payment(payment_id: str) -> PaymentResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/payments/get/` |
| Purpose | Fetch details of a single payment |
| Request body | `{"PaymentID": <int>}` |
| Returns | `PaymentResponse` |

---

### `list_payments(customer_id?, from_date?, to_date?, limit?, offset?) -> List[PaymentResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/payments/list/` |
| Purpose | List payments within a date range |
| Request body | `{"Date_From": "...", "Date_To": "...", "StartIndex": <int>}` |
| Returns | `List[PaymentResponse]` |

**Notes:**
- `from_date` defaults to one year before `to_date` when omitted.
- `to_date` defaults to today when omitted.
- `customer_id` filtering is applied **client-side**.
- `limit` is enforced client-side after the API response.

---

### `begin_payment_redirect(amount, description, return_url, customer_id?) -> str`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/payments/beginredirect/` |
| Purpose | Create a hosted payment page and return its redirect URL |
| Request body | `{"Customer": {...}, "Items": [...], "VATIncluded": true, "RedirectURL": "..."}` |
| Returns | Redirect URL string (`RedirectURL`) |

---

## Billing — Payment Methods

### `get_payment_methods(customer_id: str) -> List[PaymentMethodResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/paymentmethods/getforcustomer/` |
| Purpose | List all stored payment methods for a customer (active first) |
| Request body | `{"Customer": {"ID": <int>}, "IncludeInactive": true}` |
| Returns | `List[PaymentMethodResponse]` (payment_method_id, type, last_4_digits, expiry_date, is_default) |

---

### `set_payment_methods(customer_id, payment_method_id, is_default?) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/paymentmethods/setforcustomer/` |
| Purpose | Save a payment method for a customer (replaces existing) |
| Request body | If `payment_method_id` is numeric: `{"Customer": {...}, "PaymentMethod": {"ID": ..., "Type": "CreditCard"}}`. If a token string: `{"Customer": {...}, "SingleUseToken": "..."}`. |
| Returns | Response dict |

---

### `remove_payment_method(customer_id, payment_method_id) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/paymentmethods/remove/` |
| Purpose | Remove the customer's stored payment method |
| Request body | `{"Customer": {"ID": <int>}}` (`payment_method_id` is not sent to the API) |
| Returns | Response dict |

---

### `setup_upay_credentials(credentials: Dict[str, str]) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/generalbilling/setupaycredentials/` |
| Purpose | Link an existing Upay account to this SUMIT company |
| Request body | `{"EmailAddress": "...", "Password": "..."}` |
| Returns | Response dict |

---

## Billing — Recurring Payments

### `list_customer_recurring(customer_id: str) -> List[RecurringPaymentResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/recurring/listforcustomer/` |
| Purpose | List all recurring billing items for a customer |
| Request body | `{"Customer": {"ID": <int>}, "IncludeInactive": true}` |
| Returns | `List[RecurringPaymentResponse]` (recurring_id, customer_id, amount, currency, frequency, status, next_charge_date) |

---

### `cancel_recurring(recurring_id, customer_id?) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/recurring/cancel/` |
| Purpose | Cancel an active recurring billing item |
| Request body | `{"RecurringCustomerItemID": <int>, "Customer"?: {...}}` |
| Returns | Response dict |

---

### `update_recurring(recurring_id, updates: RecurringPaymentRequest) -> RecurringPaymentResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/recurring/update/` |
| Purpose | Update the amount or schedule of a recurring item |
| Request body | `{"Customer": {...}, "RecurringCustomerItemID": <int>, "UnitPrice": ..., "NextPaymentDate"?: "...", "LastPaymentDate"?: "..."}` |
| Returns | `RecurringPaymentResponse` |

**`RecurringPaymentRequest` fields:** `customer_id`, `amount`, `currency`, `frequency`, `start_date`, `end_date?`, `payment_method_id`, `description?`.

---

### `update_recurring_settings(settings: Dict[str, Any]) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /billing/recurring/updatesettings/` |
| Purpose | Update recurring billing application settings |
| Request body | The settings dict is POSTed as-is. Keys must match SUMIT's `Recurring_UpdateSettings_Request` fields (e.g. `AutomaticBilling_CreditCard`, `AutomaticBilling_ChargeDocument`). |
| Returns | Response dict |

---

## Credit Card Terminal — Gateway

### `create_card_transaction(transaction: TransactionRequest) -> TransactionResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/gateway/transaction/` |
| Purpose | Create a raw credit card gateway charge (prefer `charge_customer()` for most cases) |
| Request body | `{"ParamJ": "Charge", "Amount": ..., "Currency": "...", "CustomData_1"?: "..."}` |
| Returns | `TransactionResponse` (transaction_id, status, amount, currency, created_at) |

---

### `get_transaction(transaction_id: str) -> TransactionResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/gateway/gettransaction/` |
| Purpose | Retrieve a gateway transaction by ID |
| Request body | `{"ID": <int>}` |
| Returns | `TransactionResponse` |

---

### `begin_redirect(transaction_id, return_url) -> str`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/gateway/beginredirect/` |
| Purpose | Initiate a hosted payment page redirect for a gateway charge |
| Request body | `{"Mode": "Charge", "Identifier": "...", "RedirectURL": "..."}` |
| Returns | Redirect URL string (`RedirectURL`) |

---

### `get_reference_numbers(transaction_ids: List[str]) -> Dict[str, str]`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/gateway/getreferencenumbers/` |
| Purpose | Retrieve bank reference numbers for multiple gateway transactions |
| Request body | `{"IDs": [<int>, ...]}` |
| Returns | `Dict[transaction_id -> reference_number]` (zipped from `ReferenceNumbers_ByID`) |

---

## Credit Card Terminal — Billing Batch

### `process_billing_transactions(transaction_ids: List[str]) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/billing/process/` |
| Purpose | Process a billing batch by its `BillingIdentifier` |
| Request body | `{"BillingIdentifier": "..."}` (one call per identifier) |
| Returns | `{"results": {<identifier>: <response_dict>}}` |

---

### `get_billing_status(transaction_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/billing/getstatus/` |
| Purpose | Get the processing status of a billing batch |
| Request body | `{"BillingIdentifier": "...", "ListTransactions": true}` |
| Returns | Status dict (varies by SUMIT response) |

---

## Credit Card Terminal — Vault (Tokenization)

### `tokenize_card(request: TokenizeCardRequest) -> TokenResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/vault/tokenize/` |
| Purpose | Tokenize a credit card for reuse (persistent token) |
| Request body | `{"CardNumber": "...", "ForceFormatPreservingToken": ""}` |
| Returns | `TokenResponse` (token, last_4_digits, expiry_date, card_brand) — `card_brand` is always `"Unknown"` |

---

### `tokenize_single_use(request: TokenizeCardRequest) -> TokenResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/vault/tokenizesingleusejson/` |
| Purpose | Tokenize a card for a single charge (short-lived token) |
| Request body | `{"CardNumber", "ExpirationMonth", "ExpirationYear", "CVV"}` |
| Returns | `TokenResponse` (token from `SingleUseToken`) |

---

### `tokenize_single_use_json(card_data: Dict[str, Any]) -> TokenResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /creditguy/vault/tokenizesingleusejson/` |
| Purpose | Tokenize a card for single use using SUMIT's raw field names |
| Request body | `card_data` dict using SUMIT field names: `CardNumber`, `ExpirationMonth`, `ExpirationYear`, `CVV`, `CitizenID` |
| Returns | `TokenResponse` (token from `SingleUseToken`) |

**`TokenizeCardRequest` fields:** `card_number`, `expiry_month`, `expiry_year`, `cvv`, `holder_name`, `customer_id?`.

---

## CRM — Data

### `create_entity(entity: EntityRequest) -> EntityResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/createentity/` |
| Purpose | Create a new CRM entity in a folder |
| Request body | `{"Entity": {"Folder": "<folder_id>", "Properties": {<field_name>: <value>, ...}}}` |
| Returns | `EntityResponse` (entity_id, folder_id, fields, created_at, updated_at) |

---

### `update_entity(entity_id, entity: EntityRequest) -> EntityResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/updateentity/` |
| Purpose | Update an existing CRM entity |
| Request body | `{"Entity": {"ID": <int>, "Folder": "...", "Properties": {...}}}` |
| Returns | `EntityResponse` |

---

### `get_entity(entity_id: str) -> EntityResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/getentity/` |
| Purpose | Fetch a single CRM entity with all its fields |
| Request body | `{"EntityID": <int>, "IncludeFields": true}` |
| Returns | `EntityResponse` |

---

### `list_entities(folder_id, limit=100, offset=0) -> List[EntityResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/listentities/` |
| Purpose | List CRM entities in a folder with pagination |
| Request body | `{"Folder": "...", "LoadProperties": true, "Paging": {"StartIndex": ..., "PageSize": ...}}` |
| Returns | `List[EntityResponse]` |

---

### `archive_entity(entity_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/archiveentity/` |
| Purpose | Archive (soft-delete) a CRM entity |
| Request body | `{"EntityID": <int>}` |
| Returns | Response dict |

---

### `delete_entity(entity_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/deleteentity/` |
| Purpose | Permanently delete a CRM entity |
| Request body | `{"EntityID": <int>}` |
| Returns | Response dict |

---

### `count_entity_usage(entity_id: str) -> int`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/countentityusage/` |
| Purpose | Count how many times a CRM entity is referenced elsewhere |
| Request body | `{"EntityID": <int>}` |
| Returns | `int` (from `Count`, `UsageCount`, or `count`) |

---

### `get_entity_print_html(entity_id: str) -> str`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/data/getentity/` then `POST /crm/schema/getfolder/` then `POST /crm/data/getentityprinthtml/` |
| Purpose | Render a CRM entity as printable HTML (auto-resolves SchemaID via two pre-calls) |
| Request body (final call) | `{"SchemaID": <int>, "EntityID": <int>}` (binary response) |
| Returns | HTML string (decoded from binary response) |

---

## CRM — Schema

### `get_folder(folder_id: str) -> FolderResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/schema/getfolder/` |
| Purpose | Get CRM folder metadata and field schema definitions |
| Request body | `{"Folder": "...", "IncludeProperties": true}` |
| Returns | `FolderResponse` (folder_id, folder_name, field_definitions) |

---

### `list_folders() -> List[FolderResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/schema/listfolders/` |
| Purpose | List all CRM folders for this company |
| Request body | Empty (credentials only) |
| Returns | `List[FolderResponse]` (field_definitions is empty per folder in this call) |

---

## CRM — Views

### `list_views(folder_id: str) -> List[Dict[str, Any]]`

| Field | Value |
|---|---|
| Endpoint | `POST /crm/views/listviews/` |
| Purpose | List saved views within a CRM folder |
| Request body | `{"FolderID": <int>}` |
| Returns | `List[Dict]` (raw `Views` array from SUMIT) |

---

## Customer Service — Tickets

### `create_ticket(ticket: TicketRequest) -> TicketResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /customerservice/tickets/create/` |
| Purpose | Create a customer service ticket |
| Transport | **Credentials are sent as query string parameters** (`Credentials.APIKey`, `Credentials.CompanyID`), not in the JSON body — this endpoint differs from all others |
| Request (query params) | `Subject`, `ContentsText`, `CustomerID`? (int) or `CustomerName`? (string), `Credentials.APIKey`, `Credentials.CompanyID`? |
| Returns | `TicketResponse` (ticket_id, subject, status="open", created_at) |

**`TicketRequest` fields:** `subject: str`, `description: str`, `customer_id?: str`, `priority?: str`, `category?: str`.

---

## Email Subscriptions

### `list_mailing_lists() -> List[Dict[str, Any]]`

| Field | Value |
|---|---|
| Endpoint | `POST /emailsubscriptions/mailinglists/list/` |
| Purpose | List all email mailing lists |
| Request body | Empty (credentials only) |
| Returns | List of raw mailing list dicts (`MailingLists`) |

---

### `add_to_mailing_list(request: EmailListRequest) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /emailsubscriptions/mailinglists/add/` |
| Purpose | Add a contact to an email mailing list |
| Request body | `{"MailingListID": <int>, "EmailAddress": "...", "Name"?: "..."}` |
| Returns | Response dict |

**`EmailListRequest` fields:** `list_id: str`, `email: EmailStr`, `name?: str`, `custom_fields?: Dict[str, str]`.

---

## SMS

### `send_sms(sms: SMSRequest) -> SMSResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /sms/sms/send/` |
| Purpose | Send a single SMS message |
| Request body | `{"Recipient": "...", "Text": "...", "Sender"?: "..."}` |
| Returns | `SMSResponse` (message_id from `EntityID`, status="sent", sent_at) |

**`SMSRequest` fields:** `phone_number: str`, `message: str`, `sender_name?: str`.

---

### `send_multiple_sms(messages: List[SMSRequest]) -> List[SMSResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /sms/sms/sendmultiple/` (batch when all texts are identical), else `POST /sms/sms/send/` per message |
| Purpose | Send SMS to multiple recipients, batching when the same message text is used for all |
| Request body (batch) | `{"Recipients": ["...", ...], "Text": "...", "Sender"?: "..."}` |
| Returns | `List[SMSResponse]` |

---

### `list_sms_senders() -> List[str]`

| Field | Value |
|---|---|
| Endpoint | `POST /sms/sms/listsenders/` |
| Purpose | List configured SMS sender names |
| Request body | Empty (credentials only) |
| Returns | `List[str]` (sender names) |

---

### `list_sms_mailing_lists() -> List[Dict[str, Any]]`

| Field | Value |
|---|---|
| Endpoint | `POST /sms/mailinglists/list/` |
| Purpose | List SMS mailing lists |
| Request body | Empty (credentials only) |
| Returns | List of raw mailing list dicts (`MailingLists`) |

---

### `add_to_sms_mailing_list(list_id, phone_number, name?) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /sms/mailinglists/add/` |
| Purpose | Add a contact to an SMS mailing list |
| Request body | `{"MailingListID": <int>, "PhoneNumber": "...", "Name"?: "..."}` |
| Returns | Response dict |

---

## Fax

### `send_fax(fax: FaxRequest) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /fax/fax/send/` |
| Purpose | Send a fax with a base64-encoded PDF |
| Request body | `{"FaxNumber": "...", "FileBytes": "<base64>", "Filename": "document.pdf"}` |
| Returns | Dict with `fax_id` alias added (mirrors `EntityID`) |
| Note | `document_content` (base64) is required; `document_url` is not supported by the API and will raise `Exception` |

**`FaxRequest` fields:** `fax_number: str`, `document_url?: str`, `document_content?: str` (base64 required).

---

## Stock

### `list_stock() -> List[StockItemResponse]`

| Field | Value |
|---|---|
| Endpoint | `POST /stock/stock/list/` |
| Purpose | List all stock items and their current quantities |
| Request body | Empty (credentials only) |
| Returns | `List[StockItemResponse]` (item_id, name, quantity from `Stock` field, unit="unit") |

---

## Triggers / Webhooks

### `subscribe_trigger(trigger_type, webhook_url) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /triggers/triggers/subscribe/` |
| Purpose | Subscribe a webhook URL to a SUMIT trigger event type |
| Request body | `{"URL": "...", "TriggerType": "..."}` |
| Returns | Subscription response dict |

---

### `unsubscribe_trigger(subscription_id: str) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /triggers/triggers/unsubscribe/` |
| Purpose | Unsubscribe a webhook by URL (subscription_id must be the subscribed URL) |
| Request body | `{"URL": "..."}` |
| Returns | Response dict |

---

## Website — Companies

### `create_company(company: CompanyRequest) -> CompanyResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /website/companies/create/` |
| Purpose | Create a new SUMIT organization |
| Request body | `{"Company": {"Name", "CorporateNumber", "EmailAddress"?, "Phone"?, "Address"?}}` |
| Returns | `CompanyResponse` (company_id, name, tax_id, created_at) |

---

### `update_company(company_id, company: CompanyRequest) -> CompanyResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /website/companies/update/` |
| Purpose | Update organization details (overrides `Credentials.CompanyID` with `company_id`) |
| Request body | `{"Credentials": {..., "CompanyID": <int>}, "Company": {...}}` |
| Returns | `CompanyResponse` |

---

### `get_company_details(company_id: str) -> CompanyResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /website/companies/getdetails/` |
| Purpose | Fetch organization details (overrides `Credentials.CompanyID` with `company_id`) |
| Request body | `{"Credentials": {..., "CompanyID": <int>}}` |
| Returns | `CompanyResponse` |

---

### `list_quotas() -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /website/companies/listquotas/` |
| Purpose | List API usage quotas for the current company |
| Request body | Empty (credentials only) |
| Returns | Raw quotas dict |

---

### `install_applications(application_ids: List[str]) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /website/companies/installapplications/` |
| Purpose | Install SUMIT applications for the company |
| Request body | `{"Applications": ["Accounting", "CRM", ...]}` |
| Returns | Installation result dict |

Valid application names come from SUMIT's `Website_Typed_Application` enum (e.g. `"Accounting"`, `"CRM"`, `"CreditCard"`, `"SMS"`).

---

## Website — Permissions

### `set_user_permissions(user_id, permissions: List[UserPermission]) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /website/permissions/set/` |
| Purpose | Assign a company role to a user |
| Request body | `{"UserID": <int>, "Role": "<role>"}` (first granted `permission_name` is used as role) |
| Returns | Response dict |

Valid roles: `Shared`, `ReadOnly`, `None`, `Accountant`, `Manager`, `Owner`.

---

### `remove_user_permissions(user_id, permission_names) -> Dict[str, Any]`

| Field | Value |
|---|---|
| Endpoint | `POST /website/permissions/remove/` |
| Purpose | Remove a user's company role entirely |
| Request body | `{"UserID": <int>}` (`permission_names` is not sent) |
| Returns | Response dict |

---

## Website — Users

### `create_user(user: UserRequest) -> UserResponse`

| Field | Value |
|---|---|
| Endpoint | `POST /website/users/create/` |
| Purpose | Create a new user and assign a company role |
| Request body | `{"User": {"Name": "...", "EmailAddress": "..."}, "Role": "..."}` |
| Returns | `UserResponse` (user_id, email, name, role, created_at) |

**`UserRequest` fields:** `email: EmailStr`, `name: str`, `role: str`, `permissions?: List[str]`.  
Valid roles: same as `set_user_permissions`.

---

### `user_login_redirect(user_id, return_url?) -> str`

| Field | Value |
|---|---|
| Endpoint | `POST /website/users/loginredirect/` |
| Purpose | Generate a single-use login redirect URL for a user |
| Request body | `{"EmailAddress": "<user_id>", "Password": ""}` |
| Returns | Login URL string (`RedirectURL`) |
| Note | `user_id` must be the user's **email address**, not a numeric ID. `return_url` is accepted by the method signature but is not forwarded to the API. |

---

## Not-Supported Stubs

The following methods exist in the client but always raise `Exception` because the underlying SUMIT API endpoint does not work as the method signature implies. They document the correct alternative.

| Method | Raises because | Recommended alternative |
|---|---|---|
| `get_balance()` | No balance endpoint exists | `get_debt_report()` or `list_payments()` |
| `load_billing_transactions(request)` | `/creditguy/billing/load/` submits charges, not lists history | `list_payments()` |
| `charge_recurring(recurring_id)` | Cannot charge existing recurring item by ID; SUMIT bills automatically | `charge_customer()` for one-off |
| `open_upay_terminal(amount, description)` | Endpoint onboards a new terminal, not a payment session | `charge_customer()` or `begin_payment_redirect()` |
| `get_entities_html(folder_id, entity_ids)` | Requires a saved ViewID; cannot render arbitrary entity list | `get_entity_print_html()` per entity |
| `send_letter_by_click(recipient, content)` | No postal letter service in SUMIT API | `send_fax()` or `send_document()` |
| `get_letter_tracking_code(letter_id)` | No postal letter service in SUMIT API | N/A |

---

*Total documented public methods: 68*
*(Includes 7 not-supported stubs, 61 operational methods)*

---

## Wave 2 Step 8 additions (verified against the live OpenAPI spec)

Pulled `https://api.sumit.co.il/swagger/v1/swagger.json` directly (WebFetch's
summarization dropped schema fields — the raw JSON is the source of truth
here) to close out the plan's "SUMIT API gaps" item. Findings reshaped the
plan's scope — most of it doesn't exist as specified:

| Method | What it really does | Notes |
|---|---|---|
| `create_document_from_existing(document_id)` | Clones an EXISTING document via `/scheduleddocuments/documents/createfromdocument/` | Replaces the old `create_scheduled_document(document, schedule_date)` stub. There is no `schedule_date`/raw-details endpoint — confirmed by reading the full request schema (`ScheduledDocuments_Documents_CreateFromDocument_Request` only has `DocumentID` + optional `IncomeItem`). Returns `ScheduledDocumentResult` (id/date/total only — SUMIT doesn't echo back the rest of the document). |
| `DocumentRequest.payments` (cash/cheque) | Adds a `Payments` array to `/accounting/documents/create/` | `Accounting_Typed_DocumentPayment` — one `Details_Cash` (empty object) or `Details_Cheque` (BankNumber/BranchNumber/AccountNumber/ChequeNumber/DueDate) per entry. Card payments still go through `charge_customer()`, unrelated to this. |
| `DocumentRequest.original_document_id` | Sets `OriginalDocumentID` on document-create | SUMIT's documented mechanism for "keeping a relationship between an original and a created document (such as credits for debit invoices)" — this is how a credit note gets linked to the invoice it credits. **There is no separate refund/reversal endpoint anywhere in the 84-path spec** — a credit note is the only refund primitive SUMIT exposes via API. |

**Confirmed gaps — no clean API path, not built:**
- **Mandates (הרשאות מס"ב) creation**: `/billing/recurring/{cancel,charge,listforcustomer,update,updatesettings}/` all operate on an *existing* `RecurringCustomerItemID`. There is no create-a-mandate endpoint in the spec — a recurring item is created some other way (SUMIT's own UI/income-item flow), not via a documented API call. `list`/`cancel`/`update` of existing recurring items were already fully wired (`/api/payments/recurring/*`, `payment_request_service.py`) before this audit — nothing to build for the "manage existing mandates" half of 8.3.
- **Chargeback alerts**: no chargeback-specific endpoint or webhook trigger type (`/triggers/triggers/subscribe/`'s `TriggerType` is generic CRM-entity CreateOrUpdate/Create/Update/Archive/Delete, nothing payment-specific). The only signal is `Payment.Status`/`Payment.ValidPayment` from `/billing/payments/list/`, and `Status` is undocumented free text — any detection would be a heuristic guess without real chargeback data to validate against.

**Bug found while auditing 8.3**: `POST /api/payments/recurring/{id}/charge` routed directly to `charge_recurring()` — a documented Not-Supported Stub that always raises a bare `Exception` (not `SumitAPIError`), so no handler caught it and any call would have leaked an unhandled 500 in production. Removed the route (kept the stub method, same as every other Not-Supported Stub — documented, never routed).
