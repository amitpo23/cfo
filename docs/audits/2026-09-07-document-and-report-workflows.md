# Document intake, page provenance and saved reports — local implementation evidence

7 September 2026. This report supplies implementation evidence to
[MASTER_EXECUTION_PLAN](../MASTER_EXECUTION_PLAN.md), the sole status board.
The C01–C36 denominator and remaining acceptance conditions are maintained there.
Existing collection, payable, allocation, provider-event and Open Finance changes
were preserved. No provider API, production write, payment, refund, filing, batch
close, client message, push or deployment was performed.

## What the user can do locally

Upload several supported sources, or retain every supported email attachment,
including images. Each source has an organization/content identity, original bytes,
channel observations, state, attempts and version. Re-uploading identical bytes
through another channel adds provenance to the same source. Failure on one email
attachment does not discard its siblings. IMAP uses PEEK and does not mark an email
seen while an attachment has failed. The email parser does not fabricate expenses
with zero totals or use the sender as the supplier.

The existing Hebrew RTL expense workspace reads this queue from FastAPI. It can
show the original, explicitly request extraction under existing enablement/cost
limits, display missing or invalid evidence, and record a human correction. A
correction requires the source version and a reason, reuses the business duplicate
gate, and saves the actor and before/after evidence in the existing Note history.
A new Expense is a pending draft. Source review is not accounting approval, filing
or payment. Numbers and currency absent from evidence remain unknown; no VAT rate
is inferred to fill missing source totals. Unsupported currency does not become ILS.
Moshko reads the same saved source queue; its source-review write uses the existing
confirmation/policy gate and the same administrator check in the service.

An administrator can split a PDF into explicitly chosen page groups, or merge
selected PDFs in an explicit order. Every parent page must appear exactly once.
The operation saves original and derived bytes separately, source hashes, page
maps, actor/reason and one durable recipe. A repeated recipe returns the saved
outcome. Originals remain readable and are retired from independent extraction or
review. Stale source versions, a conflicting transformation, in-flight extraction,
source-integrity changes and revoked authority stop the operation. The UI navigates
from a derived document to its source; the confirmed Moshko write shares the same
service. Bounds are 1–10 PDF parents, at most 100 source pages, and 10 MiB per output.
Encrypted/unreadable PDFs, missing/duplicated pages and already handled sources are
refused without partial outputs. There is no automatic boundary detection or image
conversion. The legacy image-only OCR fallback now refuses multipage PDFs rather
than silently extracting only the first page.

Saved report templates, schedules, execution history and files now live in
organization-scoped ReportRecord rows. Template updates use versions. Scheduled
runs claim one occurrence before generating; repeated or overlapping workers do
not generate a second file. Failures persist and are not retried implicitly.
The reports screen saves a P&L template, selects a month, generates/downloads a
saved JSON report, creates a monthly download schedule, pauses/resumes it and
explicitly runs due occurrences. Reading a screen or Moshko's saved-report tool
neither generates a report nor starts sync. Files survive process-local filesystem
loss because their bytes and hashes are stored in the database. Unsupported report
formats/types/filters and external email/webhook delivery are refused. A previous
period actual is no longer labelled as a budget; missing source queries fail rather
than creating a successful empty report. HTML output escapes external text.

## Source-bound provider draft filing

The legacy direct filing route is now a reviewed-source workflow. It requires a
preserved source, explicit document kind, supplier identity/document number,
classification and balanced positive ILS amounts. A generic `invoice` OCR label
is no longer treated as evidence of a tax invoice. Credit/FX/unknown-kind cases
remain outside this creation path. Existing provider documents are not cancelled
or replaced implicitly. Unsigned bulk filing is refused.

The proposal saves the original SHA-256, source/expense IDs, exact reviewed fields,
amount/currency and destination SUMIT company/connection in the existing irreversible
action record. Credentials and file bytes are excluded from that payload. The RTL
workbench displays it beside the original, requests a reason, and uses the existing
signing service. Moshko uses the same actor-aware service and confirmation policy.
The source queue exposes source-review and filing-approval states separately.

