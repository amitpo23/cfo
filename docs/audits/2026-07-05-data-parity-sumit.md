# Data-Parity Check: Rezef vs SUMIT — Org 1 / Company 439924597

Run date: 2026-07-05. Rezef data from Neon prod (`DATABASE_URL`, read-only). SUMIT data
from live API calls (list_documents / get_debt_report only — no mutations). Org 1
(עמית פורת) confirmed to use `IntegrationConnection` id=2 → `company_id=439924597`,
matching `SUMIT_COMPANY_ID` from the pulled prod env.

**Method note on SUMIT document types** (confirmed live, not just from code comments):
`0`=Invoice, `5`=Receipt, `15`=ExpenseReceipt, `16`=ExpenseInvoice. For this company,
type `16` is essentially unused (2 stray docs, both from 2024) — virtually all expense
activity (875 docs all-time) lives under type `15`, with `IsDraft` toggling instead of
the type code changing. This one fact drives most of the discrepancies below.

## Comparison table

Present-state parity (i.e. "do the books match SUMIT right now") is in the Verdict
column. Two of the four items below are internal-consistency findings surfaced by
this exercise rather than live sync gaps — flagged as such.

| # | Metric | Rezef (Neon prod) | SUMIT live | Δ | Verdict |
|---|---|---|---|---|---|
| 1a | Open AR — invoice count | 15 | 15 (type 0, status=open) | 0 | **Match** |
| 1b | Open AR — total balance | ₪245,527.00 | ₪245,527.00 | ₪0 | **Match** |
| 1c | Invoice population, all-time | 21 rows | 20 docs (type 0) | +1 (Rezef) | **Mismatch (stale row)** — see H0 |
| 2a | Invoices 2026 — count | 6 | 6 (type 0) | 0 | **Match** |
| 2b | Invoices 2026 — sum | ₪55,000.00 | ₪55,000.00 | ₪0 | **Match** |
| 2c | Receipts 2026 — count | 0 (Payment, method=receipt) | 0 (type 5) | 0 | **Match** (trivially — none issued) |
| 2d | Expense docs 2026 (Bill table) — count & sum | 274 rows / ₪356,897.84 | 274 docs / ₪356,897.84 (type **15**, id-for-id match) | 0 | **Match today** — but see H1 (latent regression, will drift going forward) |
| 2f | Expense table (working queue) 2026 — count | 231 | 274 (type 15, all statuses) | −43 | **Mismatch** — see H2 |
| 3 | Total filed expenses 2026 (Expense.status='filed') | ₪354,384.91 (144 rows) | ₪356,897.84 (161 non-draft type-15 docs) | −₪2,512.93 (~0.7%, 17 docs) | **Mismatch (minor)** — see H2 |
| 4a | VAT — output, June 2026 | ₪0.00 | n/a (no VAT API); gross proxy: 0 type-0 docs in June | ₪0 | **Match** (both show no June sales) |
| 4b | VAT — input, June 2026 (as computed) | ₪143.31 | n/a (no VAT API) | — | See H3 — **~10.6% double-counted** (₪15.25) |
| 4c | VAT — input, June 2026, de-duplicated estimate | ₪128.06 | gross proxy: SUMIT type-15 "open" June sum = ₪839.60 (matches Rezef Bill-table June sum exactly) | ₪0 on the gross check | **Gross totals match**; VAT split not independently verifiable (SUMIT limitation) |
| 4d | VAT — input, **all-time running position** (dashboard default, confirmed via direct `compute_vat_position(db,1)` call: input=269,830.13, output=71,868.26, net=−197,961.87) | ₪269,830.13 | n/a | — | **Systemic bug, not a sync gap** — see H3 |

All ₪ amounts from SUMIT are gross (VAT-inclusive) document totals — SUMIT's
`documents/list` does not expose VAT independently (confirmed in
`sumit_integration.py::_extract_vat` and `SUMIT_API_REFERENCE.md`).

