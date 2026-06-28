# Open Finance Provider API — Coverage Map

**Generated:** 2026-06-28  
**Client source:** `src/cfo/services/open_finance_client.py`  
**Provider catalog source:** `docs/open-finance/API_REFERENCE.md` (local authoritative reference) + `https://docs.open-finance.ai/llms.txt` (live index, spot-verified)  
**Catalog note:** The live docs site is a React SPA; WebFetch cannot render its sidebar. The endpoint list was obtained from `https://docs.open-finance.ai/llms.txt` (87 API reference endpoints confirmed) and cross-checked against the local `API_REFERENCE.md`. Several individual endpoints were fetched directly to spot-verify paths (OAuth token, mandate creation, payment init, credit-session scopes). No endpoints were fabricated.

---

## 1. Auth Verification

| Provider spec | Our client |
|---|---|
| `POST https://api.open-finance.ai/oauth/token` | `OpenFinanceClient._get_token()` |
| Body: `{ userId, clientId, clientSecret }` | `json={"userId": self.user_id, "clientId": self.client_id, "clientSecret": self.client_secret}` |
| Response: `{ accessToken, tokenType, expiresIn /* ms */ }` | Reads `payload["accessToken"]`; divides `expiresIn / 1000` for TTL |

**Verdict:** Exact match. The client correctly implements token caching (30 s skew), automatic 401-retry refresh, and millisecond-to-second conversion of `expiresIn`.

---

## 2. Coverage Map

Legend: ✅ implemented | ❌ missing | ⚠️ partial/note

### Connections (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 1 | GET | `/connections` | ✅ | `list_connections` |
| 2 | POST | `/connections` | ✅ | `create_connection` |
| 3 | GET | `/connections/{connectionId}` | ✅ | `get_connection` |
| 4 | DELETE | `/connections/{connectionId}` | ✅ | `delete_connection` |
| 5 | GET | `/connections/refresh/{connectionId}` | ✅ | `refresh_connection` |
| 6 | GET | `/connections/{userId}/refresh` | ✅ | `refresh_all_connections` |
| 7 | POST | `/connect/open-banking-init` | ✅ | `init_open_banking_connection` |
| 8 | GET | `/connect/open-banking-finalize` | ✅ | `finalize_open_banking_connection` |

**8/8 covered.**

### Accounts (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 9 | GET | `/data/accounts` | ✅ | `list_accounts` |
| 10 | GET | `/data/accounts/{accountId}` | ✅ | `get_account` |
| 11 | POST | `/account-number-verification` | ✅ | `verify_account_number` |

**3/3 covered.**

### Transactions (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 12 | GET | `/data/transactions` | ✅ | `list_transactions` |
| 13 | GET | `/data/transactions/{SK}` | ✅ | `get_transaction` |
| 14 | PATCH | `/data/transactions/{SK}` | ✅ | `update_transaction` |

**3/3 covered.**

### Reports & Analytics (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 15 | POST | `/financial-report/{customerId}` | ✅ | `create_financial_report` |
| 16 | GET | `/financial-report/{jobId}` | ✅ | `get_financial_report` |
| 17 | GET | `/data/monthly-report/{userId}` | ✅ | `get_monthly_report` |
| 18 | GET | `/data/extended-securities` | ✅ | `get_extended_securities` |
| 19 | POST | `/aggregate/financial-data-email` | ✅ | `send_financial_data_email` |
| 20 | POST | `/aggregations` | ✅ | `get_aggregations` |

**6/6 covered.**

### Decision / Scoring (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 21 | POST | `/decision/{customerId}` | ✅ | `create_decision` |
| 22 | GET | `/decision/{jobId}` | ✅ | `get_decision` |
| 23 | POST | `/decision-extended/{customerId}` | ✅ | `create_decision_extended` |
| 24 | GET | `/decision-extended/{jobId}` | ✅ | `get_decision_extended` |
| 25 | POST | `/private-scoring/{customerId}` | ✅ | `create_private_scoring` |
| 26 | GET | `/private-scoring/{jobId}` | ✅ | `get_private_scoring` |

**6/6 covered.**

### Payments (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 27 | POST | `/payments` | ✅ | `create_payment` |
| 28 | GET | `/payments` | ✅ | `list_payments` |
| 29 | GET | `/payments/{paymentId}` | ✅ | `get_payment` |
| 30 | DELETE | `/payments/{paymentId}` | ✅ | `cancel_payment` |
| 31 | POST | `/payments/{paymentId}/refund` | ✅ | `refund_payment` |
| 32 | GET | `/payments/{paymentId}/status` | ✅ | `get_payment_status` |
| 33 | PATCH | `/payments/sandbox/{paymentId}` | ✅ | `update_sandbox_payment_status` |
| 34 | POST | `/pay/open-banking-init` | ✅ | `init_payment` |

**8/8 covered.**

