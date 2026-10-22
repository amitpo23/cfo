import { useEffect, useState } from 'react';
import {
  BudgetEditor, FILING_PAGE_SIZE, FilingReport, FilingRulesCard, LineDraft, PlanPayload,
  ReviewItem, ReviewList, budgetLinesPayload, customRulesPayload, firstPlanMonth, lineDefaultsFromPayload,
  linesFromPayload,
} from './dashboardFiling';
import {
  EntityLiquidity, Forecast, ForecastPanel, LiquidityPanel, Parameters, ParametersCard,
  OpeningBalanceCard, ShareLinksCard, money, openingBalancesFromPayload, parametersFromPayload, withOpeningBalance,
} from './dashboardTabs';
import TabErrorBoundary from './TabErrorBoundary';

type CashMonth = {
  month: string;
  inflows: number;
  outflows: number;
  net_flow: number;
};

type BudgetCompare = {
  budget: number | null;
  actual: number | null;
  variance: number | null;
  variance_pct: number | null;
};

type BudgetLine = BudgetCompare & {
  kind: 'revenue' | 'cost';
  category: string;
  category_he: string;
  blocked?: boolean;
};

type BudgetMonth = {
  month: string;
  source?: string | null;
  source_label?: string | null;
  blocked?: boolean;
  categories?: BudgetLine[] | null;
  totals?: { revenue?: BudgetCompare | null; costs?: BudgetCompare | null } | null;
};

type PnlMonth = {
  month: string;
  source: string | null;
  source_label?: string | null;
  coverage_label?: string | null;
  revenue: number | null;
  costs: number | null;
  net: number | null;
  unresolved_in?: number | null;
  unresolved_out?: number | null;
  blocked?: boolean;
  journal?: JournalMonth | null;
  journal_dedupe?: { rows_replaced: { id: string; label: string; bank_amount: number; journal_amount: number }[]; bank_dropped: number; journal_used: number } | null;
};

type JournalMonth = {
  source_label: string;
  lines: { code: string; label: string; row: string; amount: number }[];
  entries: number;
  unbalanced: number;
  balance_only: number;
};

type IntercompanyRemoved = {
  pairs: number;
  inflows: number;
  outflows: number;
  amount?: number;
  window_days?: number;
  rule?: string;
  items?: { from: string | null; to: string | null; out_date: string; in_date: string; amount: number; days_apart: number }[];
};

type PendingMonth = { month: string; inflows: number; outflows: number; count: number };

type CardMonth = { month: string; total: number; merchants: { merchant: string; amount: number }[] };

type QualityMessage = { message_he?: string };

type ActivityQuality = {
  notes?: QualityMessage[];
  warnings?: QualityMessage[];
};

type DashboardView = {
  source?: string;
  provider_calls?: number;
  cashflow?: {
    months?: CashMonth[];
    message?: string | null;
    coverage?: { message?: string | null } | null;
    pending?: { count?: number; months?: PendingMonth[]; message?: string | null } | null;
    activity_quality?: ActivityQuality | null;
  };
  card_breakdown?: { months?: CardMonth[]; message?: string | null } | null;
  pnl?: {
    status?: string;
    total_revenue?: number | null;
    total_expenses?: number | null;
    net_income_before_tax?: number | null;
    message?: string | null;
    basis?: string;
    months?: PnlMonth[];
  };
  budget_vs_actual?: {
    status?: string;
    has_budget?: boolean;
    months?: BudgetMonth[];
    message?: string | null;
  } | null;
  liquidity?: EntityLiquidity | null;
  forecast?: Forecast | null;
  entities?: { label: string | null; role: string; view: DashboardView }[];
  combined?: {
    pnl?: DashboardView['pnl'];
    cashflow?: DashboardView['cashflow'];
    budget_vs_actual?: DashboardView['budget_vs_actual'];
    liquidity?: EntityLiquidity | null;
    forecast?: Forecast | null;
    intercompany_removed?: IntercompanyRemoved;
  };
  error?: { message_he?: string };
};

