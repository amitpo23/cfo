import { useEffect, useState } from 'react';
import {
  BudgetEditor, FILING_PAGE_SIZE, FilingReport, FilingRulesCard, LineDraft, PlanPayload,
  ReviewItem, ReviewList, budgetLinesPayload, customRulesPayload, linesFromPayload,
} from './dashboardFiling';

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
  categories: BudgetLine[];
  totals: { revenue: BudgetCompare; costs: BudgetCompare };
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
  error?: { message_he?: string };
};

function slugFromLocation(): string {
  const parts = window.location.pathname.replace(/\/+$/, '').split('/');
  return parts[2] || '';
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'לא ידוע';
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(value);
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

function BudgetRow({ label, row, strong }: { label: string; row: BudgetCompare; strong?: boolean }) {
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

function BudgetVsActual({ section }: { section: NonNullable<DashboardView['budget_vs_actual']> }) {
  const months = section.months ?? [];
  const visible = months.filter((month) => month.categories.length > 0);
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
              {month.categories.map((line) => (
                <BudgetRow
                  key={`${line.kind}-${line.category}`}
                  label={`${line.kind === 'revenue' ? 'הכנסה' : 'הוצאה'} · ${line.category_he}${line.blocked ? ' (סטייה מוסתרת)' : ''}`}
                  row={line}
                />
              ))}
              <BudgetRow label='סה"כ הכנסות' row={month.totals.revenue} strong />
              <BudgetRow label='סה"כ הוצאות' row={month.totals.costs} strong />
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
      const [viewResponse, planResponse, filingResponse] = await Promise.all([
        fetch(`/api/dashboards/${dashboardId}/view`, { headers }),
        fetch(`/api/dashboards/${dashboardId}/plan`, { headers }),
        fetch(`/api/dashboards/${dashboardId}/filing?page=1&page_size=${FILING_PAGE_SIZE}`, { headers }),
      ]);
      const viewBody = (await viewResponse.json().catch(() => ({}))) as DashboardView;
      const planBody = (await planResponse.json().catch(() => ({}))) as {
        version?: string | null;
        payload?: PlanPayload | null;
        error?: { message_he?: string };
      };
      const filingBody = (await filingResponse.json().catch(() => ({}))) as FilingReport & {
        error?: { message_he?: string };
      };
      if (cancelled) return;
      if (!viewResponse.ok) {
        setError(viewBody.error?.message_he || 'הדשבורד לא נמצא');
        return;
      }
      setView(viewBody);
      if (planResponse.ok) {
        const payload = planBody.payload && typeof planBody.payload === 'object' ? planBody.payload : {};
        setPlan({ version: planBody.version ?? null, payload });
        setLines(linesFromPayload(payload));
      }
      if (filingResponse.ok) setFiling(filingBody);
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
          const dashboard = (await meta.json()) as { id: number; role: string; can_edit: boolean };
          if (cancelled) return;
          setEditor({ id: dashboard.id, role: dashboard.role, canEdit: dashboard.can_edit });
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

  const months = view?.cashflow?.months ?? [];
  const pnl = view?.pnl;
  const coverageNote = view?.cashflow?.coverage?.message || '';
  const pendingMonths = view?.cashflow?.pending?.months ?? [];
  const cardMonths = view?.card_breakdown?.months ?? [];
  const activityQuality = view?.cashflow?.activity_quality;
  const emptyPeriodNote = view?.cashflow?.message || 'אין תנועות בנק בתקופה.';
  const emptyPeriodRepeatsCoverage = coverageNote !== '' && emptyPeriodNote === coverageNote;

  return (
    <main dir="rtl" className="min-h-screen bg-stone-50 text-stone-900">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <p className="text-sm text-stone-500">רצף</p>
        <h1 className="mt-1 text-2xl font-semibold">דשבורד לקוח</h1>
        {editor ? (
          <p className="mt-1 text-sm text-stone-500">
            {ROLE_LABELS[editor.role] || editor.role}
            {editor.canEdit ? ' · אפשר לערוך' : ' · צפייה בלבד'}
          </p>
        ) : null}
        {notice ? <p className="mt-3 text-sm text-stone-700">{notice}</p> : null}
        {error ? <p className="mt-8 text-stone-700">{error}</p> : null}
        {!error && !view ? <p className="mt-8 text-stone-500">טוען נתונים…</p> : null}
        {view ? (
          <div className="mt-8 grid gap-6">
            {editor && filing ? (
              <BudgetEditor
                canEdit={editor.canEdit}
                categories={filing.budget_categories}
                lines={lines}
                month={month}
                onMonth={setMonth}
                onLines={setLines}
                onSave={saveBudget}
                saving={saving}
              />
            ) : null}
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
            {view.budget_vs_actual ? <BudgetVsActual section={view.budget_vs_actual} /> : null}
            {editor && filing ? (
              <FilingRulesCard
                canEdit={editor.canEdit}
                rules={filing.rules}
                categories={filing.categories}
                seed={ruleSeed}
                saving={saving}
                onSave={saveRules}
              />
            ) : null}
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
              <ActivityNotes quality={activityQuality} />
            </section>
            {cardMonths.length > 0 ? (
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
            ) : null}
          </div>
        ) : null}
      </div>
    </main>
  );
}
