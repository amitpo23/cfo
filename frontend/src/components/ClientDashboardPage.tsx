import { useEffect, useState } from 'react';
import {
  BudgetEditor, FILING_PAGE_SIZE, FilingReport, FilingRulesCard, LineDraft, PlanPayload,
  ReviewItem, ReviewList, budgetLinesPayload, customRulesPayload, firstPlanMonth, lineDefaultsFromPayload,
  linesFromPayload,
} from './dashboardFiling';
import {
  EntityLiquidity, Forecast, ForecastPanel, LiquidityEvidenceCard, LiquidityPanel, Parameters, ParametersCard,
  OpeningBalanceCard, ShareLinksCard, ZReportsCard, money, openingBalancesFromPayload, parametersFromPayload, withOpeningBalance,
  withZReport, zReportsFromPayload,
} from './dashboardTabs';
import TabErrorBoundary from './TabErrorBoundary';
import {
  CashForecast, CashForecastItemsCard, CashForecastPanel, Overdue, cashForecastItemsFromPayload,
} from './cashForecastTab';
import { BalanceSheetView, BalanceSheetCard } from './balanceSheetTab';
import { DashboardFrame, DashboardSkeleton, EmptyState, FilterBar, KpiCards, Segmented, StatusTabs } from './dashboardUi';

type CashMonth = {
  month: string;
  inflows: number | null;
  outflows: number | null;
  net_flow: number | null;
  scope_label?: string | null;
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
  z_dedupe?: { revenue_ex_vat: number; bank_till_dropped: number; source: string } | null;
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
  by_month?: Record<string, { inflows: number; outflows: number }>;
};

type SourceItem = {
  kind: string;
  kind_label: string;
  label: string | null;
  source: string;
  source_label: string;
  last_date: string | null;
  last_sync: string | null;
  rows: number;
  age_days: number | null;
  status: 'fresh' | 'aging' | 'stale' | 'unknown';
  status_label: string;
  entity?: string | null;
};

type Sources = {
  status?: string;
  items?: SourceItem[];
  stale_count?: number;
  aging_count?: number;
  rule?: string | null;
};

type StatementCells = Record<string, number | null>;

type CashStatement = {
  status?: string;
  months?: string[];
  groups?: { id: string; label: string }[];
  lines?: { id: string; label: string; group: string; review?: boolean; values: StatementCells; total: number }[];
  totals?: Record<string, StatementCells>;
  forecast?: { status?: string; months: string[]; rows: Record<string, StatementCells>; note: string; line_items?: boolean; line_note?: string } | null;
  message?: string | null;
  netting_note?: string | null;
  scope?: Record<string, { label: string; entities: string[]; missing: string[] }>;
  scope_note?: string | null;
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
  cash_forecast?: CashForecast | null;
  sources?: Sources | null;
  cash_statement?: CashStatement | null;
  balance_sheet?: BalanceSheetView | null;
  entities?: { label: string | null; role: string; view: DashboardView }[];
  combined?: {
    pnl?: DashboardView['pnl'];
    cashflow?: DashboardView['cashflow'];
    budget_vs_actual?: DashboardView['budget_vs_actual'];
    liquidity?: EntityLiquidity | null;
    forecast?: Forecast | null;
    cash_forecast?: CashForecast | null;
    intercompany_removed?: IntercompanyRemoved;
    sources?: Sources | null;
    cash_statement?: CashStatement | null;
    balance_sheet?: BalanceSheetView | null;
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
      <td>{label}</td>
      <td className={`py-2 ${row.budget === null ? 'text-stone-400' : ''}`}>{budgetCell(row.budget)}</td>
      <td>{money(row.actual)}</td>
      <td>{varianceCell(row)}</td>
    </tr>
  );
}

