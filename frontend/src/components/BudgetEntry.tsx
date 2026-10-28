import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Target, Upload, Download, Save } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

type LineMonth = { status: 'filled' | 'none' | 'missing'; status_he: string; amount: string | null; placeholder_warning?: string };
type BudgetLine = {
  id: string;
  label: string;
  kind: string;
  category: string;
  months: Record<string, LineMonth>;
  placeholder_warning?: string;
};
type Assumption = {
  id: string;
  kind: string;
  label_he: string;
  month: string | null;
  amount: number | null;
  source: string | null;
  status: string;
  missing_label: string | null;
  as_of?: string | null;
  note?: string | null;
  override?: boolean;
  bank_amount?: number | null;
  bank_as_of?: string | null;
  differs?: boolean;
  used?: string;
};
type LineUpdate = {
  id: string;
  label?: string;
  category?: string;
  kind?: string;
  month?: string;
  status?: string;
  amount?: number;
  note?: string;
  override?: boolean;
  remove?: boolean;
};
type LinesPayload = {
  lines: BudgetLine[];
  counts: { active: number; filled: number; none: number; missing: number };
  declared_payroll: { monthly: string | null; note_he: string };
  assumptions?: Assumption[];
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
const SOURCE_HE: Record<string, string> = { owner: 'הנחת בעלים', bank: 'מהבנק', books: 'מהספרים' };

type OrgOption = { id: number; name: string };

const MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];

