# Open Finance API — Reference (harvested from docs.open-finance.ai)

Authoritative implementation reference for the full Open Finance / Financy integration.
All field names are exact (some contain typos preserved by the API — flagged inline).

## Base URLs (per group)

| Group | Base URL |
|---|---|
| OAuth token | `https://api.open-finance.ai/oauth/token` |
| Connections, Accounts, Transactions, Payments, ATM, Mandates, Merchants, Providers, Bank-branches, Reports, Decision, Private-scoring, Aggregations, Communication | `https://api.open-finance.ai/v2` |
| Credit-sessions, Customers (CRM/loans) | `https://api.open-finance.ai/v3/loans` |

`API_PREFIX` host segment defaults to `api`.

## Authentication

`POST https://api.open-finance.ai/oauth/token`
Body (JSON): `{ "userId": str, "clientId": str, "clientSecret": str }`
- `userId` is **our** identifier (any unique string we choose, e.g. per-org).
Response: `{ "accessToken": str, "tokenType": str, "expiresIn": number /* MS */ }`
All other calls: header `Authorization: Bearer {accessToken}`. Per-endpoint OAuth scopes documented but the token is issued globally for our client.

---

## Connections (v2)  — bank consent journey

- `GET /connections` — query: customerId, contactId, limit, sort(1|-1), nextPage, status → `{nextPage, count, items[Connection]}`
- `POST /connections` — **Create Connection**. body: customerId, startDate, expiryDate, paymentId, journeyId, language(he|en), externalId, agentEmail, providerIds[], callbackInformation, includeFakeProviders, refreshData, iframe, psuId, psuCorporateId, redirectUrl, connectionMode(default PSD2), allowBusiness, access{accounts,balances,transactions}, restrictedTo[CACC|CARD|LOAN|SVGS|SCTS], psuIdType, allowInsurance → 201 `{ id, connectUrl }` ← **connectUrl is the hosted consent journey link**
- `GET /connections/{connectionId}` → Connection
- `DELETE /connections/{connectionId}` → 204 (423 if locked < 90 min)
- `GET /connections/refresh/{connectionId}` → 204
- `GET /connections/{userId}/refresh` → 204 (refresh all)
- `POST /connect/open-banking-init` — body: providerId*, connectionId*, psuId*, psuIdType, psuCorporateId, expiryDate, refreshData, restrictedTo[], customerApprovalGranted → `{ connection, scaOAuth }`
- `GET /connect/open-banking-finalize` — query: code, state*, error → `{ connectionId, connectionStatus, paymentStatus, orgId, userId, paymentId, token, isIframe, isPayment, psuId, redirectUrl }`

**Connection.status enum:** INACTIVE, FETCHING, CONNECTED, COMPLETED, ACTIVE, ERROR, EXPIRED, FETCHING_ERROR, REJECTED, PARTIALLY_AUTHORIZED, REPLACED, REVOKED, SUSPENDED_BY_PROVIDER, CREDENTIALS_ERROR, UNKNOWN, TERMINATED_BY_USER.

## Accounts (v2)

- `GET /data/accounts` — query: nextPage, limit, includeDuplicates(0|1), sort, connectionId, userId, accountType → array[Account] (paginated via nextPage)
- `GET /data/accounts/{accountId}` → Account
- `POST /account-number-verification` — body: accountNumber (`^\d+-\d+-\d+$`), accountIbanNumber → `{ status: RESTRICTED|VALID|INVALID, reason }`

**Account fields:** id, userId, providerId, connectionId, externalId, status, accountNumber, product, parsedAccount{bank,branch,number}, accountType, creditStatus(deleted|enabled|disabled), cardDueDate, currency, ownerInfo{nationalId,fullName}, accountName, balances[Amount], `interst`[] (sic — savings/loans), relatedDates, usage(Private|business), creditLimit, transactions(count), applicableFees[], securityPositions[], securityOrders[], loanType[].

## Transactions (v2)

