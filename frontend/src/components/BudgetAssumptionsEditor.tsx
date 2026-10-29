import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import api from '../services/api';

type LineMonth = {
  status: string;
  status_he?: string;
  amount: string | null;
  quantity?: number | null;
  rate?: number | null;
};

type BudgetLine = {
  id: string;
  label: string;
  kind: string;
  category: string;
  custom?: boolean;
  division?: string | null;
  line_source?: string | null;
  driver_formula?: string | null;
  months: Record<string, LineMonth>;
};

type Assumption = {
  id: string;
  kind: string;
  label_he: string;
  month: string | null;
  amount: number | null;
  missing_label: string | null;
};

const ASSUMPTION_LINE: Record<string, { category: string; kind: string }> = {
  income: { category: 'revenue', kind: 'revenue' },
  payroll: { category: 'payroll', kind: 'cost' },
  headcount: { category: 'headcount', kind: 'cost' },
  suppliers: { category: 'suppliers', kind: 'cost' },
  vehicle: { category: 'vehicle', kind: 'cost' },
  interest: { category: 'interest_expense', kind: 'cost' },
  loan_repayment: { category: 'loan_principal', kind: 'financing' },
};

export function monthsInRange(start: string, end: string): { year: number; months: string[] } | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return null;
  if (start.slice(0, 4) !== end.slice(0, 4)) return null;
  const year = Number(start.slice(0, 4));
  const from = Number(start.slice(5, 7));
  const to = Number(end.slice(5, 7));
  if (!year || from < 1 || to > 12 || from > to) return null;
  const months = [];
  for (let month = from; month <= to; month += 1) months.push(`${year}-${String(month).padStart(2, '0')}`);
  return { year, months };
}