**Bottom line: 4 findings, 0 of them present-day AR/revenue-recognition drift.**
AR, 2026 invoices, and 2026 expense docs (Bill table) all match SUMIT exactly
today. The four findings are: one stale legacy row (H0), one latent/future
regression that hasn't caused drift yet but will (H1), one workflow-cadence lag
(H2), and one internal double-counting bug in the VAT engine unrelated to SUMIT
sync at all (H3).

## Discrepancies — root cause with evidence

### H0 — One stale Invoice-table row is actually a SUMIT Receipt (type 5), left over from a pre-2026-06-21 broader filter

Rezef `Invoice` table (org 1, all-time): 21 rows. SUMIT type-0 (Invoice), all-time
live: 20 docs. Set-diff by `external_id` found exactly one Rezef row with no
SUMIT type-0 counterpart: `external_id=974527677`, `invoice_number="2002"`,
status `OVERDUE`, `total=-23600.00`, `issue_date=2025-06-30`.

A single `get_document_details("974527677")` call (one call, not a burst) shows
this document is actually **SUMIT type 5 (Receipt)**, status `open`, same total
and date. Explanation: before commit `60fb0d2` (2026-06-21) rewrote
`fetch_invoices()` to filter strictly by numeric type `"0"`, the prior version
filtered by document-type **names** `["invoice", "tax_invoice", "receipt",
"credit_invoice"]` — which included receipts. This Receipt document was
imported into the `Invoice` table under that old, broader filter and was never
cleaned up when the filter narrowed. It does not corrupt the AR total (row 1b
matched exactly) purely because `get_ar_aging()` filters on `Invoice.balance > 0`
and this row's balance is negative (−23,600) — it's silently excluded from AR,
not reconciled. `invoice_status_counts` shows 16 `OVERDUE` rows in the raw
table but only 15 make it into the aging report; this stale receipt-as-invoice
is exactly the one that drops out. It is a phantom "invoice" that doesn't
exist as an invoice in SUMIT at all, and inflates the all-time `Invoice` row
count by one.

### H1 — Bill-table sync uses the wrong SUMIT document-type code for this org (regression, 2 days old)

`src/cfo/services/sumit_connector.py::fetch_bills()` filters SUMIT documents by
numeric type **"16"** (comment: "ExpenseInvoice, finalized supplier invoices").
Live evidence for company 439924597:

- `list_documents(document_types=["16"])`, full history 2015→today: **2 documents total**,
  both dated 2024 (ids `441760671`, `518147993`), unrelated to any 2026 activity.
- `list_documents(document_types=["15"])`, full history: **875 documents**
  (166 still `draft`, 709 non-draft/"open") — this is where all real expense
  activity for this org actually lives.
- For 2026 specifically: type 16 → 0 docs; type 15 → 274 docs, and those 274 external_ids
  are a **100% exact match** (id-for-id) to the 274 rows currently in the `Bill` table
  for `issue_date` in 2026 (confirmed via set intersection, see
  `scratchpad/diff_bills.py` output).

`git log` shows the type code was **flipped from "15" to "16"** in commit `23353ca`
("fix: 10 bugs from high-effort code review", 2026-07-03), on the stated (and for
this org, incorrect) assumption that 16=finalized/15=draft. The prior commit
(`60fb0d2`, 2026-06-21) that introduced type "15" carried an explicit live
verification note ("242 expense 2025 documents... matches SUMIT"); the `23353ca`
flip carries no such verification.

**Consequence**: every hourly sync since 2026-07-03 finds only the 2 irrelevant
2024 stray docs for `fetch_bills()` (`recent_sync_runs[*].counts.bills` =
`{"created":0,"updated":0,"skipped":2}` in all 5 most recent runs). The 274
Bill rows in the DB are a frozen snapshot from before the regression — accurate
for what they cover, but **no new expense activity has landed in the Bill table
since 2026-07-03**, and none will until the type filter is corrected.

### H2 — Expense working-table (`Expense`) lags SUMIT because its pull is manual, not part of the automatic sync

