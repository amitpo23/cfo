// The "תזרים חזוי" tab of /d/: thirteen weeks from cashflow_source.forecast.
// Every number is from that one engine. A missing amount is "חסר נכון ל-<תאריך>".
import { Fragment, useEffect, useState } from 'react';
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { EmptyState, KpiCards, missingAsOf, type Kpi } from './dashboardUi';
import { money } from './dashboardTabs';

export type Certainty = 'certain' | 'scheduled' | 'manual' | 'estimate';

export type ForecastItem = {
  date: string | null;
  label: string | null;
  amount: number;
  certainty: Certainty;
  source?: string;
  upper_bound?: boolean;
  note?: string | null;
  entity?: string | null;
};

export type ForecastWeek = {
  start: string;
  end: string;
  in: number | null;
  out: number | null;
  net: number | null;
  closing: number | null;
  limit: number | null;
  headroom: number | null;
  items: ForecastItem[];
};

export type Overdue = { date: string; label: string | null; amount: number; kind: string; note: string; entity?: string | null };

export type CashForecast = {
  label?: string | null;
  status?: string;
  opening?: { amount: number | null; as_of: string | null } | number | null;
  weeks: ForecastWeek[];
  first_breach: { week_start: string; week_end: string; headroom: number; reasons: string[] } | null;
  overdue?: Overdue[];
  discounted_cheque_balances?: { check?: string | null; amount: number; closes_on: string; outstanding: boolean }[];
  missing: string[];
  funding_need?: { amount: number | null; label?: string; sum_of_negative_weeks?: number | null };
  shared_identity_note?: string | null;
  run_rate?: Record<string, number>;
};

export type CashForecastItem = { organizationId: number | null; date: string; amount: number; label: string };

const CERTAINTY: Record<Certainty, string> = {
  certain: 'ודאי',
  scheduled: 'קבוע',
  manual: 'ידני',
  estimate: 'הערכה',
};

const MISSING: Record<string, string> = {
  opening_balance: 'יתרת העו״ש לא ידועה, ולכן גם היתרה החזויה והמרווח. מזינים "יתרת פתיחה ידנית" בלשונית נזילות והתחייבויות.',
  facility_limit: 'גובה המסגרת לא ידוע. מוסיפים מסגרת בראיות הנזילות. חריגה לא מחושבת מול אפס.',
  run_rate: 'אין שלושה חודשים מלאים של תנועות בנק, ולכן אין קצב ריצה.',
  forecast_rules: 'חלק מכללי התזרים חסרים (הכנסה, שכר, ספקים לסוף החודש העוקב או הלוואה קצרה). החסר לא הוזן כ־0, והיתרה שאחריו לא ידועה.',
};

function day(iso: string): string {
  const [, month, dayOfMonth] = iso.split('-');
  return `${dayOfMonth}/${month}`;
}

function weekLabel(week: { start: string; end: string }): string {
  return `${day(week.start)}–${day(week.end)}`;
}

function opening(forecast: CashForecast): { amount: number | null; as_of: string | null } {
  if (forecast.opening && typeof forecast.opening === 'object') return forecast.opening;
  return { amount: typeof forecast.opening === 'number' ? forecast.opening : null, as_of: null };
}

function kpis(forecast: CashForecast): Kpi[] {
  const start = opening(forecast);
  const weeks = forecast.weeks;
  const known = weeks.filter((week) => week.headroom !== null);
  const tightest = known.reduce<ForecastWeek | null>(
    (low, week) => (low === null || (week.headroom ?? 0) < (low.headroom ?? 0) ? week : low), null,
  );
  const net = weeks.every((week) => week.net !== null) ? weeks.reduce((sum, week) => sum + (week.net ?? 0), 0) : null;
  const ceiling = weeks.some((week) => week.items.some((item) => item.upper_bound));
  const breach = forecast.first_breach;
  return [
    { label: 'יתרה היום', value: money(start.amount, start.as_of), note: start.as_of ? `נכון ל־${start.as_of}` : null },
    {
      label: 'פנוי במסגרת השבוע',
      value: money(weeks[0]?.headroom, weeks[0]?.end),
      note: (weeks[0]?.headroom ?? 0) < 0 ? 'חריגה מהמסגרת' : null,
      tone: (weeks[0]?.headroom ?? 0) < 0 ? 'warn' : null,
    },
    {
      label: 'השבוע הקשה',
      value: tightest ? money(tightest.headroom, tightest.end) : missingAsOf(weeks[0]?.end),
      note: tightest ? weekLabel(tightest) : null,
      tone: (tightest?.headroom ?? 0) < 0 ? 'warn' : null,
    },
    {
      label: 'חריגה ראשונה',
      value: breach ? weekLabel({ start: breach.week_start, end: breach.week_end }) : known.length ? 'אין חריגה צפויה' : missingAsOf(weeks[0]?.end),
      note: breach ? money(breach.headroom) : null,
      tone: breach ? 'warn' : null,
    },
    {
      label: 'תזרים 13 שבועות',
      value: money(net, weeks[weeks.length - 1]?.end),
      note: ceiling ? 'כולל סיום הלוואות לפי הסכום המרבי' : null,
    },
  ];
}

