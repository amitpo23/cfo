# Open Finance Client — API Reference

> Auto-derived from `src/cfo/services/open_finance_client.py` as of 2026-06-28.  
> This is the authoritative per-method reference for every public method on `OpenFinanceClient`.  
> For raw field shapes and enum values, see also `docs/open-finance/API_REFERENCE.md`.

---

## Table of Contents

1. [Client Setup & Authentication](#1-client-setup--authentication)
2. [Connections](#2-connections)
3. [Accounts](#3-accounts)
4. [Transactions](#4-transactions)
5. [Reports & Analytics](#5-reports--analytics)
6. [Decision / Scoring](#6-decision--scoring)
7. [Payments](#7-payments)
8. [ATM Codes](#8-atm-codes)
9. [Mandates](#9-mandates)
10. [Merchants](#10-merchants)
11. [Providers & Bank Branches](#11-providers--bank-branches)
12. [Credit Sessions / Loans (v3)](#12-credit-sessions--loans-v3)
13. [Customers / CRM (v3)](#13-customers--crm-v3)
14. [OSH Accounts & Transactions (v3)](#14-osh-accounts--transactions-v3)
15. [Communication](#15-communication)
16. [Error Handling](#16-error-handling)

---

## Base URLs

| Layer | URL |
|---|---|
| OAuth | `https://api.open-finance.ai/oauth/token` |
| v2 (accounts, transactions, payments, etc.) | `https://{api_prefix}.open-finance.ai/v2` |
| v3/loans (credit sessions, customers) | `https://{api_prefix}.open-finance.ai/v3/loans` |

`api_prefix` defaults to `"api"` and can be overridden at construction time.

---

## 1. Client Setup & Authentication

### Constructor

```python
OpenFinanceClient(
    client_id: str,
    client_secret: str,
    user_id: str,
    *,
    api_prefix: str = "api",
    oauth_url: Optional[str] = None,
    v2_base: Optional[str] = None,
    v3_loans_base: Optional[str] = None,
    timeout: float = 30.0,
    token_skew_seconds: float = 30.0,
)
```

| Parameter | Default | Description |
|---|---|---|
| `client_id` | required | OAuth client ID |
| `client_secret` | required | OAuth client secret |
| `user_id` | required | Our identifier passed to the token endpoint (also used as default in `refresh_all_connections`, `get_monthly_report`) |
| `api_prefix` | `"api"` | Subdomain prefix — `api_prefix.open-finance.ai` |
| `oauth_url` | `https://api.open-finance.ai/oauth/token` | Override token endpoint |
| `v2_base` | derived from `api_prefix` | Override v2 base URL |
| `v3_loans_base` | derived from `api_prefix` | Override v3/loans base URL |
| `timeout` | `30.0` | httpx request timeout in seconds |
| `token_skew_seconds` | `30.0` | Refresh token this many seconds before it would expire |

The client is an async context manager (`async with OpenFinanceClient(...) as client:`).

**Token lifecycle:** Tokens are obtained via `POST /oauth/token` with `{userId, clientId, clientSecret}`. The response `expiresIn` is in **milliseconds**. The client caches the token and automatically refreshes it when it is within `token_skew_seconds` of expiry, and also refreshes on a `401` response.

---

### `ping() -> bool`

**Purpose:** Lightweight credential and connectivity check — forces a token refresh.  
**Endpoint:** `POST /oauth/token` (token request only)  
**Returns:** `True` on success, `False` on any exception (errors are logged, not raised).

---

## 2. Connections

Connections represent bank consent journeys. A connection carries the `connectUrl` the end-user must visit to authorize access.

### `list_connections(...) -> dict`

```python
async def list_connections(
    *,
    customer_id=None,
    contact_id=None,
    status=None,
    limit=None,
    sort=None,
    next_page=None,
)
```

**Endpoint:** `GET /v2/connections`  
**Query params:** `customerId`, `contactId`, `status`, `limit`, `sort` (1 | -1), `nextPage`  
**Returns:** `{ nextPage, count, items: [Connection] }`

---

### `create_connection(body: dict) -> dict`

**Purpose:** Create a bank connection; launches the hosted consent journey.  
**Endpoint:** `POST /v2/connections`  
**Request body:** Pass the full body dict directly. Key fields include:
- `customerId`, `journeyId`, `language` (`he` | `en`)
- `callbackInformation`, `redirectUrl`
- `access` `{ accounts, balances, transactions }`
- `providerId`, `psuId`, `psuCorporateId`
- `startDate`, `expiryDate`, `connectionMode` (default `PSD2`)
- `allowBusiness`, `includeFakeProviders`, `iframe`

**Returns:** `{ id, connectUrl }` — `connectUrl` is the hosted consent journey link.

---

### `get_connection(connection_id: str) -> dict`

**Endpoint:** `GET /v2/connections/{connectionId}`  
**Returns:** Connection object. Status can be: `INACTIVE`, `FETCHING`, `CONNECTED`, `COMPLETED`, `ACTIVE`, `ERROR`, `EXPIRED`, `FETCHING_ERROR`, `REJECTED`, `PARTIALLY_AUTHORIZED`, `REPLACED`, `REVOKED`, `SUSPENDED_BY_PROVIDER`, `CREDENTIALS_ERROR`, `UNKNOWN`, `TERMINATED_BY_USER`.

---

### `delete_connection(connection_id: str) -> None`

**Endpoint:** `DELETE /v2/connections/{connectionId}`  
**Returns:** `None` (204). Note: returns 423 if the connection was created less than 90 minutes ago.

---

### `refresh_connection(connection_id: str) -> None`

**Endpoint:** `GET /v2/connections/refresh/{connectionId}`  
**Returns:** `None` (204).

---

### `refresh_all_connections(user_id: Optional[str] = None) -> None`

**Endpoint:** `GET /v2/connections/{userId}/refresh`  
**Behavior:** Uses `self.user_id` if `user_id` is not provided.  
**Returns:** `None` (204).

---

### `init_open_banking_connection(body: dict) -> dict`

**Purpose:** Initiate an Open Banking (PSD2) connection with a specific provider.  
**Endpoint:** `POST /v2/connect/open-banking-init`  
**Request body:** `providerId*`, `connectionId*`, `psuId*`, `psuIdType`, `psuCorporateId`, `expiryDate`, `refreshData`, `restrictedTo[]`, `customerApprovalGranted`  
**Returns:** `{ connection, scaOAuth }`

---

### `finalize_open_banking_connection(*, state, code=None, error=None) -> dict`

**Purpose:** Finalize an Open Banking connection after the provider redirect.  
**Endpoint:** `GET /v2/connect/open-banking-finalize`  
**Query params:** `state*`, `code`, `error`  
**Returns:** `{ connectionId, connectionStatus, paymentStatus, orgId, userId, paymentId, token, isIframe, isPayment, psuId, redirectUrl }`

---

## 3. Accounts

### `list_accounts(...) -> dict`

```python
async def list_accounts(
    *,
    connection_id=None,
    account_type=None,
    include_duplicates=0,
    sort=-1,
    limit=500,
    next_page=None,
)
```

**Endpoint:** `GET /v2/data/accounts`  
**Query params:** `connectionId`, `accountType`, `includeDuplicates` (0|1), `sort` (1|-1), `limit`, `nextPage`  
**Returns:** Paginated list of Account objects. Pagination via `nextPage` cursor.

**Key Account fields:** `id`, `userId`, `providerId`, `connectionId`, `accountNumber`, `accountName`, `product`, `accountType`, `currency`, `balances[]`, `creditLimit`, `parsedAccount{bank,branch,number}`, `ownerInfo{nationalId,fullName}`, `usage` (Private|business), `creditStatus`, `securityPositions[]`, `loanType[]`. Note: the API uses the key `interst` (sic) for savings/loan interest.

---

### `get_account(account_id: str) -> dict`

**Endpoint:** `GET /v2/data/accounts/{accountId}`  
**Returns:** Single Account object.

---

### `verify_account_number(*, account_number=None, account_iban_number=None) -> dict`

**Purpose:** Verify that a bank account number is valid.  
**Endpoint:** `POST /v2/account-number-verification`  
**Request body:** At least one of `accountNumber` (format `^\d+-\d+-\d+$`) or `accountIbanNumber`. Null values are stripped before sending.  
**Returns:** `{ status: "RESTRICTED" | "VALID" | "INVALID", reason }`

---

## 4. Transactions

### `list_transactions(...) -> dict`

```python
async def list_transactions(
    *,
    account_id=None,
    connection_id=None,
    provider_id=None,
    type=None,
    date_from=None,
    date_to=None,
    include_duplicates=0,
    sort=-1,
    limit=None,
    next_page=None,
)
```

**Endpoint:** `GET /v2/data/transactions`  
**Notable behavior:**
- `limit` and date filters (`date_from` / `date_to`) are **mutually exclusive**. When date filters are provided, `limit` is omitted entirely. When no date filters are given, `limit` defaults to `500`.
- `type` is `BANK` or `CARD`.
- `userId` query param is not sent (would cause 400 for non-admin callers).

**Returns:** `{ nextPage, items: [Transaction] }` or bare array depending on response shape.

**Key Transaction fields:** `id`, `SK`, `accountId`, `connectionId`, `description{description,additionalInfo}`, `amount{originalAmount{amount,currency}, chargedAmount{amount,currency}}`, `date{bookingDate,transactionDate,valueDate}`, `merchantName`, `category{main,sub,categorizedBy}`, `balancePerEndDay`, `isDuplicate`, `installments{number,total}`, `markupFee{amount,currency}`, `labels[]`, `creditorAccount`, `debtorAccount`, `endToEndId`, `entryReference`.

**Amount sign:** Sign is preserved as returned by the API (positive = inflow, negative = outflow per convention). This is unvalidated until a real bank connects — see `bank_insights.validate_sign_convention()`.

---

### `get_transaction(sk: str) -> dict`

**Endpoint:** `GET /v2/data/transactions/{SK}`  
**Returns:** Single Transaction object.

---

### `update_transaction(sk: str, *, customer_id=None, main_category=None, sub_category=None, classification=None, classification_source=None, labels=None) -> dict`

**Endpoint:** `PATCH /v2/data/transactions/{SK}`  
**Request body:** `transactionSk` (always included), plus any of: `customerId`, `mainCategory`, `subCategory`, `classification`, `classificationSource`, `labels[]`. Null values are stripped.  
**Returns:** Updated Transaction object.

---

## 5. Reports & Analytics

### `create_financial_report(customer_id: str) -> dict`

**Endpoint:** `POST /v2/financial-report/{customerId}`  
**Returns:** `{ jobId }` — poll with `get_financial_report(job_id)`.

---

### `get_financial_report(job_id: str, *, with_pdf=False) -> dict`

**Endpoint:** `GET /v2/financial-report/{jobId}`  
**Query params:** `withPdf` (`"1"` if `with_pdf=True`, omitted otherwise)  
**Returns:** `{ financialReport{...}, status: "DONE" | "RUNNING", url }`

---

### `get_monthly_report(user_id: Optional[str] = None) -> dict`

**Endpoint:** `GET /v2/data/monthly-report/{userId}`  
**Behavior:** Uses `self.user_id` if `user_id` is not provided.  
**Returns:** `OpenBankingReport` with sections:
- `openBankingReportBalances.incomes{total, incomeFromSalary, incomeFromChecks, regularIncomesSum}`
- `openBankingReportBalances.expenses{total, expensesFromMortgage, expensesFromChecks, regularExpensesSum}`
- Risk indicators: `canceledChecks`, `standingOrdersReturns`, `nsf`, `irregularWarnings`, `accountForeclosure`, `limitationAlert`
- `MonthlyReportGeneralDetails.loans{totalLoansAmount, bankLoans, creditCardLoans}`
- `.savings{totalSavingsAmount, savingsDetails}`
- `.accounts{checking[], savings[], loans[]}`

---

### `get_extended_securities() -> dict`

**Endpoint:** `GET /v2/data/extended-securities`  
**Returns:** `{ positions[...], totalPositionsValue, orders[...] }`

---

### `send_financial_data_email(*, details_to_share: list[str], email: str) -> dict`

**Endpoint:** `POST /v2/aggregate/financial-data-email`  
**Request body:** `detailsToShare` (array of `CHECKING` | `CARD` | `LOAN` | `SAVINGS` | `INSURANCE`), `email`  
**Returns:** `{ data }` (base64-encoded financial summary).

---

### `get_aggregations(user_ids: list[dict]) -> dict`

**Endpoint:** `POST /v2/aggregations`  
**Request body:** `{ userIds: [{id, segmentType}] }`  
**Returns:** `{ parameters: [{name, value}] }`

---

## 6. Decision / Scoring

All scoring methods follow a two-step async pattern: **create** (returns `jobId`) → **poll get** until `status == "DONE"`.

### `create_decision(customer_id: str) -> dict`

**Endpoint:** `POST /v2/decision/{customerId}`  
**Returns:** `{ jobId }`

---

### `get_decision(job_id: str) -> dict`

**Endpoint:** `GET /v2/decision/{jobId}`  
**Returns:** `{ decision: [DecisionGoNogo], status: "DONE" | "RUNNING" }`

---

### `create_decision_extended(customer_id: str) -> dict`

**Endpoint:** `POST /v2/decision-extended/{customerId}`  
**Returns:** `{ jobId }`

---

### `get_decision_extended(job_id: str) -> dict`

**Endpoint:** `GET /v2/decision-extended/{jobId}`  
**Returns:** `{ decision: [Extended], status }`

---

### `create_private_scoring(customer_id: str) -> dict`

**Endpoint:** `POST /v2/private-scoring/{customerId}`  
**Returns:** `{ jobId, status: "READY" | "LOADING_MORE" | "NOT_READY" | "NO_CONNECTIONS_FOUND" }`

---

### `get_private_scoring(job_id: str) -> dict`

**Endpoint:** `GET /v2/private-scoring/{jobId}`  
**Returns:** `{ status, scoring: { finalScore, customerId, orgId, createdAt } }`

---

## 7. Payments

### `create_payment(body: dict) -> dict`

**Purpose:** Create a payment via the merchant/redirect flow.  
**Endpoint:** `POST /v2/payments`  
**Request body key fields:**
- `merchantId`, `redirectUrl`, `externalId`, `psuId`, `providerIds[]`, `language` (he|en)
- `paymentService` (`masav` | `fp` | `zahav`)
- `paymentInformation{amount*, currency*, description*, creditorAccountType(bban|iban), creditorAccountNumber, debtorId, debtorAccountNumber, creditorName, debtorName}`
- `bulkPaymentInformation` or `periodicPaymentInformation` for those payment types
- `iframe`, `directPayOnly`, `callbackInformation`

**Returns:** `{ id, payUrl }` (201)

---

### `list_payments(*, limit=None, sort=None, next_page=None) -> dict`

**Endpoint:** `GET /v2/payments`  
**Query params:** `limit`, `sort`, `nextPage`  
**Returns:** `{ nextPage, items: [Payment] }`

---

### `get_payment(payment_id: str) -> dict`

**Endpoint:** `GET /v2/payments/{paymentId}`  
**Returns:** Payment object. Status enum: `ACCC`, `ACSC`, `ACSP`, `ACTC`, `ACWC`, `ACFC`, `RCVD`, `RJCT`, `PATC`, `PENDING`, `ERROR`, `CANC`, `INIT`, `PART`.

---

### `cancel_payment(payment_id: str) -> dict`

**Endpoint:** `DELETE /v2/payments/{paymentId}`  
**Returns:** Payment object (200, not 204).

---

### `refund_payment(payment_id: str, *, description: str, amount: float, psu_id=None, psu_corporate_id=None, phone_number=None, send_sms=False) -> dict`

**Endpoint:** `POST /v2/payments/{paymentId}/refund`  
**Request body:** `description*`, `amount*`, `psuId`, `psuCorporateId`, `phoneNumber`, `sendSMS`. Null values are stripped.  
**Returns:** `{ id, payUrl, sentMerchantSMS }`

---

### `get_payment_status(payment_id: str) -> dict`

**Endpoint:** `GET /v2/payments/{paymentId}/status`  
**Returns:** Payment object (same as `get_payment`).

---

### `update_sandbox_payment_status(payment_id: str, status: str) -> dict`

**Purpose:** Sandbox only — force a payment into a specific status for testing.  
**Endpoint:** `PATCH /v2/payments/sandbox/{paymentId}`  
**Request body:** `{ status }`  
**Returns:** Updated Payment object.

---

### `init_payment(body: dict) -> dict`

**Purpose:** Initiate a payment via Open Banking (PSD2) — supports single, periodic, bulk, and RTP.  
**Endpoint:** `POST /v2/pay/open-banking-init`  
**Request body:** One of `paymentId | paymentInformation | bulkPaymentInformation | periodicPaymentInformation | rtpPaymentInformation`, plus `providerId*`.  
- **Periodic** fields: `amount*`, `currency*`, `description*`, `startDate*`, `frequency*`, `debtorAccountNumber*`, `debtorAccountType*`, `creditorAccountNumber`, `creditorAccountType`, `creditorName`, `endDate`, `executionRule`, `dayOfExecution`, `monthsOfExecution[]`
- **Bulk** fields: `debtorAccountNumber*`, `debtorAccountType*`, `batchBookingPreferred`, `requestedExecutionDate`, `payments[{amount*,currency*,description*,creditorAccountNumber|merchantId,creditorAccountType,creditorName}]`

**Returns:** `{ paymentId, status, scaOAuth, requestStatus }` (201)

---

## 8. ATM Codes

### `get_atm_code(payment_id: str) -> dict`

**Endpoint:** `GET /v2/atm/code/{paymentId}`  
**Returns:** `{ status: "DONE" | "PENDING", atmCode, paymentId }`

---

### `verify_atm_code(*, atm_id, atm_code, amount, atm_date) -> dict`

**Endpoint:** `POST /v2/atm/verify`  
**Request body:** `atmId*`, `atmCode*`, `amount*`, `atmDate*` (format: `DD-MM-YYYY`)  
**Returns:** `{ dateTime }`

---

## 9. Mandates

Mandates are recurring debit authorizations. Note: these methods call paths under `/v2/mandates` but the client dispatches through `self.v2_base`, resulting in effective paths `/v2/v2/mandates/...`. This may be intentional double-prefixing if `v2_base` is set to the host root rather than `/v2`; verify against your configured `v2_base`.

### `create_mandate(body: dict, *, psu_ip_address=None) -> dict`

**Endpoint:** `POST /v2/mandates`  
**Headers:** `psu-ip-address` if provided.  
**Request body key fields:**
- `mandateId` (≤35 chars), `version` (e.g. `"v1.8"`)
- `type{localInstrumentCode, serviceLevelCode}`
- `occurrences{sequenceType, frequencyType, firstCollectionDate}`
- `firstCollectionAmount / collectionAmount / maximumAmount{currency, amount}`
- `creditor*{name, other}`, `creditorAccount{iban|bban,...}`
- `debtorAccount*{iban|bban,...}`, `providerId`, `redirectFinalizePath`

**Returns:** `{ mandateId, mandateStatus, scaOAuth }`

---

### `delete_mandate(resource_id: str) -> None`

**Endpoint:** `DELETE /v2/mandates/{resourceId}`  
**Returns:** `None` (202 or 204).

---

### `get_mandate(resource_id: str) -> dict`

**Endpoint:** `GET /v2/mandates/{resourceId}`  
**Returns:** Mandate object. Status enum: `received`, `valid`, `partiallyAuthorised`, `rejected`, `revokedByPSU`, `expired`, `terminatedByTPP`, `suspended`.

---

### `get_mandate_status(resource_id: str) -> dict`

**Endpoint:** `GET /v2/mandates/{resourceId}/status`  
**Returns:** `{ mandateStatus, mandateReasonCode, mandateReasonProprietary }`

---

## 10. Merchants

### `list_merchants(*, limit=None, sort=None, next_page=None) -> dict`

**Endpoint:** `GET /v2/merchants`  
**Query params:** `limit`, `sort`, `nextPage`  
**Returns:** `{ nextPage, items: [Merchant{name, bban, iban, id, psuId, phoneNumber, displayName, logoUrl, createdAt, isDeleted}] }`

---

### `create_merchant(body: dict) -> dict`

**Endpoint:** `POST /v2/merchants`  
**Request body key fields:** `name*`, `bban`, `iban`, `psuId`, `phoneNumber`, `displayName`, `logo{file, fileName, fileType}` (base64)  
**Returns:** `{ id }` (201)

---

### `get_merchant(merchant_id: str) -> dict`

**Endpoint:** `GET /v2/merchants/{merchantId}`  
**Returns:** Merchant object.

---

### `update_merchant(merchant_id: str, body: dict) -> dict`

**Endpoint:** `PUT /v2/merchants/{merchantId}`  
**Request body:** `name`, `displayName`, `logo`, `bban`, `iban`, `psuId`, `phoneNumber`  
**Returns:** Updated Merchant object.

---

### `delete_merchant(merchant_id: str) -> None`

**Endpoint:** `DELETE /v2/merchants/{merchantId}`  
**Returns:** `None` (204).

---

## 11. Providers & Bank Branches

### `list_providers(*, include_fake_providers=None) -> list`

**Endpoint:** `GET /v2/providers`  
**Query params:** `includeFakeProviders`  
**Returns:** Array of Provider objects: `{ providerFriendlyId, name, nameNativeLanguage, mode, site, bankCode, image, type (BANK|CARD|INSURANCE), status, successRate, ... }`

---

### `list_bank_branches(bank_code: str) -> list`

**Endpoint:** `GET /v2/bank-branches`  
**Query params:** `bankCode*`  
**Returns:** Array of BankBranch objects: `{ branchCode, city, branchName, branchAddress, telephone, bankCode, ... }`

---

## 12. Credit Sessions / Loans (v3)

All endpoints in this section use the `v3/loans` base URL.

### `create_credit_session(body: dict) -> dict`

**Endpoint:** `POST /v3/loans/credit-sessions`  
**Request body key fields:** `customerId`, `leadSource`, `leadConversion`, `withJourneyUrl`, `journeySettings{journeyId,needsOTP}`, `allowedProviderIds[]`, `refreshData`, `agentEmail`, `psuId`, `iframe`  
**Returns:** `{ sessionId, customerId, leadId, opportunityId, accountId, contactId, id, connectUrl }` (201)

---

### `create_credit_session_with_agent(body: dict) -> dict`

**Endpoint:** `POST /v3/loans/credit-sessions/create-with-agent`  
**Returns:** `{ ...connectUrl }` (201) — same shape as `create_credit_session`.

---

### `list_credit_sessions(scope: str = "user", *, sync_data=None) -> dict`

**Endpoint:** `GET /v3/loans/credit-sessions/converted/{scope}`  
**Path param `scope`:** `"advisor"` | `"org"` | `"user"` (default `"user"`)  
**Query params:** `syncData`  
**Returns:** `{ count, nextPage, items: [CreditSession] }`

---

### `get_credit_session(session_id: str) -> dict`

**Endpoint:** `GET /v3/loans/credit-sessions/converted/{sessionId}`  
**Returns:** `{ count, nextPage, items, raw }`

---

### `delete_credit_session(session_id: str) -> None`

**Endpoint:** `DELETE /v3/loans/credit-sessions/converted/{sessionId}`  
**Returns:** `None` (204).

---

### `get_credit_session_files(session_id: str) -> dict`

**Endpoint:** `GET /v3/loans/credit-sessions/converted/{sessionId}/files/other`  
**Returns:** File listing for the session.

---

### `upload_credit_session_file(session_id: str, *, api_name: str, file: dict) -> dict`

**Endpoint:** `POST /v3/loans/credit-sessions/converted/{sessionId}/files/other`  
**Request body:** `{ apiName, file }` where `file` is `{file: base64, fileName, fileType}`  
**`api_name` enum:** `sessionBankBalance`, `sessionTransactions`, `sessionOwnerCreditReport`, `sessionFinancialReports`, `sessionCurrentYearBalanceSheet`, `sessionTabo`, `sessionAssessments`, `sessionPortfolio`, `sessionCarLicense`, `sessionBid`

---

### `get_dnb_company_info_pdf(session_id: str, body: dict) -> dict`

**Purpose:** Retrieve a D&B company info PDF for a credit session.  
**Endpoint:** `POST /v3/loans/credit-sessions/{sessionId}/dnb/company-info-pdf`  
**Request body:** `subscode`, `prmtcode`, `userName`, `passWord`, `number`, `type`, `prodCode`, `comment`, `priority`  
**Returns:** `{ url }`

---

### `list_credit_leads(scope: str = "user") -> dict`

**Endpoint:** `GET /v3/loans/credit-sessions/lead/{scope}`  
**Path param `scope`:** `"advisor"` | `"org"` | `"user"` (default `"user"`)  
**Returns:** Lead list.

---

### `get_credit_lead(lead_id: str) -> dict`

**Endpoint:** `GET /v3/loans/credit-sessions/lead/{leadId}`  
**Returns:** Lead object.

---

### `delete_credit_lead(lead_id: str) -> None`

**Endpoint:** `DELETE /v3/loans/credit-sessions/lead/{leadId}`  
**Returns:** `None` (204).

---

### `get_credit_lead_files(lead_id: str) -> dict`

**Endpoint:** `GET /v3/loans/credit-sessions/lead/{leadId}/files/other`  
**Returns:** File listing for the lead.

---

### `upload_credit_lead_file(lead_id: str, *, api_name: str, file: dict) -> dict`

**Endpoint:** `POST /v3/loans/credit-sessions/lead/{leadId}/files/other`  
**Request body:** `{ apiName, file }` — same shape as `upload_credit_session_file`.

---

## 13. Customers / CRM (v3)

All endpoints use the `v3/loans` base URL.

### `list_customers(...) -> dict`

```python
async def list_customers(
    *,
    limit=None,
    next_page=None,
    use_crm=None,
    sync_data=None,
    type=None,
    use_phone=None,
)
```

**Endpoint:** `GET /v3/loans/customers`  
**Query params:** `limit`, `nextPage`, `useCrm`, `syncData`, `type`, `usePhone`  
**Returns:** `{ count, nextPage, items: [Customer] }`

---

### `create_customer(body: dict) -> dict`

**Endpoint:** `POST /v3/loans/customers`  
**Notable behavior:** Automatically sets `useCrm = False` and `syncData = False` as defaults if not already in the body (the API requires these fields).  
**Request body key fields:** `useCrm*`, `syncData*`, `firstName`, `lastName`, `nationalId`, `email`, `phoneNumber`, `businessId`, `businessName`, `businessType`, `type` (`BUSINESS` | `PRIVATE`), `geoArea`  
**Returns:** `{ customerId }` (201). Note: `buisnessPostOfficeBox` is a known API typo preserved in responses.

---

### `get_customer(customer_id: str) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}`  
**Returns:** `{ count, nextPage, items, raw }`

---

### `update_customer(customer_id: str, body: dict) -> None`

**Endpoint:** `PATCH /v3/loans/customers/{customerId}`  
**Request body:** `firstName`, `lastName`, `email`, `phoneNumber`, `type`, `nationalId`, `businessId`, `businessName`, `businessType`, `geoArea`, and others.  
**Returns:** `None` (204).

---

### `delete_customer(customer_id: str) -> None`

**Endpoint:** `DELETE /v3/loans/customers/{customerId}`  
**Returns:** `None` (204).

---

### `get_customer_contact(customer_id: str, contact_id: str) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/contacts/{contactId}`  
**Returns:** `{ count, items: [Contact] }`

---

### `get_customer_balances(customer_id: str, *, sort=None, limit=None, next_page=None) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/files/balances`  
**Query params:** `sort`, `limit`, `nextPage`  
**Returns:** `{ count, nextPage, items: [{accountId, balanceType, balanceAmount{amount,currency}, ...}] }`

---

### `upload_customer_checking_account(customer_id: str, body: dict) -> dict`

**Endpoint:** `POST /v3/loans/customers/{customerId}/files/checking-account`  
**Request body:** `providerId*`, `file{file,fileName,fileType}` (base64), `sfFiles[]`, `useCrm`

---

### `get_customer_financial_relations(customer_id: str, *, sort=None, limit=None, next_page=None) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/files/financial-relations`  
**Query params:** `sort`, `limit`, `nextPage`  
**Returns:** `{ items: [{customerId, fileId, year, amount, category, subCategory}] }`

---

### `upload_customer_financial_report(customer_id: str, body: dict) -> dict`

**Purpose:** Upload a 6111 financial report (base64-encoded).  
**Endpoint:** `POST /v3/loans/customers/{customerId}/files/financial-report`

---

### `share_customer_financial_report(customer_id: str, *, file: str, session_id: str) -> dict`

**Purpose:** Share a financial report from the customer CRM to a credit session agent.  
**Endpoint:** `POST /v3/loans/customers/{customerId}/files/financial-report/share-with-agent`  
**Request body:** `{ file: base64*, sessionId* }`

---

### `upload_customer_invoice(customer_id: str, body: dict) -> dict`

**Purpose:** Upload a PCN (VAT invoice) file.  
**Endpoint:** `POST /v3/loans/customers/{customerId}/files/invoice`

---

### `list_customer_invoices(customer_id: str, *, sort=None, limit=None, next_page=None) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/files/invoices`  
**Returns:** `{ items: [{id, customerId, reportMonth, invoiceDate, totalInvoiceVat, sumInvoice, ...}] }`

---

### `delete_customer_invoice(customer_id: str, pcn_id: str) -> None`

**Endpoint:** `DELETE /v3/loans/customers/{customerId}/files/invoice/{pcnId}`  
**Returns:** `None` (204).

---

### `get_customer_other_file(customer_id: str) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/files/other`  
**Returns:** File listing.

---

### `upload_customer_other_file(customer_id: str, *, api_name: str, file: dict, use_crm=None) -> dict`

**Endpoint:** `POST /v3/loans/customers/{customerId}/files/other`  
**Request body:** `apiName`, `file{file,fileName,fileType}` (base64), `useCrm`. Null values are stripped.  
**`api_name` enum (customer):** `customerBankDetails`, `customerIdCard`, and others.

---

## 14. OSH Accounts & Transactions (v3)

OSH (Open Savings & Investments Hub) data is accessed via customer sub-resources under `v3/loans`.

### `list_osh_accounts(customer_id: str, *, sort=None, limit=None, next_page=None) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/osh/accounts`  
**Query params:** `sort`, `limit`, `nextPage`  
**Returns:** `{ items: [OSH Account] }`

---

### `update_osh_account(*, account_id, customer_id, credit_limit=None, balance=None) -> dict`

**Notable behavior:** IDs are in the **request body**, not the path.  
**Endpoint:** `PATCH /v3/loans/customers/osh/accounts`  
**Request body:** `accountId*`, `customerId*`, `creditLimit`, `balance`. Null values are stripped.

---

### `list_osh_transactions(customer_id: str, account_id: str, *, sort=None, limit=None, next_page=None) -> dict`

**Endpoint:** `GET /v3/loans/customers/{customerId}/osh/accounts/{accountId}`  
**Query params:** `sort`, `limit`, `nextPage`  
**Returns:** `{ items: [OSH Transaction] }`

---

### `delete_osh_account(customer_id: str, account_id: str) -> None`

**Endpoint:** `DELETE /v3/loans/customers/{customerId}/osh/accounts/{accountId}`  
**Returns:** `None` (204).

---

### `update_osh_transaction(*, transaction_sk, main_category=None, sub_category=None, classification=None, classification_source=None, labels=None) -> dict`

**Notable behavior:** Transaction SK and all IDs are in the **request body**, not the path.  
**Endpoint:** `PATCH /v3/loans/customers/osh/transactions`  
**Request body:** `transactionSk*`, `mainCategory`, `subCategory`, `classification`, `classificationSource`, `labels[]`. Null values are stripped.

---

## 15. Communication

### `send_whatsapp_link(*, body: str, from_: str) -> dict`

**Purpose:** Send or receive a WhatsApp message link via the Open Finance communication gateway.  
**Endpoint:** `POST /v2/v2/completion/wh/incoming`  
**Notable behavior:** Field names use capitalized keys `Body` and `From` as required by the API.  
**Request body:** `{ "Body": body, "From": from_ }`  
**Returns:** 200 with response payload.

---

## 16. Error Handling

All API errors raise `OpenFinanceError` (a subclass of `RuntimeError`):

```python
class OpenFinanceError(RuntimeError):
    status_code: int   # HTTP status code
    message: str       # API error message or truncated response text
    payload: Any       # Full JSON response body (if parseable), else None
```

**Automatic retry:** On a `401` response, the client refreshes the token once and retries the request automatically. All other 4xx/5xx responses raise `OpenFinanceError` immediately.

**204 / empty body:** Returns `None` rather than raising an error.

---

## Pagination

Most list methods return `{ nextPage, count, items }`. To paginate:

```python
next_page = None
while True:
    resp = await client.list_transactions(next_page=next_page, limit=500)
    items = resp.get("items", [])
    # process items ...
    next_page = resp.get("nextPage")
    if not next_page:
        break
```

The connector helper `_items_and_next(payload)` handles both `{items, nextPage}` dicts and bare arrays.

---

## File Upload Shape

All file uploads (customers, sessions, leads) use base64-in-JSON — **not multipart**:

```python
file = {
    "file": "<base64-encoded content>",
    "fileName": "statement.pdf",
    "fileType": "application/pdf",
}
```

---

## Known API Quirks

| Quirk | Detail |
|---|---|
| `interst` typo | Account field for savings/loan interest is `interst` (sic), not `interest` |
| `buisnessPostOfficeBox` typo | Customer field has a misspelling preserved by the API |
| Capitalized WhatsApp fields | `Body` and `From` are capitalized in `POST /v2/completion/wh/incoming` |
| OSH body IDs | `PATCH /customers/osh/accounts` and `/customers/osh/transactions` take IDs in the body, not the path |
| `expiresIn` in milliseconds | Token `expiresIn` is milliseconds, not seconds |
| `limit` vs date filters | `GET /data/transactions` — `limit` and date range are mutually exclusive |
| Amount sign unvalidated | Transaction amount sign convention (positive=inflow) is assumed but only validated at batch level by `bank_insights.validate_sign_convention()` when a real bank connects |
