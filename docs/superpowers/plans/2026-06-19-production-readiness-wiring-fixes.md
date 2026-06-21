# Production-Readiness Wiring & Data-Integrity Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing, real backends actually display correctly — fix the 5 verified wiring/data-integrity defects that cause real data to render as zeros or wrong values ("מי חייב לנו / איפה אנחנו עומדים").

**Architecture:** SUMIT is the source of truth; our ledger/reports are deterministic *derived* layers labeled "לבדיקת רו"ח". These fixes change only the wiring between real backends and the UI, and one VAT-derivation fallback — no architectural change.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy (backend, `pytest`), React + TypeScript + Vite + react-query (frontend; verification via `tsc && vite build` — no unit-test runner installed), Decimal-based VAT math.

## Global Constraints
- All derived financial outputs MUST carry `derived: true` + a Hebrew "לבדיקת רו"ח" disclaimer — copy this exact pattern from `ledger_service.DISCLAIMER = "נגזר מהמסמכים — לא הספרים הרשמיים. לבדיקת רו\"ח."`.
- VAT math uses `Decimal`; never float. Reuse `vat_utils` / the existing `split_inclusive` — do not hand-roll.
- Run backend tests from repo root inside the venv: `source .venv/bin/activate && python -m pytest -q`.
- Frontend has **no** unit-test runner; the gate for frontend tasks is `cd frontend && npx tsc --noEmit` (typecheck) plus the documented contract check. Do NOT invent a vitest config.
- Do not touch SUMIT-as-source-of-truth, org-based tenancy, or the in-memory→DB decision for AgreementCashFlow (that is a separate P0 plan).

---

### Task 1: VAT split fallback in the live SUMIT connector

**Why:** `sync_engine` uses `SumitConnector` (`sumit_connector.py:620`), whose `fetch_invoices`/`fetch_bills` set `tax = doc.vat_amount or 0` with **no inclusive-split fallback**. When a SUMIT doc lacks `vat_amount`, VAT silently becomes 0 → ledger tax line, VAT report and P&L all under-report. The fallback exists only in the unused `sumit_integration.py`.

**Files:**
- Modify: `src/cfo/services/sumit_connector.py:222-223` (invoices) and the parallel block in `fetch_bills` (~`275-276`)
- Reference (copy logic from): `src/cfo/integrations/sumit_integration.py:337-343` and `src/cfo/services/vat_utils.py`
- Test: `tests/test_vat_utils.py` (add a connector-normalization test, or new `tests/test_sumit_connector_vat.py`)

**Interfaces:**
- Consumes: `vat_utils.split_inclusive(gross: Decimal, doc_date: date) -> tuple[Decimal, Decimal]` (returns `(subtotal, vat)`). Confirm the exact symbol name in `vat_utils.py` before use — it may be `split_inclusive` or `split_vat`; use whichever the module exports.
- Produces: `NormalizedInvoice.subtotal`/`.tax` and `NormalizedBill.subtotal`/`.tax` that always satisfy `subtotal + tax == total` (within agorot), even when the source doc omits `vat_amount`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sumit_connector_vat.py
from datetime import date
from decimal import Decimal
from src.cfo.services.vat_utils import split_inclusive  # adjust if exported name differs

def _derive_tax(doc_vat, total, doc_date):
    """Mirror of the connector's intended derivation: use vat_amount if present,
    otherwise inclusive-split the gross. This is the behavior Task 1 introduces."""
    if doc_vat is not None:
        tax = Decimal(str(doc_vat))
        subtotal = total - tax
    else:
        subtotal, tax = split_inclusive(total, doc_date)
    return subtotal, tax

def test_missing_vat_amount_is_split_not_zeroed():
    total = Decimal("1180.00")
    subtotal, tax = _derive_tax(None, total, date(2026, 6, 1))
    assert tax > 0, "VAT must be derived, not zeroed, when vat_amount is absent"
    assert subtotal + tax == total

def test_present_vat_amount_is_respected():
    total = Decimal("1180.00")
    subtotal, tax = _derive_tax(Decimal("180.00"), total, date(2026, 6, 1))
    assert tax == Decimal("180.00")
    assert subtotal == Decimal("1000.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_sumit_connector_vat.py -v`
