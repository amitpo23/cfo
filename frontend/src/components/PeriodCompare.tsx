import { Fragment, useState } from 'react';

export type Grain = 'day' | 'week' | 'month';

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
  budget: { revenue: Figure; costs: Figure; net: Figure; month_context?: { month: string; revenue: number | null; costs: number | null; net: number | null }[] };
  bank: { in: Figure; out: Figure; net: Figure; count?: number; lines?: { date: string; amount: number; description?: string | null; account_id?: number | null }[] };
  books: { revenue: Figure; costs: Figure; net: Figure };
  variance: { books_vs_budget: Figure; bank_vs_budget: Figure };
};

export type PeriodCompare = {
  grain: Grain;
  start: string;
  end: string;
  note_he?: string;
  periods: PeriodRow[];
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
  const start = new Date(today.getFullYear(), today.getMonth(), 1);
  const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  return { start: isoDate(start), end: isoDate(end) };
}

function text(figure?: Figure): string {
  if (!figure || figure.amount == null) return figure?.missing_label || 'חסר';
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

export function PeriodCompareTable({ report }: { report: PeriodCompare | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!report) return <p className="text-sm text-stone-500">טוען תקציב, בנק וספרים…</p>;
  return (
    <section className="d-card" aria-label="תקציב מול בנק מול ספרים">
      <h2>תקציב · בנק · ספרים</h2>
      {report.note_he ? <p className="mt-1 text-xs text-stone-500">{report.note_he}</p> : null}
      <div className="mt-3 overflow-x-auto">
        <table className="d-table text-sm">
          <thead>
            <tr>
              <th>טווח</th>
              <th>תקציב</th>
              <th>בנק</th>
              <th>ספרים</th>
              <th>סטייה ספרים</th>
              <th>סטייה בנק</th>
            </tr>
          </thead>
          <tbody>
            {report.periods.map((period) => {
              const lines = period.bank.lines || [];
              const expanded = open === period.start;
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
                    <td>
                      {text(period.budget.net)}
                      <span className="mt-1 block text-xs text-stone-500">{stamp(period.budget.net)}</span>
                      {period.budget.month_context?.length ? (
                        <span className="mt-1 block text-xs text-stone-500">
                          הקשר חודשי: {period.budget.month_context.map((row) => `${row.month} נטו ${row.net == null ? 'חסר' : row.net}`).join(' · ')}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      נכנס {text(period.bank.in)} · יוצא {text(period.bank.out)} · נטו {text(period.bank.net)}
                      <span className="mt-1 block text-xs text-stone-500">{stamp(period.bank.net)}</span>
                    </td>
                    <td>
                      {text(period.books.net)}
                      <span className="mt-1 block text-xs text-stone-500">{stamp(period.books.net)}</span>
                    </td>
                    <td>{text(period.variance.books_vs_budget)}</td>
                    <td>{text(period.variance.bank_vs_budget)}</td>
                  </tr>
                  {expanded ? (
                    <tr key={`${period.start}-lines`}>
                      <td colSpan={6}>
                        <ul>
                          {lines.map((line) => (
                            <li key={`${line.date}-${line.amount}-${line.description}`}>
                              {line.date} · {line.amount} · {line.description || 'בלי תיאור'}
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
          </tbody>
        </table>
      </div>
    </section>
  );
}