Execution rechecks actor/membership, policy/signing authority, source parity,
duplicate evidence and connection identity. It claims the approved request before
one `addexpense` call. The documented request fields preserve source number,
supplier company number, filename and **IsDraft=true**. A consistent returned
DocumentID means `submitted` and an executed action; it does not mean verified
books, final classification, payment or period close. Missing/contradictory IDs and
timeouts persist `outcome_unknown` and block repeats and replacement proposals.
Source changes during execution retain the acknowledgement and immutable approved
values while creating a `source_conflict`. Editing, reclassification and local
account filing cannot overwrite these unresolved states. A later list sync reuses
the acknowledged document by exact saved company/connection/reference, without a
second Expense or silent source overwrite.

A signer can withdraw an approval with a reason while execution has not started.
The old payload and signing records remain; a corrected replacement has a new ID.
Approval/withdrawal transitions use row locks and conditional updates. Withdrawal
cannot reverse an execution, provider document or money transfer.

The current provider contract was checked against the repository's latest saved
Swagger, `sumit_swagger_v1_2026-08-19.json`, on 7 September 2026. No provider call was
made. The adapter's fake-payload test verifies only that documented request shape;
it does not prove live provider acceptance.

- [Connected filing browser](evidence/2026-09-07-expense-filing-connected-browser.json):
  actual React → FastAPI → temporary SQLite; all API responses are real. Only the
  provider is fake. Twelve explicit writes cover source/classification, distinct
  signing, withdrawal/replacement, one draft acknowledgement, page provenance and
  saved-report download across an application-lifespan restart.
- [Filing screen](evidence/2026-09-07-expense-filing-connected.png).
- [PostgreSQL filing races](evidence/2026-09-07-expense-filing-concurrency.json):
  one durable proposal, exactly one fake provider call under overlapping workers,
  six signer-withdrawal versus execution races with one winner, preserved source
  and company identity after disposing the connection pool.
- `tests/test_expense_filing_workflow.py` covers unsigned calls, partial/missing
  source evidence, duplicate/repeated execution, timeout/unknown result, existing
  provider documents, stale source/company, source changes during the request,
  organization isolation, revoked execution authority, unsupported writing,
  document-kind honesty, draft request shape, pre-execution withdrawal and late sync.
  The focused filing/approval run passed **77 tests**. The later source/preview/chat/filing check passed 104 tests. The final full
  suite was interrupted at the owner’s handoff request; it has no completion result.

## Evidence and limits of the tests

The initial intake/report implementation passed 2,789 full-suite tests. The source
review/PDF/Moshko follow-up passed 165 focused tests; the final membership refresh
passed 11 further PDF tests and the PostgreSQL revocation race. The follow-up full run had 2,805 passes and one explicit actor-tool inventory
failure. The inventory was updated for the two new confirmed writes; 38 focused
regression tests then passed. A clean full rerun remains required before commit.
Frontend lint and production build passed. No commit was made.

- [Connected browser evidence](evidence/2026-09-07-document-connected-browser.json):
  real React requests are forwarded to the actual FastAPI ASGI application with a
  fresh temporary SQLite database. No API response or business service is mocked.
  Three email attachments → cross-channel upload duplicate → reviewed pending
  expense → PDF split/page lineage → application lifespan/connection-pool restart
  → saved report and download. Reads did not create sync checkpoints. Five explicit
  browser writes, no JavaScript errors. This is not a production server restart.
- [Mobile source provenance](evidence/2026-09-07-document-connected-mobile.png) and
  [connected saved-report screen](evidence/2026-09-07-reports-connected.png).
- [Fixture browser](evidence/2026-09-07-document-intake-browser.json) and
  [saved-report fixture browser](evidence/2026-09-07-saved-reports-browser.json):
  synthetic responses cover missing OCR evidence, replay, correction, PDF lineage,
  stale/revoked report permission messages, download, reload and 390px RTL layout.
  These fixture-browser responses are mocked; they supplement the real ASGI test.