Expected: FAIL on import or on `split_inclusive` signature mismatch — this confirms you have located the real exported helper before editing the connector. Fix the import to the actual exported name, re-run; both tests should then PASS against the helper (they encode the target behavior).

- [ ] **Step 3: Apply the fallback in the connector**

In `src/cfo/services/sumit_connector.py`, replace the invoice derivation (lines 222-223):

```python
                    raw_vat = getattr(doc, "vat_amount", None)
                    if raw_vat is not None:
                        tax = Decimal(str(raw_vat or 0))
                        subtotal = Decimal(str(getattr(doc, "subtotal", None) or (total - tax)))
                    else:
                        from .vat_utils import split_inclusive  # exported name confirmed in Step 2
                        doc_day = doc.date if isinstance(doc.date, date) else date.today()
                        subtotal, tax = split_inclusive(total, doc_day)
```

Apply the identical change to the `fetch_bills` block (~lines 275-276), using the bill's date field.

- [ ] **Step 4: Run the full suite to verify no regression**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 216+ passed (new tests included), 0 failed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sumit_connector_vat.py src/cfo/services/sumit_connector.py
git commit -m "fix: derive VAT via inclusive split in live SUMIT connector when vat_amount absent"
```

---

### Task 2: AR aging dashboard reads the real API shape (currently shows 0)

**Why:** `/ar/aging` returns `{status, data: {buckets: {current, days_31_60, days_61_90, days_91_120, over_120}, total_receivables, customers}}` (`financial_management.py:173-187`). `apiService.get` returns the raw HTTP body (`api.ts:62`), so `CFOARDashboard` receives that envelope but reads top-level `agingData.bucket_0_30/...` (`CFOARDashboard.tsx:73-135`) → every field is `undefined` → renders 0.

**Files:**
- Modify: `frontend/src/components/CFOARDashboard.tsx:33-135`
- Reference (API shape, do not change): `src/cfo/api/routes/financial_management.py:173-187`

**Interfaces:**
- Consumes: response object `{ status: string, data: { total_receivables: number, buckets: { current, days_31_60, days_61_90, days_91_120, over_120 }, customers: Array } }`.
- Produces: `bucketChart` array + summary cards bound to the real `data.buckets.*` values. `90+` = `days_91_120 + over_120`; `total` = `data.total_receivables`; the open-items table binds to `data.customers`.

- [ ] **Step 1: Establish the contract (verification artifact)**

Confirm the live shape (no live SUMIT needed — the route shape is static):
Run: `cd /Users/mymac/coding/cfo && grep -n "buckets\|total_receivables\|customers" src/cfo/api/routes/financial_management.py | head`
Expected: shows `buckets`, `current/days_31_60/days_61_90/days_91_120/over_120`, `total_receivables`, `customers` — matching the mapping below.

- [ ] **Step 2: Map the real shape in the component**

In `CFOARDashboard.tsx`, replace the `agingData` derivation (line 33) and the chart/cards:

```tsx
  const root = aging as { data?: Record<string, any> } | undefined;
  const d = root?.data;
  const buckets = (d?.buckets ?? {}) as Record<string, number>;
  const fmtN = (v: unknown) => (typeof v === 'number' ? v : 0);

  const bucketChart = [
    { name: '0-30', amount: fmtN(buckets.current) },
    { name: '31-60', amount: fmtN(buckets.days_31_60) },
    { name: '61-90', amount: fmtN(buckets.days_61_90) },
    { name: '90+', amount: fmtN(buckets.days_91_120) + fmtN(buckets.over_120) },
  ];
  const totalReceivables = fmtN(d?.total_receivables);
  const customers = (d?.customers as Array<Record<string, unknown>>) ?? [];
```

Then update the summary cards (lines 101-135) and the table to use `bucketChart`, `totalReceivables`, and `customers` (replace `agingData?.total`→`totalReceivables`, `agingData?.bucket_0_30`→`bucketChart[0].amount`, the 31-90 sum→`bucketChart[1].amount + bucketChart[2].amount`, `agingData?.bucket_90_plus`→`bucketChart[3].amount`, `agingData?.invoices`→`customers`, `agingData?.count`→`customers.length`).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors in `CFOARDashboard.tsx`.

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CFOARDashboard.tsx
git commit -m "fix: bind AR aging dashboard to real /ar/aging {data.buckets} shape"
```

