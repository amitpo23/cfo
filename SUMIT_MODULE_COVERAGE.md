# SUMIT Module Coverage

This is the internal coverage map for Rezef's SUMIT-facing capabilities. The public landing page must not name upstream providers; this file and the authenticated UI can be explicit for product and engineering work.

## Current Answer

Rezef can cover a large part of the SUMIT module list through existing API surfaces, but not every visible SUMIT product module is a one-to-one API feature in this codebase.

- **Ready:** customers, income documents, expenses, debt reports, payments, payment methods, recurring payments, CRM entities/folders/views, SMS/mailing lists, stock, users/permissions, companies, double-entry dashboards, annual-report preparation, cash/cheque payment recording on document issuance, credit-note linking to an original invoice (`OriginalDocumentID`), and cloning an existing document into a new scheduled occurrence.
- **Partial:** payment pages, wallet activation, refunds/chargebacks alerts, Masav mandates/returns, custom dashboards/views builder, triggers, outgoing email/domain settings, file storage quotas. "Future documents" is now Ready only in the clone-an-existing-document sense (`/scheduleddocuments/documents/createfromdocument/`) — there is still no date-driven "schedule from raw line-item details" primitive in SUMIT's API.
- **Blocked / adapter needed:** BlueSnap, PayPal, Bit-specific adapters, arbitrary CRM list HTML export, charging an existing recurring item by ID, creating a new recurring-billing mandate from scratch (SUMIT's `/billing/recurring/*` only operates on an existing `RecurringCustomerItemID`; no create-mandate endpoint exists), card-terminal transaction listing by date range using `/creditguy/billing/load/`.

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
