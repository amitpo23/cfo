import { useEffect, useState, type ReactNode } from 'react';
import { EmptyState } from './dashboardUi';

// The Eliav tool's tabs inside /d/: liquidity and obligations, forecast,
// budget parameters and share links. Unknown amounts are shown as "לא ידוע".

export type Debt = { label: string; amount: number | null; as_of?: string | null; entity?: string | null; note?: string | null };
export type Upcoming = {
  date: string; label: string | null; amount: number | null; kind: string; note?: string | null; entity?: string | null;
  amount_basis?: string | null; amount_as_of?: string | null; reference_amount?: number | null;
};
export type EntityPosition = {
  entity: string | null; balance: number | null; as_of: string | null; balance_source?: string | null;
  limit: number | null; limit_source?: string | null; available_to_limit: number | null;
};
export type CardRow = {
  name: string; balance: number | null; credit_limit?: number | null; available?: number | null;
  as_of: string | null; entity?: string | null;
};
export type CardSummary = {
  available: number | null; available_known: number | null; credit_limit: number | null; credit_limit_known: number | null;
};
export type DebtService = { month: string; principal: number; interest: number; new_loans: number };

export type EntityLiquidity = {
  status?: string;
  position?: {
    balance: number | null;
    as_of: string | null;
    balance_source?: string | null;
    limit: number | null;
    limit_source: string | null;
    available_to_limit: number | null;
  };
  accounts?: { name: string; kind: string; balance: number | null; credit_limit: number | null; as_of: string | null; balance_source?: string | null }[];
  cards?: CardRow[];
  card_summary?: CardSummary;
  loans?: { name: string; balance: number | null; as_of: string | null; maturity?: string | null }[];
  months?: { month: string; days: number; min: number | null; negative_days: number; beyond_limit_days: number | null; last: number | null }[];
  checks?: { check: string; date: string; amount: number; payee: string | null; state: string; cleared_on?: string }[];
  // combined only
  balance?: number | null;
  balance_known?: number | null;
  balance_note?: string | null;
  as_of?: string | null;
  limit?: number | null;
  limit_known?: number | null;
  available_to_limit?: number | null;
  entities?: EntityPosition[];
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
    <section className="d-card">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Th({ children }: { children?: ReactNode }) {
  return <th>{children}</th>;
}

const CHECK_STATES: Record<string, string> = {
  cleared: 'נפרע',
  future: 'עתידי',
  not_found: 'לא נמצא בבנק',
  no_coverage: 'אין נתוני בנק',
};

const BALANCE_SOURCES: Record<string, string> = {
  accounts: 'יתרת חשבון',
  imported_running_balance: 'יתרה רצה בדף הבנק המיובא',
  mixed: 'יתרת חשבון ודף בנק מיובא',
  opening_balance: 'יתרת פתיחה ידנית ותנועות הבנק שאחריה',
};

// The amount column of an upcoming date: the documented amount, else what the
// evidence shows about it (a loan's balance, a facility's limit).
export function upcomingAmount(item: Upcoming): string {
  if (item.amount !== null && item.amount !== undefined) return money(item.amount);
  if (item.reference_amount !== null && item.reference_amount !== undefined) return `מסגרת ${money(item.reference_amount)}`;
  return 'לא ידוע';
}

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
  const asOf = combined ? section.as_of : section.position?.as_of;
  const balanceSource = combined ? null : section.position?.balance_source;
  const limit = combined ? (section.limit ?? section.limit_known) : section.position?.limit;
  const available = combined ? section.available_to_limit : section.position?.available_to_limit;
  const partial = combined && (balance === null || balance === undefined) && section.balance_known !== null && section.balance_known !== undefined;
  return (
    <div className="grid gap-6">
      <Card title="נזילות">
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-sm text-stone-500">יתרת עו״ש</dt>
            <dd className="text-xl">{partial ? `${money(section.balance_known)} (חלקי)` : money(balance)}</dd>
            {asOf && !partial ? <dd className="text-xs text-stone-500">נכון ל־{asOf}</dd> : null}
            {balanceSource && balanceSource !== 'accounts' ? <dd className="text-xs text-stone-500">{BALANCE_SOURCES[balanceSource] ?? balanceSource}</dd> : null}
          </div>
          <div>
            <dt className="text-sm text-stone-500">מסגרת אשראי</dt>
            <dd className="text-xl">{combined && section.limit === null && section.limit_known !== null && section.limit_known !== undefined ? `${money(section.limit_known)} (חלקי)` : money(limit)}</dd>
          </div>
          <div>
            <dt className="text-sm text-stone-500">פנוי עד המסגרת</dt>
            <dd className={`text-xl ${(available ?? 0) < 0 ? 'text-red-700' : ''}`}>
              {money(available)}
            </dd>
          </div>
        </dl>
        {combined && (section.entities ?? []).length > 0 ? (
          <table className="mt-4 d-table">
            <thead><tr><Th>ישות</Th><Th>יתרת עו״ש</Th><Th>נכון ל</Th><Th>מסגרת</Th><Th>פנוי עד המסגרת</Th></tr></thead>
            <tbody>
              {(section.entities ?? []).map((entity, index) => (
                <tr key={`${entity.entity}-${index}`}>
                  <td>{entity.entity}</td>
                  <td>
                    {money(entity.balance)}
                    {entity.balance_source && entity.balance_source !== 'accounts' ? (
                      <div className="text-xs text-stone-500">{BALANCE_SOURCES[entity.balance_source] ?? entity.balance_source}</div>
                    ) : null}
                  </td>
                  <td>{entity.as_of ?? '—'}</td>
                  <td>{money(entity.limit)}</td>
                  <td>{money(entity.available_to_limit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {section.balance_note ? <p className="mt-3 text-sm text-amber-800">{section.balance_note}</p> : null}
        {section.months && section.months.length > 0 ? (
          <table className="mt-4 d-table">
            <thead><tr><Th>חודש</Th><Th>ימים</Th><Th>שפל</Th><Th>ימי מינוס</Th><Th>ימים מעבר למסגרת</Th><Th>סוף חודש</Th></tr></thead>
            <tbody>
              {section.months.map((month) => (
                <tr key={month.month}>
                  <td>{month.month}</td>
                  <td>{month.days}</td>
                  <td>{money(month.min)}</td>
                  <td>{month.negative_days}</td>
                  <td>{month.beyond_limit_days ?? 'לא ידוע'}</td>
                  <td>{money(month.last)}</td>
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
          <table className="mt-4 d-table">
            <thead><tr><Th>התחייבות</Th>{combined ? <Th>ישות</Th> : null}<Th>סכום</Th><Th>נכון ל</Th></tr></thead>
            <tbody>
              {(section.debts ?? []).map((debt, index) => (
                <tr key={`${debt.label}-${index}`}>
                  <td>{debt.label}{debt.note ? <span className="mr-2 text-xs text-stone-500">{debt.note}</span> : null}</td>
                  {combined ? <td>{debt.entity}</td> : null}
                  <td>{money(debt.amount)}</td>
                  <td>{debt.as_of ?? '—'}</td>
                </tr>
              ))}
              <tr className="font-medium">
                <td>סה״כ ידוע</td>
                {combined ? <td /> : null}
                <td>{money(section.debts_known_total)}</td>
                <td className="py-2 text-xs text-stone-500">{section.debts_complete ? '' : 'חלק מהסכומים לא ידועים'}</td>
              </tr>
            </tbody>
          </table>
        )}
        {(section.debt_service ?? []).some((row) => row.principal || row.interest || row.new_loans) ? (
          <table className="mt-4 d-table">
            <thead><tr><Th>חודש</Th><Th>החזרי קרן</Th><Th>ריבית</Th><Th>הלוואות חדשות</Th></tr></thead>
            <tbody>
              {(section.debt_service ?? []).map((row) => (
                <tr key={row.month}>
                  <td>{row.month}</td>
                  <td>{money(row.principal)}</td>
                  <td>{money(row.interest)}</td>
                  <td>{money(row.new_loans)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Card>
      {(section.cards ?? []).length > 0 ? (
        <Card title="כרטיסי אשראי">
          <div className="mt-4 overflow-x-auto">
          <table className="d-table">
            <thead><tr><Th>כרטיס</Th>{combined ? <Th>ישות</Th> : null}<Th>חיוב אחרון</Th><Th>מסגרת</Th><Th>פנוי</Th><Th>נכון ל</Th></tr></thead>
            <tbody>
              {(section.cards ?? []).map((card, index) => (
                <tr key={`${card.entity ?? ''}-${card.name}-${index}`}>
                  <td>{card.name}</td>
                  {combined ? <td>{card.entity}</td> : null}
                  <td>{money(card.balance)}</td>
                  <td>{money(card.credit_limit ?? null)}</td>
                  <td>{money(card.available ?? null)}</td>
                  <td>{card.as_of ?? '—'}</td>
                </tr>
              ))}
              {section.card_summary ? (
                <tr className="font-medium">
                  <td>{section.card_summary.available === null ? 'סה״כ ידוע' : 'סה״כ'}</td>
                  {combined ? <td /> : null}
                  <td />
                  <td>{money(section.card_summary.credit_limit ?? section.card_summary.credit_limit_known)}</td>
                  <td>{money(section.card_summary.available ?? section.card_summary.available_known)}</td>
                  <td className="py-2 text-xs text-stone-500">
                    {section.card_summary.available === null ? 'לחלק מהכרטיסים הבנק לא מסר כמה פנוי' : ''}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          </div>
        </Card>
      ) : null}
      <Card title="מועדים קרובים">
        {(section.upcoming ?? []).length === 0 ? <p className="mt-3 text-stone-600">אין מועדים ידועים.</p> : (
          <table className="mt-4 d-table">
            <thead><tr><Th>תאריך</Th><Th>מה</Th>{combined ? <Th>ישות</Th> : null}<Th>סכום</Th></tr></thead>
            <tbody>
              {(section.upcoming ?? []).map((item, index) => (
                <tr key={`${item.date}-${index}`}>
                  <td>{item.date}</td>
                  <td>{item.label}{item.note ? <span className="mr-2 text-xs text-stone-500">{item.note}</span> : null}</td>
                  {combined ? <td>{item.entity}</td> : null}
                  <td>{upcomingAmount(item)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section.checks && section.checks.length > 0 ? (
          <>
            <h3 className="mt-4 font-medium">צ׳קים דחויים</h3>
            <table className="mt-2 w-full text-sm">
              <thead><tr><Th>צ׳ק</Th><Th>תאריך</Th><Th>מוטב</Th><Th>סכום</Th><Th>מצב</Th></tr></thead>
              <tbody>
                {section.checks.map((check) => (
                  <tr key={`${check.check}-${check.date}`}>
                    <td>{check.check}</td>
                    <td>{check.date}</td>
                    <td>{check.payee}</td>
                    <td>{money(check.amount)}</td>
                    <td>{CHECK_STATES[check.state] ?? check.state}{check.cleared_on ? ` · ${check.cleared_on}` : ''}</td>
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
    return (
      <EmptyState title="אין נתונים לתחזית">
        התחזית נבנית מתקציב שהוזן או משלושה חודשים מלאים עם ספרים או תנועות בנק.
      </EmptyState>
    );
  }
  return (
    <Card title="תחזית">
      <div className="mt-4 overflow-x-auto">
        <table className="d-table">
          <thead>
            <tr><Th>סעיף</Th>{forecast.months.map((month) => <Th key={month}>{month}</Th>)}</tr>
          </thead>
          <tbody>
            {forecast.rows.map((row) => (
              <tr key={row.id}>
                <td>{row.label}</td>
                {forecast.months.map((month) => {
                  const cell = row.months[month];
                  return (
                    <td key={month}>
                      {money(cell?.value)}
                      {cell?.source ? <div className="text-xs text-stone-500">{SOURCE_LABELS[cell.source] ?? cell.source}</div> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
            {(['result', 'cash_flow', 'cumulative_cash', 'projected_balance'] as const).map((key) => (
              <tr key={key} className="border-b border-stone-100 font-medium">
                <td>{{ result: 'תוצאה', cash_flow: 'תזרים (קירוב)', cumulative_cash: 'תזרים מצטבר', projected_balance: 'יתרה צפויה' }[key]}</td>
                {forecast.months.map((month) => <td key={month}>{money(forecast.totals[month]?.[key])}</td>)}
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

export type OpeningBalance = {
  organizationId: number; accountId?: number | null; date: string; amount: number; source: string; note?: string | null;
};

// The opening balances of plan.liquidityEvidence (the tool's openingBalance).
export function openingBalancesFromPayload(payload: Record<string, unknown> | null | undefined): OpeningBalance[] {
  const evidence = payload?.liquidityEvidence;
  const items = evidence && typeof evidence === 'object' ? (evidence as Record<string, unknown>).openingBalances : null;
  return Array.isArray(items) ? items.filter((item): item is OpeningBalance => !!item && typeof item === 'object') : [];
}

// The payload with one entity's opening balance replaced (null removes it).
export function withOpeningBalance(
  payload: Record<string, unknown>, organizationId: number, item: OpeningBalance | null,
): Record<string, unknown> {
  const evidence = payload.liquidityEvidence && typeof payload.liquidityEvidence === 'object'
    ? payload.liquidityEvidence as Record<string, unknown> : {};
  const others = openingBalancesFromPayload(payload).filter((row) => row.organizationId !== organizationId || row.accountId);
  return { ...payload, liquidityEvidence: { ...evidence, openingBalances: item ? [...others, item] : others } };
}

// A dated opening balance for an imported bank account whose file has no
// balance column: the closing balance of one day from a bank statement. The
// balance is that amount plus the BOOKED rows after the day. Owner only.
export function OpeningBalanceCard({
  entities, items, saving, onSave,
}: {
  entities: { organization_id: number; label: string | null }[];
  items: OpeningBalance[];
  saving: boolean;
  onSave: (organizationId: number, item: OpeningBalance | null) => void;
}) {
  const [orgId, setOrgId] = useState<number | null>(entities[entities.length - 1]?.organization_id ?? null);
  const current = items.find((item) => item.organizationId === orgId && !item.accountId) ?? null;
  const [date, setDate] = useState(current?.date ?? '');
  const [amount, setAmount] = useState(current ? String(current.amount) : '');
  const [source, setSource] = useState(current?.source ?? '');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDate(current?.date ?? '');
    setAmount(current ? String(current.amount) : '');
    setSource(current?.source ?? '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, items]);

  function save() {
    if (orgId === null) return;
    const value = Number(amount.replace(/,/g, ''));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !amount.trim() || !Number.isFinite(value) || !source.trim()) {
      setError('יש למלא תאריך, סכום (אפשר שלילי) ומקור — למשל "דף בנק ליום …"');
      return;
    }
    setError(null);
    onSave(orgId, { organizationId: orgId, date, amount: value, source: source.trim() });
  }

  return (
    <Card title="יתרת פתיחה ידנית">
      <p className="mt-2 text-sm text-stone-600">
        לחשבון בנק שיובא מקובץ בלי עמודת יתרה. מזינים את יתרת סוף היום מדף בנק, והיתרה מחושבת כיתרה הזו ועוד תנועות הבנק שאחרי התאריך. רק בעלי הדשבורד יכולים לשנות אותה.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
        <label className="text-stone-600">
          ישות
          <select className="mt-1 block rounded border border-stone-300 px-2 py-1" value={orgId ?? ''}
            onChange={(event) => setOrgId(Number(event.target.value))}>
            {entities.map((entity) => (
              <option key={entity.organization_id} value={entity.organization_id}>{entity.label ?? entity.organization_id}</option>
            ))}
          </select>
        </label>
        <label className="text-stone-600">
          יתרת סוף יום בתאריך
          <input type="date" dir="ltr" className="mt-1 block rounded border border-stone-300 px-2 py-1" value={date}
            onChange={(event) => setDate(event.target.value)} />
        </label>
        <label className="text-stone-600">
          סכום (₪)
          <input dir="ltr" inputMode="decimal" className="mt-1 block w-32 rounded border border-stone-300 px-2 py-1 text-left"
            value={amount} onChange={(event) => setAmount(event.target.value)} />
        </label>
        <label className="text-stone-600">
          מקור
          <input className="mt-1 block w-56 rounded border border-stone-300 px-2 py-1" value={source}
            placeholder="דף בנק 1662 ליום …" onChange={(event) => setSource(event.target.value)} />
        </label>
        <button type="button" className="rounded bg-stone-900 px-3 py-1 text-white disabled:opacity-50" disabled={saving} onClick={save}>
          שמור יתרת פתיחה
        </button>
        {current ? (
          <button type="button" className="rounded border border-stone-300 px-3 py-1 disabled:opacity-50" disabled={saving}
            onClick={() => orgId !== null && onSave(orgId, null)}>
            הסר
          </button>
        ) : null}
      </div>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
    </Card>
  );
}

export type EvidenceKind = 'facilities' | 'loans' | 'checks' | 'events';
export type EvidenceItem = Record<string, unknown>;
type EvidenceField = { key: string; label: string; type: 'text' | 'amount' | 'date'; required?: boolean; negative?: boolean; positive?: boolean };

const COMMON_FIELDS: EvidenceField[] = [
  { key: 'source', label: 'מקור', type: 'text' },
  { key: 'note', label: 'הערה', type: 'text' },
];

// The kinds of plan.liquidityEvidence the form edits, with the fields the server checks.
export const EVIDENCE_KINDS: { kind: EvidenceKind; label: string; title: string; fields: EvidenceField[] }[] = [
  { kind: 'facilities', label: 'מסגרות', title: 'label', fields: [
    { key: 'label', label: 'שם', type: 'text', required: true },
    { key: 'limit', label: 'מסגרת (₪)', type: 'amount' },
    { key: 'validFrom', label: 'בתוקף מ-', type: 'date' },
    { key: 'validTo', label: 'בתוקף עד', type: 'date' },
  ] },
  { kind: 'loans', label: 'הלוואות', title: 'label', fields: [
    { key: 'label', label: 'שם', type: 'text', required: true },
    { key: 'balance', label: 'יתרה (₪)', type: 'amount' },
    { key: 'asOf', label: 'נכון ל-', type: 'date' },
    { key: 'maturity', label: 'סיום', type: 'date' },
  ] },
  { kind: 'checks', label: 'צ׳קים דחויים', title: 'check', fields: [
    { key: 'check', label: 'מספר צ׳ק', type: 'text', required: true },
    { key: 'date', label: 'תאריך פירעון', type: 'date', required: true },
    { key: 'amount', label: 'סכום (₪)', type: 'amount', required: true, positive: true },
    { key: 'payee', label: 'לפקודת', type: 'text' },
  ] },
  { kind: 'events', label: 'מועדים', title: 'label', fields: [
    { key: 'label', label: 'אירוע', type: 'text', required: true },
    { key: 'date', label: 'תאריך', type: 'date', required: true },
    { key: 'amount', label: 'סכום (₪, אפשר שלילי)', type: 'amount', negative: true },
    { key: 'kind', label: 'סוג', type: 'text' },
  ] },
];

export function evidenceItems(payload: Record<string, unknown> | null | undefined, kind: EvidenceKind): EvidenceItem[] {
  const evidence = payload?.liquidityEvidence;
  const items = evidence && typeof evidence === 'object' ? (evidence as Record<string, unknown>)[kind] : null;
  return Array.isArray(items) ? items.filter((item): item is EvidenceItem => !!item && typeof item === 'object') : [];
}

// The payload with one evidence item added (index null), replaced, or removed (item null).
// Every other key of the plan and of liquidityEvidence (openingBalances, observedAt, ...) is kept.
export function withEvidenceItem(
  payload: Record<string, unknown>, kind: EvidenceKind, index: number | null, item: EvidenceItem | null,
): Record<string, unknown> {
  const evidence = payload.liquidityEvidence && typeof payload.liquidityEvidence === 'object'
    ? payload.liquidityEvidence as Record<string, unknown> : {};
  const items = [...evidenceItems(payload, kind)];
  if (index === null) {
    if (item) items.push(item);
  } else if (item) {
    items[index] = item;
  } else {
    items.splice(index, 1);
  }
  return { ...payload, liquidityEvidence: { ...evidence, [kind]: items } };
}

export type EvidenceDraft = Record<string, string>;

export function draftFromItem(kind: EvidenceKind, item: EvidenceItem | null): EvidenceDraft {
  const spec = EVIDENCE_KINDS.find((entry) => entry.kind === kind)!;
  const draft: EvidenceDraft = { organizationId: item && typeof item.organizationId === 'number' ? String(item.organizationId) : '' };
  [...spec.fields, ...COMMON_FIELDS].forEach((field) => {
    const value = item?.[field.key];
    draft[field.key] = value === null || value === undefined ? '' : String(value);
  });
  return draft;
}

// The item the server accepts, or the first error in Hebrew. An empty amount is null
// (unknown), never 0. Fields the form does not edit are kept from the original item.
export function itemFromDraft(kind: EvidenceKind, draft: EvidenceDraft, original: EvidenceItem | null): { item: EvidenceItem } | { error: string } {
  const spec = EVIDENCE_KINDS.find((entry) => entry.kind === kind)!;
  const item: EvidenceItem = { ...(original ?? {}) };
  const org = draft.organizationId?.trim();
  if (org) item.organizationId = Number(org);
  else delete item.organizationId;
  for (const field of [...spec.fields, ...COMMON_FIELDS]) {
    const raw = (draft[field.key] ?? '').trim();
    if (!raw) {
      if (field.required) return { error: `חסר ${field.label}` };
      item[field.key] = null;
      continue;
    }
    if (field.type === 'amount') {
      const value = Number(raw.replace(/,/g, ''));
      if (!Number.isFinite(value) || (!field.negative && value < 0) || (field.positive && value <= 0)) {
        return { error: `${field.label}: סכום לא תקין` };
      }
      item[field.key] = value;
    } else if (field.type === 'date') {
      if (!/^20\d{2}-\d{2}-\d{2}$/.test(raw)) return { error: `${field.label}: תאריך לא תקין` };
      item[field.key] = raw;
    } else {
      item[field.key] = raw;
    }
  }
  return { item };
}

function evidenceCell(field: EvidenceField, value: unknown): string {
  if (value === null || value === undefined || value === '') return field.type === 'amount' ? 'לא ידוע' : '—';
  return field.type === 'amount' && typeof value === 'number' ? money(value) : String(value);
}

// Credit facilities, loans, post-dated checks and events of plan.liquidityEvidence:
// add, edit and delete. Owner only (the server refuses other roles).
export function LiquidityEvidenceCard({
  entities, payload, saving, onSave,
}: {
  entities: { organization_id: number; label: string | null }[];
  payload: Record<string, unknown>;
  saving: boolean;
  onSave: (next: Record<string, unknown>) => void;
}) {
  const [kind, setKind] = useState<EvidenceKind>('facilities');
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<EvidenceDraft>(() => draftFromItem('facilities', null));
  const [error, setError] = useState<string | null>(null);
  const spec = EVIDENCE_KINDS.find((entry) => entry.kind === kind)!;
  const items = evidenceItems(payload, kind);
  const entityLabel = (id: unknown) => entities.find((entity) => entity.organization_id === id)?.label ?? (id ? String(id) : '—');

  function open(nextKind: EvidenceKind, index: number | null) {
    setKind(nextKind);
    setEditing(index);
    setDraft(draftFromItem(nextKind, index === null ? null : evidenceItems(payload, nextKind)[index] ?? null));
    setError(null);
  }

  function save() {
    const built = itemFromDraft(kind, draft, editing === null ? null : items[editing] ?? null);
    if ('error' in built) {
      setError(built.error);
      return;
    }
    setError(null);
    onSave(withEvidenceItem(payload, kind, editing, built.item));
    open(kind, null);
  }

  return (
    <Card title="ראיות נזילות">
      <p className="mt-2 text-sm text-stone-600">
        מסגרות, הלוואות, צ׳קים דחויים ומועדים שאינם מגיעים מהבנק. סכום שלא ידוע נשאר ריק ומוצג כ"לא ידוע". רק בעלי הדשבורד יכולים לשנות.
      </p>
      <div className="mt-3 flex flex-wrap gap-2 text-sm" role="tablist">
        {EVIDENCE_KINDS.map((entry) => (
          <button key={entry.kind} type="button" role="tab" aria-selected={kind === entry.kind}
            className={`rounded-full border px-3 py-1 ${kind === entry.kind ? 'border-stone-900 bg-stone-900 text-white' : 'border-stone-300'}`}
            onClick={() => open(entry.kind, null)}>
            {entry.label} ({evidenceItems(payload, entry.kind).length})
          </button>
        ))}
      </div>
      {items.length > 0 ? (
        <table className="mt-3 d-table">
          <thead>
            <tr>
              <Th>ישות</Th>
              {spec.fields.map((field) => <Th key={field.key}>{field.label}</Th>)}
              <Th>מקור</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={`${kind}-${index}`} className={`border-b border-stone-100 ${editing === index ? 'bg-amber-50' : ''}`}>
                <td>{entityLabel(item.organizationId)}</td>
                {spec.fields.map((field) => <td key={field.key} className="py-1">{evidenceCell(field, item[field.key])}</td>)}
                <td className="py-1 text-xs text-stone-500">{typeof item.source === 'string' ? item.source : '—'}</td>
                <td className="py-1 whitespace-nowrap">
                  <button type="button" className="text-stone-700 underline disabled:opacity-50" disabled={saving}
                    onClick={() => open(kind, index)}>ערוך</button>
                  {' · '}
                  <button type="button" className="text-red-700 underline disabled:opacity-50" disabled={saving}
                    onClick={() => onSave(withEvidenceItem(payload, kind, index, null))}>מחק</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="mt-3 text-sm text-stone-500">אין פריטים מסוג זה.</p>}
      <div className="mt-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="text-stone-600">
          ישות
          <select className="mt-1 block rounded border border-stone-300 px-2 py-1" value={draft.organizationId}
            onChange={(event) => setDraft({ ...draft, organizationId: event.target.value })}>
            <option value="">ללא ישות</option>
            {entities.map((entity) => (
              <option key={entity.organization_id} value={entity.organization_id}>{entity.label ?? entity.organization_id}</option>
            ))}
          </select>
        </label>
        {[...spec.fields, ...COMMON_FIELDS].map((field) => (
          <label key={field.key} className="text-stone-600">
            {field.label}{field.required ? ' *' : ''}
            <input
              type={field.type === 'date' ? 'date' : 'text'}
              dir={field.type === 'text' ? undefined : 'ltr'}
              inputMode={field.type === 'amount' ? 'decimal' : undefined}
              className="mt-1 block w-36 rounded border border-stone-300 px-2 py-1"
              value={draft[field.key] ?? ''}
              onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })}
            />
          </label>
        ))}
        <button type="button" className="rounded bg-stone-900 px-3 py-1 text-white disabled:opacity-50" disabled={saving} onClick={save}>
          {editing === null ? 'הוסף' : 'שמור שינוי'}
        </button>
        {editing !== null ? (
          <button type="button" className="rounded border border-stone-300 px-3 py-1" onClick={() => open(kind, null)}>ביטול</button>
        ) : null}
      </div>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
    </Card>
  );
}

export type ZReport = {
  organizationId: number; month: string; revenueExVat: number; totalInclVat?: number | null;
  cashNet?: number | null; cardNet?: number | null; source: string; note?: string | null;
};

export function zReportsFromPayload(payload: Record<string, unknown> | null | undefined): ZReport[] {
  const items = payload?.zReports;
  return Array.isArray(items) ? items.filter((item): item is ZReport => !!item && typeof item === 'object') : [];
}

// The payload with one organization-month Z report replaced or added (null removes it).
// Every other plan key is kept.
export function withZReport(
  payload: Record<string, unknown>, organizationId: number, month: string, item: ZReport | null,
): Record<string, unknown> {
  const others = zReportsFromPayload(payload).filter((row) => row.organizationId !== organizationId || row.month !== month);
  const next = item ? [...others, item] : others;
  next.sort((a, b) => a.organizationId - b.organizationId || a.month.localeCompare(b.month));
  return { ...payload, zReports: next };
}

// Pizza revenue from a reviewed Z report, per entity and month. Owner only. In the
// cash-basis P&L the Z total replaces the bank's card settlements and cash deposits.
export function ZReportsCard({
  entities, items, saving, onSave,
}: {
  entities: { organization_id: number; label: string | null }[];
  items: ZReport[];
  saving: boolean;
  onSave: (organizationId: number, month: string, item: ZReport | null) => void;
}) {
  const [orgId, setOrgId] = useState<number | null>(entities[entities.length - 1]?.organization_id ?? null);
  const [month, setMonth] = useState('');
  const [revenue, setRevenue] = useState('');
  const [total, setTotal] = useState('');
  const [source, setSource] = useState('');
  const [error, setError] = useState<string | null>(null);
  const label = (id: number) => entities.find((entity) => entity.organization_id === id)?.label ?? String(id);

  function edit(item: ZReport) {
    setOrgId(item.organizationId);
    setMonth(item.month);
    setRevenue(String(item.revenueExVat));
    setTotal(item.totalInclVat === null || item.totalInclVat === undefined ? '' : String(item.totalInclVat));
    setSource(item.source);
  }

  function save() {
    if (orgId === null) return;
    const value = Number(revenue.replace(/,/g, ''));
    const gross = total.trim() ? Number(total.replace(/,/g, '')) : null;
    if (!/^20\d{2}-(0[1-9]|1[0-2])$/.test(month) || !revenue.trim() || !Number.isFinite(value) || value < 0
      || (gross !== null && (!Number.isFinite(gross) || gross < 0)) || !source.trim()) {
      setError('יש למלא חודש, הכנסה ללא מע״מ (לא שלילית) ומקור — למשל "דוח Z חודשי של הקופה"');
      return;
    }
    setError(null);
    const original = items.find((item) => item.organizationId === orgId && item.month === month);
    onSave(orgId, month, { ...(original ?? {}), organizationId: orgId, month, revenueExVat: value, totalInclVat: gross, source: source.trim() });
  }

  return (
    <Card title="הכנסות פיצה מדוחות Z">
      <p className="mt-2 text-sm text-stone-600">
        סכום חודשי מדוח Z מאומת של הקופה. בחודש שיש לו דוח Z, ההכנסה ברווח והפסד היא סכום ה-Z, וסליקת האשראי והפקדות המזומן בבנק לא נספרות שוב. רק בעלי הדשבורד יכולים לשנות.
      </p>
      {items.length > 0 ? (
        <table className="mt-3 d-table">
          <thead>
            <tr>
              <Th>ישות</Th><Th>חודש</Th><Th>ללא מע״מ</Th><Th>כולל מע״מ</Th><Th>מקור</Th><Th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.organizationId}-${item.month}`}>
                <td>{label(item.organizationId)}</td>
                <td>{item.month}</td>
                <td>{money(item.revenueExVat)}</td>
                <td>{money(item.totalInclVat ?? null)}</td>
                <td className="py-1 text-xs text-stone-500">{item.source}</td>
                <td className="py-1 whitespace-nowrap">
                  <button type="button" className="underline" onClick={() => edit(item)}>ערוך</button>
                  {' · '}
                  <button type="button" className="text-red-700 underline disabled:opacity-50" disabled={saving}
                    onClick={() => onSave(item.organizationId, item.month, null)}>מחק</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="mt-3 text-sm text-stone-500">לא הוזנו דוחות Z.</p>}
      <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
        <label className="text-stone-600">
          ישות
          <select className="mt-1 block rounded border border-stone-300 px-2 py-1" value={orgId ?? ''}
            onChange={(event) => setOrgId(Number(event.target.value))}>
            {entities.map((entity) => (
              <option key={entity.organization_id} value={entity.organization_id}>{entity.label ?? entity.organization_id}</option>
            ))}
          </select>
        </label>
        <label className="text-stone-600">
          חודש
          <input type="month" dir="ltr" className="mt-1 block rounded border border-stone-300 px-2 py-1" value={month}
            onChange={(event) => setMonth(event.target.value)} />
        </label>
        <label className="text-stone-600">
          הכנסה ללא מע״מ (₪)
          <input dir="ltr" inputMode="decimal" className="mt-1 block w-32 rounded border border-stone-300 px-2 py-1"
            value={revenue} onChange={(event) => setRevenue(event.target.value)} />
        </label>
        <label className="text-stone-600">
          כולל מע״מ (₪, רשות)
          <input dir="ltr" inputMode="decimal" className="mt-1 block w-32 rounded border border-stone-300 px-2 py-1"
            value={total} onChange={(event) => setTotal(event.target.value)} />
        </label>
        <label className="text-stone-600">
          מקור
          <input className="mt-1 block w-56 rounded border border-stone-300 px-2 py-1" value={source}
            placeholder="דוח Z חודשי של הקופה" onChange={(event) => setSource(event.target.value)} />
        </label>
        <button type="button" className="rounded bg-stone-900 px-3 py-1 text-white disabled:opacity-50" disabled={saving} onClick={save}>
          שמור דוח Z
        </button>
      </div>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
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
