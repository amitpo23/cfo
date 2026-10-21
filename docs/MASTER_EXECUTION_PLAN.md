# תכנית הביצוע הראשית — מנהל חשבונות ממוחשב מלא

**גרסה 1.0 · 2026-07-24 · זהו לוח הסטטוס היחיד של הפרויקט.** כל מסמכי התכנון האחרים כפופים לו; עבודה שלא מקדמת שער בתכנית הזו — לא מתבצעת.

## עדכון תפעולי — 23.09.2026

ב־`main` הוסר ב־10.09 ה־cron היומי `/api/cron/sync-sumit` לפי הוראת בעלים לעצור קריאות אוטומטיות ל־SUMIT בשל עלות ומכסה. שבעת ה־crons האחרים נשארו ב־`vercel.json`. עצירת הסנכרון היא מצב תפעולי פעיל, גם כאשר סעיפים היסטוריים בהמשך מתארים את החזרת שמונת ה־crons באוגוסט. ענף `fix/rezef-stabilization-20260906` כולל עבודת פיתוח שטרם מוזגה ל־`main` ואינו הוכחת פריסה או פיילוט חי. אין להסיק ממנו שהשערים 0–6 הושלמו.

סנדבוקס המפתחים `cfo-dev-sandbox.vercel.app` דיווח ב־23.09 על פריסה `Ready`, DB בריא וכניסה לחשבון הבדיקה; תצורת הפריסה מ־22.09 עדיין כללה `sync-sumit` יומי. יש לאמת את תצורת הפריסה האחרונה לפני חיבור ספק כלשהו. בדיקת health לבדה אינה הוכחה לבידוד המסד או לאימות כל מסע העבודה.

## Competitor completion — 7 September 2026 (active local work)

The authorized scope extends the existing provider work; it does not replace it.
C01–C36 below are the complete denominator from the September competitor research.
This table is the completion map and the sole status board for this extension.
“Partial” means the broader capability is still open, even when a bounded local
scenario passes. A provider or professional dependency is not an implemented feature.
The current priority remains evidence-backed document intake and the pilot month;
market expansion is retained below rather than silently dropped.

| ID | Current classification and business process | Existing implementation to reuse | Required change / dependency / acceptance |
|---|---|---|---|
| C01 | Partial: multichannel document intake | `expense_intake_email`, `chat_expense_intake`, `document_intake`, `ExpenseFiling` | Three email attachments → cross-channel duplicate → source correction → one pending expense passes through React, real FastAPI and temporary SQLite. Explicit extraction, bounded retry and revocation tests pass. Interrupted claims still need a recovery operation; unattended queue scheduling and additional image formats remain open. |
| C02 | Works end to end locally in the declared PDF scope | `DocumentIntake`, `DocumentDerivation`, `DocumentDerivationForm`, confirmed Moshko tool | Reviewed split/merge preserves original bytes, exact page maps, order, actor/reason and stable replay. Parent processing is blocked; changed source/version and revoked membership cannot overwrite a decision. Real PDF HTTP tests, connected React/FastAPI browser, PostgreSQL races and populated restore pass. Scope: 1–10 PDF parents, all pages exactly once, at most 100 pages, 10 MiB/output; image conversion/automatic document-boundary detection are not implemented. |
| C03 | Partial: duplicate control | `duplicate_gate`, org/content unique intake identity, collection allocation guards | Exact byte duplicates share source history locally. Business duplicates remain evidence-based review; verify variant scans and concurrent receipt creation. |
| C04 | Partial: original alongside accounting proposal | `ExpenseFiling`, `DocumentIntakePanel`, `expense_account_filing`, `ledger_service` | Versioned source correction with reviewer/reason/history, duplicate check and pending expense link now works in UI and Moshko. The connected filing workbench now shows the exact source, destination company, signing approval and fake-provider draft acknowledgement. Journal lines and official intake/readback remain open. |
| C05 | Partial: line extraction | `vision_extractor`, `expense_ocr_pipeline` | Persist true line evidence and header parity; missing lines cannot be reconstructed from totals. |
| C06 | Partial / professional dependency: complex journals | `JournalEntry`, manual journal route, `israeli_tax_rules`, `expense_account_filing` | Source-linked balanced multiline proposal, correction history and professional review; provider posting/readback remains separate. |
| C07 | Partial: organizational learning | `expense_classifier`, `classifier_ml_training`, `test_classifier_learning_loop` | Versioned promotion and reversal of approved precedents; no cross-organization or legal-policy override. |
| C08 | Partial / disconnected onboarding | `chart_of_accounts_importer`, `hashavshevet_journal_importer`, `office_service` | Wizard with mapping, periods, balance/dedup errors and approval; repeated import must preserve existing accounts/history. |
| C09 | Provider/format validation dependency | `openfrmt` DRAFT and source import adapters | A specified product/version and accepted test import are required; generic CSV is not ERP integration. |
| C10 | Deferred beyond active pilot: additional ERPs | `connector_base`, provider business evidence matrix | Per-operation read/write/event/export/result contract for each justified target; no new connector without a verified need/specification. |
| C11 | Partial: supplier evidence and withholding | `Contact`, `company_registry`, supplier workbench | Effective dates and professional evidence for supplier certificates; no guessed form-1000 format or deduction. |
| C12 | Partial / provider dependency: draft to official journal | `irreversible_action_service`, `expense_account_filing`, SUMIT createbatch adapter | Reviewed source → immutable company-bound proposal → distinct signer → one provider draft request is implemented and tested locally. Unknown outcomes and source drift stay unresolved; pre-execution withdrawal preserves history. Independent document/books readback and SUMIT batch finality remain open. |
| C13 | Missing official reversal workflow | `JournalEntry`, irreversible approvals; local allocation reversal history | Original-entry linkage, reason and accepted reversal evidence; allocation reversal cannot substitute for storno. |
| C14 | Partial; AR/AP local slices proven | `collection_allocation_service`, `payable_settlement`, both workbenches | September 6 synthetic HTTP/browser/PostgreSQL proofs cover partial/repeated/source-conflict cases. Aggregate/FX and official writeback remain open. |
| C15 | Partial; linked request/money states proven locally | `payment_evidence`, collection/payable status services | Bring the same durable links into document workspace; never equate verified request or provisional movement with cash. |
| C16 | Partial: business AP approval rounds | `PolicyGrant`, signing authority, irreversible approval service | Business invoice routing, groups/delegation/escalation; invoice approval must not grant payment signing authority. |
| C17 | Partial / disconnected document collaboration | Existing `Note`, `Task`, `AuditLog` | Document-scoped comments, assignee and chronological decisions, with authorization and optimistic concurrency. |
| C18 | Missing three-way procurement match | Document type enums only; no goods-receipt-line model found | Actual PO/receipt lines and quantity/price exceptions; partial goods receipt must not approve a full invoice. |
| C19 | Partial: archive and search | Intake source hash, `Expense.receipt_file`, document views | Search, versions, evidence export, retention and restore; no archive certification claim. |
| C20 | External professional/business dependency | Source evidence and audit history | Verified archive/signature requirements and certification evidence; hashes do not establish legal certification. |
| C21 | Partial: missing materials and case readiness | `Task`, `bank_expense_gap`, `office_service`, morning brief | Assign each unresolved source/period gap to an actionable task and show its evidence; outbound reminders retain permission gates. |
| C22 | Partial; durable saved-report slice works locally | `report_builder_service`, `report_storage`, `ReportRecord`, `SavedReportsPanel`, Moshko `get_saved_reports` | Templates/schedules/executions/files persist per org with versions and occurrence claims. Real React/FastAPI creation/download and app-lifespan restart pass; PostgreSQL overlapping workers and encrypted restore pass. External delivery is refused; unattended scheduler activation, broader report/source drilldown and complete freshness evidence remain open. |
| C23 | Partial: variance explanation | `financial_reports_service`, report builder, CFO services | Period comparison with source drilldown and distinction between business movement and missing data. |
| C24 | Partial: month-close workspace | `DailySnapshot`, `filing_verification`, `parity_service`, `Task`, KB10 | Persistent checklist/dependencies/workpapers/sign-offs; snapshot and local readiness cannot close official books. |
| C25 | Missing full accrual/recurring journal engine | `JournalEntry`, existing approvals | Separate professional packages for prepaids/accruals/recurring journals, reversals and period locks; recurring payment is not a journal engine. |
| C26 | Deferred beyond pilot: consolidation | `office_service` is office oversight only | Ownership group, authorized cross-company mappings/currencies and eliminations; never sum unrelated office clients as a group. |
| C27 | Partial: concurrent case work | Membership, durable action claims, allocation locks; intake version claim | Assignees and conflict controls across the complete document/journal workflow; test source changes after decisions. |
| C28 | Partial / later market scope: client UX and languages | Existing channel gateways and RTL expense workspace | Complete short client intake/missing-material journey; additional languages require per-screen tests and business prioritization. |
| C29 | Provider/owner/professional dependency: authority filing | `filing_verification`, SUMIT operations map | Triple verification plus authorized filing/acknowledgement; no live submission is authorized here. |
| C30 | Partial / professional dependency: FX | Currency-tagged bank/payment evidence; mixed-currency allocation refusal | Preserve currency/date/rate evidence and explicit FX journal adjustments; source intake blocks unsupported FX expense conversion. |
| C31 | Business dependency: service and onboarding | Existing runbooks, office/task services | Named support ownership, escalation and evidence handoff; code cannot prove staffed support. |
| C32 | Deferred business decision: pricing/trial | Moshko usage/cost telemetry, synthetic journeys | Measure full completed-document cost including human work; no pricing or competitor accuracy claims from endpoint counts. |
| C33 | Partial: measured extraction quality | `vision_extractor`, existing synthetic OCR tests | Source-field parity checks added locally; agreed human-labelled sample and time/correction/silent-error measures remain necessary. |
| C34 | Missing fixed-assets engine | Tax classification has depreciation category only | Asset register, source cost, book/tax schedules, disposal and professionally approved journal examples. |
| C35 | Partial; split receipt/reversal slices proven | Collection allocations and reversals, AP bank settlement history | Existing synthetic capacity/replay/reversal proofs retained; fees, refunds, aggregate payouts and currency adjustments remain explicit cases. |
| C36 | Partial: explained bank/books/CFO | `ledger_service`, `financial_synthesis`, live cash/forecast services | Evidence-linked period package and actionable assumptions; official parity/live freshness and complete journey are still open. |