// /d/<slug>?tab=bva opens a tab directly (the legacy /budget page links here).
function tabFromLocation(): TabId {
  const wanted = new URLSearchParams(window.location.search).get('tab');
  return TABS.find((item) => item.id === wanted)?.id ?? 'status';
}

function slugFromLocation(): string {
  const parts = window.location.pathname.replace(/\/+$/, '').split('/');
  return parts[2] || '';
}


function ActivityNotes({ quality }: { quality: ActivityQuality | null | undefined }) {
  const notes = quality?.notes ?? [];
  const warnings = quality?.warnings ?? [];
  if (notes.length === 0 && warnings.length === 0) return null;
  return (
    <div className="mt-3 grid gap-2 text-sm">
      {notes.map((note, index) => (
        <p key={`note-${index}`} className="text-stone-600">{note.message_he}</p>
      ))}
      {warnings.map((warning, index) => (
        <p key={`warning-${index}`} className="text-amber-800">{warning.message_he}</p>
      ))}
    </div>
  );
}

function budgetCell(value: number | null | undefined): string {
  return value === null || value === undefined ? 'אין תקציב' : money(value);
}

function varianceCell(row: BudgetCompare): string {
  if (row.variance === null || row.variance === undefined) return '—';
  const pct = row.variance_pct === null || row.variance_pct === undefined ? '' : ` (${row.variance_pct}%)`;
  return `${money(row.variance)}${pct}`;
}

const NO_COMPARE: BudgetCompare = { budget: null, actual: null, variance: null, variance_pct: null };

function BudgetRow({ label, row: given, strong }: { label: string; row: BudgetCompare | null | undefined; strong?: boolean }) {
  const row = given ?? NO_COMPARE;
  return (
    <tr className={`border-b border-stone-100 ${strong ? 'font-medium' : ''}`}>
      <td className="py-2">{label}</td>
      <td className={`py-2 ${row.budget === null ? 'text-stone-400' : ''}`}>{budgetCell(row.budget)}</td>
      <td className="py-2">{money(row.actual)}</td>
      <td className="py-2">{varianceCell(row)}</td>
    </tr>
  );
}