`ExpenseFilingService.sync_pending_from_sumit()` (which populates the `Expense`
table from type-15/16 docs) is invoked on demand, not by the hourly
`sync_engine` cron that refreshes `Invoice`/`Bill`. Live comparison for 2026:

- SUMIT type-15, 2026: 274 docs — **113 draft** (unscanned, total=0) + **161 open/non-draft**.
- Rezef `Expense` table, 2026: 231 rows — **87 pending** + **144 filed**.
- Gap: 43 SUMIT docs (26 more drafts + 17 more non-draft) exist in SUMIT but have
  never been pulled into the `Expense` table at all.
- The 17 non-draft/"filed"-equivalent docs not yet imported sum to ≈₪2,512.93
  (356,897.84 − 354,384.91), which is exactly the size of the "Total filed
  expenses" gap in row 3 of the table above.

This matches the pattern already logged in memory
(`sumit-expense-filing-progress.md`, `sumit-may2026-vat-state.md`): expense
filing for this org is a manual, drip-fed workflow, and the working queue is
consistently a few days/weeks behind the live SUMIT draft inbox.

### H3 — `compute_vat_position()` double-counts input VAT: `Bill` and `Expense` are two independent syncs of the *same* underlying SUMIT documents

Found while investigating item 4. `Bill` rows (from `fetch_bills()`, type-15/16)
and `Expense` rows (from `sync_pending_from_sumit()`, type-15/16) are populated
independently from the same SUMIT documents, keyed by the same `external_id`.
`financial_synthesis.compute_vat_position()` sums `Bill.tax` for eligible bills
**and separately** sums `Expense.vat_amount` for eligible (`status='filed'`)
expenses, with no deduplication by `external_id`.

Live measurement, org 1, all `external_id`s:

- All-time: 877 distinct Bill external_ids, 834 distinct Expense external_ids —
  **100% of Expense external_ids (834/834) also exist as Bill rows.**
- All-time input_vat as currently computed: ₪269,830.13
  (bill-side ₪141,740.08 + expense-side ₪128,090.05).
- All 684 `Expense.status='filed'` rows overlap with a counted `Bill` row — i.e.
  **every filed-expense VAT amount is added a second time** on top of the bill's
  own tax figure. De-duplicated estimate: **₪141,740.08** — the all-time figure
  is inflated by **47.5%** (₪128,090.05).
- For the June-2026 period specifically the effect is much smaller (only 1 of 72
  bill-counted docs also had a `filed` Expense counterpart in that window — most
  June expenses are still `pending`), inflating the June input_vat by ≈10.6%
  (₪15.25 of ₪143.31). The size of the double-count will grow as more June/July
  drafts get manually filed (H2), since filing flips `Expense.status` to `filed`
  without ever removing/deduplicating the parallel `Bill` row.

This is a genuine internal-consistency bug (not a Rezef-vs-SUMIT sync gap) that
this exercise surfaced as a side effect of trying to reconcile VAT gross totals.
It affects the "all-time running VAT position" shown by the synthesis dashboard
far more than any single monthly report.

## What could NOT be compared, and why

- **Per-document VAT.** SUMIT's `/accounting/documents/list/` does not return a
  VAT field for the vast majority of documents (confirmed live — every doc in
  this pull needed either an absent-VAT fallback or showed no VAT key at all).
  `get_document_details()` recovers VAT from line items, but that requires one
  API call per document; per the hard rate-limit constraint this run relied on
  list-level calls for all bulk comparisons (the sole exception: one single
  `get_document_details` call for H0, to identify one specific document's real
  type — not a burst). So **no per-doc VAT was bulk-pulled from SUMIT** — VAT
  comparisons above are gross-total (VAT-inclusive) proxies only, as instructed.
- **"Current period" for VAT is an assumption, not a confirmed org setting.**
  June 2026 was used as the last-closed monthly period based on `tax_service.py`'s
  hardcoded `self.reporting_frequency = 'monthly'` default. Org 1's `settings`
  JSON (`{"seeded": true}`) carries no explicit VAT-frequency field, so this
  could not be confirmed as this org's actual filing cadence (monthly vs.
  bi-monthly) — flagging so the June-2026 VAT figures aren't read as
  authoritative for filing purposes.
