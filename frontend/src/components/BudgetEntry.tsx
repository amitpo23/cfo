import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Target, Upload, Download, Save } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

type LineMonth = { status: 'filled' | 'none' | 'missing'; status_he: string; amount: string | null };
type BudgetLine = {
  id: string;
  label: string;
  kind: string;
  category: string;
  months: Record<string, LineMonth>;
};
type LinesPayload = {
  lines: BudgetLine[];
  counts: { active: number; filled: number; none: number; missing: number };
  declared_payroll: { monthly: string | null; note_he: string };
};

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
    const updates = Object.entries(drafts).map(([id, raw]) => {
      const text = raw.trim();
      if (text === 'none') return { id, month: key, status: 'none' };
      return { id, month: key, status: 'filled', amount: Number(text) };
    }).filter((update) => update.status === 'none' || Number.isFinite(update.amount as number));
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
                      <td className="py-2">{line.label}</td>
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