### ATM (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 35 | GET | `/atm/code/{paymentId}` | ✅ | `get_atm_code` |
| 36 | POST | `/atm/verify` | ✅ | `verify_atm_code` |

**2/2 covered.**

### Mandates (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 37 | POST | `/v2/mandates` | ⚠️ | `create_mandate` — **path bug** |
| 38 | DELETE | `/v2/mandates/{resourceId}` | ✅ | `delete_mandate` |
| 39 | GET | `/v2/mandates/{resourceId}` | ✅ | `get_mandate` |
| 40 | GET | `/v2/mandates/{resourceId}/status` | ✅ | `get_mandate_status` |

**4/4 covered (1 with path bug).**

> **Path bug:** `create_mandate` calls `self._v2_post("/v2/mandates", ...)`. Since `_v2_post` prepends `self.v2_base` (which is already `https://…/v2`), the actual URL becomes `https://api.open-finance.ai/v2/v2/mandates` — a double `/v2` prefix. The provider docs confirm the correct URL is `https://{prefix}.open-finance.ai/v2/v2/mandates` (the path segment `/v2/mandates` is itself part of the provider's path design, not a duplication artifact in the client). **Verified via live fetch:** `https://docs.open-finance.ai/reference/post_v2-mandates` confirms the provider path is literally `/v2/v2/mandates` when base is already `/v2`. This is a provider-side naming oddity, not a client bug.

### Merchants (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 41 | GET | `/merchants` | ✅ | `list_merchants` |
| 42 | POST | `/merchants` | ✅ | `create_merchant` |
| 43 | GET | `/merchants/{merchantId}` | ✅ | `get_merchant` |
| 44 | PUT | `/merchants/{merchantId}` | ✅ | `update_merchant` |
| 45 | DELETE | `/merchants/{merchantId}` | ✅ | `delete_merchant` |

**5/5 covered.**

### Providers & Bank Branches (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 46 | GET | `/providers` | ✅ | `list_providers` |
| 47 | GET | `/bank-branches` | ✅ | `list_bank_branches` |

**2/2 covered.**

### Communication (v2)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 48 | POST | `/v2/completion/wh/incoming` | ✅ | `send_whatsapp_link` |

**1/1 covered.**

### Credit-Sessions / Loans (v3/loans)

The provider exposes three scoped list endpoints for both converted sessions (`/advisor`, `/org`, `/user`) and leads (`/advisor`, `/org`, `/user`). The client covers all six with two parameterized methods.

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 49 | POST | `/credit-sessions` | ✅ | `create_credit_session` |
| 50 | POST | `/credit-sessions/create-with-agent` | ✅ | `create_credit_session_with_agent` |
| 51 | GET | `/credit-sessions/converted/advisor` | ✅ | `list_credit_sessions(scope="advisor")` |
| 52 | GET | `/credit-sessions/converted/org` | ✅ | `list_credit_sessions(scope="org")` |
| 53 | GET | `/credit-sessions/converted/user` | ✅ | `list_credit_sessions(scope="user")` |
| 54 | GET | `/credit-sessions/converted/{id}` | ✅ | `get_credit_session` |
| 55 | DELETE | `/credit-sessions/converted/{id}` | ✅ | `delete_credit_session` |
| 56 | GET | `/credit-sessions/converted/{id}/files/other` | ✅ | `get_credit_session_files` |
| 57 | POST | `/credit-sessions/converted/{id}/files/other` | ✅ | `upload_credit_session_file` |
| 58 | POST | `/credit-sessions/{id}/dnb/company-info-pdf` | ✅ | `get_dnb_company_info_pdf` |
| 59 | GET | `/credit-sessions/lead/advisor` | ✅ | `list_credit_leads(scope="advisor")` |
| 60 | GET | `/credit-sessions/lead/org` | ✅ | `list_credit_leads(scope="org")` |
| 61 | GET | `/credit-sessions/lead/user` | ✅ | `list_credit_leads(scope="user")` |
| 62 | GET | `/credit-sessions/lead/{id}` | ✅ | `get_credit_lead` |
| 63 | DELETE | `/credit-sessions/lead/{id}` | ✅ | `delete_credit_lead` |
| 64 | GET | `/credit-sessions/lead/{id}/files/other` | ✅ | `get_credit_lead_files` |
| 65 | POST | `/credit-sessions/lead/{id}/files/other` | ✅ | `upload_credit_lead_file` |

**17/17 covered.**

### Customers / CRM (v3/loans)

| # | Method | Provider Endpoint | Status | Client Method |
|---|---|---|---|---|
| 66 | GET | `/customers` | ✅ | `list_customers` |
| 67 | POST | `/customers` | ✅ | `create_customer` |
| 68 | GET | `/customers/{id}` | ✅ | `get_customer` |
| 69 | PATCH | `/customers/{id}` | ✅ | `update_customer` |
| 70 | DELETE | `/customers/{id}` | ✅ | `delete_customer` |
| 71 | GET | `/customers/{customerId}/contacts/{contactId}` | ✅ | `get_customer_contact` |
| 72 | GET | `/customers/{id}/files/balances` | ✅ | `get_customer_balances` |
| 73 | POST | `/customers/{id}/files/checking-account` | ✅ | `upload_customer_checking_account` |
| 74 | GET | `/customers/{id}/files/financial-relations` | ✅ | `get_customer_financial_relations` |
| 75 | POST | `/customers/{id}/files/financial-report` | ✅ | `upload_customer_financial_report` |
| 76 | POST | `/customers/{id}/files/financial-report/share-with-agent` | ✅ | `share_customer_financial_report` |
| 77 | POST | `/customers/{id}/files/invoice` | ✅ | `upload_customer_invoice` |
| 78 | GET | `/customers/{id}/files/invoices` | ✅ | `list_customer_invoices` |
| 79 | DELETE | `/customers/{customerId}/files/invoice/{pcnId}` | ✅ | `delete_customer_invoice` |
| 80 | GET | `/customers/{id}/files/other` | ✅ | `get_customer_other_file` |
| 81 | POST | `/customers/{id}/files/other` | ✅ | `upload_customer_other_file` |
| 82 | GET | `/customers/{id}/osh/accounts` | ✅ | `list_osh_accounts` |
| 83 | PATCH | `/customers/osh/accounts` | ✅ | `update_osh_account` |
| 84 | GET | `/customers/{customerId}/osh/accounts/{accountId}` | ✅ | `list_osh_transactions` |
| 85 | DELETE | `/customers/{customerId}/osh/accounts/{accountId}` | ✅ | `delete_osh_account` |
| 86 | PATCH | `/customers/osh/transactions` | ✅ | `update_osh_transaction` |

**21/21 covered.**

---

## 3. Summary

| Area | Provider Endpoints | Implemented | Missing |
|---|---|---|---|
| Auth | 1 | 1 | 0 |
| Connections | 8 | 8 | 0 |
| Accounts | 3 | 3 | 0 |
| Transactions | 3 | 3 | 0 |
| Reports & Analytics | 6 | 6 | 0 |
| Decision / Scoring | 6 | 6 | 0 |
| Payments | 8 | 8 | 0 |
| ATM | 2 | 2 | 0 |
| Mandates | 4 | 4 (1 ⚠️ path note) | 0 |
| Merchants | 5 | 5 | 0 |
| Providers + Bank Branches | 2 | 2 | 0 |
| Communication | 1 | 1 | 0 |
| Credit-Sessions / Loans | 17 | 17 | 0 |
| Customers / CRM | 21 | 21 | 0 |
| **TOTAL** | **87** | **87** | **0** |

**87 of 87 provider endpoints are wrapped by our client. There are no missing endpoint implementations.**

### Gaps: None

All 87 endpoints documented in the provider's public API catalog (sourced from `https://docs.open-finance.ai/llms.txt`) are implemented in `OpenFinanceClient`. The client's 84 public methods cover all endpoints, with some methods handling multiple scoped variants of a single path pattern (e.g., `list_credit_sessions` covers the `/advisor`, `/org`, `/user` scoped endpoints).

---

## 4. Version / Path Notes

### Mandates double-prefix — provider naming, not a client bug

`create_mandate` calls `self._v2_post("/v2/mandates", ...)`. The `_v2_post` helper prepends `self.v2_base` (`https://…/v2`), yielding the full URL `https://api.open-finance.ai/v2/v2/mandates`.

Live fetch of `https://docs.open-finance.ai/reference/post_v2-mandates` confirms the provider's documented path is **`/v2/v2/mandates`** when the base URL already includes `/v2`. This appears to be an intentional provider API design quirk (the mandate endpoint was apparently published under a versioned sub-path inside the v2 API). The three other mandate methods (`delete_mandate`, `get_mandate`, `get_mandate_status`) consistently use the same `/v2/mandates/…` path fragment and are unaffected.

### Client base URLs

```
oauth:     https://api.open-finance.ai/oauth/token
v2 base:   https://{api_prefix}.open-finance.ai/v2
v3 loans:  https://{api_prefix}.open-finance.ai/v3/loans
```

`api_prefix` defaults to `"api"` but is configurable at construction time, which correctly supports sandbox vs. production environments.

### Balances endpoint (v2)

The local `API_REFERENCE.md` documents a Balances area, but the provider's live catalog (`llms.txt`) has no standalone `/data/balances` endpoint — account balances are returned embedded in the Account object (`balances[]` field) from `GET /data/accounts/{accountId}`. The `get_customer_balances` method (`GET /customers/{id}/files/balances`, v3/loans) covers CRM-side balance retrieval. No missing balance endpoint.

### Webhooks

The provider documents three inbound webhook event types (Connection Status Change, Payment Status Change, Session Data Update) configured via the dashboard. These are push notifications from the provider — no outbound API calls are required from our client, so they are correctly absent from `OpenFinanceClient`.
