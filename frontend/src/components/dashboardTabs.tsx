import { useEffect, useState, type ReactNode } from 'react';

// The Eliav tool's tabs inside /d/: liquidity and obligations, forecast,
// budget parameters and share links. Unknown amounts are shown as "לא ידוע".

export type Debt = { label: string; amount: number | null; as_of?: string | null; entity?: string | null; note?: string | null };
export type Upcoming = { date: string; label: string | null; amount: number | null; kind: string; note?: string | null; entity?: string | null };
export type DebtService = { month: string; principal: number; interest: number; new_loans: number };

export type EntityLiquidity = {
  status?: string;
  position?: {
    balance: number | null;
    as_of: string | null;
    limit: number | null;
    limit_source: string | null;
    available_to_limit: number | null;
  };
  accounts?: { name: string; kind: string; balance: number | null; credit_limit: number | null; as_of: string | null }[];
  cards?: { name: string; balance: number | null; as_of: string | null }[];
  loans?: { name: string; balance: number | null; as_of: string | null; maturity?: string | null }[];
  months?: { month: string; days: number; min: number | null; negative_days: number; beyond_limit_days: number | null; last: number | null }[];
  checks?: { check: string; date: string; amount: number; payee: string | null; state: string; cleared_on?: string }[];
  // combined only
  balance?: number | null;
  balance_note?: string | null;
  upcoming?: Upcoming[];
  debts?: Debt[];
  debts_known_total?: number | null;
  debts_complete?: boolean;
  debt_service?: DebtService[];
  message?: string | null;
};

export type Forecast = {
  status?: string;
  months: string[];
  rows: { id: string; label: string; months: Record<string, { value: number | null; source: string | null }> }[];
  totals: Record<string, {
    revenue: number | null; costs: number | null; result: number | null; principal: number | null;
    cash_flow: number | null; cumulative_cash: number | null; projected_balance: number | null;
  }>;
  based_on: string[];
  message?: string | null;
};

export type Parameters = {
  scenario: string;
  horizonMonths: number;
  revenueGrowthPct: number;
  costGrowthPct: number;
  vatRate: number;
};

export const DEFAULT_PARAMETERS: Parameters = {
  scenario: 'בסיס', horizonMonths: 6, revenueGrowthPct: 0, costGrowthPct: 0, vatRate: 0.18,
};

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'לא ידוע';
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(value);
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">{title}</h2>
      {children}
    </section>
  );
}

function Th({ children }: { children?: ReactNode }) {
  return <th className="py-2 text-right font-medium">{children}</th>;
}

const CHECK_STATES: Record<string, string> = {
  cleared: 'נפרע',
  future: 'עתידי',
  not_found: 'לא נמצא בבנק',
  no_coverage: 'אין נתוני בנק',
};

const ACCOUNT_KINDS: Record<string, string> = {
  checking: 'עו״ש',
  card: 'כרטיס אשראי',
  loan: 'הלוואה',
  credit_line_mirror: 'מסגרת (משקף את המינוס)',
  other: 'אחר',
};