function PnlMonths({ months }: { months: PnlMonth[] }) {
  const known = months.filter((month) => month.source);
  if (known.length === 0) return null;
  return (
    <table className="mt-4 w-full text-sm">
      <thead>
        <tr className="border-b text-stone-500">
          <th className="py-2 text-right font-medium">חודש</th>
          <th className="py-2 text-right font-medium">מקור</th>
          <th className="py-2 text-right font-medium">הכנסות</th>
          <th className="py-2 text-right font-medium">הוצאות</th>
          <th className="py-2 text-right font-medium">תוצאה</th>
          <th className="py-2 text-right font-medium">לבירור (נכנס / יצא)</th>
        </tr>
      </thead>
      <tbody>
        {known.map((month) => (
          <tr key={month.month} className="border-b border-stone-100">
            <td className="py-2">{month.month}</td>
            <td className="py-2 text-xs text-stone-600">
              {month.source === 'cash_basis' ? 'בסיס מזומן' : 'ספרים'}
              {month.journal_dedupe ? ' + יומן SUMIT' : ''}
              {month.coverage_label ? ` · ${month.coverage_label}` : ''}
            </td>
            <td className="py-2">{money(month.revenue)}</td>
            <td className="py-2">{money(month.costs)}</td>
            <td className="py-2">{money(month.net)}</td>
            <td className={`py-2 ${month.blocked ? 'text-amber-700' : 'text-stone-500'}`}>
              {month.source === 'cash_basis'
                ? `${money(month.unresolved_in ?? null)} / ${money(month.unresolved_out ?? null)}`
                : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// The imported SUMIT journal (Food Group) by source account and month, and which
// comparison rows of the cash-basis P&L it replaced (the bank amount of those rows is dropped).
export function JournalCard({ months }: { months: PnlMonth[] }) {
  const withJournal = months.filter((month) => month.journal && month.journal.lines.length > 0);
  if (withJournal.length === 0) return null;
  const codes = new Map<string, string>();
  withJournal.forEach((month) => month.journal?.lines.forEach((line) => codes.set(line.code, line.label)));
  const amount = (month: PnlMonth, code: string) => month.journal?.lines.find((line) => line.code === code)?.amount ?? null;
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">יומן SUMIT מיובא ברווח והפסד</h2>
      <p className="mt-1 text-sm text-stone-500">
        מיפוי טיוטה של כרטיסי המקור לשורות הרווח וההפסד (ללא מע״מ), לאישור מנהלת החשבונות. בחודש שבו ליומן יש סכום בשורה,
        השורה נלקחת מהיומן וסכום הבנק שלה לא נספר, כדי שהוצאה ותשלומה לא ייספרו פעמיים.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500">
              <th className="py-2 text-right font-medium">כרטיס</th>
              {withJournal.map((month) => <th key={month.month} className="py-2 text-right font-medium">{month.month}</th>)}
            </tr>
          </thead>
          <tbody>
            {[...codes.entries()].map(([code, label]) => (
              <tr key={code} className="border-b border-stone-100">
                <td className="py-2">{label} <span className="text-xs text-stone-400">({code})</span></td>
                {withJournal.map((month) => <td key={month.month} className="py-2">{money(amount(month, code))}</td>)}
              </tr>
            ))}
            <tr className="text-stone-600">
              <td className="py-2">סכום בנק שלא נספר</td>
              {withJournal.map((month) => (
                <td key={month.month} className="py-2">{month.journal_dedupe ? money(month.journal_dedupe.bank_dropped) : 'לא נכלל'}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-stone-500">
        חודש בלי תנועות בנק אינו נכלל ברווח והפסד: ביומן אין כרטיסי הכנסה, ולכן הרווח וההפסד של החודש לא ידוע.
      </p>
    </section>
  );
}

// The intercompany transfers netted out of the consolidated cash flow, and the rule that matched them.
export function IntercompanyCard({ removed }: { removed: IntercompanyRemoved | null | undefined }) {
  if (!removed) return null;
  const items = removed.items ?? [];
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">קיזוז בין-חברתי</h2>
      <p className="mt-2 text-sm">
        קוזזו {removed.pairs} העברות בסך {money(removed.amount ?? removed.inflows)} מהכניסות ומהיציאות של התזרים המאוחד.
      </p>
      {removed.rule ? <p className="mt-1 text-xs text-stone-500">{removed.rule}</p> : null}
      {items.length > 0 ? (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500">
              <th className="py-2 text-right font-medium">מ-</th>
              <th className="py-2 text-right font-medium">אל</th>
              <th className="py-2 text-right font-medium">יציאה</th>
              <th className="py-2 text-right font-medium">כניסה</th>
              <th className="py-2 text-right font-medium">סכום</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.out_date}-${item.in_date}-${item.amount}-${item.from}`} className="border-b border-stone-100">
                <td className="py-2">{item.from ?? '—'}</td>
                <td className="py-2">{item.to ?? '—'}</td>
                <td className="py-2">{item.out_date}</td>
                <td className="py-2">{item.in_date}{item.days_apart ? ` (${item.days_apart} ימים)` : ''}</td>
                <td className="py-2">{money(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

export function BudgetVsActual({ section }: { section: NonNullable<DashboardView['budget_vs_actual']> }) {
  const months = section.months ?? [];
  const visible = months.filter((month) => (month.categories ?? []).length > 0);
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">תקציב מול ביצוע</h2>
      {!section.has_budget ? <p className="mt-3 text-stone-600">לא הוזן תקציב לתקופה.</p> : null}
      {visible.length === 0 ? null : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500">
              <th className="py-2 text-right font-medium">קטגוריה</th>
              <th className="py-2 text-right font-medium">תקציב</th>
              <th className="py-2 text-right font-medium">ביצוע</th>
              <th className="py-2 text-right font-medium">סטייה</th>
            </tr>
          </thead>
          {visible.map((month) => (
            <tbody key={month.month}>
              <tr className="border-b bg-stone-50">
                <td className="py-2 font-medium" colSpan={4}>
                  {month.month}
                  {month.source_label ? <span className="ms-2 text-xs text-stone-500">· {month.source_label}</span> : null}
                  {month.blocked ? <span className="ms-2 text-xs text-amber-700">· סטייה בשכר ובספקים מוסתרת: יותר מ־5,000 ₪ לבירור</span> : null}
                </td>
              </tr>
              {(month.categories ?? []).map((line) => (
                <BudgetRow
                  key={`${line.kind}-${line.category}`}
                  label={`${line.kind === 'revenue' ? 'הכנסה' : 'הוצאה'} · ${line.category_he || line.category}${line.blocked ? ' (סטייה מוסתרת)' : ''}`}
                  row={line}
                />
              ))}
              <BudgetRow label='סה"כ הכנסות' row={month.totals?.revenue} strong />
              <BudgetRow label='סה"כ הוצאות' row={month.totals?.costs} strong />
            </tbody>
          ))}
        </table>
      )}
      {section.message ? <p className="mt-3 text-sm text-stone-500">{section.message}</p> : null}
    </section>
  );
}

type EditorContext = {
  id: number;
  role: string;
  canEdit: boolean;
  title?: string;
};

const ROLE_LABELS: Record<string, string> = {
  owner: 'בעלים',
  accountant: 'רואה חשבון',
  client_editor: 'עורך',
  client_viewer: 'צופה',
};

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export default function ClientDashboardPage() {
  const [view, setView] = useState<DashboardView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorContext | null>(null);
  const [plan, setPlan] = useState<{ version: string | null; payload: PlanPayload } | null>(null);
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [month, setMonth] = useState(currentMonth);
  const [filing, setFiling] = useState<FilingReport | null>(null);
  const [ruleSeed, setRuleSeed] = useState({ text: '', nonce: 0 });
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<TabId>(tabFromLocation);
  const [scope, setScope] = useState('combined');

  useEffect(() => {
    const slug = slugFromLocation();
    const shareToken = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('k');
    if (window.location.hash) {
      window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`);
    }
    let cancelled = false;

    async function loadPublic() {
      const response = await fetch(`/api/public/d/${slug}`, { credentials: 'include' });
      const body = (await response.json().catch(() => ({}))) as DashboardView;
      if (cancelled) return;
      if (!response.ok) {
        setError(body.error?.message_he || 'הדשבורד לא נמצא');
        return;
      }
      setView(body);
    }

    async function loadEditor(dashboardId: number) {
      const headers = authHeaders();
      // The three requests run together, and each one is shown when it arrives:
      // the page does not wait for the filing report to show the view.
      const viewTask = (async () => {
        const viewResponse = await fetch(`/api/dashboards/${dashboardId}/view`, { headers });
        const viewBody = (await viewResponse.json().catch(() => ({}))) as DashboardView;
        if (cancelled) return;
        if (!viewResponse.ok) {
          setError(viewBody.error?.message_he || 'הדשבורד לא נמצא');
          return;
        }
        setView(viewBody);
      })();
      const planTask = (async () => {
        const planResponse = await fetch(`/api/dashboards/${dashboardId}/plan`, { headers });
        const planBody = (await planResponse.json().catch(() => ({}))) as {
          version?: string | null;
          payload?: PlanPayload | null;
          error?: { message_he?: string };
        };
        if (cancelled || !planResponse.ok) return;
        const payload = planBody.payload && typeof planBody.payload === 'object' ? planBody.payload : {};
        setPlan({ version: planBody.version ?? null, payload });
        setLines(linesFromPayload(payload));
        const first = firstPlanMonth(payload, currentMonth());
        if (first) setMonth(first);
      })();
      const filingTask = (async () => {
        const filingResponse = await fetch(`/api/dashboards/${dashboardId}/filing?page=1&page_size=${FILING_PAGE_SIZE}`, { headers });
        const filingBody = (await filingResponse.json().catch(() => ({}))) as FilingReport & {
          error?: { message_he?: string };
        };
        if (cancelled || !filingResponse.ok) return;
        setFiling(filingBody);
      })();
      await Promise.all([viewTask, planTask, filingTask]);
    }

    async function load() {
      if (shareToken) {
        await fetch(`/api/public/d/${slug}/session`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: shareToken }),
        });
      }
      if (localStorage.getItem('auth_token')) {
        const meta = await fetch(`/api/dashboards/by-slug/${slug}`, { headers: authHeaders() });
        if (meta.ok) {
          const dashboard = (await meta.json()) as { id: number; role: string; can_edit: boolean; title?: string };
          if (cancelled) return;
          setEditor({ id: dashboard.id, role: dashboard.role, canEdit: dashboard.can_edit, title: dashboard.title });
          await loadEditor(dashboard.id);
          return;
        }
      }
      await loadPublic();
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function reloadFiling(page: number) {
    if (!editor) return;
    const response = await fetch(
      `/api/dashboards/${editor.id}/filing?page=${page}&page_size=${FILING_PAGE_SIZE}`,
      { headers: authHeaders() },
    );
    const body = (await response.json().catch(() => ({}))) as FilingReport & { error?: { message_he?: string } };
    if (!response.ok) {
      setNotice(body.error?.message_he || 'טעינת התיוק נכשלה');
      return;
    }
    setFiling(body);
  }

  async function reloadView() {
    if (!editor) return;
    const response = await fetch(`/api/dashboards/${editor.id}/view`, { headers: authHeaders() });
    if (!response.ok) return;
    setView((await response.json()) as DashboardView);
  }

  async function savePayload(next: PlanPayload, resetLines: boolean): Promise<boolean> {
    if (!editor || !plan) return false;
    setSaving(true);
    setNotice(null);
    const response = await fetch(`/api/dashboards/${editor.id}/plan`, {
      method: 'PUT',
      headers: { ...authHeaders(), 'Content-Type': 'application/json', 'If-Match': plan.version ?? 'null' },
      body: JSON.stringify({ payload: next }),
    });
    const body = (await response.json().catch(() => ({}))) as {
      version?: string;
      payload?: PlanPayload;
      error?: { message_he?: string };
    };
    setSaving(false);
    if (!response.ok || !body.version || !body.payload) {
      setNotice(body.error?.message_he || 'השמירה נכשלה');
      return false;
    }
    setPlan({ version: body.version, payload: body.payload });
    if (resetLines) setLines(linesFromPayload(body.payload));
    await Promise.all([reloadView(), reloadFiling(filing?.review.page ?? 1)]);
    return true;
  }

  function saveBudget() {
    if (!plan || !filing) return;
    const built = budgetLinesPayload(lines, filing.budget_categories);
    if ('error' in built) {
      setNotice(built.error);
      return;
    }
    void savePayload({ ...plan.payload, budgetLines: built.lines }, true);
  }

  function saveRules(rules: FilingReport['rules']) {
    if (!plan) return;
    void savePayload({ ...plan.payload, statusRules: customRulesPayload(rules) }, false);
  }

  function approve(item: ReviewItem, category: string, note: string) {
    if (!plan) return;
    const existing = plan.payload.statusDecisions;
    const decisions = existing && typeof existing === 'object' ? { ...(existing as Record<string, unknown>) } : {};
    decisions[item.id] = {
      category,
      action: 'approve',
      organizationId: item.organization_id,
      date: item.date,
      amount: item.amount,
      source: 'dashboard',
      note: note || null,
      updatedAt: new Date().toISOString(),
    };
    void savePayload({ ...plan.payload, statusDecisions: decisions }, false);
  }

  function saveParameters(next: Parameters) {
    if (!plan) return;
    void savePayload({ ...plan.payload, statusParameters: next }, false);
  }

  const entities = view?.entities ?? [];
  const multi = entities.length > 1;
  const scoped: DashboardView | null = !view ? null : !multi ? view : scope === 'combined' ? {
    pnl: view.combined?.pnl,
    cashflow: view.combined?.cashflow,
    budget_vs_actual: view.combined?.budget_vs_actual,
    liquidity: view.combined?.liquidity,
    forecast: view.combined?.forecast,
  } : entities[Number(scope)]?.view ?? view;
  const parameters = parametersFromPayload(plan?.payload);

  return (
    <main dir="rtl" className="min-h-screen bg-stone-50 text-stone-900">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <p className="text-sm text-stone-500">רצף</p>
        <h1 className="mt-1 text-2xl font-semibold">{editor?.title || 'דשבורד לקוח'}</h1>
        {editor ? (
          <p className="mt-1 text-sm text-stone-500">
            {ROLE_LABELS[editor.role] || editor.role}
            {editor.canEdit ? ' · אפשר לערוך' : ' · צפייה בלבד'}
          </p>
        ) : null}
        {notice ? <p className="mt-3 text-sm text-stone-700">{notice}</p> : null}
        {error ? <p className="mt-8 text-stone-700">{error}</p> : null}
        {!error && !view ? <p className="mt-8 text-stone-500">טוען נתונים…</p> : null}
        {view && scoped ? (
          <>
            <nav className="mt-6 flex flex-wrap gap-1 border-b border-stone-200" role="tablist">
              {TABS.filter((item) => item.id !== 'budget' || editor).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === item.id}
                  className={`px-3 py-2 text-sm ${tab === item.id ? 'border-b-2 border-stone-900 font-medium' : 'text-stone-600'}`}
                  onClick={() => setTab(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </nav>
            {multi ? (
              <div className="mt-3 flex flex-wrap gap-2 text-sm" role="radiogroup" aria-label="ישות">
                {[{ key: 'combined', label: 'מאוחד' }, ...entities.map((entity, index) => ({ key: String(index), label: entity.label || `ישות ${index + 1}` }))].map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    role="radio"
                    aria-checked={scope === option.key}
                    className={`rounded-full border px-3 py-1 ${scope === option.key ? 'border-stone-900 bg-stone-900 text-white' : 'border-stone-300'}`}
                    onClick={() => setScope(option.key)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            ) : null}
            <TabErrorBoundary tab={`${tab}:${scope}`}>
            <div className="mt-6 grid gap-6">
              {tab === 'status' ? (
                <>
                  <StatusKpis view={scoped} reviewCount={filing?.review.total ?? null} />
                  <PnlCard pnl={scoped.pnl} />
                  <JournalCard months={scoped.pnl?.months ?? []} />
                  <CashflowCard view={scoped} />
                  {multi && scope === 'combined' ? <IntercompanyCard removed={view.combined?.intercompany_removed} /> : null}
                  {editor && filing ? (
                    <ReviewList
                      canEdit={editor.canEdit}
                      report={filing}
                      saving={saving}
                      onPage={(page) => { void reloadFiling(page); }}
                      onApprove={approve}
                      onCreateRule={(description) => setRuleSeed({ text: description.slice(0, 80), nonce: Date.now() })}
                    />
                  ) : null}
                  {editor && filing ? (
                    <FilingRulesCard
                      canEdit={editor.canEdit}
                      rules={filing.rules}
                      categories={filing.categories}
                      seed={ruleSeed}
                      saving={saving}
                      onSave={saveRules}
                      manifest={filing.builtin_manifest}
                    />
                  ) : null}
                  <CardBreakdown view={scoped} />
                </>
              ) : null}
              {tab === 'bva' ? (
                scoped.budget_vs_actual ? <BudgetVsActual section={scoped.budget_vs_actual} /> : <p className="text-stone-600">אין נתוני תקציב.</p>
              ) : null}
              {tab === 'liquidity' ? <LiquidityPanel section={scoped.liquidity} /> : null}
              {tab === 'liquidity' && editor?.role === 'owner' && plan && filing ? (
                <OpeningBalanceCard
                  entities={filing.entities ?? []}
                  items={openingBalancesFromPayload(plan.payload)}
                  saving={saving}
                  onSave={(organizationId, item) => void savePayload(withOpeningBalance(plan.payload, organizationId, item), false)}
                />
              ) : null}
              {tab === 'forecast' ? <ForecastPanel forecast={scoped.forecast} /> : null}
              {tab === 'budget' && editor ? (
                <>
                  {filing ? (
                    <BudgetEditor
                      canEdit={editor.canEdit}
                      categories={filing.budget_categories}
                      lines={lines}
                      lineDefaults={lineDefaultsFromPayload(plan?.payload)}
                      month={month}
                      onMonth={setMonth}
                      onLines={setLines}
                      onSave={saveBudget}
                      saving={saving}
                    />
                  ) : null}
                  <ParametersCard value={parameters} canEdit={editor.canEdit} saving={saving} onSave={saveParameters} />
                  {editor.role === 'owner' ? (
                    <ShareLinksCard dashboardId={editor.id} slug={slugFromLocation()} headers={authHeaders} />
                  ) : null}
                </>
              ) : null}
              {tab === 'budget' && editor && !filing ? <p className="text-stone-500">טוען את התקציב…</p> : null}
            </div>
            </TabErrorBoundary>
          </>
        ) : null}
      </div>
    </main>
  );
}

const TABS = [
  { id: 'status', label: 'תמונת מצב' },
  { id: 'bva', label: 'תקציב מול ביצוע' },
  { id: 'liquidity', label: 'נזילות והתחייבויות' },
  { id: 'forecast', label: 'תחזית' },
  { id: 'budget', label: 'תקציב ופרמטרים' },
] as const;

export type TabId = (typeof TABS)[number]['id'];

function StatusKpis({ view, reviewCount }: { view: DashboardView; reviewCount: number | null }) {
  const liquidity = view.liquidity;
  const balance = liquidity ? (liquidity.position ? liquidity.position.balance : liquidity.balance) : null;
  const partial = !liquidity?.position && (balance === null || balance === undefined)
    && liquidity?.balance_known !== null && liquidity?.balance_known !== undefined;
  const items = [
    { label: 'הכנסות בתקופה', value: money(view.pnl?.total_revenue) },
    { label: 'הוצאות בתקופה', value: money(view.pnl?.total_expenses) },
    { label: 'יתרת עו״ש', value: partial ? `${money(liquidity?.balance_known)} (חלקי)` : money(balance ?? null) },
    { label: 'התחייבויות ידועות', value: money(liquidity?.debts_known_total ?? null) },
    ...(reviewCount === null ? [] : [{ label: 'תנועות לבירור', value: String(reviewCount) }]),
  ];
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {items.map((item) => (
        <div key={item.label} className="rounded-xl bg-white p-4 shadow-sm">
          <p className="text-xs text-stone-500">{item.label}</p>
          <p className="mt-1 text-lg">{item.value}</p>
        </div>
      ))}
    </section>
  );
}

function PnlCard({ pnl }: { pnl: DashboardView['pnl'] }) {
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">רווח והפסד</h2>
      {pnl?.status === 'unknown' ? (
        <p className="mt-3 text-stone-600">{pnl.message}</p>
      ) : (
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-sm text-stone-500">הכנסות</dt>
            <dd className="text-xl">{money(pnl?.total_revenue)}</dd>
          </div>
          <div>
            <dt className="text-sm text-stone-500">הוצאות</dt>
            <dd className="text-xl">{money(pnl?.total_expenses)}</dd>
          </div>
          <div>
            <dt className="text-sm text-stone-500">רווח לפני מס</dt>
            <dd className="text-xl">{money(pnl?.net_income_before_tax)}</dd>
          </div>
        </dl>
      )}
      {pnl?.status === 'ready' && pnl.months ? <PnlMonths months={pnl.months} /> : null}
      {pnl?.status === 'ready' && pnl.message ? (
        <p className="mt-3 text-sm text-stone-500">{pnl.message}</p>
      ) : null}
    </section>
  );
}

function CashflowCard({ view }: { view: DashboardView }) {
  const months = view.cashflow?.months ?? [];
  const coverageNote = view.cashflow?.coverage?.message || '';
  const pendingMonths = view.cashflow?.pending?.months ?? [];
  const emptyPeriodNote = view.cashflow?.message || 'אין תנועות בנק בתקופה.';
  const emptyPeriodRepeatsCoverage = coverageNote !== '' && emptyPeriodNote === coverageNote;
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">תזרים</h2>
      {months.length === 0 ? (
        emptyPeriodRepeatsCoverage ? null : (
          <p className="mt-3 text-stone-600">{emptyPeriodNote}</p>
        )
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500">
              <th className="py-2 text-right font-medium">חודש</th>
              <th className="py-2 text-right font-medium">כניסות</th>
              <th className="py-2 text-right font-medium">יציאות</th>
              <th className="py-2 text-right font-medium">נטו</th>
            </tr>
          </thead>
          <tbody>
            {months.map((cashMonth) => (
              <tr key={cashMonth.month} className="border-b border-stone-100">
                <td className="py-2">{cashMonth.month}</td>
                <td className="py-2">{money(cashMonth.inflows)}</td>
                <td className="py-2">{money(cashMonth.outflows)}</td>
                <td className="py-2">{money(cashMonth.net_flow)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {coverageNote ? (
        <p className="mt-3 text-sm text-stone-600">{coverageNote}</p>
      ) : null}
      <p className="mt-3 text-sm text-stone-500">התזרים כולל רק תנועות שנרשמו בבנק (BOOKED). חיובי כרטיסי האשראי נספרים פעם אחת, כחיוב החודשי בעו״ש.</p>
      {pendingMonths.length > 0 ? (
        <div className="mt-3 text-sm text-stone-600">
          <p>{view.cashflow?.pending?.message}</p>
          <ul className="mt-1">
            {pendingMonths.map((month) => (
              <li key={month.month}>
                {month.month}: נכנס {money(month.inflows)} · יצא {money(month.outflows)} ({month.count})
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <ActivityNotes quality={view.cashflow?.activity_quality} />
    </section>
  );
}

function CardBreakdown({ view }: { view: DashboardView }) {
  const cardMonths = view.card_breakdown?.months ?? [];
  if (cardMonths.length === 0) return null;
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">פירוט כרטיסי אשראי</h2>
      {cardMonths.map((month) => (
        <div key={month.month} className="mt-3 text-sm">
          <p className="font-medium">{month.month} · {money(month.total)}</p>
          <ul className="mt-1 text-stone-600">
            {month.merchants.map((item) => (
              <li key={item.merchant}>{item.merchant}: {money(item.amount)}</li>
            ))}
          </ul>
        </div>
      ))}
      {view.card_breakdown?.message ? (
        <p className="mt-3 text-sm text-stone-500">{view.card_breakdown.message}</p>
      ) : null}
    </section>
  );
}