- `GET /data/transactions` — query: nextPage, limit(≤500, mutually exclusive with date filters), dateFrom(YYYY-MM-DD), dateTo, accountId, connectionId, providerId, type(BANK|CARD), includeDuplicates(0|1), sort(1|-1) → `{ nextPage, items[Transaction] }`. **No userId param for non-admin (400).**
- `GET /data/transactions/{SK}` → Transaction
- `PATCH /data/transactions/{SK}` — body: transactionSk*, customerId, mainCategory, subCategory, classification, classificationSource, labels[]

**Transaction fields:** id, SK, userId, orgId, connectionId, accountId, providerId, transactionProviderIdentifier, accountNumber, status, description{description,additionalInfo}, amount{originalAmount{amount,currency}, chargedAmount{amount,currency}}, category{main,sub,categorizedBy}, changedCategory{main,sub}, date{valueDate,bookingDate,transactionDate}, type, merchantName, merchantAddress{streetName,buildingNumber,townName,postCode,country}, balancePerEndDay, isDuplicate, installments{number,total}, labels[], code, categoryCode, entryReference, isInvoiced, details, creditorAccount{iban,bban,maskedPan,currency}, debtorAccount, endToEndId, markupFee{amount,currency}.

**Categories** (API pre-categorizes every txn):
- Expense main: HOUSEHOLD_&_SERVICES, HOME_IMPROVEMENTS, FOOD_&_DRINKS, TRANSPORT, SHOPPING, LEISURE, HEALTH_&_BEAUTY, OTHER, FINANCE
- Income main: SALARY, PENSION, REIMBURSEMENTS, BENEFITS, FINANCE, OTHER

## Reports & Analytics (v2)

- `POST /financial-report/{customerId}` → `{ jobId }`
- `GET /financial-report/{jobId}` — query withPdf(0|1) → `{ financialReport{...}, status(DONE|RUNNING), url }`
- `GET /data/monthly-report/{userId}` → OpenBankingReport:
  - `openBankingReportBalances.incomes{total,incomeFromSalary,incomeFromChecks,regularIncomesSum}`
  - `.expenses{total,expensesFromMortgage,expensesFromChecks,regularExpensesSum}`
  - risk: canceledChecks, standingOrdersReturns, irregularWarnings, accountForeclosure, nsf, transfersForFallingBehind, limitationAlert, fallingBehindWarnings
  - `MonthlyReportGeneralDetails.loans{totalLoansAmount,bankLoans,creditCardLoans}`, `.savings{totalSavingsAmount,savingsDetails}`, `.accounts{checking[],savings[],loans[]}`
- `GET /data/extended-securities` → `{ positions[...], totalPositionsValue, orders[...] }`
- `POST /aggregate/financial-data-email` — body: detailsToShare[CHECKING|CARD|LOAN|SAVINGS|INSURANCE]*, email* → `{ data /* base64 */ }`
- `POST /aggregations` — body: userIds[{id,segmentType}] → `{ parameters[{name,value}] }`

## Decision / Scoring (v2)

- `POST /decision/{customerId}` → `{ jobId }`
- `GET /decision/{jobId}` → `{ decision[DecisionGoNogo], status(DONE|RUNNING) }`
- `POST /decision-extended/{customerId}` → `{ jobId }`
- `GET /decision-extended/{jobId}` → `{ decision[Extended], status }`
- `POST /private-scoring/{customerId}` → `{ jobId, status(READY|LOADING_MORE|NOT_READY|NO_CONNECTIONS_FOUND) }`
- `GET /private-scoring/{jobId}` → `{ status, scoring{finalScore,customerId,orgId,createdAt} }`

## Payments (v2)

- `POST /payments` — Create. body: version, merchantId, redirectUrl, externalId, psuId, providerIds[], language(he|en), paymentService(masav|fp|zahav), iframe, directPayOnly, **paymentInformation{amount*,currency*,description*,creditorAccountType(bban|iban),creditorAccountNumber,debtorId,debtorAccountType,debtorAccountNumber,creditorName,debtorName}**, bulkPaymentInformation, periodicPaymentInformation, callbackInformation → 201 `{ id, payUrl }`
- `GET /payments` — query limit, sort, nextPage → `{ nextPage, items[Payment] }`
- `GET /payments/{paymentId}` → Payment
- `DELETE /payments/{paymentId}` → cancel (200)
- `POST /payments/{paymentId}/refund` — body: description*, amount*, psuId, psuCorporateId, phoneNumber, sendSMS → `{ id, payUrl, sentMerchantSMS }`
- `GET /payments/{paymentId}/status` → Payment
- `PATCH /payments/sandbox/{paymentId}` — body: status* → Payment
- `POST /pay/open-banking-init` — body: one of {paymentId|paymentInformation|bulkPaymentInformation|periodicPaymentInformation|rtpPaymentInformation} + providerId* → 201 `{ paymentId, status, scaOAuth, requestStatus }`
- `GET /atm/code/{paymentId}` → `{ status(DONE|PENDING), atmCode, paymentId }`
- `POST /atm/verify` — body: atmId*, atmCode*, amount*, atmDate*(DD-MM-YYYY) → `{ dateTime }`