export function LiquidityPanel({ section }: { section: EntityLiquidity | null | undefined }) {
  if (!section) return <Card title="נזילות והתחייבויות"><p className="mt-3 text-stone-600">אין נתוני נזילות.</p></Card>;
  const combined = section.position === undefined;
  const balance = combined ? section.balance : section.position?.balance;
  return (
    <div className="grid gap-6">
      <Card title="נזילות">
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-sm text-stone-500">יתרת עו״ש</dt>
            <dd className="text-xl">{money(balance)}</dd>
            {section.position?.as_of ? <dd className="text-xs text-stone-500">נכון ל־{section.position.as_of}</dd> : null}
          </div>
          {!combined ? (
            <>
              <div>
                <dt className="text-sm text-stone-500">מסגרת אשראי</dt>
                <dd className="text-xl">{money(section.position?.limit)}</dd>
              </div>
              <div>
                <dt className="text-sm text-stone-500">פנוי עד המסגרת</dt>
                <dd className={`text-xl ${(section.position?.available_to_limit ?? 0) < 0 ? 'text-red-700' : ''}`}>
                  {money(section.position?.available_to_limit)}
                </dd>
              </div>
            </>
          ) : null}
        </dl>
        {section.balance_note ? <p className="mt-3 text-sm text-amber-800">{section.balance_note}</p> : null}
        {section.months && section.months.length > 0 ? (
          <table className="mt-4 w-full text-sm">
            <thead><tr className="border-b text-stone-500"><Th>חודש</Th><Th>ימים</Th><Th>שפל</Th><Th>ימי מינוס</Th><Th>ימים מעבר למסגרת</Th><Th>סוף חודש</Th></tr></thead>
            <tbody>
              {section.months.map((month) => (
                <tr key={month.month} className="border-b border-stone-100">
                  <td className="py-2">{month.month}</td>
                  <td className="py-2">{month.days}</td>
                  <td className="py-2">{money(month.min)}</td>
                  <td className="py-2">{month.negative_days}</td>
                  <td className="py-2">{month.beyond_limit_days ?? 'לא ידוע'}</td>
                  <td className="py-2">{money(month.last)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {section.accounts && section.accounts.length > 0 ? (
          <ul className="mt-4 text-sm text-stone-600">
            {section.accounts.map((account, index) => (
              <li key={`${account.name}-${index}`}>
                {account.name} · {ACCOUNT_KINDS[account.kind] ?? account.kind} · {money(account.balance)}
              </li>
            ))}
          </ul>
        ) : null}
        {section.message ? <p className="mt-3 text-sm text-stone-500">{section.message}</p> : null}
      </Card>
      <Card title="התחייבויות והלוואות">
        {(section.debts ?? []).length === 0 ? <p className="mt-3 text-stone-600">אין התחייבויות ידועות.</p> : (
          <table className="mt-4 w-full text-sm">
            <thead><tr className="border-b text-stone-500"><Th>התחייבות</Th>{combined ? <Th>ישות</Th> : null}<Th>סכום</Th><Th>נכון ל</Th></tr></thead>
            <tbody>
              {(section.debts ?? []).map((debt, index) => (
                <tr key={`${debt.label}-${index}`} className="border-b border-stone-100">
                  <td className="py-2">{debt.label}{debt.note ? <span className="mr-2 text-xs text-stone-500">{debt.note}</span> : null}</td>
                  {combined ? <td className="py-2">{debt.entity}</td> : null}
                  <td className="py-2">{money(debt.amount)}</td>
                  <td className="py-2">{debt.as_of ?? '—'}</td>
                </tr>
              ))}
              <tr className="font-medium">
                <td className="py-2">סה״כ ידוע</td>
                {combined ? <td /> : null}
                <td className="py-2">{money(section.debts_known_total)}</td>
                <td className="py-2 text-xs text-stone-500">{section.debts_complete ? '' : 'חלק מהסכומים לא ידועים'}</td>
              </tr>
            </tbody>
          </table>
        )}
        {(section.debt_service ?? []).some((row) => row.principal || row.interest || row.new_loans) ? (
          <table className="mt-4 w-full text-sm">
            <thead><tr className="border-b text-stone-500"><Th>חודש</Th><Th>החזרי קרן</Th><Th>ריבית</Th><Th>הלוואות חדשות</Th></tr></thead>
            <tbody>
              {(section.debt_service ?? []).map((row) => (
                <tr key={row.month} className="border-b border-stone-100">
                  <td className="py-2">{row.month}</td>
                  <td className="py-2">{money(row.principal)}</td>
                  <td className="py-2">{money(row.interest)}</td>
                  <td className="py-2">{money(row.new_loans)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Card>
      <Card title="מועדים קרובים">
        {(section.upcoming ?? []).length === 0 ? <p className="mt-3 text-stone-600">אין מועדים ידועים.</p> : (
          <table className="mt-4 w-full text-sm">
            <thead><tr className="border-b text-stone-500"><Th>תאריך</Th><Th>מה</Th>{combined ? <Th>ישות</Th> : null}<Th>סכום</Th></tr></thead>
            <tbody>
              {(section.upcoming ?? []).map((item, index) => (
                <tr key={`${item.date}-${index}`} className="border-b border-stone-100">
                  <td className="py-2">{item.date}</td>
                  <td className="py-2">{item.label}{item.note ? <span className="mr-2 text-xs text-stone-500">{item.note}</span> : null}</td>
                  {combined ? <td className="py-2">{item.entity}</td> : null}
                  <td className="py-2">{money(item.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section.checks && section.checks.length > 0 ? (
          <>
            <h3 className="mt-4 font-medium">צ׳קים דחויים</h3>
            <table className="mt-2 w-full text-sm">
              <thead><tr className="border-b text-stone-500"><Th>צ׳ק</Th><Th>תאריך</Th><Th>מוטב</Th><Th>סכום</Th><Th>מצב</Th></tr></thead>
              <tbody>
                {section.checks.map((check) => (
                  <tr key={`${check.check}-${check.date}`} className="border-b border-stone-100">
                    <td className="py-2">{check.check}</td>
                    <td className="py-2">{check.date}</td>
                    <td className="py-2">{check.payee}</td>
                    <td className="py-2">{money(check.amount)}</td>
                    <td className="py-2">{CHECK_STATES[check.state] ?? check.state}{check.cleared_on ? ` · ${check.cleared_on}` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </Card>
    </div>
  );
}

const SOURCE_LABELS: Record<string, string> = { budget: 'תקציב', trend: 'מגמה' };

export function ForecastPanel({ forecast }: { forecast: Forecast | null | undefined }) {
  if (!forecast || forecast.months.length === 0) {
    return <Card title="תחזית"><p className="mt-3 text-stone-600">אין נתונים לתחזית.</p></Card>;
  }
  return (
    <Card title="תחזית">
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500"><Th>סעיף</Th>{forecast.months.map((month) => <Th key={month}>{month}</Th>)}</tr>
          </thead>
          <tbody>
            {forecast.rows.map((row) => (
              <tr key={row.id} className="border-b border-stone-100">
                <td className="py-2">{row.label}</td>
                {forecast.months.map((month) => {
                  const cell = row.months[month];
                  return (
                    <td key={month} className="py-2">
                      {money(cell?.value)}
                      {cell?.source ? <div className="text-xs text-stone-500">{SOURCE_LABELS[cell.source] ?? cell.source}</div> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
            {(['result', 'cash_flow', 'cumulative_cash', 'projected_balance'] as const).map((key) => (
              <tr key={key} className="border-b border-stone-100 font-medium">
                <td className="py-2">{{ result: 'תוצאה', cash_flow: 'תזרים (קירוב)', cumulative_cash: 'תזרים מצטבר', projected_balance: 'יתרה צפויה' }[key]}</td>
                {forecast.months.map((month) => <td key={month} className="py-2">{money(forecast.totals[month]?.[key])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {forecast.message ? <p className="mt-3 text-sm text-stone-500">{forecast.message}</p> : null}
    </Card>
  );
}

export function parametersFromPayload(payload: Record<string, unknown> | null | undefined): Parameters {
  const raw = payload?.statusParameters;
  const value = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const number = (key: keyof Parameters, fallback: number) => (typeof value[key] === 'number' ? (value[key] as number) : fallback);
  return {
    scenario: typeof value.scenario === 'string' && value.scenario.trim() ? value.scenario : DEFAULT_PARAMETERS.scenario,
    horizonMonths: number('horizonMonths', DEFAULT_PARAMETERS.horizonMonths),
    revenueGrowthPct: number('revenueGrowthPct', DEFAULT_PARAMETERS.revenueGrowthPct),
    costGrowthPct: number('costGrowthPct', DEFAULT_PARAMETERS.costGrowthPct),
    vatRate: number('vatRate', DEFAULT_PARAMETERS.vatRate),
  };
}

export function ParametersCard({
  value, canEdit, saving, onSave,
}: { value: Parameters; canEdit: boolean; saving: boolean; onSave: (next: Parameters) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const field = (key: keyof Parameters, label: string, step = '1') => (
    <label className="text-stone-600">
      {label}
      <input
        dir="ltr"
        type="number"
        step={step}
        className="mt-1 block w-28 rounded border border-stone-300 px-2 py-1 text-left"
        value={draft[key] as number}
        readOnly={!canEdit}
        onChange={(event) => setDraft({ ...draft, [key]: Number(event.target.value) })}
      />
    </label>
  );
  return (
    <Card title="פרמטרים">
      <div className="mt-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="text-stone-600">
          תרחיש
          <input
            className="mt-1 block rounded border border-stone-300 px-2 py-1"
            value={draft.scenario}
            readOnly={!canEdit}
            onChange={(event) => setDraft({ ...draft, scenario: event.target.value })}
          />
        </label>
        {field('horizonMonths', 'אופק (חודשים)')}
        {field('revenueGrowthPct', 'צמיחת הכנסות % לחודש', '0.1')}
        {field('costGrowthPct', 'צמיחת הוצאות % לחודש', '0.1')}
        {field('vatRate', 'מע״מ', '0.01')}
        {canEdit ? (
          <button type="button" className="rounded bg-stone-900 px-3 py-1 text-white disabled:opacity-50" disabled={saving} onClick={() => onSave(draft)}>
            שמור פרמטרים
          </button>
        ) : null}
      </div>
    </Card>
  );
}

type ShareLink = { id: number; label: string | null; revoked_at: string | null; expires_at: string | null; use_count: number };

export function ShareLinksCard({ dashboardId, slug, headers }: { dashboardId: number; slug: string; headers: () => HeadersInit }) {
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [created, setCreated] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const response = await fetch(`/api/dashboards/${dashboardId}/share-links`, { headers: headers() });
    if (!response.ok) return;
    const body = (await response.json()) as { links: ShareLink[] };
    setLinks(body.links);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId]);

  async function create() {
    setError(null);
    const response = await fetch(`/api/dashboards/${dashboardId}/share-links`, {
      method: 'POST',
      headers: { ...headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: 'קישור ללקוח' }),
    });
    const body = (await response.json().catch(() => ({}))) as { token?: string; error?: { message_he?: string } };
    if (!response.ok || !body.token) {
      setError(body.error?.message_he || 'יצירת הקישור נכשלה');
      return;
    }
    // The token travels in the fragment, so it is not sent to the server or logged.
    setCreated(`${window.location.origin}/d/${encodeURIComponent(slug)}#k=${body.token}`);
    await load();
  }

  async function revoke(linkId: number) {
    await fetch(`/api/dashboards/${dashboardId}/share-links/${linkId}`, { method: 'DELETE', headers: headers() });
    await load();
  }

  return (
    <Card title="קישורי שיתוף">
      <p className="mt-3 text-sm text-stone-600">קישור נותן צפייה בלבד, בלי התחברות. הקישור מוצג פעם אחת בלבד.</p>
      {created ? <p dir="ltr" className="mt-3 break-all rounded bg-stone-100 p-2 text-sm">{created}</p> : null}
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
      <ul className="mt-3 text-sm">
        {links.map((link) => (
          <li key={link.id} className="flex gap-3">
            <span>{link.label || `קישור ${link.id}`}</span>
            <span className="text-stone-500">{link.revoked_at ? 'בוטל' : `פעיל · ${link.use_count} כניסות`}</span>
            {!link.revoked_at ? <button type="button" className="text-stone-600 underline" onClick={() => { void revoke(link.id); }}>בטל</button> : null}
          </li>
        ))}
      </ul>
      <button type="button" className="mt-3 rounded border border-stone-300 px-3 py-1 text-sm" onClick={() => { void create(); }}>
        צור קישור חדש
      </button>
    </Card>
  );
}