The source-filing follow-up adds a real React/FastAPI/SQLite approval journey with
**12 explicit browser writes and one fake provider request**, including withdrawal
and replacement of an unexecuted approval. PostgreSQL tests prove one proposal,
one provider call under overlapping execution, and six withdrawal/claim races.
The latest focused filing/approval run passed **77 tests**; a later source/preview/chat/filing run passed **104 tests**. The final full offline suite
was stopped at the owner’s handoff request and has no completion result. No additional broad C capability is
marked complete: C04/C12 advance locally but official journal/books verification
remains open. [Filing browser evidence](audits/evidence/2026-09-07-expense-filing-connected-browser.json).

Execution was stopped at the owner’s request on 7 September. Continue from the
[agent handoff](audits/2026-09-07-agent-handoff.md); do not treat the interrupted full run as green.

Current local evidence is detailed in the
[document and report implementation audit](audits/2026-09-07-document-and-report-workflows.md).
The initial intake/report package passed **2,789 full-suite tests**. Subsequent source
correction, PDF transformations, Moshko writes and multipage OCR safeguards passed
**165 focused tests**, followed by **11 PDF tests** after the cached-membership fix.
The follow-up full run reached **2,805 passed / 1 failed**: the explicit actor-tool
inventory omitted the two new confirmed writes. That inventory was corrected and
**38 focused tests passed**; a clean full rerun is still required before commit. Frontend build/lint,
synthetic failure-browser checks and the connected React/FastAPI browser pass.
Revision `c81e6395fd71` passes local SQLite schema parity and a **74-table populated
PostgreSQL encrypted restore**, including original sources, page recipes and report
files. These are local proofs. The full requested document→books→payment→month-close
journey remains open; C02 is complete only in the explicitly bounded local PDF scope.

## Provider business-flow expansion — 6 September 2026 (in progress)

The owner explicitly authorized extending the existing local stabilization work
across relevant SUMIT business/representative and Open Finance/Financy workflows.
The [business evidence matrix](provider_business_evidence.json) is subordinate to
this board. Its rows describe business processes; previous endpoint-wrapper counts
below are historical inventories and do not establish business capability coverage.

Current local implementation: authenticated provider event history and replay guards;
split receipt/invoice/bank allocations, excess and reversals; supplier bill-linked
requests, partial/multiple bank settlement and source-parity protection; shared
HTTP/Moshko workbenches; explicit Financy product/plan and connected-party limits.
Both collection and supplier screens pass synthetic browser journeys. Final serial
QA passed **all nine local gates**, including **2,763 full-suite tests** and **86
tenant-isolation tests**. The Neon check was skipped. The previous 2,668-test result
below belongs to `ab3fd18`.
A final **39-test focused run** verifies supplier workflows and the corrected
Moshko provider-call audit classification after the gate.
Revision `95eb3062ca48` passes fresh synthetic PostgreSQL migration/encrypted restore
(71 tables), and guarded PostgreSQL tests verify allocation capacities, replay,
reversal and overlapping sync. The backed-up local SQLite schema matches the models.
Changes remain uncommitted and do not establish live readiness.
[Implementation report and remaining gates](audits/2026-09-06-provider-business-expansion.md).
[Final local validation](audits/evidence/2026-09-06-provider-final-validation.json).