**Periodic** (via /pay/open-banking-init): periodicPaymentInformation{amount*,currency*,description*,startDate*,frequency*,debtorAccountNumber*,debtorAccountType*,creditorAccountNumber,creditorAccountType,creditorName,endDate,executionRule,dayOfExecution,monthsOfExecution[]}.
**Bulk**: bulkPaymentInformation{debtorAccountNumber*,debtorAccountType*,batchBookingPreferred,requestedExecutionDate,payments[{amount*,currency*,description*,creditorAccountNumber|merchantId,creditorAccountType,creditorName}]}.

**Payment.status enum:** ACCC, ACSC, ACSP, ACTC, ACWC, ACFC, RCVD, RJCT, PATC, PENDING, ERROR, CANC, INIT, PART.

## Mandates (v2) — recurring debit authorizations

- `POST /v2/mandates` — body: mandateId(≤35), type{localInstrumentCode,serviceLevelCode}, occurrences{sequenceType,frequencyType,firstCollectionDate}, firstCollectionAmount/collectionAmount/maximumAmount{currency,amount}, creditor*{name,other}, creditorAccount{iban,bban,...}, debtorAccount*{iban,bban,...}, version(v1.8), providerId, redirectFinalizePath → `{ mandateId, mandateStatus, scaOAuth }`
- `DELETE /v2/mandates/{resourceId}` → 202/204
- `GET /v2/mandates/{resourceId}` → Mandate
- `GET /v2/mandates/{resourceId}/status` → `{ mandateStatus, mandateReasonCode, mandateReasonProprietary }`

**mandateStatus enum:** received, valid, partiallyAuthorised, rejected, revokedByPSU, expired, terminatedByTPP, suspended.

## Merchants / Banks (v2)

- `GET /merchants` — query limit, sort, nextPage → `{ nextPage, items[Merchant{name,bban,iban,id,psuId,phoneNumber,displayName,logoUrl,createdAt,isDeleted}] }`
- `POST /merchants` — body: name*, bban, iban, psuId, phoneNumber, displayName, logo{file,fileName,fileType} → 201 `{ id }`
- `GET /merchants/{merchantId}` → Merchant
- `PUT /merchants/{merchantId}` — body: name, displayName, logo, bban, iban, psuId, phoneNumber → Merchant
- `DELETE /merchants/{merchantId}` → 204
- `GET /providers` — query includeFakeProviders → array[Provider{providerFriendlyId,name,nameNativeLanguage,mode,site,bankCode,image,type(BANK|CARD|INSURANCE),status,successRate,...}]
- `GET /bank-branches` — query bankCode* → array[BankBranch{branchCode,city,branchName,branchAddress,telephone,bankCode,...}]

## Credit-sessions / Loans (v3/loans)

- `POST /credit-sessions` — Create credit request. body: CreditSessionRequest + iframe, customerId, leadSource, leadConversion, withJourneyUrl, journeySettings{journeyId,needsOTP}, allowedProviderIds[], refreshData, agentEmail, psuId → 201 `{ sessionId, customerId, leadId, opportunityId, accountId, contactId, id, connectUrl }`
- `POST /credit-sessions/create-with-agent` — → 201 `{ ...connectUrl }`
- `GET /credit-sessions/converted/{advisor|org|user}` — query syncData → `{ count, nextPage, items[CreditSession] }`
- `GET /credit-sessions/converted/{id}` → `{ count, nextPage, items, raw }`
- `DELETE /credit-sessions/converted/{id}` → 204
- `GET|POST /credit-sessions/converted/{id}/files/other` — get/upload files (base64 in `file.file`)
- `POST /credit-sessions/{id}/dnb/company-info-pdf` — body: subscode, prmtcode, userName, passWord, number, type, prodCode, comment, priority → `{ url }`
- `GET /credit-sessions/lead/{advisor|org|user}` , `GET|DELETE /credit-sessions/lead/{id}` , `GET|POST /credit-sessions/lead/{id}/files/other`