export function BudgetAssumptionsEditor({
  start, end, slug,
}: {
  start: string;
  end: string;
  slug?: string | null;
}) {
  const range = monthsInRange(start, end);
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const linesQuery = useQuery({
    queryKey: ['budget-lines', range?.year, range?.months[0], range?.months.at(-1)],
    enabled: range != null,
    queryFn: () => api.get<{ status: string; data: { lines: BudgetLine[]; assumptions?: Assumption[] } }>(
      '/financial/budget/lines',
      { params: { year: range!.year, from_month: Number(range!.months[0].slice(5)), to_month: Number(range!.months.at(-1)!.slice(5)) } },
    ),
  });
  const save = useMutation({
    mutationFn: (updates: Array<Record<string, unknown>>) => api.put('/financial/budget/lines', { updates }),
    onSuccess: async () => {
      setDrafts({});
      setMessage('נשמר לאותן שורות תקציב של התחזית והדשבורד.');
      await queryClient.invalidateQueries({ queryKey: ['budget-lines'] });
      await queryClient.invalidateQueries({ queryKey: ['cashflow-period'] });
      await queryClient.invalidateQueries({ queryKey: ['budget-vs-actual'] });
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => {
      setMessage(error?.response?.data?.detail || 'השמירה נכשלה');
    },
  });

  function draftKey(id: string, month: string, field = 'amount') {
    return `${id}|${month}|${field}`;
  }

  function saveEdits() {
    if (!range) return;
    const data = linesQuery.data?.data;
    const updates: Array<Record<string, unknown>> = [];
    for (const line of data?.lines ?? []) {
      for (const month of range.months) {
        const amountText = drafts[draftKey(line.id, month)];
        const formula = drafts[draftKey(line.id, month, 'formula')];
        const qtyText = drafts[draftKey(line.id, month, 'qty')];
        const rateText = drafts[draftKey(line.id, month, 'rate')];
        if (amountText === undefined && formula === undefined && qtyText === undefined && rateText === undefined) continue;
        const base: Record<string, unknown> = {
          id: line.id,
          label: line.label,
          category: line.category,
          kind: line.kind,
          month,
          custom: Boolean(line.custom),
          division: line.division || undefined,
          source: line.line_source || undefined,
          driver_formula: formula !== undefined ? formula : line.driver_formula || undefined,
        };
        const cell = line.months[month];
        const kept = cell?.status === 'confirmed' ? 'confirmed' : 'assumption';
        const qty = qtyText !== undefined ? Number(qtyText) : cell?.quantity;
        const rate = rateText !== undefined ? Number(rateText) : cell?.rate;
        const editedDriver = qtyText !== undefined || rateText !== undefined;
        if (line.custom && editedDriver) {
          if (qtyText === '' || rateText === '') {
            updates.push({ ...base, status: 'missing' });
            continue;
          }
          if (Number.isFinite(qty) && Number.isFinite(rate)) {
            updates.push({ ...base, status: kept, qty, unit_price: rate });
            continue;
          }
        }
        if (amountText === undefined) {
          if (formula === undefined) continue;
          if (cell?.quantity != null && cell?.rate != null) {
            updates.push({ ...base, status: kept, qty: Number(cell.quantity), unit_price: Number(cell.rate) });
          } else if (cell?.amount != null) {
            updates.push({ ...base, status: line.custom ? kept : 'filled', amount: Number(cell.amount) });
          }
          continue;
        }
        const text = amountText.trim();
        if (text === '' || text === 'none') {
          updates.push({ ...base, status: 'missing' });
          continue;
        }
        const amount = Number(text);
        if (!Number.isFinite(amount)) continue;
        updates.push({ ...base, status: line.custom ? kept : 'filled', amount });
      }
    }
    for (const row of data?.assumptions ?? []) {
      if (!row.month || !range.months.includes(row.month) || row.kind === 'opening_balance') continue;
      const text = drafts[draftKey(row.id, row.month)];
      if (text === undefined) continue;
      const mapped = ASSUMPTION_LINE[row.kind];
      if (!mapped) continue;
      const trimmed = text.trim();
      const target = {
        id: `assumption:${row.kind}`, label: row.label_he, category: mapped.category, kind: mapped.kind, month: row.month,
      };
      updates.push(trimmed === '' ? { ...target, status: 'missing' } : { ...target, status: 'filled', amount: Number(trimmed) });
    }
    if (updates.length === 0) {
      setMessage('אין שינוי לשמירה');
      return;
    }
    save.mutate(updates);
  }

  const bva = slug ? `/d/${encodeURIComponent(slug)}?tab=bva` : '/dashboards';
  return (
    <section className="bg-white rounded-xl shadow-sm p-6 border border-gray-100" aria-label="עריכת הנחות תקציב">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold text-gray-900">הנחות וסכומים</h2>
        <div className="flex flex-wrap gap-3 text-sm">
          <Link className="underline" to={bva}>תקציב מול ביצוע בדשבורד</Link>
          <Link className="underline" to="/budget-entry">הזנת תקציב</Link>
          <Link className="underline" to="/pnl">רווח והפסד</Link>
        </div>
      </div>
      <p className="mt-1 text-sm text-gray-500">השמירה נכתבת לאותן שורות תקציב שהתחזית, חבילת הבנק והדשבורד קוראים.</p>
      {!range ? <p className="mt-3 text-sm text-gray-600">עריכה כאן היא בתוך שנה אחת. לטווח שחוצה שנה השתמשו בהזנת התקציב.</p> : null}
      {range && linesQuery.isLoading ? <p className="mt-3 text-sm text-gray-500">טוען שורות…</p> : null}
      {range && linesQuery.data ? (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-right text-gray-500">
                <th className="py-2">שורה</th>
                {range.months.map((month) => <th key={month} className="py-2">{month}</th>)}
              </tr>
            </thead>
            <tbody>
              {(linesQuery.data.data.lines ?? []).map((line) => (
                <tr key={line.id} className="border-t">
                  <td className="py-2 pe-3">
                    {line.division ? <span className="text-gray-500">{line.division} · </span> : null}
                    {line.label}
                    <span className="mt-1 block text-xs text-gray-400">{line.kind === 'revenue' ? 'הכנסה' : 'הוצאה'}</span>
                  </td>
                  {range.months.map((month) => {
                    const cell = line.months[month];
                    return (
                      <td key={month} className="py-2">
                        <input
                          className="w-28 rounded border border-gray-300 px-2 py-1"
                          aria-label={`${line.label} ${month}`}
                          inputMode="decimal"
                          placeholder={cell?.status_he || 'חסר'}
                          value={drafts[draftKey(line.id, month)] ?? (cell?.amount ?? '')}
                          onChange={(event) => setDrafts((current) => ({ ...current, [draftKey(line.id, month)]: event.target.value }))}
                        />
                        {line.custom ? (
                          <span className="mt-1 block text-xs text-gray-500">
                            <input
                              className="w-16 rounded border border-gray-200 px-1"
                              aria-label={`כמות ${line.label} ${month}`}
                              value={drafts[draftKey(line.id, month, 'qty')] ?? (cell?.quantity ?? '')}
                              onChange={(event) => setDrafts((current) => ({ ...current, [draftKey(line.id, month, 'qty')]: event.target.value }))}
                            />
                            ×
                            <input
                              className="w-16 rounded border border-gray-200 px-1"
                              aria-label={`תעריף ${line.label} ${month}`}
                              value={drafts[draftKey(line.id, month, 'rate')] ?? (cell?.rate ?? '')}
                              onChange={(event) => setDrafts((current) => ({ ...current, [draftKey(line.id, month, 'rate')]: event.target.value }))}
                            />
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {(linesQuery.data.data.assumptions ?? []).filter((row) => row.month && range.months.includes(row.month) && row.kind !== 'opening_balance').map((row) => (
                <tr key={`${row.id}-${row.month}`} className="border-t">
                  <td className="py-2 pe-3">{row.label_he}<span className="mt-1 block text-xs text-gray-400">הנחה</span></td>
                  {range.months.map((month) => (
                    <td key={month} className="py-2">
                      {month === row.month ? (
                        <input
                          className="w-28 rounded border border-gray-300 px-2 py-1"
                          aria-label={`${row.label_he} ${month}`}
                          inputMode="decimal"
                          placeholder={row.missing_label || 'חסר'}
                          value={drafts[draftKey(row.id, month)] ?? (row.amount ?? '')}
                          onChange={(event) => setDrafts((current) => ({ ...current, [draftKey(row.id, month)]: event.target.value }))}
                        />
                      ) : null}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
            disabled={save.isPending}
            onClick={saveEdits}
          >
            {save.isPending ? 'שומר…' : 'שמירת סכומים'}
          </button>
        </div>
      ) : null}
      {message ? <p className="mt-3 text-sm text-gray-700" role="status">{message}</p> : null}
    </section>
  );
}
