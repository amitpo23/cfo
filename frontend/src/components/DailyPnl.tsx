import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Grain, PeriodCompare } from './PeriodCompare';
import { cumulativeRows, dailyChartRows, hasDailyBudget, type RunningFigure } from './periodDaily';

const GRAIN_HE: Record<Grain, string> = { day: 'יום', week: 'שבוע', month: 'חודש', quarter: 'רבעון', year: 'שנה' };

const money = new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 });

function cell(value: number | null | undefined): string {
  return value == null ? 'חסר' : money.format(value);
}

function running(figure: RunningFigure): string {
  if (figure.notStarted) return 'עוד לא התחיל';
  if (figure.missingSince) return `חסר מ-${figure.missingSince}`;
  return cell(figure.amount);
}

type Source = 'books' | 'bank';

/** Income vs expense per bucket, from the same period payload as the table. */
export function PnlChart({ report }: { report: PeriodCompare | null }) {
  const [source, setSource] = useState<Source>('books');
  if (!report) return null;
  const rows = dailyChartRows(report);
  const withBudget = hasDailyBudget(report);
  const income = source === 'books' ? 'booksRevenue' : 'bankIn';
  const expense = source === 'books' ? 'booksCosts' : 'bankOut';
  const gaps = rows.filter((row) => row.elapsed && (row[income] == null || row[expense] == null)).length;
  return (
    <section className="d-card" aria-label="הכנסות מול הוצאות">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2>הכנסות מול הוצאות לפי {GRAIN_HE[report.grain]}</h2>
        <div className="flex gap-1 text-sm" role="group" aria-label="מקור הנתונים בגרף">
          {(['books', 'bank'] as const).map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={source === id}
              className={`rounded-md px-3 py-1 ${source === id ? 'bg-navy-800 text-white' : 'border border-navy-200 bg-white text-navy-800'}`}
              onClick={() => setSource(id)}
            >
              {id === 'books' ? 'ספרים' : 'בנק (BOOKED)'}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs text-stone-500">
        {source === 'books' ? 'הכנסות והוצאות ממסמכים שתויקו (לפני מע"מ).' : 'כסף שנכנס ויצא בתנועות BOOKED.'}
        {gaps ? ` ${gaps} תקופות בלי נתון מלא: מוצגות בלי עמודה (חסר, לא 0).` : ''}
        {withBudget ? ' הקו: תקציב נטו, רק כשהתקציב מחולק לפי יום.' : ''}
      </p>
      <div className="mt-3 h-72" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" reversed tick={{ fontSize: 11 }} tickFormatter={(label: string) => (report.grain === 'day' ? label.slice(8) : label)} />
            <YAxis orientation="right" tick={{ fontSize: 11 }} tickFormatter={(value: number) => money.format(value)} width={80} />
            <Tooltip formatter={(value) => cell(typeof value === 'number' ? value : null)} labelFormatter={(label: string) => label} />
            <Legend />
            <Bar dataKey={income} name={source === 'books' ? 'הכנסות' : 'נכנס'} fill="#16a34a" radius={[3, 3, 0, 0]} />
            <Bar dataKey={expense} name={source === 'books' ? 'הוצאות' : 'יוצא'} fill="#dc2626" radius={[3, 3, 0, 0]} />
            {withBudget ? <Line dataKey="budgetNet" name="תקציב נטו" stroke="#1e3a8a" dot={false} connectNulls={false} /> : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

/** Running totals with the server's rules: a missing day ends the known total. */
export function CumulativeTable({ report }: { report: PeriodCompare | null }) {
  if (!report || report.periods.length === 0) return null;
  const rows = cumulativeRows(report);
  const withBudget = hasDailyBudget(report);
  return (
    <section className="d-card" aria-label="מצטבר">
      <h2>מצטבר מתחילת הטווח</h2>
      <p className="mt-1 text-xs text-stone-500">
        כל שורה היא הסכום מ-{report.start} עד סוף אותה תקופה. תקופה בלי נתון עוצרת את המצטבר (חסר), כמו בסיכום של השרת.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="d-table text-sm">
          <thead>
            <tr>
              <th>עד</th>
              <th>הכנסות (ספרים)</th>
              <th>הוצאות (ספרים)</th>
              <th>נטו (ספרים)</th>
              <th>נכנס (בנק)</th>
              <th>יוצא (בנק)</th>
              <th>נטו (בנק)</th>
              {withBudget ? <th>תקציב נטו</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.date}>
                <td>{row.label}</td>
                <td>{running(row.booksRevenue)}</td>
                <td>{running(row.booksCosts)}</td>
                <td className="font-semibold">{running(row.booksNet)}</td>
                <td>{running(row.bankIn)}</td>
                <td>{running(row.bankOut)}</td>
                <td className="font-semibold">{running(row.bankNet)}</td>
                {withBudget ? <td>{running(row.budgetNet)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