The public SUMIT help index crawl discovered 763 article links across cached pages,
including 161 IDs absent from the local corpus index. The local 12-file corpus has
968 distinct referenced article IDs. These are index observations, not counts of
reviewed implementations. HTTP 429 stopped further public crawling; 144 discovered
collection URLs remain uncached. [Partial index evidence](audits/evidence/2026-09-06-provider-public-index.json).
The latest saved SUMIT Swagger remains `sumit_swagger_v1_2026-08-19.json` (84 paths).
All 20 reference entries in the checked Financy public index were separately parsed
for route, effective server, scopes, inputs and response contracts. This is a defined
documentation inventory, not a business coverage percentage. Fee conditions and
scope/debtor-field discrepancies are recorded in the
[public contract review](audits/2026-09-06-provider-contract-review.md).

Remaining implementation: advances/document selection; terminal or ambiguous request
resolution; multi-bill/scheduled outgoing payments; recurring/mandate lifecycle;
aggregate/FX/internal-transfer reconciliation; official batch/operator evidence;
source completeness and remaining office capabilities. Provider/accountant/owner
blocks stay explicit in the matrix. The broad completion request remains open.
No live provider API, production operation,
payment, filing, batch close, quota bypass, push or deployment is authorized here.

## Current stabilization status — 6 September 2026

This is the current status for the approved September review plan. Earlier dated
sections below are historical context. Local completion does not change the live
pilot or official-book gates.

| Work package | Current state | Evidence / remaining gate |
|---|---|---|
| Tenant registration and public authentication | Implemented locally | Regression tests passed; deployment/configuration verification pending |
| Legacy action approvals and checkout | Implemented locally with explicit gated legacy prototypes | Durable intent/replay/failure tests and signed checkout/webhook tests passed; provider readback and live owner-approved verification remain gated |
| P&L and cash-flow corrections | Implemented locally | Duplicate/credit/journal/payroll/partial-payment/null/export tests passed; official book reconciliation remains required |
| Dependencies and QA | Implemented locally | 2,668 backend tests passed after the collection extension; all nine local QA checks have passing evidence; live Neon check skipped |
| Organization picker and mobile journeys | Verified locally | Both admin roles passed offline browser journeys at desktop and 390 px |
| Health and recovery tooling | Verified with synthetic PostgreSQL | 69-table encrypted restore, migration parity, hashes and constraints passed; actual production backup/key/PITR evidence remains required |
| Authorized provider pilot | Gated | Current consent/ownership/quota evidence, 20 documents, official posting evidence, seven morning cycles, triple-verified period package |
| Calendar-month expansion decision | Gated by elapsed pilot evidence | At least 25 green days; no unexplained financial differences |

Implementation details, API compatibility changes, release steps and evidence:
[September stabilization report](audits/2026-09-06-stabilization.md).
Review baseline: [English project review](audits/2026-09-06-project-review.md).
Source counts: `python scripts/project_inventory.py`.

No live sync, payment, customer message, regulatory submission, production schema
change or deployment was performed during this local stabilization work. Release
through the existing PR and Gate 0 process; do not use a successful synthetic drill
as production recovery or official-book evidence.

## Invoice–payment–bank slice — 6 September 2026

The existing stabilization branch now includes an offline, approval-bound collection
slice for one final SUMIT tax invoice in ILS. It links the selected payment channel,
request, existing receipt and booked bank movement with a reviewed allocation and
residual balance. Request verification is explicitly separate from money received.
Weak/provisional matches remain candidates; unsupported SUMIT writeback stays visible.

[Implementation, API journey, evidence and limits](audits/2026-09-06-collection-settlement.md).
Validation: **2,668 backend tests passed**, 55 final focused tests passed, all nine
local QA checks have passing evidence, synthetic browser passed, and PostgreSQL
69-table restore plus allocation uniqueness passed.
Migration: `62b80d39f715` after `51a79c28e604`; local SQLite backed up and migrated;
production owner gates unchanged.
Capabilities remain partial/gated/blocked pending live source and official-book evidence.
No live provider call or sync-budget bypass was performed. Next: owner-controlled
release, source identity review and the existing pilot gates; not automatic document
creation from an ambiguous bank amount.

## 1. הצפון

> **חודש קלנדרי מלא של תיק אחד, מקצה לקצה, ממוחשב לחלוטין: מסמך → תיוק → ספרים → התאמות → ניתוח → דיווח. האדם רק מכריע ומאשר — לא מקליד, לא מתאים, לא זוכר.**

הגדרת "עובד": בסוף החודש — הצ'ק-ליסט הקדם-דיווחי PASS, דוח מע"מ מוכן באימות משולש, אפס פעולות ידניות שאינן הכרעה/אישור, ומדדי scorecard ירוקים ≥25 ימים מתוך החודש.

רק כשזה קורה על תיק אחד — משכפלים. לא בונים שום יכולת חדשה שאינה בדרך לצפון.

## 1א. תכנית ההשלמה — 17/08/2026

**מה השתנה היום.** שלוש פריסות לפרודקשיין (`main` = `7e139f1`) והמיגרציה
הראשונה עברה: `b0c1d2e3f4a5` → `05c6d7e8f9a0`, כל `remaining` ריק, הנתונים
שלמים (15,060 פקודות · 1,036 כרטיסים · 1,531 הוצאות). **כל השורות "לא פרוס"
בסעיף 2 שמתחת מתייחסות למצב 24/07 ואינן תקפות עוד לקוד שנפרס היום.**