---

### Task 3: Dedicated AP dashboard (stop rendering AR under /ap)

**Why:** `App.tsx:314` maps `/ap` → `CFOARDashboard`, which queries `/ar/aging`. Users on "AP / Payables" see receivables. Real AP aging exists at `GET /api/daily-reports/ap-aging` (`daily_reports.py:45-51`, real Bill data).

**Files:**
- Create: `frontend/src/components/CFOAPDashboard.tsx`
- Modify: `frontend/src/App.tsx:78` (import) and `:314` (route)
- Reference: `frontend/src/components/DailyReportsDashboard.tsx:42` (the correct `api.get('/api/daily-reports/ap-aging')` call) and `CFOARDashboard.tsx` (layout to mirror)

**Interfaces:**
- Consumes: `GET /daily-reports/ap-aging` → confirm its response shape with the grep in Step 1 and bind to it (mirror Task 2's defensive `?? {}` pattern).
- Produces: default-exported `CFOAPDashboard({ darkMode }: { darkMode?: boolean })` React component rendered at route `/ap`.

- [ ] **Step 1: Confirm the AP aging response shape**

Run: `cd /Users/mymac/coding/cfo && sed -n '1,60p' src/cfo/services/daily_reports_service.py | grep -n "ap_aging\|bucket\|supplier\|total" ; sed -n '40,55p' src/cfo/api/routes/daily_reports.py`
Expected: reveals the field names returned by `/daily-reports/ap-aging` — use these verbatim in Step 2.

- [ ] **Step 2: Create the AP component**

Create `frontend/src/components/CFOAPDashboard.tsx` modeled on `CFOARDashboard.tsx` but:
- `queryKey: ['ap-aging']`, `queryFn: () => apiService.get('/daily-reports/ap-aging')`
- Bind summary cards + bucket chart to the field names confirmed in Step 1 (defensive `?? {}` / `?? []`).
- Title: "AP / ספקים — גיול חובות לתשלום". Render the supplier/bill list in the table.

```tsx
import { useQuery } from '@tanstack/react-query';
import apiService from '../services/api';

export default function CFOAPDashboard({ darkMode }: { darkMode?: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ['ap-aging'],
    queryFn: () => apiService.get('/daily-reports/ap-aging'),
  });
  // bind to fields confirmed in Step 1; mirror CFOARDashboard layout/cards/table.
  // ...
}
```

- [ ] **Step 3: Wire the route**

In `App.tsx`, add near line 78: `import CFOAPDashboard from './components/CFOAPDashboard';`
Change line 314 from `<Route path="/ap" element={<CFOARDashboard darkMode={darkMode} />} />` to `<Route path="/ap" element={<CFOAPDashboard darkMode={darkMode} />} />`.

- [ ] **Step 4: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: succeeds; `/ap` now renders `CFOAPDashboard`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CFOAPDashboard.tsx frontend/src/App.tsx
git commit -m "feat: dedicated AP payables dashboard wired to /daily-reports/ap-aging"
```

---

### Task 4: Wire CashFlowDashboard into navigation

**Why:** `CashFlowDashboard.tsx` is implemented (calls `/cashflow/monthly|daily|burn-rate|liquidity-ratios|by-category`) but is not routed/navigated. `/cashflow` is already taken by `CFOCashFlowProjection` (`App.tsx:312`), so this needs a distinct path.

**Files:**
- Modify: `frontend/src/App.tsx` — add import (near line 66), nav item (near line 104 block), and route (near line 312)

**Interfaces:**
- Consumes: existing default export `CashFlowDashboard` from `./components/CashFlowDashboard`.
- Produces: a reachable route `path="/cashflow-detail"` + a nav entry labeled "תזרים — מפורט".

- [ ] **Step 1: Add the import**

In `App.tsx` near the other component imports (around line 66): `import CashFlowDashboard from './components/CashFlowDashboard';` (skip if an import already exists — grep first: `grep -n "CashFlowDashboard'" frontend/src/App.tsx`).

- [ ] **Step 2: Add the route**

After line 312 (`<Route path="/cashflow" .../>`), add:
```tsx
                <Route path="/cashflow-detail" element={<CashFlowDashboard />} />
```

- [ ] **Step 3: Add the nav item**

In the nav array near line 104, add an entry:
```tsx
      { to: '/cashflow-detail', icon: TrendingUp, label: 'תזרים — מפורט', description: 'חודשי/יומי/burn-rate' },
```
(Use an icon already imported in `App.tsx`; grep the import line for an available lucide icon such as `TrendingUp` and reuse it.)

- [ ] **Step 4: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: succeeds; `/cashflow-detail` reachable from the sidebar.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: wire detailed CashFlowDashboard into nav at /cashflow-detail"
```

---

### Task 5: Mark the balance sheet as derived (parity with ledger)

**Why:** `ledger_service.balance_sheet()` carries `derived: true` + disclaimer, but `financial_reports_service.generate_balance_sheet()` → `BalanceSheetReport.to_dict()` (`asdict`) does not. `/api/reports/balance-sheet` therefore presents as if it were official books — a regulatory-mislabel risk.

**Files:**
- Modify: `src/cfo/services/financial_reports_service.py` — `BalanceSheetReport.to_dict` (the dataclass starting ~line 78; its `to_dict` is the one returning `asdict(self)` for the balance sheet)
- Test: `tests/test_financial_synthesis.py` or a new `tests/test_balance_sheet_derived.py`

**Interfaces:**
- Consumes: existing `BalanceSheetReport` dataclass + `generate_balance_sheet(organization_id, as_of_date)`.
- Produces: `to_dict()` output additionally containing `"derived": True` and `"disclaimer": "נגזר מהמסמכים — לא הספרים הרשמיים. לבדיקת רו\"ח."`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_balance_sheet_derived.py
from datetime import date
from src.cfo.services.financial_reports_service import FinancialReportsService

def test_balance_sheet_is_flagged_derived(db_session, seed_org):
    svc = FinancialReportsService(db_session)
    report = svc.generate_balance_sheet(seed_org.id, date(2026, 6, 30))
    out = report.to_dict()
    assert out.get("derived") is True
    assert "לבדיקת רו" in out.get("disclaimer", "")
```
(Use whatever org/db fixtures `tests/conftest.py` already provides — match their names; if a ready fixture seeds an org, reuse it instead of `seed_org`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_balance_sheet_derived.py -v`
Expected: FAIL — `out.get("derived")` is `None`.

- [ ] **Step 3: Add the flag in to_dict**

In `BalanceSheetReport.to_dict`, replace `return asdict(self)` with:
```python
        data = asdict(self)
        data["derived"] = True
        data["disclaimer"] = "נגזר מהמסמכים — לא הספרים הרשמיים. לבדיקת רו\"ח."
        return data
```

- [ ] **Step 4: Run test + full suite**

Run: `source .venv/bin/activate && python -m pytest tests/test_balance_sheet_derived.py -v && python -m pytest -q`
Expected: new test PASS; full suite still green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_balance_sheet_derived.py src/cfo/services/financial_reports_service.py
git commit -m "fix: flag derived balance sheet with disclaimer (parity with ledger)"
```

---

## Self-Review notes
- **Coverage vs the slice:** all 5 P1 wiring/data-integrity items from the roadmap's "P1 — נכונות וחיווט" that are bounded + verified are covered (AR schema, AP route, VAT fallback, CashFlow nav, balance-sheet flag). Deferred to separate plans: AgreementCashFlow persistence (P0, needs tables), AR/AP hardcoded-value cleanup, opening balances, `date_trunc` portability, and all P1/P2 enrichments (collection workflow, OF provisional staging, deduction mechanics, PCN874, 856/6111).
- **Type consistency:** frontend tasks read `data.buckets.*` consistently; `split_inclusive` symbol name is verified in Task 1 Step 2 before any connector edit; disclaimer string is copied verbatim from `ledger_service.DISCLAIMER`.
- **Assumption to confirm at execution:** Task 1's `split_inclusive` export name and Task 3's `/daily-reports/ap-aging` field names are each confirmed by an explicit Step-1 grep before code is written.
