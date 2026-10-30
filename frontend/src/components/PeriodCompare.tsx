import { Fragment, useState } from 'react';
import { missingAsOf } from './dashboardUi';

export type Grain = 'day' | 'week' | 'month' | 'quarter' | 'year';

export type Figure = {
  amount: number | null;
  source?: string | null;
  as_of?: string | null;
  missing_label?: string | null;
};

export type PeriodRow = {
  label: string;
  start: string;
  end: string;
  elapsed?: boolean;
  budget: {
    revenue: Figure;
    costs: Figure;
    net: Figure;
    month_context?: { month: string; revenue: number | null; costs: number | null; net: number | null }[];
    months_filled?: string[];
    months_missing?: string[];
    months_ahead?: string[];
    ahead?: { revenue: Figure; costs: Figure; net: Figure; months?: string[] };
  };
  bank: { in: Figure; out: Figure; net: Figure; count?: number; lines?: { date: string; amount: number | null; description?: string | null; account_id?: number | null }[] };
  books: { revenue: Figure; costs: Figure; net: Figure };
  variance: { books_vs_budget: Figure; bank_vs_budget: Figure };
};

export type PeriodTotals = {
  budget: { revenue: Figure; costs: Figure; net: Figure };
  books: { revenue: Figure; costs: Figure; net: Figure };
  bank: { in: Figure; out: Figure; net: Figure };
  /** Booked movement. Stays known when a profit claim withholds bank.net. */
  cash?: { in: Figure; out: Figure; net: Figure };
};

export type PeriodCompare = {
  grain: Grain;
  start: string;
  end: string;
  as_of?: string;
  note_he?: string;
  periods: PeriodRow[];
  totals?: PeriodTotals;
  profit?: { label: string; books: Figure; bank: Figure; budget: Figure }[];
  organization_id?: number;
  dashboard_slug?: string | null;
  partial_banner?: { text_he?: string | null; bank_as_of?: string | null; books_as_of?: string | null };
  unclassified_outflows?: { count?: number; amount?: number | null; label_he?: string | null; blocks_profit?: boolean };
  profit_claim?: { allowed?: boolean; reason_he?: string | null };
};

