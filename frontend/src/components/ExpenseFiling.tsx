import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FileCheck, Plus, Send, RefreshCw, CheckCircle, Clock, XCircle, Tags, Upload as UploadAll } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

interface Expense {
  id: number;
  supplier_name: string;
  amount: number;
  vat_amount: number;
  total: number;
  expense_date: string;
  category?: string;
  invoice_number?: string;
  status: 'pending' | 'filed' | 'error';
  sumit_expense_id?: string;
  filing_error?: string;
}

const todayISO = () => new Date().toISOString().slice(0, 10);
const empty = { supplier_name: '', amount: 0, vat_amount: 0, expense_date: todayISO(), category: '', invoice_number: '', description: '' };

const ExpenseFiling: React.FC<Props> = ({ darkMode }) => {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<any>(empty);
  const [message, setMessage] = useState<string | null>(null);

  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';
  const input = `w-full px-3 py-2 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`;
  const cellInput = `px-2 py-1 rounded border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`;

  const { data, isLoading } = useQuery({
    queryKey: ['expenses'],
    queryFn: async () => {
      const res: any = await apiService.listExpenses();
      return res.data as Expense[];
    },
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['expenses'] });

  const createMutation = useMutation({
    mutationFn: () => apiService.createExpense(form),
    onSuccess: () => { setMessage('הוצאה נוצרה'); setShowForm(false); setForm(empty); refresh(); },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה ביצירה'),
  });

  const fileMutation = useMutation({
    mutationFn: (id: number) => apiService.fileExpense(id),
    onSuccess: () => { setMessage('ההוצאה תויקה ב-SUMIT'); refresh(); },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בתיוק'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => apiService.updateExpense(id, data),
    onSuccess: () => refresh(),
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בעדכון'),
  });

  const syncMutation = useMutation({
    mutationFn: () => apiService.syncPendingExpenses(),
    onSuccess: (res: any) => { setMessage(`יובאו ${res?.data?.imported ?? 0} מסמכים מ-SUMIT`); refresh(); },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בסנכרון'),
  });

  const classifyMutation = useMutation({
    mutationFn: () => apiService.classifyExpenses(),
    onSuccess: (res: any) => { setMessage(`סווגו אוטומטית ${res?.data?.classified ?? 0} הוצאות`); refresh(); },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בסיווג'),
  });

  const pcnMutation = useMutation({
    mutationFn: () => apiService.getPcn874Readiness(),
    onSuccess: (res: any) => {
      const d = res?.data || {};
      setMessage(
        `מוכנות PCN874: ${d.pcn_ready}/${d.filed_total} מוכנות · חסר ח"פ: ${d.missing_tax_id_count} · ` +
        `חסר מע"מ: ${d.missing_vat_count} · לא בספרים: ${d.not_in_books_count} · ` +
        `סה"כ ₪${Math.round(d.totals?.amount || 0).toLocaleString()}`
      );
    },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בבדיקת מוכנות'),
  });

  const resolveMutation = useMutation({
    mutationFn: () => apiService.resolveSuppliers(),
    onSuccess: (res: any) => {
      const d = res?.data || {};
      setMessage(`נפתרו ${d.resolved ?? 0} שמות ספקים${d.rate_limited ? ' (נעצר ע"י SUMIT rate-limit — הרץ שוב בעוד מספר דקות)' : ''}`);
      refresh();
    },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בפתרון שמות'),
  });

  const fileAllMutation = useMutation({
    mutationFn: () => apiService.fileAllExpenses(),
    onSuccess: (res: any) => { setMessage(`תויקו ${res?.data?.filed ?? 0}, נכשלו ${res?.data?.failed ?? 0}`); refresh(); },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בתיוק גורף'),
  });

  const statusBadge = (s: string, err?: string) => {
    if (s === 'filed') return <span className="text-green-600 flex items-center gap-1"><CheckCircle className="w-4 h-4" />תויק</span>;
    if (s === 'error') return <span className="text-red-600 flex items-center gap-1" title={err}><XCircle className="w-4 h-4" />שגיאה</span>;
    return <span className="text-amber-600 flex items-center gap-1"><Clock className="w-4 h-4" />ממתין</span>;
  };

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileCheck className="w-8 h-8 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold">תיוק הוצאות</h1>
            <p className="text-sm text-gray-500">יצירת הוצאות ותיוקן ב-SUMIT מתוך המערכת</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowForm(!showForm)}
            className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg flex items-center gap-2 hover:bg-blue-50">
            <Plus className="w-4 h-4" /> הוצאה
          </button>
          <button onClick={() => resolveMutation.mutate()} disabled={resolveMutation.isPending}
            className="px-4 py-2 border border-indigo-600 text-indigo-600 rounded-lg flex items-center gap-2 hover:bg-indigo-50 disabled:opacity-50">
            <Tags className="w-4 h-4" /> פתור שמות ספקים
          </button>
          <button onClick={() => classifyMutation.mutate()} disabled={classifyMutation.isPending}
            className="px-4 py-2 border border-purple-600 text-purple-600 rounded-lg flex items-center gap-2 hover:bg-purple-50 disabled:opacity-50">
            <Tags className="w-4 h-4" /> סווג אוטומטית
          </button>
          <button onClick={() => pcnMutation.mutate()} disabled={pcnMutation.isPending}
            className="px-4 py-2 border border-teal-600 text-teal-600 rounded-lg flex items-center gap-2 hover:bg-teal-50 disabled:opacity-50">
            <FileCheck className="w-4 h-4" /> מוכנות PCN874
          </button>
          <button onClick={() => fileAllMutation.mutate()} disabled={fileAllMutation.isPending}
            className="px-4 py-2 border border-green-600 text-green-600 rounded-lg flex items-center gap-2 hover:bg-green-50 disabled:opacity-50">
            <UploadAll className="w-4 h-4" /> תייק הכל
          </button>
          <button onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg flex items-center gap-2 hover:bg-blue-700 disabled:opacity-50">
            <RefreshCw className={`w-4 h-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} /> משיכה מ-SUMIT
          </button>
        </div>
      </div>

      {message && <div className={`p-3 rounded-lg border ${card}`}>{message}</div>}

      {showForm && (
        <div className={`rounded-xl border p-5 ${card}`}>
          <h2 className="text-lg font-semibold mb-4">הוצאה חדשה</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div><label className="block text-sm mb-1">ספק</label>
              <input className={input} value={form.supplier_name} onChange={(e) => setForm({ ...form, supplier_name: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">סכום (לפני מע"מ)</label>
              <input type="number" className={input} value={form.amount} onChange={(e) => setForm({ ...form, amount: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="block text-sm mb-1">מע"מ</label>
              <input type="number" className={input} value={form.vat_amount} onChange={(e) => setForm({ ...form, vat_amount: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="block text-sm mb-1">תאריך</label>
              <input type="date" className={input} value={form.expense_date} onChange={(e) => setForm({ ...form, expense_date: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">קטגוריה</label>
              <input className={input} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">מס' חשבונית</label>
              <input className={input} value={form.invoice_number} onChange={(e) => setForm({ ...form, invoice_number: e.target.value })} /></div>
          </div>
          <button onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !form.supplier_name}
            className="mt-4 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
            {createMutation.isPending ? 'שומר...' : 'שמירה'}
          </button>
        </div>
      )}

      <div className={`rounded-xl border p-5 ${card}`}>
        {isLoading ? (
          <div className="text-center py-8 text-gray-500">טוען...</div>
        ) : !data || data.length === 0 ? (
          <div className="text-center py-8 text-gray-500">אין הוצאות. צור הוצאה או משוך מ-SUMIT.</div>
        ) : (
          <>
            <p className="text-sm text-gray-500 mb-3">
              אשר/תקן את <b>הפריט (סיווג)</b> ואת <b>הסכום</b> לכל הוצאה לפני התיוק. השדות ניתנים לעריכה.
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-right border-b">
                  <th className="py-2">ספק</th><th>תאריך</th><th>פריט (סיווג)</th><th>סכום</th><th>מע"מ</th><th>סטטוס</th><th></th>
                </tr>
              </thead>
              <tbody>
                {data.map((e) => {
                  const isFiled = e.status === 'filed';
                  return (
                    <tr key={e.id} className="border-b">
                      <td className="py-2">{e.supplier_name}</td>
                      <td>{e.expense_date}</td>
                      <td>
                        {isFiled ? (e.category || '-') : (
                          <input className={cellInput} defaultValue={e.category || ''}
                            onBlur={(ev) => {
                              if (ev.target.value !== (e.category || ''))
                                updateMutation.mutate({ id: e.id, data: { category: ev.target.value } });
                            }} />
                        )}
                      </td>
                      <td>
                        {isFiled ? `₪${e.amount.toLocaleString()}` : (
                          <input type="number" className={cellInput + ' w-28'} defaultValue={e.amount}
                            onBlur={(ev) => {
                              const v = parseFloat(ev.target.value) || 0;
                              if (v !== e.amount) updateMutation.mutate({ id: e.id, data: { amount: v } });
                            }} />
                        )}
                      </td>
                      <td>₪{e.vat_amount.toLocaleString()}</td>
                      <td>{statusBadge(e.status, e.filing_error)}</td>
                      <td>
                        {!isFiled && (
                          <button onClick={() => fileMutation.mutate(e.id)} disabled={fileMutation.isPending}
                            className="px-3 py-1 bg-blue-600 text-white rounded flex items-center gap-1 hover:bg-blue-700 disabled:opacity-50">
                            <Send className="w-3 h-3" /> אשר ותייק
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
};

export default ExpenseFiling;
