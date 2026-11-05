# Simplify C — Max clearing ↔ card sales, expense-card charges (FIX_SUMMARY)

Branch: `feat/simplify-c-max-card-rules` · base: `e961c65` (#102, Simplify A on main)
HEAD (code): `bcfd1f7`. This FIX_SUMMARY update is the commit after it.

Scope: C only. A is on main; B (#103) stays on `feat/simplify-b-bank-match`.
No migration, no prod, no SUMIT/Open Finance calls, no frontend change.

## Product rules (encoded in `src/cfo/services/card_flow_rules.py`)

One module, used by the gap engine, bank match (reconcile + manual suggestions),
the synthesis worklist and the bot's missing-document tool.

### R1. Direction decides, not the issuer name
Max, Isracard and Cal both **clear merchant sales** (money in) and **issue expense
cards** (money out). So:

| Bank row | Category | Meaning |
|---|---|---|
| amount > 0, card-company term | `clearing_income` | weekly net clearing deposit for card sales |
| amount < 0, card-company term, or OF category `CREDIT_CARD_CHECKING`/`CREDIT_CARD` | `card_settlement` | expense-card charge |

The OF category is honoured in every path: gap engine, `reconcile_organization`
(`BankTxnLite.card_category`) and `suggest_matches`.

The hypothesis in the brief ("take Max out of the card keyword list") was
rejected on purpose. An outgoing Max card bill would then become
`expense_candidate` and get flagged for a missing tax invoice. Inbound Max and
outbound Isracard now differ by sign (tested).

Card-company terms: מקס/max, ישראכרט/isracard, כאל/כא"ל/cal, ויזה/visa,
אמריקן אקספרס/american express/amex, לאומי קארד, diners/דיינרס, סליקה, שב"א.
- **Whole-word match.** One Hebrew prefix letter (ו/ב/ל/מ/ה) is allowed. Before this, `cal` caught "MEDICAL" and
  `max` caught "MAXIMUM", which hid real expenses as card charges (bug fixed, tested).
- **Exclusion:** "מקס סטוק"/"MAX STOCK" is a retail chain, not a card company.

### R2. `card_settlement` (Isracard/Cal/Amex/Max OUT)
- No tax invoice is required for the bank row. It is never a supplier Bill/Expense candidate.
  - `reconcile()` does not offer it 1:1 and lists it under `card_flows.card_settlement`.
  - `suggest_matches()` returns `[]` for it.
  - Synthesis emits `review_card_settlement` (info) and not the generic `review_bank_evidence`.
  - `bank_query_service` buckets it as `card_settlement` by keyword too, not just by OF sub-category.
- The purchases themselves are documented per card line, which is outside the bank row.

### R3. `clearing_income` (Max weekly clearing IN) ↔ card sales, N:1
- **Window:** sales dated from (deposit − 7 calendar days − 3 Israeli business days)
  to the deposit date, inclusive. Business days are Sun–Thu. A sale after the deposit is never included.
- **Gross:** the sum of card sales in the window not already offered to an earlier deposit.
  Deposits are processed by date, and a sale goes to one deposit only.
- **Fee:** `gross − net`.
  - Accepted only when `0 ≤ fee ≤ 5% of gross`. The result is then `status=candidate`, with `fee` and `fee_rate`.
  - `net > gross` gives `status=review`, `reason=net_exceeds_gross`, `fee=None`.
  - A fee above 5% gives `status=review`, `reason=fee_above_cap`, `fee=None` (likely missing sales or two cycles).
  - No card sales in the window gives `status=missing`, `reason=no_card_sales_in_window`, `gross=None`,
    `fee=None`, with `as_of`. **Never 0.**
- **Card-sale evidence (explicit only):**
  - a SUMIT invoice whose `raw_data.Payments[]` has `Type == "CreditCard"` (amount = the card part);
  - or `Payment.method == "credit_card"` with no `bill_id`, so a vendor paid by card is not a sale.
    A payment on an invoice already counted through its `Payments[]` is skipped, so nothing is
    counted twice (tested).
- It is never a confirmed match. It is a suggestion for review, as with the rest of reconcile.
- Wired into:
  - `suggest_matches()`: one `card_sales` suggestion carrying the result, with `applyable: False`.
    It is evidence for review; the apply path does not accept `card_sales`.
  - `reconcile()`: no 1:1 against an invoice, listed under `card_flows.clearing_income`.
  - Synthesis: `match_clearing_to_card_sales`.
  - `gap_report`: `inflows.clearing_income` with `{count, total}`. Clearing deposits are no longer counted as
    "inflow without invoice".

### R4. Owner → חו״ז (`owner_draw`)
- An explicit owner term in the description (משיכת/הפקדת בעלים, חו"ז בעלים, הלוואת בעלים), or
- a counterparty that matches a **saved filing rule** of the org: `plan.statusRules` with
  `category=owner_draws` and direction out/both. Its `contains` text is matched against the
  OF payee (`is_intercompany_counterparty` matching).
- No new plan schema and no hardcoded names. The gap report, the suppliers list and the daily alerts all
  use it, so an owner transfer is not a missing document.

### R5. Salary stays `salary`. Supplier is the rest of `expense_candidate`
- The order in `classify_transaction` is: card_settlement → owner_draw → tax → salary → loan →
  self_transfer → bank_fee → other_excluded → expense_candidate.

### R6. Payee from Open Finance
- `card_flow_rules.payee(row)` takes debtor/creditor (creditor first for OUT) and then
  payee/merchant/beneficiary keys, all through the #101 helpers in `dashboards/filing.py`.
- A transfer memo ("מטרת ההעברה") is **not** a payee.
- Nothing found returns `None`.
- `gap_report` rows now carry `counterparty`, and `suppliers_missing_invoices` groups by the OF payee
  before falling back to the description.
- Saved rules (`statusDecisions` > `statusRules` > built-ins in `filing.py`) are untouched.
  `filing.py` `RULES` are not changed, so the `builtin_rules_manifest` hash is stable.

## Tests

Run locally (GitHub CI is billing-blocked). The test env is cleared of the shell's Vercel variables;
conftest forces a temporary SQLite DB.

- New: `tests/test_card_flow_rules.py`, 49 tests on synthetic data only. Every one was watched red before
  the code was written.
- Related suites (card_flow_rules, bank_expense_gap, bank_reconciliation, financial_synthesis,
  manual_reconciliation ×2, bank_query_service, owner_presentation, ai_chat_tools): **204 passed**.
- Full suite, each run in its own clean worktree:
  - base `e961c65`: **45 failed, 3,553 passed, 10 skipped**
  - HEAD `bcfd1f7`: **45 failed, 3,602 passed, 10 skipped**
  - The set of failed tests is **identical by name**. No new failure; +49 are the new tests.
- Frontend not touched, so `tsc` is not needed.

## Remaining gaps (honest)

1. **Account 10004 is not linked in this matcher.** There is one local path that holds SUMIT chart
   codes: `JournalEntry(source='reviewed_local_import')`, read by `dashboards/source_journal.py` with
   `plan.journalAccountMap`. It exists only for import-only clients. **Next step:** read card sales from
   10004 lines of that journal for those clients. Not implemented here. For synced clients, nothing ties a
   document to 10004:
   - Journal entries are derived from our own chart.
   - SUMIT receipts are stored as `Payment.method='receipt'` without the card method.

   **Not verified:** the read-back shape of a SUMIT document's `Payments[]`. In code, `Type`/`Amount`
   appear only on the create side (`_document_payment_payload`, cash/cheque). That a synced invoice's
   `raw_data.Payments[]` carries `Type == "CreditCard"` is an assumption, and checking it needs one
   SUMIT read (needs a GO).

   Until a SUMIT readback stores the income account or payment type, `load_card_sales` finds
   card sales only from the two explicit sources above. In production most clearing deposits will
   show `status=missing`, with no gross and no fee. That is the honest answer, not a match. Next step:
   map SUMIT payment type / income account on sync. It needs a SUMIT read and a GO, so it was not done here.
2. The owner rule needs a saved `owner_draws` filing rule per org, or an explicit owner term. Orgs without
   one still see owner transfers as `expense_candidate`.
3. Frontend not changed:
   - `card_sales` suggestions and the new synthesis action types render through the existing
     generic lists.
   - A dedicated "clearing fee" UI is not built.
4. `bank_query_service` keeps its own taxonomy (shape locked by tests). It only gained the card keyword.

5. Gershayim: `כא"ל`/`שב"א` match the ASCII quote only. Bank text with ״ (U+05F4) won't match the
   card rule for those two forms. The plain words (כאל, ישראכרט, מקס ...) do match.

## Overlap with #103 (feat/simplify-b-bank-match)

Both PRs change `bank_reconciliation.py`, `manual_reconciliation.py`, `financial_synthesis.py`
and `bank_expense_gap.py`. Whichever merges second needs a rebase that keeps **both** B's
settled-document rule and C's card-flow guards. Compare the files themselves, not the conflict count.

## GO notes

- No migration. Nothing to apply to Neon.
- No env flag changes. `OPEN_FINANCE_SCHEDULED_SYNC_ENABLED` untouched.
- Not merged. #104 alias, BDO and prod are untouched.