נפרס: שער מכסת SUMIT (#22), ריצת סנכרון אחת ביום לכל מפתח (#23), אינדקס
מרכז הידע (#24). pytest 2,144 · QA GATE 10/10.

### תיקון לטענה שנאמרה כאן ובשיחה יותר מפעם אחת

נטען ש-`build_journal` "אינו קורא `JournalEntry`". **זה שגוי.** הוא כן קורא
אותו — דרך `_entries_by_source` — אבל **רק** עבור `source IN ('manual','payroll')`.
15,060 הפקודות של org5 נושאות `source='hashavshevet_mdb'` (נמדד בפרוד:
זהו ה-source **היחיד** בטבלה), ולכן הן מסוננות בשקט.

כמו כן נטען ש"שני הארגונים מחזירים 7 כרטיסים גנריים". **גם זה שגוי.** נמדד:
org1=12, org2=10, org3=5, org5=1,009.

הבעיה אמיתית — אבל היא מסנן `source` ולא היעדר קריאה, וזה הופך אותה
מ"שכתוב מנוע" לתיקון ממוקד.

### חמישה מסלולים, לפי מה שחוסם את מה

| # | מסלול | חוסם | מי מבצע |
|---|-------|------|---------|
| **A** | **סודות פרוד ריקים** | מושקו, כל הערוצים, מייל, מפתח משרד | **בעלים בלבד** |
| **B** | מיגרציית `kb_chunks` (`16d7e8f9a0b1`) | האינדקס שנפרס | **בעלים** |
| **C** | מסנן ה-`source` ב-`_entries_by_source` | מאזן org5, כל דוח | קוד — אפשר מיד |
| **D** | `FilingCrosscheck` בהקלדה ידנית בלבד | הצלע רצף↔SUMIT ב-parity | קוד + הכרעה |
| **E** | 4 ניחושים בסך ₪21,472 | אימות משולש | קוד + הכרעה |

### מסלול A — סודות (חוסם הכי הרבה, ואין לקוד תחליף)

נמדד היום ואומת **בשלוש דרכים** (סוג המשתנה, שיוך ל-Production, ואורך השורה
הגולמית): הערכים הבאים הם ליטרלית `""` בפרודקשיין —

| משתנה | שיוך | אורך ערך |
|---|---|---|
| `ANTHROPIC_API_KEY` | Preview, Production | **0** |
| `SUMIT_OFFICE_API_KEY` | Production | **0** |
| `WHATSAPP_ACCESS_TOKEN` | Preview, Production | **0** |
| `WHATSAPP_PHONE_NUMBER_ID` | Production | **0** |
| `SMTP_HOST` / `USER` / `PASSWORD` / `FROM` / `PORT` | Preview, Production | **0** |
| `TELEGRAM_BOT_TOKEN` | — | **אינו מוגדר כלל** |
| להשוואה: `CRON_SECRET` | Production | 48 |
| להשוואה: `SUMIT_API_KEY` | Production | 50 |

השיוך תקין בכולם, והסוג (`Encrypted`) זהה לאלה שכן נמשכו — כלומר זו אינה
בעיית הרשאה או קריאוּת. הערכים ריקים.

**מה זה אומר בפועל:** מושקו מחזיר "עוזר ה-AI לא הוגדר" (כשל כן, לא שקט);
אין וואטסאפ, אין טלגרם, אין מייל. יכולת `conversational-channels` מסומנת
`gated` במרשם — **וזו הסיבה המדויקת**.

### מסלול C — מה שאפשר להתחיל מיד, בלי סודות ובלי כתיבה לפרוד

תיקון מסנן ה-`source`, ב-TDD: RED שמוכיח ש-15,060 הפקודות אינן נספרות
במאזן, ואז הרחבת המקורות. שתי החלטות שאינן שלי:

1. האם `hashavshevet_mdb` נכלל בדוחות **הרשמיים** או רק בתצוגת ניתוח —
   התיק דיווח לרשויות עד 30/06 דרך ההנה"ח החיצונית, ולכן הכללה כפולה
   בתקופה הזו היא סיכון אמיתי.
2. פער ידוע של ₪217,116.65 מ-19 תנועות חד-צדיות — נכלל, מושמט, או חוסם.

### מסלול D — תקרת ה-parity

`_check_sumit_crosscheck` דורש רשומת `FilingCrosscheck` שמוקלדת ידנית מהפורטל;
בלעדיה `skipped`. **SUMIT אינה חושפת קריאת מאזן** (`/books` = `createbatch`
בלבד, כתיבה) — כלומר אוטומציה מלאה חסומה ברמת הספק, לא אצלנו. מה שכן אפשר:
מסך הקלדה ייעודי + תזכורת חודשית, כדי שהצלע תפסיק להיות `skipped` בשקט.

### מה בכוונה **לא** בתכנית

**RAG סמנטי (pgvector).** זמין ב-Neon, אך ל-Anthropic אין API של embeddings
וספק נוסף הוא עלות חיצונית שלא אושרה. האחזור היום לקסיקלי (טריגרמים +
אותיות שימוש; ל-PostgreSQL אין stemmer עברי — נמדד: אפס תצורות). עמודת
embedding ריקה בלי כותב נקראת כיכולת קיימת בזמן שאינה, ולכן אינה קיימת.
אם ייבחר ספק — revision נפרד.

## 2. תמונת מצב כנה (24/07/2026)

| רכיב | מצב |
|---|---|
| מרכז ידע + מנוע מס (תקנה 14/18, שער-מסמך, vat_claimable) | ✅ בנוי, בסיס מדוד 1,847 טסטים — **הקוד החדש בסבב זה טרם פרוס** |
| מחזור בוקר (parity→חריגים→התאמות→מסגרת→snapshot→חייבים→בריף) + cron-ים | ✅ בנוי — **לא פרוס** |
| OCR-תיוק + שער כפילויות | ✅ בנוי — חי חלקית, cron חדש 02:45 UTC לא פרוס |
| התאמת בנק + פער בנק-מסמכים | ✅ חי בפרוד |
| **רישום לספרים (פקודות יומן, מנות)** | 🔴 **לא קיים ב-API — החוליה השבורה. הכול ידני בדפדפן** |
| org1 עמית | OF חי (6 חשבונות) · SUMIT **חסום obligo** |
| org5 עומר ועודד | SUMIT חי · **אין חיבור בנק OF**. **מקורות אמת נקבעו 10/08/2026:** עד 30/06 — תיק היבוא (`Journal_PORAT.mdb` מההנה"ח החיצונית, שדיווחה לרשויות עד יוני כולל); מ-01/07 — מודול העסק ב-SUMIT ותיק היבוא כתיק המדווח. **התיק הישן `f2114195104` היה טסטים בלבד** — מנות 1–4, כולל ה"סגורות", היו ניסויי תיוק ולא דיווח; מחיקתו מאושרת. זה מבטל את אזהרת "סכנת הכפל" מ-30/07 ומסביר 13 שורות כפולות שנותרו בלתי-מוסברות באודיט 17/07. |
| org2 שף אליהב כהן | ✅ **הוחזר ללולאה 10/08/2026.** ההשהיה מ-17/07 לא הייתה תקלה: SUMIT חייבה את חברת הלקוח **₪62.23/יום** בעודף קריאות — הסנכרון רץ 24 פעמים ביום. השער `sumit_sync_min_interval_hours=20` נוסף אחרי האירוע ומדוד בפועל על org1 (ריצה אחת ביום, הפחתה 96%), ולכן ההחזרה בטוחה. |
| org3 מדיצ׳י | ⏸️ **מוקפא — החלטת בעלים 10/08/2026, ממתין לשיוך תוכנית.** אין מפתח API (`Invalid Credentials` מ-06/07), התיק אינו מוגדר, ואין לו משתמשים. 0 הוצאות · 0 חשבוניות · 0 תנועות בנק. **אינו נחשב פער בדוחות התאמה** עד שתשויך לו תוכנית. נרשם `ORG_FROZEN` ב-AuditLog. |
| בקרת כיסוי (roster-health) | ✅ נבנתה 05/08 — `roster_coverage.py` + cron 05:30 UTC. תופסת נשירה פר-מקור, ריצות זומבי, כפילות פנקס, ושלמות נתונים. **לא פרוסה** |
| שלמות נתונים (מדוד בפרוד 10/08) | 🟡 טיוטות בסכום 0: org1 246, org2 16, **org5 171 — כולן מ-07/2026 ואילך** (לא מכוסות ביבוא, שמסתיים 30/06). `journal_entries` **כבר לא 0**: org5 מחזיק 15,060 פקודות מיובאות, 25/11/2021→30/06/2026, עם פער ידוע ₪217,116.65 מ-19 תנועות חד-צדיות שלא הושמטו. אינדקס org5: 1,004 כרטיסי חשבשבת. |
| פרופילי רכב (VehicleProfile) | טבלה ריקה — רכב נופל לתור הכרעה |
| שידורי מע"מ | מוקפאים עד שהמנוע חי בפרוד (הפרת ה-100% תוקנה בקוד, לא בפרוד) |
| ממשק שיחה (3 פרסונות + ווב/טלגרם/וואטסאפ + observability + ידע/משימות) | ✅ בנוי אופליין — **לא פרוס**; 1,730 טסטים עברו בריצה מלאה יחידה ב־2026-08-08, על העץ שאחרי יישור הענף מול main. זיכרון לומד מנוהל עם אישור/audit ופרטיות אישית, 49 כלי צ׳אט כוללים משימות מאושרות, וה־KB נגיש לאדמין בקריאה בלבד עם honest-null. חסם: אישור deploy, מיגרציות `d6e7f8a9b0c1` ו־`e7f8a9b0c1d2`, סודות, תמחור מדויק, אימות אריזת docs ותבנית Meta מאושרת לפי הצורך |

## 3. עקרונות ביצוע

1. **מדד אחד**: התקדמות = שערים שנסגרו. לא טסטים, לא פיצ'רים.
2. שער נסגר רק בהוכחה חיה על תיק הפיילוט (לא בטסטים בלבד).
3. TDD; הסוויטה ירוקה בכל commit; deploy רק באישור בעלים.
4. הדוקטרינות מחייבות: honest-null, אימות משולש, אפס אוטונומיה בבלתי-הפיך, משמעת עלויות API.
5. עבודה שאינה בשער הפעיל — נרשמת ב"חניון" (סעיף 10) ולא מתבצעת.

### 3.1 תשתית control plane (הושלם 2026-07-25)

לבקשת בעלים בוצע יישור של שכבות הידע וה-workflow בלי לשנות את השער הפעיל:
`REZEF_OPERATING_SYSTEM.md` מגדיר חוזים יציבים; `rezef_capabilities.json` מחבר
11 יכולות לקוד, טסטים ושערים; `rezef-operator` מנתב סוכנים לאותם מקורות; והבוט
מציג את מפת היכולות מאותו מניפסט. טסט drift מקומי מונע הפניה לקובץ/טסט שאינם
קיימים. **השער הפעיל נשאר שער 0** — התשתית אינה הוכחת פרוד.

### 3.2 בסיס בטיחות מקומי (הושלם חלקית 2026-07-25)

- `FinancialService` דורש `organization_id`, מסנן קריאות ומונע רישום תנועה
  לחשבון של ארגון אחר; מכוסה ב־`tests/test_financial_service_tenancy.py`.
- `viewer` נחסם מרכזית מכל בקשת כתיבה שתלויה ב־`get_current_org_id`.
- נתיבי חיוב, ביטול חיוב מחזורי, תשלום/החזר/מנדט Open Finance וביצוע תשלום
  דורשים `admin`; הטסטים מחליפים את המחברים בחומת רשת שנכשלת אם מגיעים אליה.
- קיימת רשומה עמידה ומבודדת־ארגון של הצעה → אישור מורשה חתימה → claim אטומי →
  קבלת ספק → readback (`IRREVERSIBLE_ACTION_CONTROL.md`). נתיב התשלום המדומה
  הוחלף בסירוב 501, והמלצות/סטטוס תשלום נקראים כעת מ־Bill/Payment אמיתיים.
- בעלים ומורשי חתימה נפרדים מ־RBAC, scoped לפי פעולה, ו־Super Admin אינו
  עוקף אותם. יצירת תשלום Open Finance צורכת payload מאושר, מבצעת פעם אחת
  ושומרת readback — מוכח offline בלבד.
- פריסה מקומית על DB ריק דרך `alembic upgrade head` נבדקת כעת מול כל מודלי
  ה־ORM, כולל ריצה חוזרת ו־DB ישן שכבר קיבל תיקון additive. הבדיקה חשפה ותיקנה
  unique constraint לא־תואם SQLite ועמודת `bank_transactions.is_provisional`
  שחסרה משרשרת המיגרציות. ב־09/08 הורחב השער מבדיקת טבלאות/עמודות בלבד גם
  לטיפוסים, nullability, PK/FK, unique constraints ואינדקסים. FK שמסלול
  additive/legacy של SQLite אינו יכול ליצור מדווח כ־`dialect_exemptions` גלוי;
  ב־PostgreSQL אין להם פטור. זו הוכחת readiness אופליין בלבד — לא deploy לפרוד.
- נתיב שינוי הסכימה של שער 0 הוקשח: רק `SUPER_ADMIN` עם אישור מדויק רשאי
  להפעיל `/api/admin/db/migrate`; במסד legacy מבוצע repair → drift מבני מלא →
  `stamp head`, בסדר הזה, ונרשם AuditLog. שלושת סקריפטי התיקון החלקיים אינם
  מסמנים עוד `head`. נוהל הבעלים: `GATE0_DEPLOYMENT_RUNBOOK.md`.
- חוזה ה־cron תוקן ל־UTC של Vercel: המחזור מסתיים עד 06:45 בישראל בקיץ ובחורף,
  והסדר נבדק מול `vercel.json`. enrichment של SUMIT ירד משש ריצות ליום לריצה
  אחת, קיבל claim אטומי של 20 שעות לפני כל קונקטור ותקרה פנימית של 25 פעולות
  `getdetails` בתשלום לארגון/יום. `CustomerName` שכבר מגיע ב־list נשמר ישירות
  ואינו יוצר קריאת N+1 רק לשחזור שם. OCR כבוי לפני כל גישת SUMIT אלא אם הופעל
  במפורש, ואז מקבל claim נפרד של 20 שעות וברירת מחדל של 10 מסמכים (תקרה 25).
  הכול מוכח offline; טרם נפרס.
- bootstrap מפורש לארגונים קיימים קיים כפעולה חד־פעמית
  `I_AM_AUTHORIZED_OWNER`: רק admin פעיל בארגון ריק ממדיניות יכול להפעילו,
  replay נחסם והרישום נשמר ב־AuditLog. הוכח ב־30 בדיקות ממוקדות; לא הופעל
  על ארגון פרוד.
- סף מספרי ההקצאה 2026 אומת מול שני דפי רשות המסים והוראת ביצוע 01/2025:
  סכום לפני מע"מ העולה על ₪10,000 מ־1.1.2026 ועל ₪5,000 מ־1.6.2026.
  הטבלה המתוארכת מקודדת עם honest-null לפני הטווח המאומת.
- מסע Open Finance לארגון קיים הוכן offline: התחלה דורשת admin, תגובה חלקית
  מהספק נכשלת, `BankConnection` נשמר לפי ארגון, מזהה חיבור זר נחסם לפני הספק,
  ו־cron מדלג לפני budget/connector כל עוד consent מקומי ממתין. scope
  `create:connections`, השלמת consent ו־sync ראשון עדיין דורשים בעלים וספק חי.
- **הפרדה רב־ארגונית נסגרה אופליין 13/08:** כל בקשה ארגונית מוכרעת מחדש
  מ־`OrganizationMembership`; אין fallback ל־`users.organization_id`, וסופר־אדמין
  חייב לבחור ארגון במפורש. invite/accept/suspend/revoke מחוברים ל־HTTP ול־AuditLog,
  השבתה ארגונית אינה משביתה זהות גלובלית, ופקיעה עתידית אינה יכולה להשאיר ארגון
  בלי מנהל נגיש. חוזה ה־drift כולל כעת CheckConstraints וחוסם `stamp head` כשאילוץ
  האבטחה חסר. מסך מושקו זמין גם ב־`/agent/{session_id}` עם שיחה חדשה וקישורי
  ניטור/ידע לסופר־אדמין; נבדק ב־Playwright מקומי. מדידת מועמד 13/08:
  2,060 טסטים, route audit ‏264·179·46·38·1, schema drift/frontend/tenancy
  ירוקים. שרשרת המיגרציות עד `27f0f87c152f` נפרסה לפרוד ב־23/08; ה־head הנוכחי
  `3f8c2a1d9e70` (P0-C, ‏24/08) ו־smoke שאחריו עדיין דורשים אישור בעלים לפי הרונבוק.
- **מועמד הסגירה של מושקו והרשאות הושלם מקומית 13/08:** `policy_grants`
  נשמרים ומבוקרים, ונבדקים מחדש בהצעה/אישור/ביצוע עם תקרות סכום ותקופה,
  ערוצים, מספר מאשרים והפרדת תפקידים. כל לקוח SUMIT יצרני חייב כעת מונה
  משותף ועמיד במסד (תקרה גלובלית לדקה + תקרה לארגון ליום) לפני קריאת רשת,
  וכשל במונה נסגר בסירוב. מושקו כולל משוב משתמש, תור איכות רוחבי לסופר־אדמין,
  תיקון וקידום מפורש לידע ארגוני; זהות ערוץ נבדקת מחדש מול חברות פעילה בכל
  הודעה, ומייל/Google אינם מנחשים ארגון למשתמש רב־ארגוני. ממשקי
  `/agent/{session_id}`, `/admin-moshko` ו־`/policies` עברו Playwright מקומי.
  שרשרת המיגרציות שהייתה אז בעלת head יחיד `05c6d7e8f9a0` עברה upgrade,
  downgrade, upgrade ו־drift נקי על PostgreSQL 16 זמני. נכון ל־24/08 פרוד על
  `27f0f87c152f`; ה־head הנוכחי `3f8c2a1d9e70` טרם נפרס ולא נבדק מול ספק חי.
- **טרם הושלם:** הוכחה חיה באישור בעלים ושאר adapters
  (החזר/ביטול/מנדט/SUMIT/שידור/סגירה).
- **מסלול מורשה־חתימה שני במושקו הושלם אופליין 24/08:** `ChatMessage`
  בלתי־הפיך פתוח נחשף כעת ב־GET ארגוני רק למורשה פעיל אחר עם scope תואם;
  טאב "ממתין לאישורי" מאפשר confirm או דחייה, והמציע אינו רואה עוד אישור
  עצמי מטעה. ניתוב יזום לזהויות Telegram/WhatsApp של מורשים נוספים נשאר
  follow-up נפרד כדי לא לעקוף opt-in, חלון WhatsApp ומיפוי זהות־ערוץ.
- **הפרדת חיבורי Open Finance הושלמה אופליין 13/08:** חשבון שומר כעת את
  `connectionId` המקורי מהספק, ונתיבי status/accounts/transactions מפרידים
  חיבור, חשבון ותנועה בלי קריאת ספק. נוספו transaction-get, קטגוריות cached,
  סינון ו־pagination מקומיים ו־refresh-all בעל אישור מדויק, AuditLog ותביעת 20 שעות.
  ה־head החדש הוא `05c6d7e8f9a0`. רשומות legacy נשארות NULL עד sync רגיל — אין
  backfill מנחש. CLI/MCP תועדו בחניון ולא נבנו.

## 4. שער 0 — פתיחת תיק הפיילוט + פריסת מה שבנוי

**עיקרון: לא בוחרים תיק — פותחים את שני החסמים במקביל; הלולאה רצה על הראשון שנפתח.**

| # | משימה | מבצע | תנאי סיום |
|---|---|---|---|
| 0.1 | **deploy לפרוד** של ה־PR המאושר → זרימת הסכימה המאומתת ב־`GATE0_DEPLOYMENT_RUNBOOK.md` → smoke | בעלים + מפעיל מורשה בלבד | ✅ **הושלם 24/08/2026.** שדרוג `27f0f87c152f` → `3f8c2a1d9e70` בוצע ב-CLI ישירות מול `DATABASE_URL_UNPOOLED` (הוראת בעלים מפורשת וחוזרת — לא דרך ה-endpoint, ראה `AuditLog id=208` לחריגה המתועדת ולנימוק: הרצה דרך ה-endpoint הייתה יוצרת מבוי-סתום, כי `dependencies.py:115` קורא `user.token_version` בכל בקשה מאומתת כולל ה-endpoint עצמו). אומת: row-count parity מלא, smoke (health/login/webhook 200/401/403), אפס קריאות SUMIT לאורך כל התהליך (`provider_request_budgets` עלה ב-1 שורה בלבד, `provider='auth'` מבדיקת ה-smoke, לא `sumit`). 17 קומיטים נוספים (P0-A עד P0-F) נפרסו באותו push. |
| 0.6 | **בדיקה חיה של מושקו** — שיחה אמיתית על ארגון פועל, לא רק טסטים | קלוד (טוקן זמני 1h, `scripts/grant_superadmin_token.py`, בלי סיסמה) | ✅ **הושלם 24/08/2026** על org2 (שף אליהב כהן). שתי שאלות אמיתיות: מצב בנק (39 תנועות/+₪41,439, honest-null על 72 לא-מותאמות) ומצב חובות לקוחות (₪1,625,162 פתוח, DSO=139 יום, פירוט לקוחות אמיתי). מוסבר ב-[[moshko-whole-system-view-2026-08-19]]. |
| 0.7 | **כיסוי מלא של יכולות SUMIT** — כמה מ-89 המתודות ב-`SumitIntegration` באמת מחוברות לקוד שירות/route כלשהו (לא רק "מוגדרות") | קלוד | ✅ **85/89 (95.5%), נמדד 24/08 — לא הועתק מזיכרון ישן.** הוראת קבע (הוראת-קבע/recurring): מלא — `list_recurring`/`create_recurring`/`cancel_recurring`/`update_recurring`, כל ארבעתם כלי-מושקו אמיתיים דרך `recurring_billing_service.py`. **4 מתודות לא מחוברות משום מקום:** `get_entities_html`, `multivendor_charge`, `tokenize_single_use_json`, `update_recurring_settings` (שונה מ-`update_recurring` המחובר). 106 כלי-מושקו רשומים כרגע (גדל מ-33 ב-20/08 — המספר הישן במסמכים אחרים מיושן). |
| 0.8 | **שמירת שיחות + תור-כישלונות לבדיקה/אימון** | קלוד | ✅ **תשתית קיימת ועובדת, נמדד 24/08.** כל הודעה נשמרת (`ai_chat_messages`, 18 שורות אמיתיות בפרוד). `_capture_gap_if_giveup` לוכד כל תשובת-ויתור של מושקו ל-`moshko_gaps` אוטומטית — **אך 0 שורות בפרוד עד כה** (honest-null: המנגנון קיים ומחווט, אבל טרם נצפה בפועל, כי סה"כ 18 הודעות אמיתיות זה מעט מכדי שוויתור יקרה). לוח-בקרה מלא ב-`/admin-moshko` (`MoshkoObservabilityDashboard.tsx`, מקושר מ-`ChatAssistant.tsx`): תמלולי שיחות מלאים, tool-calls, שימוש-יומי, תור-משוב, ותור-פערים — כולם קריאים ב-UI, לא רק API גולמי. |
| 0.2 | **obligo org1**: תשלום/הסדר + שליחת IP 147.235.152.82 לסיגל | **בעלים** | קריאת API עוברת בלי "restricted" |
| 0.3 | **חיבור בנק org5**: מסע consent ב-Open Finance — ההכנה המקומית הושלמה; נותר ניסיון `create:connections` חי, השלמת בעלים ופנייה לספק אם 403 | **בעלים** + קלוד | חשבונות org5 נמשכים ב-sync היומי |
| 0.4 | זריעת פרופילי רכב לתיק הפיילוט (אילו רכבים, עיקר שימוש, צמוד-עובד) | **בעלים** (5 דקות) + קלוד מזין | אפס הוצאות רכב בתור ההכרעה מסיבת "אין פרופיל" |
| 0.5 | ✅ אימות סף מספרי ההקצאה 2026 מול gov.il | קלוד | הושלם 2026-07-25: 10K מ־1.1, 5K מ־1.6; `VERIFICATION_NEEDED` והטבלה המתוארכת עודכנו |

**יציאה משער 0: מחזור הבוקר רץ בפרוד על תיק אחד עם בנק+SUMIT חיים.**

## 5. שער 1 — קליטה: כל מסמך נוחת אוטומטית

| # | משימה | תנאי סיום |
|---|---|---|
| 1.1 | cron OCR 02:45 UTC חי בפרוד; כיסוי כל טיוטה נכנסת | תור הטיוטות מתרוקן יומית; טיוטה חדשה מטופלת ≤24h |
| 1.2 | ערוץ קליטה ללקוח (מייל תיוק ייעודי קיים — לאמת חי) | מסמך שנשלח במייל מופיע ברצף |
| 1.3 | בריף מציג "תור תיוק" אמיתי מהפיילוט | מספר תואם ידנית מול הפורטל |

## 6. שער 2 — תיוק: סיווג + מס נכונים אוטומטית

| # | משימה | תנאי סיום |
|---|---|---|
| 2.1 | מנוע המס חי על כל תיוק (שער-מסמך, יחסי מע"מ, כפילויות) | 20 מסמכים רצופים מתויקים נכון (ביקורת ידנית מדגמית) |
| 2.2 | תור ההכרעות עם תקדים-פר-ספק — הכרעה אחת ≤ דקה | חריג בן >48h = אפס |
| 2.3 | דיוק: ≥90% מהמסמכים עוברים בלי מגע אדם | מדד שבועי ב-scorecard |

## 7. שער 3 — הספרים: החוליה השבורה (הפיתוח המרכזי)

זה הפער בין "עוזר" ל"מנהל חשבונות": היום שום דבר לא נרשם לספרים בלי דפדפן ידני.

| # | משימה | פירוט | תנאי סיום |
|---|---|---|---|
| 3.1 | **עטיפת `books/transactions/createbatch`** בקונקטור | ✅ adapter אופליין הושלם 09/08/2026: חוזה Swagger מדויק, payload מאושר ושמור, claim אטומי, execute-once, `BatchURL` ו־`executed_unverified`. נותר dry-run חי באישור מפעיל על מנה חדשה והשוואה שורה-שורה מול הפורטל | פקודה שנוצרה ב-API זהה לפקודה ידנית |
| 3.2 | קורא מנות (`books` read) | ה־OpenAPI שנשמר בריפו אינו חושף readback/close; נדרש adapter מאומת למסך המנות או SOP מפעיל. `sync=0` נשאר נקודה עיוורת ואסור לפרשו כסגירה | סטטוס "סגורה" נצפה תכנותית |
| 3.3 | צינור תיוק→פקודה | כל מסמך מתויק מייצר שורת פקודה במנה פתוחה (חובה 90xxx + 40002 לפי vat_claimable, זכות 10001) — לפי המיפוי ב-SUMIT_BOOKS_AMIT_PORAT | הוצאה מתויקת מופיעה במנה בלי מגע יד |
| 3.4 | יבוא הכנסות אוטומטי | "יבוא הכנסות מהעסק" מופעל תכנותית או SOP דפדפן ממוכן | צד ההכנסות נרשם בלי כפל |
| 3.5 | סגירת מנה בזרימת אישור | הצעת סגירה בבריף → אישור בעלים בקליק → סגירה (API/דפדפן) → אימות במסך המנות | מנה נסגרת עם אישור אחד, אפס הקלדה |
| 3.6 | fallback | אם createbatch לא יציב — SOP הדפדפן הממוכן (הפלייבוק המוכח) כמסלול ביניים מתועד | הלולאה לא נעצרת |

**יציאה: שבוע שלם שבו כל מסמך שנקלט הגיע לספרים בלי הקלדה ידנית.**

## 8. שער 4 — התאמות + סט הניתוח היומי

| # | משימה | תנאי סיום |
|---|---|---|
| 4.1 | מחזור הבוקר המלא חי על הפיילוט (parity, חריגים, התאמות, מסגרת, snapshot, חייבים, בריף 08:00) | 7 ימים רצופים של בריף ≤08:00 עם נתונים מאומתים |
| 4.2 | **סט 10 השאלות היומיות** ([06-daily-analysis-prompts.md](bookkeeper_kb/06-daily-analysis-prompts.md)) רץ אוטומטית: השלמת baseline פר-ספק (שאלה 5) + חיווט כצעד ניתוח במחזור + 10 השאילתות זמינות בבוט | תשובות ל-10 השאלות בבריף/בבוט, כולל "מה ירד אתמול", "חיוב חריג מול ספק", "תזרים להמשך החודש" |
| 4.3 | אימות משולש ידני של בריף אחד מול הפורטל והבנק | הפרש ₪0 |

## 9. שער 5 — דיווח: סגירת תקופה ממוחשבת

| # | משימה | תנאי סיום |
|---|---|---|
| 5.1 | צ'ק-ליסט קדם-דיווחי PASS על תקופת הפיילוט (כולל שער התשומות החדש) | כל הסעיפים ירוקים עם ראיות |
| 5.2 | PCN874/דוח מע"מ באימות משולש; שידור ידני ע"י בעלים | דוח הוגש במועד; אפס תיקונים בדיעבד |
| 5.3 | הפשרת שידורי מע"מ (אחרי שהמנוע הוכח על התקופה) | ההקפאה מוסרת רשמית |

## 10. שער 6 — חודש ירוק → סקייל

חודש מלא ירוק על הפיילוט ⇒ onboarding התיק הבא לפי תבנית התיק (מודל מכונן 4.2) — org1/org5 (השני), אחר כך org2, org3. במקביל בלבד מהשלב הזה: פיילוט שכר Celery (4 האימותים), איחוד טבלאות פרופיל-רכב, שאר החניון.

**החניון (מוקפא עד אחרי שער 6):** שכר Celery · תזכורות גבייה אוטומטיות מורחבות · דשבורדים נוספים · ML forecasting · איחוד VehicleProfile/VehicleDeductionProfile · CLI/MCP של רצף לפי [`REZEF_CLI_ROADMAP.md`](REZEF_CLI_ROADMAP.md) (ה־CLI הישן אינו בטוח לשימוש עסקי) · כל רעיון חדש.

## 10א. סדר הבדיקות והיעדים היומיים (ה-goals של כל יום)

**סדר הבדיקות היומי** (רץ אוטומטית במחזור; ידנית כשעדיין לא פרוס — אותו סדר בדיוק):

1. אמינות: parity + טריות סנכרונים (שאלה 10 בסט) — לפני כל מספר אחר.
2. דחוף: שיקים חוזרים / הו"ק שנכשלו / חיובים שהוחזרו (שאלה 8).
3. בנק: מה ירד ומה נכנס אתמול (שאלות 1–2) + התאמת כל התנועות.
4. תיוק: התור, החריגים, מה חסר מסמך (שאלה 3).
5. כסף: מסגרת/headroom (9), תזרים להמשך החודש (7).
6. גבייה: מי שילם, מי באיחור (4).
7. חריגות ספקים והתייקרויות (5–6).
8. בריף 08:00 — אדומים תחילה.

**היעדים היומיים (daily goals) — מה חייב להיות נכון בסוף כל בוקר:**

| # | יעד | מדד | סף |
|---|---|---|---|
| G1 | הבריף יצא בזמן | שעת MorningBrief | ≤ 08:00 |
| G2 | אפס תנועות בנק פתוחות מאתמול | unreconciled מאתמול | 0 (חדשות מהיום — עד מחר) |
| G3 | תור תיוק נשלט | open_expense_drafts | ≤ 20 |
| G4 | אפס חריגים ישנים | exceptions_over_48h | 0 |
| G5 | אמינות נתונים | parity_status | ok (או stale מוסבר) |
| G6 | אין הפתעת מזומן | חריגת מסגרת צפויה | אין, או מטופלת עם תכנית |
| G7 | חריג דחוף טופל ביום גילויו | bank_anomaly פתוח בסוף היום | 0 |
| G8 | דדליין תחת שליטה | days_to_next_deadline≤3 ⇒ צ'ק-ליסט התקדם | אין אדום-דדליין |

היעדים נמדדים ב-DailySnapshot (cycle_status ירוק = כל G עומדים) ומוצגים ברצועת המגמה. **יעד שבועי:** ≥6/7 ימים ירוקים בתיק הפיילוט; חודש ירוק (סעיף 9→10) = ≥25 ימים.

**היעד היומי של העבודה על הפרויקט עצמו:** כל סשן מקדם את השער הפעיל בלבד ומסתיים ב: (א) הוכחה חיה או טסט ירוק על ההתקדמות; (ב) עדכון סטטוס בלוח הזה; (ג) שורת "איפה נעצרנו" לסשן הבא.

## 10ב. תוכנית "המימוש המלא" — עדכון 22/08/2026

**איפה נעצרנו (22/08/2026):** תוכנית "המימוש המלא" הושלמה (6 משימות):
Forecasting + CashFlow-detail + מאזן על ספרים חיים (סוף הטבלה הקפואה
במסכים; `credit_line_service` נותר תלוי ב-`Transaction` — follow-up נפרד),
דירוג פידבק בטלגרם מאוחד עם הווב, regression runner ידני לשאלות שקודמו
(W1.5), חוקי המס בלולאת הסיווג (4.4), כלי קריאה גל 2 (מלאי/CRM/טריגרים/
סטטוס סליקה; טריגרים ללא מתודת קריאה בקונקטור — פער מתועד ולא הומצא).
כל משימה עברה סקירה בלתי-תלויה; 2,431 טסטים ירוקים.

## 11. ניהול התכנית

- מסמך זה = לוח הסטטוס. עדכון סטטוס שערים בכל סשן עבודה; ביקורת שבועית קצרה מול הבעלים.
- מסמכי התכנון הקודמים (REZEF_MASTER_ORCHESTRATION_PLAN, COMPLETION_PLAN, TODO, superpowers/plans/*) — **בארכיון מרגע זה**; אין לעבוד מהם.
- סדר יומי לקלוד בכל סשן: (1) איפה הלולאה נעצרה אתמול בתיק הפיילוט; (2) קידום השער הפעיל בלבד; (3) עדכון הלוח.

## 12. החלטות פתוחות (בעלים)

| # | החלטה | ברירת מחדל אם אין הכרעה |
|---|---|---|
| א | אישור deploy (0.1) | ממתין — שום דבר לא נפרס בלי אישור |
| ב | obligo (0.2) / consent org5 (0.3) — מה קודם | שניהם במקביל; הלולאה על הראשון שנפתח |
| ג | פרופילי רכב (0.4) | הוצאות רכב ימשיכו לתור הכרעה (כנות, לא טעות) |
| ד | החייאת `sumit` ל-org2 (`paused`) ו-org3 (`inactive`) — האם להחזיר ללולאה או להשאיר מושבתים במכוון | נשארים מחוץ ללולאה; `roster-health` יתריע עליהם כל בוקר |
| ה | רשומת הרפאים `may way` (`sumit_companies` id=5, חברה 895072659, מצביעה ל-org5) — השבתה בלבד או מחיקה | מושבתת ולא נמחקת; `scripts/deactivate_may_way.py` מוכן והפיך |
| ו | 415 הטיוטות בסכום 0 — האם להשקיע במסלול דפדפן, שהוא היחיד שיכול למשוך את הצילום הקריא | נשארות ממתינות; ה-OCR מטפל קודם במה שנושא סכום |

## עדכון 23/08/2026 (המשך)
- שלוש הכרעות הבעלים בוצעו: (1) המחזור האוטומטי המלא הוחזר — 8 crons עם שער עלות מבני מאומת פר-cron; (2) כל 8 פריטי המעקב נסגרו (כולל credit_line על נתונים חיים ותיקון פלייק החצות); (3) הכול נדחף לפרוד (d40eac8..fbfbc2c, 13 commits).
- פרוד עלה ב־23/08 ל־`27f0f87c152f`; ממתינים לאישור בעלים לשדרוג ל־head
  `3f8c2a1d9e70` ולאימות בריאות אחרי deploy.