function PnlMonths({ months }: { months: PnlMonth[] }) {
  const known = months.filter((month) => month.source);
  if (known.length === 0) return null;
  return (
    <table className="mt-4 d-table">
      <thead>
        <tr>
          <th>חודש</th>
          <th>מקור</th>
          <th>הכנסות</th>
          <th>הוצאות</th>
          <th>תוצאה</th>
          <th>לבירור (נכנס / יצא)</th>
        </tr>
      </thead>
      <tbody>
        {known.map((month) => (
          <tr key={month.month}>
            <td>{month.month}</td>
            <td className="py-2 text-xs text-stone-600">
              {month.source === 'cash_basis' ? 'בסיס מזומן' : 'ספרים'}
              {month.journal_dedupe ? ' + יומן SUMIT' : ''}
              {month.z_dedupe ? ' + דוח Z' : ''}
              {month.coverage_label ? ` · ${month.coverage_label}` : ''}
            </td>
            <td>{money(month.revenue)}</td>
            <td>{money(month.costs)}</td>
            <td>{money(month.net)}</td>
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
    <section className="d-card">
      <h2>יומן SUMIT מיובא ברווח והפסד</h2>
      <p className="mt-1 text-sm text-stone-500">
        מיפוי טיוטה של כרטיסי המקור לשורות הרווח וההפסד (ללא מע״מ), לאישור מנהלת החשבונות. בחודש שבו ליומן יש סכום בשורה,
        השורה נלקחת מהיומן וסכום הבנק שלה לא נספר, כדי שהוצאה ותשלומה לא ייספרו פעמיים.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="d-table">
          <thead>
            <tr>
              <th>כרטיס</th>
              {withJournal.map((month) => <th key={month.month}>{month.month}</th>)}
            </tr>
          </thead>
          <tbody>
            {[...codes.entries()].map(([code, label]) => (
              <tr key={code}>
                <td>{label} <span className="text-xs text-stone-400">({code})</span></td>
                {withJournal.map((month) => <td key={month.month} className="py-2">{money(amount(month, code))}</td>)}
              </tr>
            ))}
            <tr className="text-stone-600">
              <td>סכום בנק שלא נספר</td>
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
  const byMonth = Object.entries(removed.by_month ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <section className="d-card">
      <h2>קיזוז בין-חברתי</h2>
      <p className="mt-2 text-sm">
        קוזזו {removed.pairs} העברות בסך {money(removed.amount ?? removed.inflows)} מהכניסות ומהיציאות של התזרים המאוחד.
      </p>
      {removed.rule ? <p className="mt-1 text-xs text-stone-500">{removed.rule}</p> : null}
      {byMonth.length > 0 ? (
        <table className="mt-3 d-table">
          <thead>
            <tr>
              <th>חודש</th>
              <th>כניסות שקוזזו</th>
              <th>יציאות שקוזזו</th>
            </tr>
          </thead>
          <tbody>
            {byMonth.map(([month, cut]) => (
              <tr key={month}>
                <td>{month}</td>
                <td>{money(cut.inflows)}</td>
                <td>{money(cut.outflows)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {byMonth.length > 0 ? (
        <p className="mt-1 text-xs text-stone-500">הסכומים כבר הוסרו מהכניסות ומהיציאות של התזרים המאוחד, כל צד בחודש שבו נרשם בבנק.</p>
      ) : null}
      {items.length > 0 ? (
        <table className="mt-3 d-table">
          <thead>
            <tr>
              <th>מ-</th>
              <th>אל</th>
              <th>יציאה</th>
              <th>כניסה</th>
              <th>סכום</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.out_date}-${item.in_date}-${item.amount}-${item.from}`}>
                <td>{item.from ?? '—'}</td>
                <td>{item.to ?? '—'}</td>
                <td>{item.out_date}</td>
                <td>{item.in_date}{item.days_apart ? ` (${item.days_apart} ימים)` : ''}</td>
                <td>{money(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

// Labels and thresholds come from the API (dashboards/freshness.py); only the tone lives here.
const STATUS_TONE: Record<string, string> = {
  fresh: 'text-emerald-700',
  aging: 'text-amber-600',
  stale: 'text-red-700',
  unknown: 'text-stone-500',
};

// Sources and freshness: one row per bank account and per books source.
export function SourcesCard({ sources }: { sources: Sources | null | undefined }) {
  const items = sources?.items ?? [];
  if (items.length === 0) return null;
  const withEntity = items.some((item) => item.entity);
  return (
    <section className="d-card">
      <h2>מקורות ורעננות</h2>
      {sources?.stale_count ? (
        <p className="mt-1 text-sm text-red-700">{sources.stale_count} מקורות לא עדכניים.</p>
      ) : null}
      {sources?.aging_count ? (
        <p className="mt-1 text-sm text-amber-600">{sources.aging_count} מקורות מתיישנים.</p>
      ) : null}
      <div className="mt-3 overflow-x-auto">
        <table className="d-table">
          <thead>
            <tr>
              {withEntity ? <th>ישות</th> : null}
              <th>מקור</th>
              <th>חשבון / סוג</th>
              <th>תנועה אחרונה</th>
              <th>סנכרון / יבוא אחרון</th>
              <th>שורות</th>
              <th>מצב</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.entity ?? ''}-${item.kind}-${item.label ?? ''}-${item.source}`}>
                {withEntity ? <td>{item.entity ?? '—'}</td> : null}
                <td>{item.source_label}</td>
                <td>{item.kind === 'bank' ? item.label : item.kind_label}</td>
                <td>{item.last_date ?? 'לא ידוע'}</td>
                <td>{item.last_sync ? item.last_sync.slice(0, 16).replace('T', ' ') : 'לא ידוע'}</td>
                <td>{item.rows.toLocaleString('he-IL')}</td>
                <td className={`py-2 ${STATUS_TONE[item.status] ?? ''}`}>
                  {item.status_label}{item.age_days !== null ? ` (${item.age_days} ימים)` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sources?.rule ? <p className="mt-2 text-xs text-stone-500">{sources.rule}</p> : null}
    </section>
  );
}

function cell(value: number | null | undefined): string {
  return value === null || value === undefined ? 'לא ידוע' : money(value);
}

// Cash flow by line item × month: actual months from filed BOOKED rows, then the forecast months.
export function CashStatementCard({ statement }: { statement: CashStatement | null | undefined }) {
  const months = statement?.months ?? [];
  if (!statement || months.length === 0 || statement.status !== 'ready') return null;
  const lines = statement.lines ?? [];
  const totals = statement.totals ?? {};
  const forecast = statement.forecast && statement.forecast.months.length > 0 ? statement.forecast : null;
  const forecastMonths = forecast?.months ?? [];
  // The forecast has group totals only: a line's forecast cell says so instead of staying empty.
  const blank = forecastMonths.map((month) => (
    <td key={`f-${month}`} className="bg-stone-50 py-1 text-stone-400" title="תחזית לפי קבוצה בלבד">—</td>
  ));
  return (
    <section className="d-card">
      <h2>דוח תזרים לפי סעיף וחודש</h2>
      <div className="mt-3 overflow-x-auto">
        <table className="d-table">
          <thead>
            <tr>
              <th>סעיף</th>
              {months.map((month) => (
                <th key={month}>
                  {month}
                  {statement.scope?.[month] ? <div className="text-[11px] font-normal text-amber-700">{statement.scope[month].label}</div> : null}
                </th>
              ))}
              {forecastMonths.map((month) => (
                <th key={`f-${month}`} className="bg-stone-50 py-2 text-right font-medium">{month} (תחזית)</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(statement.groups ?? []).map((group) => {
              const rows = lines.filter((line) => line.group === group.id);
              if (rows.length === 0) return null;
              const forecastRow = forecast?.rows[group.id];
              return [
                ...rows.map((line) => (
                  <tr key={line.id}>
                    <td className={`py-1 ${line.review ? 'text-amber-700' : ''}`}>{line.label}</td>
                    {months.map((month) => <td key={month}>{cell(line.values[month])}</td>)}
                    {blank}
                  </tr>
                )),
                <tr key={`total-${group.id}`} className="border-b font-medium">
                  <td>סה״כ {group.label}</td>
                  {months.map((month) => <td key={month}>{cell(totals[group.id]?.[month])}</td>)}
                  {forecastMonths.map((month) => (
                    <td key={`f-${month}`} className={`bg-stone-50 py-1 ${forecastRow ? '' : 'font-normal text-stone-400'}`}>
                      {forecastRow ? cell(forecastRow[month]) : 'לא נחזה'}
                    </td>
                  ))}
                </tr>,
              ];
            })}
            <tr className="font-semibold">
              <td>תזרים נטו</td>
              {months.map((month) => <td key={month}>{cell(totals.net?.[month])}</td>)}
              {forecastMonths.map((month) => (
                <td key={`f-${month}`} className="bg-stone-50 py-2">{cell(forecast?.rows.net?.[month])}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {statement.message ? <p className="mt-2 text-xs text-stone-500">{statement.message}</p> : null}
      {statement.netting_note ? <p className="mt-1 text-xs text-stone-500">{statement.netting_note}</p> : null}
      {statement.scope_note ? <p className="mt-1 text-xs text-amber-800">{statement.scope_note}</p> : null}
      {forecast ? <p className="mt-1 text-xs text-stone-500">{forecast.note}</p> : null}
      {forecast ? (
        <p className="mt-1 text-xs text-stone-500">
          {forecast.line_note || 'התחזית מחושבת לפי קבוצה בלבד, בלי פירוט לפי סעיף.'}
        </p>
      ) : null}
    </section>
  );
}

export function BudgetVsActual({ section }: { section: NonNullable<DashboardView['budget_vs_actual']> }) {
  const months = section.months ?? [];
  const visible = months.filter((month) => (month.categories ?? []).length > 0);
  return (
    <section className="d-card">
      <h2>תקציב מול ביצוע</h2>
      {!section.has_budget ? <p className="mt-3 text-stone-600">לא הוזן תקציב לתקופה.</p> : null}
      {visible.length === 0 ? null : (
        <table className="mt-4 d-table">
          <thead>
            <tr>
              <th>קטגוריה</th>
              <th>תקציב</th>
              <th>ביצוע</th>
              <th>סטייה</th>
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
  // The title from the last visit, shown with the skeleton before the first request returns.
  const [cachedTitle] = useState(() => sessionStorage.getItem(`rezef:d:title:${slugFromLocation()}`));

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
          if (dashboard.title) sessionStorage.setItem(`rezef:d:title:${slug}`, dashboard.title);
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
    cash_forecast: view.combined?.cash_forecast,
    sources: view.combined?.sources,
    cash_statement: view.combined?.cash_statement,
    balance_sheet: view.combined?.balance_sheet,
  } : entities[Number(scope)]?.view ?? view;
  // Past-due items are per entity; the combined scope lists every entity's, named.
  const overdue: Overdue[] = !view ? [] : !multi ? (view.cash_forecast?.overdue ?? [])
    : scope === 'combined'
      ? entities.flatMap((entity) => (entity.view.cash_forecast?.overdue ?? []).map((item) => ({ ...item, entity: entity.label })))
      : (entities[Number(scope)]?.view.cash_forecast?.overdue ?? []);
  const parameters = parametersFromPayload(plan?.payload);

  return (
    <DashboardFrame
      title={editor?.title || cachedTitle || 'דשבורד לקוח'}
      subtitle={editor ? `${ROLE_LABELS[editor.role] || editor.role}${editor.canEdit ? ' · אפשר לערוך' : ' · צפייה בלבד'}` : null}
    >
        {notice ? <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">{notice}</p> : null}
        {error ? <div className="mt-6"><EmptyState title={error}>בדקו את הקישור, או בקשו קישור חדש מבעלי הדשבורד.</EmptyState></div> : null}
        {!error && !view ? <DashboardSkeleton /> : null}
        {view && scoped ? (
          <>
            <StatusTabs tabs={TABS.filter((item) => item.id !== 'budget' || editor)} active={tab} onSelect={setTab} />
            {multi ? (
              <FilterBar>
                <Segmented
                  label="ישות"
                  value={scope}
                  onChange={setScope}
                  options={[{ key: 'combined', label: 'מאוחד' }, ...entities.map((entity, index) => ({ key: String(index), label: entity.label || `ישות ${index + 1}` }))]}
                />
                {view.source === 'snapshot' ? <span className="text-xs text-stone-500">תמונת מצב שפורסמה</span> : null}
              </FilterBar>
            ) : null}
            <TabErrorBoundary tab={`${tab}:${scope}`}>
            <div id="dashboard-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="mt-4 grid gap-4">
              {tab === 'balance' ? <BalanceSheetCard sheet={scoped.balance_sheet} /> : null}
              {tab === 'status' ? (
                <>
                  <StatusKpis view={scoped} reviewCount={filing?.review.total ?? null} />
                  <SourcesCard sources={scoped.sources} />
                  <PnlCard pnl={scoped.pnl} />
                  <JournalCard months={scoped.pnl?.months ?? []} />
                  <CashflowCard view={scoped} />
                  <CashStatementCard statement={scoped.cash_statement} />
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
                scoped.budget_vs_actual ? <BudgetVsActual section={scoped.budget_vs_actual} /> : <EmptyState title="אין נתוני תקציב">אפשר להזין תקציב בלשונית "תקציב ופרמטרים".</EmptyState>
              ) : null}
              {tab === 'liquidity' ? <LiquidityPanel section={scoped.liquidity} /> : null}
              {tab === 'liquidity' && editor?.role === 'owner' && plan && filing ? (
                <LiquidityEvidenceCard
                  entities={filing.entities ?? []}
                  payload={plan.payload}
                  saving={saving}
                  onSave={(next) => void savePayload(next, false)}
                />
              ) : null}
              {tab === 'liquidity' && editor?.role === 'owner' && plan && filing ? (
                <OpeningBalanceCard
                  entities={filing.entities ?? []}
                  items={openingBalancesFromPayload(plan.payload)}
                  saving={saving}
                  onSave={(organizationId, item) => void savePayload(withOpeningBalance(plan.payload, organizationId, item), false)}
                />
              ) : null}
              {tab === 'cashforecast' ? <CashForecastPanel forecast={scoped.cash_forecast} overdue={overdue} /> : null}
              {tab === 'cashforecast' && editor?.role === 'owner' && plan && filing ? (
                <CashForecastItemsCard
                  entities={filing.entities ?? []}
                  items={cashForecastItemsFromPayload(plan.payload)}
                  saving={saving}
                  onSave={(next) => void savePayload({ ...plan.payload, cashForecastItems: next }, false)}
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
                  {editor.role === 'owner' && plan && filing ? (
                    <ZReportsCard
                      entities={filing.entities ?? []}
                      items={zReportsFromPayload(plan.payload)}
                      saving={saving}
                      onSave={(organizationId, zMonth, item) => void savePayload(withZReport(plan.payload, organizationId, zMonth, item), false)}
                    />
                  ) : null}
                  {editor.role === 'owner' ? (
                    <ShareLinksCard dashboardId={editor.id} slug={slugFromLocation()} headers={authHeaders} />
                  ) : null}
                </>
              ) : null}
              {tab === 'budget' && editor && !filing ? <DashboardSkeleton /> : null}
            </div>
            </TabErrorBoundary>
          </>
        ) : null}
    </DashboardFrame>
  );
}

const TABS = [
  { id: 'status', label: 'תמונת מצב' },
  { id: 'balance', label: 'מאזן' },
  { id: 'cashforecast', label: 'תזרים חזוי' },
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
    ...(reviewCount === null ? [] : [{ label: 'תנועות לבירור', value: String(reviewCount), tone: reviewCount > 0 ? 'warn' as const : null }]),
  ];
  return <KpiCards items={items} />;
}

function PnlCard({ pnl }: { pnl: DashboardView['pnl'] }) {
  return (
    <section className="d-card">
      <h2>רווח והפסד</h2>
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
    <section className="d-card">
      <h2>תזרים</h2>
      {months.length === 0 ? (
        emptyPeriodRepeatsCoverage ? null : (
          <p className="mt-3 text-stone-600">{emptyPeriodNote}</p>
        )
      ) : (
        <table className="mt-4 d-table">
          <thead>
            <tr>
              <th>חודש</th>
              <th>כניסות</th>
              <th>יציאות</th>
              <th>נטו</th>
            </tr>
          </thead>
          <tbody>
            {months.map((cashMonth) => (
              <tr key={cashMonth.month}>
                <td>
                  {cashMonth.month}
                  {cashMonth.scope_label ? <span className="ms-2 text-xs text-amber-700">{cashMonth.scope_label}</span> : null}
                </td>
                <td>{money(cashMonth.inflows)}</td>
                <td>{money(cashMonth.outflows)}</td>
                <td>{money(cashMonth.net_flow)}</td>
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
    <section className="d-card">
      <h2>פירוט כרטיסי אשראי</h2>
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
