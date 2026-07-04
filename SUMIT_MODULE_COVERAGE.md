# SUMIT Module Coverage

This is the internal coverage map for Rezef's SUMIT-facing capabilities. The public landing page must not name upstream providers; this file and the authenticated UI can be explicit for product and engineering work.

## Current Answer

Rezef can cover a large part of the SUMIT module list through existing API surfaces, but not every visible SUMIT product module is a one-to-one API feature in this codebase.

- **Ready:** customers, income documents, expenses, debt reports, payments, payment methods, recurring payments, CRM entities/folders/views, SMS/mailing lists, stock, users/permissions, companies, double-entry dashboards, annual-report preparation, cash/cheque payment recording on document issuance, credit-note linking to an original invoice (`OriginalDocumentID`), and cloning an existing document into a new scheduled occurrence.
- **Partial:** refunds/chargebacks alerts, Masav mandates/returns, custom dashboards/views builder, outgoing email/domain settings, file storage quotas. "Future documents" is now Ready only in the clone-an-existing-document sense (`/scheduleddocuments/documents/createfromdocument/`) — there is still no date-driven "schedule from raw line-item details" primitive in SUMIT's API.
- **Blocked / adapter needed:** BlueSnap, PayPal, Bit-specific adapters, arbitrary CRM list HTML export, charging an existing recurring item by ID, creating a new recurring-billing mandate from scratch (SUMIT's `/billing/recurring/*` only operates on an existing `RecurringCustomerItemID`; no create-mandate endpoint exists), card-terminal transaction listing by date range using `/creditguy/billing/load/`.

### Scoped for implementation (2026-07-04) — moved out of vague "Partial", concrete API surface found
Re-checked against the full downloaded swagger spec (not the live SUMIT UI — that needs a real login the agent doesn't have and shouldn't enter itself). Three items that were listed as vague "Partial" turned out to have a clean, well-documented API surface, not requiring any browser-script bridge:
- **Payment pages** — `POST /billing/payments/beginredirect/` (`PaymentsController_Payments_BeginRedirect`). Takes `Customer` + `Items` + `VATIncluded`/`VATRate`/`DocumentType` + a `RedirectURL` (where the customer lands after paying); SUMIT creates the accounting document AND a hosted payment page, returning `RedirectURL` = the payment-page URL to send the customer. This is exactly a "send a customer a payable link" primitive — directly useful for the collection-reminders/AR workflow (send a payment link instead of just a balance notice). **Not implemented.** Effort: medium (new service method + route + a UI entry point, e.g. a "Send Payment Link" action on an overdue invoice).
- **Wallet activation** — `POST /billing/generalbilling/openupayterminal/` ("Open an instant credit card terminal using Upay") and `POST /billing/generalbilling/setupaycredentials/` ("Setup existing Upay account credentials"). Both exist and are documented; **not implemented**. Effort: medium — this is genuinely an onboarding/activation flow (a client wiring up their own card-processing), likely belongs with the office/client-onboarding UI rather than a routine sync feature.
- **Triggers** — `POST /triggers/triggers/subscribe/` / `.../unsubscribe/`, described in SUMIT's own spec as "usually done by make.com/zapier, but can also be used directly." This is a real webhook-subscription mechanism — potentially higher-value than it looks: subscribing directly could let Rezef receive real-time push notifications on new documents instead of relying purely on periodic polling sync. **Not implemented, not investigated further this pass** (would need to check the trigger event payload shapes and add a webhook-receiving route) — flagged as a genuinely promising candidate for a future "real-time sync" iteration, not just a coverage checkbox.

Not re-investigated this pass (search turned up nothing under any obvious terminology — genuinely no API surface found, not just unchecked): Masav mandates/returns, outgoing email/domain settings, custom dashboards/views builder, file storage quotas (`/website/companies/listquotas/` exists but has no summary text and wasn't inspected further — lowest-priority of this batch).

## Payment Readiness

The Rezef signup checkout is implemented with Stripe Checkout so card, Apple Pay and Google Pay can work without a new code path once production billing is configured.

Required production configuration:

- `STRIPE_SECRET_KEY`
- `STRIPE_PRICE_COMPANY_UP_TO_2_5M`
- `STRIPE_PRICE_COMPANY_ABOVE_2_5M`
- `STRIPE_PRICE_OFFICE`
- Stripe payment methods enabled for card wallets
- Production domain registered and verified for Apple Pay

The public endpoint `/api/admin/billing/status` reports whether the live checkout is ready and which env vars are still missing.

## Internal UI

The authenticated app now has `/sumit-coverage`, available from the Monitoring navigation as **כיסוי מודולי SUMIT**. It includes search, category filtering, status filtering, implementation surfaces and next steps.

## Product Principle

Public marketing should describe Rezef outcomes:

- automatic bank matching
- collection and payment control
- daily P&L and cash-flow visibility
- double-entry bookkeeping automation
- exceptions, duplicates, fees and missing-payment detection
- financial recommendations and action guidance

It should not name the upstream systems or APIs that make those outcomes possible.