function monthKey(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`;
}

const BudgetEntry: React.FC<Props> = ({ darkMode }) => {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [orgs, setOrgs] = useState<OrgOption[]>([]);
  const [orgId, setOrgId] = useState(() => localStorage.getItem('active_org_id') || '');
  const [openingDate, setOpeningDate] = useState('');
  const [openingNote, setOpeningNote] = useState('');
  const [openingOverride, setOpeningOverride] = useState(false);
  const queryClient = useQueryClient();
  const fromMonth = 1;
  const toMonth = year === now.getFullYear() ? Math.max(month, now.getMonth() + 1) : 12;

  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';
  const input = `px-3 py-2 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`;

  useEffect(() => {
    apiService.get<OrgOption[]>('/admin/auth/organizations').then(setOrgs).catch(() => setOrgs([]));
  }, []);

  const linesQuery = useQuery({
    queryKey: ['budget-lines', orgId, year, fromMonth, toMonth],
    queryFn: () => apiService.get<{ status: string; data: LinesPayload }>('/financial/budget/lines', {
      params: { year, from_month: fromMonth, to_month: toMonth },
    }),
  });
  const data = linesQuery.data?.data;
  const key = monthKey(year, month);
  const monthAssumptions = (data?.assumptions ?? []).filter((row) => row.month === key || row.kind === 'opening_balance');
  const openingRow = monthAssumptions.find((row) => row.kind === 'opening_balance');
  const savedOpeningDate = openingRow?.month && openingRow.month.length >= 10 ? openingRow.month.slice(0, 10) : '';
  const savedOpeningNote = openingRow?.note ?? '';
  const savedOpeningOverride = openingRow?.override === true;

  useEffect(() => {
    setOpeningDate(savedOpeningDate);
    setOpeningNote(savedOpeningNote);
    setOpeningOverride(savedOpeningOverride);
  }, [savedOpeningDate, savedOpeningNote, savedOpeningOverride]);

  const saveMutation = useMutation({
    mutationFn: (updates: Array<Record<string, unknown>>) => apiService.put('/financial/budget/lines', { updates }),
    onSuccess: async () => {
      setDrafts({});
      setMessage('הסכומים נשמרו. הדשבורד יציג אותם בלי רענון ידני.');
      await queryClient.invalidateQueries({ queryKey: ['budget-lines'] });
      await queryClient.invalidateQueries({ queryKey: ['budget-vs-actual'] });
      await queryClient.invalidateQueries({ queryKey: ['budget-alerts'] });
      await queryClient.invalidateQueries({ queryKey: ['dashboard-pnl'] });
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => {
      setMessage(error?.response?.data?.detail || 'שגיאה בשמירה');
    },
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => apiService.importBudgetExcel(file),
    onSuccess: async (res: { data?: { saved?: number; skipped?: number } }) => {
      setMessage(`יובאו ${res?.data?.saved ?? 0} שורות (${res?.data?.skipped ?? 0} דולגו)`);
      await queryClient.invalidateQueries({ queryKey: ['budget-lines'] });
      await queryClient.invalidateQueries({ queryKey: ['budget-vs-actual'] });
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => setMessage(error?.response?.data?.detail || 'שגיאה בייבוא'),
  });

  function save() {
    const updates = Object.entries(drafts).map(([id, raw]): LineUpdate => {
      const text = raw.trim();
      const assumption = monthAssumptions.find((row) => row.id === id);
      if (assumption?.kind === 'opening_balance') {
        const when = openingDate || (assumption.month && assumption.month.length >= 10 ? assumption.month.slice(0, 10) : `${key}-01`);
        const target = {
          id: 'opening_balance',
          label: assumption.label_he,
          category: 'opening_balance',
          kind: 'financing',
          note: openingNote,
          override: openingOverride,
        };
        if (text === '' || text === 'none') return { ...target, month: when, status: 'missing' };
        return { ...target, month: when, status: 'filled', amount: Number(text) };
      }
      const line = assumption ? ASSUMPTION_LINE[assumption.kind] : null;
      const target = line ? {
        id: `assumption:${assumption!.kind}`,
        label: assumption!.label_he,
        category: line.category,
        kind: line.kind,
      } : { id };
      if (text === '' || text === 'none') return { ...target, month: key, status: 'missing' };
      return { ...target, month: key, status: 'filled', amount: Number(text) };
    }).filter((update) => update.status === 'missing' || update.status === 'none' || Number.isFinite(update.amount));
    if (updates.length === 0) {
      setMessage('אין שינוי לשמירה');
      return;
    }
    saveMutation.mutate(updates);
  }

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Target className="w-8 h-8 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold">הזנת תקציב</h1>
          <p className="text-sm text-gray-500">כל שורת הכנסה והוצאה פעילה, עם סכום או סימון חסר. אין סכום מומצא.</p>
        </div>
      </div>

      {message && <div className={`p-3 rounded-lg border ${card}`}>{message}</div>}
      {data?.declared_payroll?.monthly ? (
        <p className={`text-sm ${darkMode ? 'text-amber-200' : 'text-amber-800'}`}>
          שכר מוצהר לחודש: ₪{Number(data.declared_payroll.monthly).toLocaleString('he-IL')}. {data.declared_payroll.note_he}
        </p>
      ) : null}

      <div className={`rounded-xl border p-5 ${card} flex flex-wrap items-end gap-4`}>
        <div>
          <label className="block text-sm mb-1" htmlFor="budget-org">ארגון</label>
          <select id="budget-org" className={input} value={orgId} onChange={(event) => {
            const next = event.target.value;
            if (next) localStorage.setItem('active_org_id', next);
            setOrgId(next);
            setDrafts({});
          }}>
            <option value="">הארגון הפעיל</option>
            {orgs.map((org) => <option key={org.id} value={String(org.id)}>{org.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm mb-1">שנה</label>
          <input type="number" className={input} value={year} onChange={(e) => setYear(parseInt(e.target.value, 10) || year)} />
        </div>
        <div>
          <label className="block text-sm mb-1">חודש</label>
          <select className={input} value={month} onChange={(e) => setMonth(parseInt(e.target.value, 10))}>
            {MONTHS.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
          </select>
        </div>
        <button onClick={() => apiService.downloadBudgetTemplate()}
          className="px-4 py-2 border border-gray-400 rounded-lg flex items-center gap-2 hover:bg-gray-50">
          <Download className="w-4 h-4" /> תבנית Excel
        </button>
        <label className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg flex items-center gap-2 hover:bg-blue-50 cursor-pointer">
          <Upload className="w-4 h-4" /> ייבוא Excel
          <input type="file" accept=".xlsx" className="hidden"
            onChange={(e) => e.target.files?.[0] && importMutation.mutate(e.target.files[0])} />
        </label>
      </div>

      <div className={`rounded-xl border p-5 ${card}`}>
        <h2 className="text-lg font-semibold mb-1">הנחות עבודה</h2>
        <p className="text-sm text-gray-500 mb-3">הכנסות, שכר ומצבת, ספקים, רכב, ריבית, החזרי קרן ויתרת פתיחה. חסר אינו 0, ומוצג כחסר נכון לתאריך. ספקים נפרעים בסוף החודש העוקב: ספטמבר ב־1/11, אוקטובר ב־30/11, נובמבר ב־31/12, דצמבר ב־31/1.</p>
        <table className="w-full text-sm mb-2">
          <thead>
            <tr className="text-right border-b">
              <th className="py-2">הנחה</th>
              <th>מקור</th>
              <th>סטטוס</th>
              <th>סכום</th>
            </tr>
          </thead>
          <tbody>
            {monthAssumptions.map((row) => (
              <tr key={row.id} className="border-b">
                <td className="py-2">{row.label_he}</td>
                <td>{row.source ? (SOURCE_HE[row.source] ?? row.source) : '—'}</td>
                <td>{row.missing_label ?? (row.status === 'assumption' ? 'הנחת בעלים' : row.status === 'confirmed' ? 'מאושר' : row.status)}</td>
                <td>
                  {ASSUMPTION_LINE[row.kind] || row.kind === 'opening_balance' ? (
                    <div className="grid gap-1">
                      <input
                        className={input + ' w-40'}
                        value={drafts[row.id] !== undefined ? drafts[row.id] : (row.amount ?? '')}
                        placeholder={row.missing_label ?? ''}
                        onChange={(event) => setDrafts({ ...drafts, [row.id]: event.target.value })}
                      />
                      {row.kind === 'opening_balance' ? (
                        <>
                          <input type="date" className={input + ' w-40'} value={openingDate} onChange={(event) => setOpeningDate(event.target.value)} />
                          <input className={input + ' w-40'} value={openingNote} placeholder="הערה" onChange={(event) => setOpeningNote(event.target.value)} />
                          <label className="text-xs">
                            <input type="checkbox" checked={openingOverride} onChange={(event) => setOpeningOverride(event.target.checked)} />
                            {' '}היתרה שלי גוברת על צילום הבנק
                          </label>
                          <p className="text-xs text-gray-500">
                            בנק: {row.bank_amount == null ? (row.missing_label ?? 'חסר') : row.bank_amount}{row.bank_as_of ? ` נכון ל-${row.bank_as_of}` : ''}
                            {row.differs ? ' · שונה מיתרת הבעלים' : ''}
                            {row.used === 'bank' ? ' · צילום הבנק בתוקף' : row.used === 'owner' ? ' · יתרת הבעלים בתוקף' : ''}
                          </p>
                        </>
                      ) : null}
                    </div>
                  ) : (
                    <span>{row.amount ?? row.missing_label}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={`rounded-xl border p-5 ${card}`}>
        {linesQuery.isLoading ? <p>טוען שורות…</p> : null}
        {linesQuery.isError ? <p>לא ניתן לטעון את שורות התקציב לפני בחירת ארגון.</p> : null}
        {data ? (
          <>
            <p className="mb-3 text-sm text-gray-600">
              {MONTHS[month - 1]} {year}: {data.counts.filled} עם סכום, {data.counts.none} מסומנות «אין», {data.counts.missing} חסרות מתוך {data.counts.active}.
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-right border-b">
                  <th className="py-2">שורה</th>
                  <th>סטטוס</th>
                  <th>סכום</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((line) => {
                  const cell = line.months[key];
                  const draft = drafts[line.id];
                  const shown = draft !== undefined ? draft : (cell?.amount ?? '');
                  return (
                    <tr key={line.id} className="border-b">
                      <td className="py-2">
                        {line.label}
                        {line.placeholder_warning ? <p className="text-xs text-amber-700">{line.placeholder_warning}</p> : null}
                      </td>
                      <td className={cell?.status === 'missing' ? 'text-amber-700' : ''}>{cell?.status_he ?? 'חסר, הבעלים יזין'}</td>
                      <td>
                        <input
                          className={input + ' w-40'}
                          value={shown}
                          placeholder={cell?.status === 'missing' ? 'חסר' : ''}
                          onChange={(event) => setDrafts({ ...drafts, [line.id]: event.target.value })}
                        />
                      </td>
                      <td>
                        <button type="button" className="text-stone-600 underline"
                          onClick={() => setDrafts({ ...drafts, [line.id]: 'none' })}>
                          סמן אין
                        </button>
                        <button type="button" className="mr-3 text-red-700 underline"
                          onClick={() => {
                            if (!window.confirm(`למחוק את «${line.label}»? המחיקה רק באישור, לא אוטומטית.`)) return;
                            saveMutation.mutate([{ id: line.id, label: line.label, category: line.category, kind: line.kind, remove: true }]);
                          }}>
                          מחק שורה
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <button onClick={save} disabled={saveMutation.isPending}
              className="mt-4 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2">
              <Save className="w-4 h-4" /> {saveMutation.isPending ? 'שומר...' : 'שמירת תקציב'}
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
};

export default BudgetEntry;