export function isoDate(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

export function presetRange(grain: Grain, today = new Date()): { start: string; end: string } {
  if (grain === 'day') {
    const day = isoDate(today);
    return { start: day, end: day };
  }
  if (grain === 'week') {
    const start = new Date(today);
    start.setDate(today.getDate() - today.getDay());
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    return { start: isoDate(start), end: isoDate(end) };
  }
  if (grain === 'quarter') {
    const quarterStart = Math.floor(today.getMonth() / 3) * 3;
    const start = new Date(today.getFullYear(), quarterStart, 1);
    const end = new Date(today.getFullYear(), quarterStart + 3, 0);
    return { start: isoDate(start), end: isoDate(end) };
  }
  if (grain === 'year') {
    return { start: `${today.getFullYear()}-01-01`, end: `${today.getFullYear()}-12-31` };
  }
  const start = new Date(today.getFullYear(), today.getMonth(), 1);
  const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  return { start: isoDate(start), end: isoDate(end) };
}

function text(figure?: Figure): string {
  if (!figure || figure.amount == null) {
    const when = missingAsOf(figure?.as_of);
    const label = figure?.missing_label;
    if (!label) return when;
    if (label.includes('נכון ל-')) return label;
    return `${label} · ${when}`;
  }
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(figure.amount);
}

function stamp(figure?: Figure): string {
  const parts = [figure?.source, figure?.as_of].filter(Boolean);
  return parts.join(' · ');
}

export function PeriodControls({
  grain, start, end, onGrain, onStart, onEnd,
}: {
  grain: Grain;
  start: string;
  end: string;
  onGrain: (grain: Grain) => void;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
}) {
  const choices: { id: Grain; label: string }[] = [
    { id: 'day', label: 'יום' },
    { id: 'week', label: 'שבוע' },
    { id: 'month', label: 'חודש' },
    { id: 'quarter', label: 'רבעון' },
    { id: 'year', label: 'שנה' },
  ];
  return (
    <div className="flex flex-wrap items-end gap-2 text-sm" role="group" aria-label="טווח תאריכים">
      {choices.map((choice) => (
        <button
          key={choice.id}
          type="button"
          aria-pressed={grain === choice.id}
          className={`rounded-md px-3 py-1 ${grain === choice.id ? 'bg-navy-800 text-white' : 'border border-navy-200 bg-white text-navy-800'}`}
          onClick={() => onGrain(choice.id)}
        >
          {choice.label}
        </button>
      ))}
      <label className="text-stone-600">
        מ־
        <input className="ms-1 rounded border border-stone-300 px-2 py-1" type="date" value={start} onChange={(event) => onStart(event.target.value)} />
      </label>
      <label className="text-stone-600">
        עד
        <input className="ms-1 rounded border border-stone-300 px-2 py-1" type="date" value={end} onChange={(event) => onEnd(event.target.value)} />
      </label>
    </div>
  );
}

export function PeriodCompareTable({ report, booksFirst = false }: { report: PeriodCompare | null; booksFirst?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!report) return <p className="text-sm text-stone-500">טוען תקציב, בנק וספרים…</p>;
  return (
    <section className="d-card" aria-label="תקציב מול בנק מול ספרים">
      <h2>{booksFirst ? 'ספרים · בנק · תקציב' : 'תקציב · בנק · ספרים'}</h2>
      {report.note_he ? <p className="mt-1 text-xs text-stone-500">{report.note_he}</p> : null}
      <div className="mt-3 overflow-x-auto">
        <table className="d-table text-sm">
          <thead>
            <tr>
              <th>טווח</th>
              {booksFirst ? <th>ספרים</th> : <th>תקציב</th>}
              <th>בנק</th>
              {booksFirst ? <th>תקציב</th> : <th>ספרים</th>}
              <th>סטייה ספרים</th>
              <th>סטייה בנק</th>
              {booksFirst ? <th>רווח</th> : null}
            </tr>
          </thead>
          <tbody>
            {report.periods.map((period) => {
              const lines = period.bank.lines || [];
              const expanded = open === period.start;
              const budgetCell = (
                <td>
                  {text(period.budget.net)}
                  <span className="mt-1 block text-xs text-stone-500">{stamp(period.budget.net)}</span>
                  {period.budget.months_missing?.length ? (
                    <span className="mt-1 block text-xs text-stone-500">חודשים בלי תקציב: {period.budget.months_missing.join(', ')}. לא הוזן 0.</span>
                  ) : null}
                  {period.budget.months_ahead?.length ? (
                    <span className="mt-1 block text-xs text-stone-500">
                      לא בהשוואה (עוד לא התחיל): {period.budget.months_ahead.join(', ')}
                      {period.budget.ahead?.net?.amount != null ? ` · נטו ${text(period.budget.ahead.net)}` : ''}
                    </span>
                  ) : null}
                  {period.budget.month_context?.length ? (
                    <span className="mt-1 block text-xs text-stone-500">
                      הקשר חודשי: {period.budget.month_context.map((row) => `${row.month} נטו ${row.net == null ? 'חסר' : row.net}`).join(' · ')}
                    </span>
                  ) : null}
                </td>
              );
              const bankCell = (
                <td>
                  נכנס {text(period.bank.in)} · יוצא {text(period.bank.out)} · נטו {text(period.bank.net)}
                  <span className="mt-1 block text-xs text-stone-500">{stamp(period.bank.net)}</span>
                </td>
              );
              const booksCell = booksFirst ? (
                <td>
                  הכנסות {text(period.books.revenue)} · הוצאות {text(period.books.costs)} · נטו {text(period.books.net)}
                  <span className="mt-1 block text-xs text-stone-500">{stamp(period.books.net)}</span>
                </td>
              ) : (
                <td>
                  {text(period.books.net)}
                  <span className="mt-1 block text-xs text-stone-500">{stamp(period.books.net)}</span>
                </td>
              );
              return (
                <Fragment key={period.start}>
                  <tr>
                    <td>
                      {report.grain === 'day' && lines.length > 0 ? (
                        <button type="button" className="underline" onClick={() => setOpen(expanded ? null : period.start)}>
                          {period.label}
                        </button>
                      ) : period.label}
                    </td>
                    {booksFirst ? booksCell : budgetCell}
                    {bankCell}
                    {booksFirst ? budgetCell : booksCell}
                    <td>{text(period.variance.books_vs_budget)}</td>
                    <td>{text(period.variance.bank_vs_budget)}</td>
                    {booksFirst ? <td>{text(period.books.net)}</td> : null}
                  </tr>
                  {expanded ? (
                    <tr key={`${period.start}-lines`}>
                      <td colSpan={booksFirst ? 7 : 6}>
                        <ul>
                          {lines.map((line) => (
                            <li key={`${line.date}-${line.amount}-${line.description}`}>
                              {line.date} · {line.amount == null ? missingAsOf(line.date) : line.amount} · {line.description || 'בלי תיאור'}
                              {line.account_id != null ? ` · חשבון ${line.account_id}` : ''}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
            {report.totals ? (
              <tr className="font-semibold">
                <td>סיכום להשוואה</td>
                {booksFirst ? <td>{text(report.totals.books.net)}</td> : <td>{text(report.totals.budget.net)}</td>}
                <td>{text(report.totals.bank.net)}</td>
                {booksFirst ? <td>{text(report.totals.budget.net)}</td> : <td>{text(report.totals.books.net)}</td>}
                <td />
                <td />
                {booksFirst ? <td>{text(report.totals.books.net)}</td> : null}
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {report.profit?.length ? (
        <p className="mt-2 text-xs text-stone-500">
          רווח לפי {report.grain === 'day' ? 'יום' : report.grain === 'week' ? 'שבוע' : report.grain === 'month' ? 'חודש' : report.grain === 'quarter' ? 'רבעון' : 'שנה'}:{' '}
          {report.profit.map((row) => `${row.label} ספרים ${text(row.books)} · בנק ${text(row.bank)} · תקציב ${text(row.budget)}`).join(' | ')}
        </p>
      ) : null}
    </section>
  );
}