Upload `apiName` enum (sessions): sessionBankBalance, sessionTransactions, sessionOwnerCreditReport, sessionFinancialReports, sessionCurrentYearBalanceSheet, sessionTabo, sessionAssessments, sessionPortfolio, sessionCarLicense, sessionBid.

## Customers (v3/loans) — CRM

- `GET /customers` — query limit, nextPage, useCrm, syncData, type, usePhone → `{ count, nextPage, items[Customer] }`
- `POST /customers` — body: useCrm*, syncData*, firstName, lastName, nationalId, email, phoneNumber, businessId, businessName, businessType, ... → 201 `{ customerId }`
- `GET /customers/{id}` → `{ count, nextPage, items, raw }`
- `PATCH /customers/{id}` — body: firstName, lastName, email, phoneNumber, type(BUSINESS|PRIVATE), nationalId, businessId, businessName, businessType, geoArea, ... → 204
- `DELETE /customers/{id}` → 204
- `GET /customers/{customerId}/contacts/{contactId}` → `{ count, items[Contact] }`
- `GET /customers/{id}/files/balances` → `{ count, nextPage, items[{accountId,balanceType,balanceAmount{amount,currency},...}] }`
- `POST /customers/{id}/files/checking-account` — body: providerId*, file{file,fileName,fileType}, sfFiles[], useCrm
- `GET /customers/{id}/files/financial-relations` → items[{customerId,fileId,year,amount,category,subCategory}]
- `POST /customers/{id}/files/financial-report` — upload 6111 (base64)
- `POST /customers/{id}/files/financial-report/share-with-agent` — body: file*(base64), sessionId*
- `POST /customers/{id}/files/invoice` — upload PCN (base64)
- `GET /customers/{id}/files/invoices` → items[{id,customerId,reportMonth,invoiceDate,totalInvoiceVat,sumInvoice,...}]
- `DELETE /customers/{customerId}/files/invoice/{pcnId}` → 204
- `GET|POST /customers/{id}/files/other` — get/upload (apiName enum: customerBankDetails, customerIdCard, ...)
- `GET /customers/{id}/osh/accounts` → items[OSH Account]
- `PATCH /customers/osh/accounts` — body: accountId*, customerId*, creditLimit, balance (no path params!)
- `GET /customers/{customer_id}/osh/accounts/{account_id}` → items[OSH Transaction]
- `DELETE /customers/{customerId}/osh/accounts/{accountId}` → 204
- `PATCH /customers/osh/transactions` — body: transactionSk*, mainCategory, subCategory, classification, classificationSource, labels[] (no path params!)

## Communication (v2)

- `POST /v2/completion/wh/incoming` — body: `Body`* (capitalized), `From`* → 200 (WhatsApp message link)

## Webhooks (registered in dashboard.open-finance.ai/settings/alerts; no signature mechanism documented)

Event types:
1. **Connection Status Change** — {expiryDate, bankName, connectionId, connectionStatus, userId, orgId, connectionError{message,type}, accountNumbers[]}
2. **Payment Status Change** — {bankName, paymentId, paymentStatus, userId, orgId, paymentError{message,type}}
3. **Session Data Update** — {session{...}, customer{...}, contacts[...], status}

### Notes / quirks (copy verbatim)
- Account interest field key is `interst` (sic).
- Customer-by-id has `buisnessPostOfficeBox` (sic).
- WhatsApp body uses capitalized `Body`/`From`.
- PATCH `/customers/osh/accounts` and `/customers/osh/transactions` take IDs in the body, not the path.
- File uploads are base64-in-JSON `file:{file,fileName,fileType}`, not multipart.
- `expiresIn` from the token endpoint is in **milliseconds**.
