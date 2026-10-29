import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Target, Upload, Download, Save } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

type LineMonth = {
  status: 'filled' | 'none' | 'missing' | 'assumption' | 'confirmed';
  status_he: string;
  amount: string | null;
  quantity?: number | null;
  rate?: number | null;
  placeholder_warning?: string;
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
  covers?: string | null;
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
  custom?: boolean;
  division?: string;
  source?: string;
  qty?: number;
  unit_price?: number;
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
  const [newLine, setNewLine] = useState({
    lineKey: '', label: '', amount: '', qty: '', rate: '', status: 'assumption', source: '', division: '', kind: 'income',
  });
  const [person, setPerson] = useState({ name: '', role: '', cost: '' });
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
    const updates = Object.entries(drafts).filter(([id]) => !id.startsWith('qty:') && !id.startsWith('rate:')).map(([id, raw]): LineUpdate => {
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
      const custom = data?.lines.find((row) => row.custom && row.id === id);
      if (custom) {
        const kept = custom.months[key]?.status === 'confirmed' ? 'confirmed' : 'assumption';
        const target = {
          id: custom.id, label: custom.label, category: custom.category, kind: custom.kind,
          custom: true, division: custom.division || undefined, source: custom.line_source || undefined,
        };
        const qtyText = drafts[`qty:${custom.id}`];
        const rateText = drafts[`rate:${custom.id}`];
        const qty = qtyText !== undefined ? Number(qtyText) : custom.months[key]?.quantity;
        const rate = rateText !== undefined ? Number(rateText) : custom.months[key]?.rate;
        if (qtyText !== undefined || rateText !== undefined) {
          if (qtyText === '' || rateText === '') return { ...target, month: key, status: 'missing' };
          if (Number.isFinite(qty) && Number.isFinite(rate)) {
            return { ...target, month: key, status: kept, qty: Number(qty), unit_price: Number(rate) };
          }
        }
        if (text === '' || text === 'none') return { ...target, month: key, status: 'missing' };
        return { ...target, month: key, status: kept, amount: Number(text) };
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
    }).filter((update) => update.status === 'missing' || update.status === 'none' || Number.isFinite(update.amount) || (Number.isFinite(update.qty) && Number.isFinite(update.unit_price)));
    const seen = new Set(updates.map((update) => update.id));
    for (const line of data?.lines ?? []) {
      if (!line.custom || seen.has(line.id)) continue;
      if (drafts[`qty:${line.id}`] === undefined && drafts[`rate:${line.id}`] === undefined) continue;
      const qty = Number(drafts[`qty:${line.id}`] ?? line.months[key]?.quantity);
      const rate = Number(drafts[`rate:${line.id}`] ?? line.months[key]?.rate);
      const kept = line.months[key]?.status === 'confirmed' ? 'confirmed' : 'assumption';
      if (!Number.isFinite(qty) || !Number.isFinite(rate)) continue;
      updates.push({
        id: line.id, label: line.label, category: line.category, kind: line.kind, custom: true,
        division: line.division || undefined, source: line.line_source || undefined,
        month: key, status: kept, qty, unit_price: rate,
      });
    }
    if (updates.length === 0) {
      setMessage('אין שינוי לשמירה');
      return;
    }
    saveMutation.mutate(updates);
  }

  function addCustomLine() {
    const label = newLine.label.trim();
    if (!label) {
      setMessage('לשורה חדשה חסרה כותרת');
      return;
    }
    const income = newLine.kind === 'income';
    const qty = Number(newLine.qty);
    const rate = Number(newLine.rate);
    const hasDriver = newLine.qty.trim() !== '' && newLine.rate.trim() !== '';
    const blank = newLine.status === 'missing' || (!hasDriver && newLine.amount.trim() === '');
    const amount = Number(newLine.amount);
    if (hasDriver && (!Number.isFinite(qty) || !Number.isFinite(rate))) {
      setMessage('כמות או תעריף אינם מספר');
      return;
    }
    if (!blank && !hasDriver && !Number.isFinite(amount)) {
      setMessage('הסכום אינו מספר');
      return;
    }
    saveMutation.mutate([{
      id: newLine.lineKey.trim() || `custom_${Date.now()}`,
      label,
      custom: true,
      kind: income ? 'revenue' : 'cost',
      category: income ? 'revenue' : 'other',
      division: newLine.division.trim(),
      source: newLine.source.trim() || 'owner',
      month: key,
      status: blank ? 'missing' : newLine.status,
      ...(hasDriver ? { qty, unit_price: rate } : blank ? {} : { amount }),
    }]);
    setNewLine({ lineKey: '', label: '', amount: '', qty: '', rate: '', status: 'assumption', source: '', division: '', kind: 'income' });
  }

  const customLines = (data?.lines ?? []).filter((line) => line.custom);
  const people = customLines.filter((line) => line.line_source === 'headcount');
  const driverLines = customLines.filter((line) => line.line_source !== 'headcount');
  const divisions = [...new Set(driverLines.map((line) => line.division || 'ללא חטיבה'))];

  function addPerson() {
    const name = person.name.trim();
    if (!name) {
      setMessage('חסר שם עובד');
      return;
    }
    const blank = person.cost.trim() === '';
    const amount = Number(person.cost);
    if (!blank && !Number.isFinite(amount)) {
      setMessage('עלות העובד אינה מספר');
      return;
    }
    saveMutation.mutate([{
      id: `person_${name.replace(/\s+/g, '_').slice(0, 40)}`,
      label: name,
      custom: true,
      kind: 'cost',
      category: 'payroll',
      division: person.role.trim() || 'מצבת',
      source: 'headcount',
      month: key,
      status: blank ? 'missing' : 'assumption',
      ...(blank ? {} : { amount }),
    }]);
    setPerson({ name: '', role: '', cost: '' });
  }

  function monthSum(kind: string): number | null {
    let total = 0;
    let any = false;
    for (const line of customLines) {
      if (line.kind !== kind || line.placeholder_warning) continue;
      const cell = line.months[key];
      if (!cell || cell.amount == null || cell.status === 'missing' || cell.placeholder_warning) continue;
      any = true;
      total += Number(cell.amount);
    }
    return any ? total : null;
  }
  const incomeMonth = monthSum('revenue');
  const costMonth = monthSum('cost');

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
        <label className="px-4 py-2 border border-stone-500 rounded-lg flex items-center gap-2 cursor-pointer">
          <Upload className="w-4 h-4" /> ייבוא CSV לדרייברים
          <input type="file" accept=".csv,text/csv" className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              file.text().then((csv_text) => apiService.post('/financial/budget/lines/csv', { csv_text, month: key }))
                .then(async () => {
                  setMessage('שורות הדרייבר יובאו לחודש שנבחר. סכום ריק נשאר חסר.');
                  await queryClient.invalidateQueries({ queryKey: ['budget-lines'] });
                })
                .catch((error: { response?: { data?: { detail?: string } } }) => {
                  setMessage(error?.response?.data?.detail || 'שגיאה בייבוא CSV');
                });
            }} />
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
        <h2 className="text-lg font-semibold mb-1">שורות דרייבר</h2>
        <p className="text-sm text-gray-500 mb-3">כל שורה נשמרת בנפרד, לפי חטיבה. חסר אינו 0. סכום עגול של מיליון בהכנסות לא נכנס לסיכום.</p>
        <div className="grid gap-3 md:grid-cols-3 mb-4">
          <input className={input} placeholder="מזהה (line_key)" value={newLine.lineKey} onChange={(event) => setNewLine({ ...newLine, lineKey: event.target.value })} />
          <input className={input} placeholder="כותרת" value={newLine.label} onChange={(event) => setNewLine({ ...newLine, label: event.target.value })} />
          <input className={input} placeholder="חטיבה" value={newLine.division} onChange={(event) => setNewLine({ ...newLine, division: event.target.value })} />
          <select className={input} value={newLine.kind} onChange={(event) => setNewLine({ ...newLine, kind: event.target.value })}>
            <option value="income">הכנסה</option>
            <option value="expense">הוצאה</option>
          </select>
          <select className={input} value={newLine.status} onChange={(event) => setNewLine({ ...newLine, status: event.target.value })}>
            <option value="assumption">הנחה</option>
            <option value="confirmed">מאושר</option>
            <option value="missing">חסר</option>
          </select>
          <input className={input} placeholder="כמות" value={newLine.qty} onChange={(event) => setNewLine({ ...newLine, qty: event.target.value })} />
          <input className={input} placeholder="תעריף" value={newLine.rate} onChange={(event) => setNewLine({ ...newLine, rate: event.target.value })} />
          <input className={input} placeholder="סכום (אם אין כמות×תעריף)" value={newLine.amount} onChange={(event) => setNewLine({ ...newLine, amount: event.target.value })} />
          <input className={input} placeholder="מקור" value={newLine.source} onChange={(event) => setNewLine({ ...newLine, source: event.target.value })} />
          <button type="button" onClick={addCustomLine} className="px-4 py-2 bg-blue-600 text-white rounded-lg">הוספת שורה</button>
        </div>
        <div className="mb-4">
          <h3 className="font-medium mb-1">מצבת לפי שם</h3>
          <div className="flex flex-wrap gap-2 mb-2">
            <input className={input} placeholder="שם" value={person.name} onChange={(event) => setPerson({ ...person, name: event.target.value })} />
            <input className={input} placeholder="תפקיד" value={person.role} onChange={(event) => setPerson({ ...person, role: event.target.value })} />
            <input className={input} placeholder="עלות חודשית, או ריק אם חסר" value={person.cost} onChange={(event) => setPerson({ ...person, cost: event.target.value })} />
            <button type="button" onClick={addPerson} className="px-4 py-2 border rounded-lg">הוספת עובד</button>
          </div>
          {people.map((line) => {
            const cell = line.months[key];
            return (
              <p key={line.id} className="text-sm">
                {line.label} · {line.division || 'ללא תפקיד'} · {cell?.amount == null || cell.status === 'missing' ? 'חסר' : `₪${Number(cell.amount).toLocaleString('he-IL')}`}
                <button type="button" className="mr-2 text-red-700 underline" onClick={() => saveMutation.mutate([{ id: line.id, remove: true }])}>מחק</button>
              </p>
            );
          })}
        </div>
        {divisions.map((division) => (
          <div key={division} className="mb-4">
            <h3 className="font-medium mb-1">{division}</h3>
            <table className="w-full text-sm">
              <tbody>
                {driverLines.filter((line) => (line.division || 'ללא חטיבה') === division).map((line) => {
                  const cell = line.months[key];
                  const shown = drafts[line.id] !== undefined ? drafts[line.id] : (cell?.amount ?? '');
                  return (
                    <tr key={line.id} className="border-b">
                      <td className="py-2">
                        {line.label}
                        <span className="mr-2 text-xs text-gray-500">{line.kind === 'revenue' ? 'הכנסה' : 'הוצאה'} · {line.id}</span>
                        {line.covers === 'income_and_expense' ? <span className="mr-2 text-xs">הכנסה והוצאה</span> : null}
                        {line.driver_formula ? <p className="text-xs text-gray-500">{line.driver_formula}</p> : null}
                      </td>
                      <td className={cell?.status === 'missing' ? 'text-amber-700' : ''}>{cell?.status === 'missing' ? 'חסר' : (cell?.status_he ?? 'חסר')}</td>
                      <td>
                        <input className={input + ' w-24'} placeholder="כמות"
                          value={drafts[`qty:${line.id}`] !== undefined ? drafts[`qty:${line.id}`] : (cell?.quantity ?? '')}
                          onChange={(event) => setDrafts({ ...drafts, [`qty:${line.id}`]: event.target.value })} />
                        <span className="mx-1">×</span>
                        <input className={input + ' w-24'} placeholder="תעריף"
                          value={drafts[`rate:${line.id}`] !== undefined ? drafts[`rate:${line.id}`] : (cell?.rate ?? '')}
                          onChange={(event) => setDrafts({ ...drafts, [`rate:${line.id}`]: event.target.value })} />
                        <span className="mx-2 text-xs text-gray-500">= {shown === '' ? 'חסר' : shown}</span>
                      </td>
                      <td>
                        <button type="button" className="text-red-700 underline" onClick={() => {
                          if (!window.confirm(`למחוק את «${line.label}»?`)) return;
                          saveMutation.mutate([{ id: line.id, remove: true }]);
                        }}>מחק</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
        <p className="text-sm">
          הכנסות בחודש: {incomeMonth == null ? 'חסר' : `₪${incomeMonth.toLocaleString('he-IL')}`}
          {' · '}
          הוצאות: {costMonth == null ? 'חסר' : `₪${costMonth.toLocaleString('he-IL')}`}
        </p>
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
                {data.lines.filter((line) => !line.custom).map((line) => {
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