- **SUMIT `get_debt_report()`.** Called for context: returns only **2** customer
  debt rows totaling ₪138,839 — starkly incomplete against the 15 real open
  invoices (₪245,527) confirmed via `list_documents`. This matches an existing,
  already-documented finding from 2026-07-04 (see `sumit_connector.py::fetch_customers`
  docstring) that this endpoint is unreliable for this org's data shape
  (reverse-engineered `DebitSource`/`CreditSource` payload). Not used for the AR
  comparison above; flagged here only so it isn't mistaken for a fresh discrepancy.
- **Partial payments / true invoice balance from SUMIT.** SUMIT's list payload
  doesn't expose a per-invoice paid/balance figure independent of the
  draft/open/closed status flags, so "open AR" on the SUMIT side is a status-based
  proxy (`status == "open"`), not a true balance-due figure. It happened to match
  Rezef exactly here (both derive from the same 15 invoices with `balance == total`,
  i.e. no partial payments exist yet for this org), so the proxy wasn't stress-tested
  against a partially-paid invoice.
- **Bank/cash reconciliation, journal entries.** Out of scope for this check and
  also not meaningfully exposed by SUMIT's API (`fetch_journal_entries()` and
  `fetch_bank_transactions()` are known-unsupported/best-effort in this codebase).

## Evidence files (scratchpad, not committed)

- `parity_check.py`, `parity_data.json` — main DB + SUMIT pull (AR, 2026 counts, VAT).
- `diff_bills.py` — external_id set comparison, Bill/Expense vs SUMIT type 15/16.
- `diff_invoices.py`, `check_single_doc.py` — Invoice population diff (H0) and the
  one `get_document_details` confirmation call.
- `check_type16_full.py`, `check_type15_2026_status.py`, `check_type15_june.py` —
  live SUMIT type-code and status breakdowns.
- `check_overlap.py`, `check_vat_doublecount.py` — Bill↔Expense external_id
  overlap and VAT double-count quantification, June 2026 and all-time (H3 evidence).
- `check_org.py` — confirms org 1 ↔ SUMIT company 439924597 credential mapping.
- `check_settings.py` — org 1 `settings` JSON (VAT-frequency caveat) + direct
  `compute_vat_position(db, 1)` all-time confirmation.

No writes were made to the database, no SUMIT documents were created/modified/cancelled,
and no files outside this scratchpad were changed.

---

# תיקונים (2026-07-05, בוצעו inline ע"י הסוכן המפקח)

| ממצא | תיקון | commit |
|---|---|---|
| H3 — כפל מע"מ תשומות (+47.5%) | compute_vat_position: Bill קנוני, Expense-תאום (external_id משותף) מדולג | `0f5c9b9` |
| H1 — פילטר 16-בלבד יקפיא סנכרון | fetch_bills מושך סוגים 15+16, מדלג טיוטות (IsDraft→draft), dedupe לפי id | `d3e47b1` |
| H2 — טבלת הוצאות מפגרת (~43 מסמכים) | משיכת הוצאות ממתינות שולבה ב-cron/sync פר-ארגון, כשל מבודד | `e80ac72` |
| H0 — שורת קבלה ישנה כ-Invoice | טסט רגרסיה: fetch_invoices מבקש רק סוג 0 (התיקון עצמו מ-60fb0d2) | (עם H1) |

**H0 — נדרש אישור משתמש לניקוי חד-פעמי בפרוד (מחיקה = רק באישור):**
שורת Invoice ישנה, org 1: `external_id=974527677`, `invoice_number="2002"`,
status=OVERDUE, total=-23600.00, issue_date=2025-06-30 — בפועל קבלה (סוג 5)
ב-SUMIT. עד למחיקה היא מנפחת את מניין החשבוניות הכל-זמני ב-1.