function chartRows(forecast: CashForecast) {
  const balanceKnown = forecast.weeks.some((week) => week.closing !== null);
  let cumulative = 0;
  return {
    balanceKnown,
    rows: forecast.weeks.map((week) => {
      cumulative += week.net ?? 0;
      return {
        week: day(week.start),
        value: balanceKnown ? week.closing : Math.round(cumulative),
        floor: week.limit === null ? null : -week.limit,
      };
    }),
  };
}

function ForecastChart({ forecast }: { forecast: CashForecast }) {
  const { balanceKnown, rows } = chartRows(forecast);
  const compact = (value: number) => new Intl.NumberFormat('he-IL', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
  return (
    <section className="d-card">
      <h2>{balanceKnown ? 'יתרה חזויה מול רצפת המסגרת' : 'שינוי מצטבר מהיום (היתרה לא ידועה)'}</h2>
      <p className="mt-1 text-sm text-stone-600">
        {balanceKnown
          ? 'הקו המקווקו הוא המינוס המרבי שהמסגרות מאפשרות. ירידה מתחתיו היא חריגה. כשמסגרת פוקעת, הקו עולה.'
          : 'בלי יתרת פתיחה אפשר לראות רק כמה כסף ייכנס או ייצא מהיום. המרווח במסגרת לא ידוע.'}
      </p>
      <div className="mt-4 h-64" dir="ltr" role="img" aria-label={balanceKnown ? 'גרף יתרה חזויה לפי שבוע' : 'גרף שינוי מצטבר לפי שבוע'}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#e3e8f3" vertical={false} />
            <XAxis dataKey="week" tick={{ fill: '#57534e', fontSize: 12 }} tickLine={false} axisLine={{ stroke: '#c3cde3' }} />
            <YAxis tickFormatter={compact} tick={{ fill: '#57534e', fontSize: 12 }} tickLine={false} axisLine={false} width={56} />
            <Tooltip
              formatter={(value: number, name: string) => [money(value), name === 'floor' ? 'רצפת המסגרת' : balanceKnown ? 'יתרה חזויה' : 'שינוי מצטבר']}
              labelFormatter={(label: string) => `שבוע ${label}`}
            />
            <ReferenceLine y={0} stroke="#8e9fc6" />
            <Area type="monotone" dataKey="value" stroke="#2c3e6b" strokeWidth={2} fill="#e3e8f3" isAnimationActive={false} />
            {balanceKnown ? (
              <Line type="stepAfter" dataKey="floor" stroke="#b91c1c" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function CertaintyTag({ certainty }: { certainty: Certainty }) {
  return <span className="rounded border border-stone-300 px-1.5 text-xs text-stone-600">{CERTAINTY[certainty]}</span>;
}

function WeekItems({ items }: { items: ForecastItem[] }) {
  if (!items.length) return <p className="text-sm text-stone-500">אין תנועות צפויות בשבוע הזה.</p>;
  return (
    <ul className="grid gap-1 text-sm">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span className="w-14 shrink-0 tabular-nums text-stone-500">{item.date ? day(item.date) : 'לאורך השבוע'}</span>
          <span className="min-w-0 flex-1 text-navy-900">
            {item.entity ? <span className="text-stone-500">{item.entity} · </span> : null}
            {item.label}
            {item.upper_bound ? <span className="text-xs text-amber-800"> · סכום מרבי</span> : null}
          </span>
          <span className={`tabular-nums ${item.amount < 0 ? 'text-red-700' : 'text-emerald-800'}`}>{money(item.amount)}</span>
          <CertaintyTag certainty={item.certainty} />
        </li>
      ))}
    </ul>
  );
}

function WeeksTable({ forecast }: { forecast: CashForecast }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section className="d-card">
      <h2>שבוע אחרי שבוע</h2>
      <div className="mt-3 overflow-x-auto">
        <table className="d-table">
          <thead>
            <tr><th>שבוע</th><th>כניסות</th><th>יציאות</th><th>נטו</th><th>יתרת סגירה</th><th>מסגרת</th><th>פנוי</th></tr>
          </thead>
          <tbody>
            {forecast.weeks.map((week) => {
              const expanded = open === week.start;
              const breach = week.headroom !== null && week.headroom < 0;
              return (
                <Fragment key={week.start}>
                  <tr>
                    <td>
                      <button
                        type="button"
                        className="text-navy-700 underline-offset-2 hover:underline"
                        aria-expanded={expanded}
                        onClick={() => setOpen(expanded ? null : week.start)}
                      >
                        {expanded ? '▾' : '◂'} {weekLabel(week)}
                      </button>
                    </td>
                    <td>{money(week.in, week.end)}</td>
                    <td>{money(week.out, week.end)}</td>
                    <td className={(week.net ?? 0) < 0 ? 'text-red-700' : ''}>{money(week.net, week.end)}</td>
                    <td>{money(week.closing, week.end)}</td>
                    <td>{money(week.limit, week.end)}</td>
                    <td className={breach ? 'font-medium text-red-700' : ''}>
                      {money(week.headroom, week.end)}{breach ? ' · חריגה' : ''}
                    </td>
                  </tr>
                  {expanded ? (
                    <tr>
                      <td colSpan={7} className="bg-navy-50/40 px-3 py-3"><WeekItems items={week.items} /></td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-stone-500">
        ברירת המחדל לספקים היא סוף החודש העוקב: ספטמבר נפרע ב־1/11 (31/10 הוא שבת), אוקטובר ב־30/11, נובמבר ב־31/12, דצמבר ב־31/1. בשבוע 25–30/10 הספקים של ספטמבר (30,000−) אינם נכללים; במנוע הקודם הם נפלו ב־30/10. שוטף+30 נשאר חלופה לארגון. שבוע הוא מיום ראשון עד יום שישי. מזומן שחל בשבת נזקף ליום ראשון שאחריו, פעם אחת. ודאי: צ׳ק דחוי או סיום הלוואה מתוארכים. קבוע: החזר קרן חודשי. ידני: פריט שבעלי הדשבורד הזינו. הערכה: ממוצע שלושת החודשים המלאים
        האחרונים בבנק, לפי קבוצה. צ׳ק ידוע נגרע מקצב היציאות של החודש שלו ולא נוסף עליו.
      </p>
    </section>
  );
}

export function CashForecastPanel({ forecast, overdue }: { forecast: CashForecast | null | undefined; overdue: Overdue[] }) {
  if (!forecast || !forecast.weeks?.length) {
    return <EmptyState title="אין תזרים חזוי">אין מספיק נתונים לחשב תחזית לישות הזו.</EmptyState>;
  }
  const missing = forecast.missing.filter((key) => MISSING[key]);
  return (
    <div className="grid gap-6">
      {forecast.funding_need ? (
        <p className="text-sm text-stone-700">
          צורך מימון: {forecast.funding_need.amount == null
            ? (forecast.funding_need.label || 'חסר')
            : money(forecast.funding_need.amount)}
          {forecast.funding_need.sum_of_negative_weeks != null
            ? ` · סכום שבועות שליליים ${money(forecast.funding_need.sum_of_negative_weeks)}`
            : ''}
        </p>
      ) : null}
      {forecast.shared_identity_note ? (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">{forecast.shared_identity_note}</p>
      ) : null}
      {missing.length ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="status">
          <p className="font-medium">חסר כדי לחשב עד הסוף</p>
          <ul className="mt-1 list-disc pr-5">{missing.map((key) => <li key={key}>{MISSING[key]}</li>)}</ul>
        </div>
      ) : null}
      {overdue.length ? (
        <section className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900" aria-label="מועדים שעברו">
          <p className="font-medium">מועדים שעברו, וסטטוס התשלום לא ידוע</p>
          <ul className="mt-1 grid gap-0.5">
            {overdue.map((item, index) => (
              <li key={`${item.date}-${index}`}>
                {day(item.date)} · {item.entity ? `${item.entity} · ` : ''}{item.label} · <span className="tabular-nums">{money(item.amount)}</span>
                <span className="text-red-800"> — {item.note}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {(forecast.discounted_cheque_balances ?? []).length ? (
        <section className="d-card" aria-label="יתרות ניכיון">
          <h2>ניכיון שיקים — יתרת הלוואה עד הפירעון</h2>
          <table className="mt-2 w-full text-sm">
            <thead>
              <tr className="text-right text-stone-500">
                <th className="py-1">שיק</th>
                <th>יתרה</th>
                <th>נסגר ב</th>
                <th>מצב</th>
              </tr>
            </thead>
            <tbody>
              {(forecast.discounted_cheque_balances ?? []).map((row, index) => (
                <tr key={`${row.check ?? index}-${row.closes_on}`} className="border-t border-stone-200">
                  <td className="py-1">{row.check || 'שיק מנוכה'}</td>
                  <td className="tabular-nums">{money(row.amount)}</td>
                  <td>{day(row.closes_on)}</td>
                  <td>{row.outstanding ? 'פתוח' : 'נסגר'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
      <KpiCards items={kpis(forecast)} />
      {forecast.first_breach ? (
        <section className="d-card">
          <h2>למה יש חריגה בשבוע {weekLabel({ start: forecast.first_breach.week_start, end: forecast.first_breach.week_end })}</h2>
          <ul className="mt-2 list-disc pr-5 text-sm text-stone-700">
            {forecast.first_breach.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </section>
      ) : null}
      <ForecastChart forecast={forecast} />
      <WeeksTable forecast={forecast} />
    </div>
  );
}

export function cashForecastItemsFromPayload(payload: Record<string, unknown> | null | undefined): CashForecastItem[] {
  const raw = payload?.cashForecastItems;
  return Array.isArray(raw) ? (raw as CashForecastItem[]) : [];
}

export function CashForecastItemsCard({
  entities, items, saving, onSave,
}: {
  entities: { organization_id: number; label: string | null }[];
  items: CashForecastItem[];
  saving: boolean;
  onSave: (next: CashForecastItem[]) => void;
}) {
  const [orgId, setOrgId] = useState<number | null>(entities[0]?.organization_id ?? null);
  const [date, setDate] = useState('');
  const [amount, setAmount] = useState('');
  const [label, setLabel] = useState('');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setError(null); }, [items]);
  const name = (id: number | null) => entities.find((entity) => entity.organization_id === id)?.label ?? 'ללא ישות';

  function add() {
    const value = Number(amount.replace(/,/g, ''));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(value) || value === 0 || !label.trim()) {
      setError('יש למלא תאריך, סכום שונה מאפס (תשלום במינוס) ותיאור');
      return;
    }
    onSave([...items, { organizationId: orgId, date, amount: value, label: label.trim() }]);
    setDate('');
    setAmount('');
    setLabel('');
  }

  return (
    <section className="d-card">
      <h2>פריטים ידניים בתזרים</h2>
      <p className="mt-2 text-sm text-stone-600">
        התחייבות או תקבול שהבנק עוד לא רואה, למשל חוב לעובדים. פריט כזה נוסף על קצב הריצה. רק בעלי הדשבורד יכולים לשנות.
      </p>
      {items.length ? (
        <ul className="mt-3 grid gap-1 text-sm">
          {items.map((item, index) => (
            <li key={`${item.date}-${index}`} className="flex flex-wrap items-baseline gap-3">
              <span className="tabular-nums text-stone-500">{item.date}</span>
              <span className="text-stone-500">{name(item.organizationId)}</span>
              <span className="flex-1 text-navy-900">{item.label}</span>
              <span className="tabular-nums">{money(item.amount)}</span>
              <button type="button" className="rounded border border-stone-300 px-2 py-0.5 text-xs disabled:opacity-50" disabled={saving}
                onClick={() => onSave(items.filter((_, other) => other !== index))}>
                הסר
              </button>
            </li>
          ))}
        </ul>
      ) : null}
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
          תאריך
          <input type="date" dir="ltr" className="mt-1 block rounded border border-stone-300 px-2 py-1" value={date}
            onChange={(event) => setDate(event.target.value)} />
        </label>
        <label className="text-stone-600">
          סכום (₪, תשלום במינוס)
          <input dir="ltr" inputMode="decimal" className="mt-1 block w-32 rounded border border-stone-300 px-2 py-1 text-left"
            value={amount} onChange={(event) => setAmount(event.target.value)} />
        </label>
        <label className="text-stone-600">
          תיאור
          <input className="mt-1 block w-56 rounded border border-stone-300 px-2 py-1" value={label}
            placeholder="חוב לעובדים" onChange={(event) => setLabel(event.target.value)} />
        </label>
        <button type="button" className="rounded bg-stone-900 px-3 py-1 text-white disabled:opacity-50" disabled={saving} onClick={add}>
          הוסף פריט
        </button>
      </div>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
    </section>
  );
}