- `tests/test_document_intake.py`, `tests/test_document_source_review.py`,
  `tests/test_document_derivation.py`, `tests/test_report_persistence.py` cover
  source/amount/currency integrity, tenant isolation, replay, business duplicates,
  real PDF page text/order, stale versions, inactive actors, failure persistence,
  bounded extraction retries, saved report files and occurrence claims.
- [PostgreSQL transformation races](evidence/2026-09-07-document-derivation-concurrency.json):
  identical recipes replay one result; conflicting recipes preserve the first
  decision; an extraction claim blocks transformation; user deactivation and a
  revoked cached membership during native PDF generation roll back all new output.
  The cached-membership case was red before the authority refresh was added.
- [Document/report concurrency](evidence/2026-09-07-document-report-concurrency.json):
  concurrent cross-channel uploads preserve both observations in one source;
  overlapping due-report workers create one execution and one saved file.
- [Populated encrypted restore](evidence/2026-09-07-document-package-populated-restore.json):
  revision c81e6395fd71, 74 tables, 10 source/derived rows, two page recipes and
  three report rows. All-table hashes, original/derived identity, report bytes and
  schema parity survived restore into a separate empty local PostgreSQL database.
  This does not verify production backup operations.

TDD logs are local `/private/tmp/rezef-*` artifacts. Meaningful red cases included
missing shared intake/report storage, inconsistent source amounts, invented
currency, absent review/transform routes, silent multipage OCR truncation, and
cached membership revocation. No pytest runs were overlapped.

## Migration and implementation references

Additive local revisions are `a6fc4173db59` (source intake), `b70d5284ec60`
(report records), and `c81e6395fd71` (page recipes). Downgrades refuse evidence loss.
The local SQLite database was backed up before each migration. Its current drift
check passes with the three previously documented SQLite FK exceptions; these
exceptions do not apply to PostgreSQL. Deployment still needs the existing
owner-controlled schema/runbook process.

The implementation reuses the existing classifier, tax-evidence calculation,
duplicate gate, membership service, Moshko confirmation/policy catalog and expense
model. It adds source/provenance objects rather than another set of books.
PDF page import/save and native thread constraints were checked against the
[official pypdfium2 v4 API](https://pypdfium2.readthedocs.io/en/v4/python_api.html)
on 7 September 2026. Native work is serialized within each process and resources
are closed explicitly. The accounting rules were not broadened by this package.

## What remains open

The complete requested document→approved journal→official books→payment→bank→close
journey has not been proven. The source is now joined to a durable provider-draft
filing action, but not a reviewed multiline journal or independently verified books. Existing local account filing
and `Expense.status=filed` are not independent evidence of official books. SUMIT
batch readback/close remains an authorized portal step; createbatch is not finality.
Independent document readback must validate raw provider fields without the legacy
parser defaults for missing ID/date/amount/currency. A request acknowledgement is
insufficient. Recovery after an ambiguous external result and a sync that sees a
provider document before its creation acknowledgement need a reviewed resolution
operation; the sequential late-sync proof does not cover every such race.

Interrupted extraction has a visible durable claim but no recovery action yet.
Unattended queue scheduling, images beyond the explicit allowlist, email-error
work items, source assignment/comments/search/retention and broader document
collaboration remain open. OCR quality and human-time/correction/silent-error
metrics need an agreed labelled sample; these synthetic tests are not an accuracy
claim. A single multipage logical document may require manual source correction
when the selected OCR provider cannot read all pages.

Report definitions and occurrence history are durable, but unattended scheduler
activation, external delivery, finer report-sharing policy, full source freshness,
period-specific drilldown and a signed month-close workpaper package remain open.
The document and report extensions do not add official posting, live freshness,
payments, refunds, accounting reversals, period locks, FX journals, three-way
procurement matching, fixed assets, consolidation, archive certification or
staffed business support. Their exact C-row gates remain visible in MASTER.
