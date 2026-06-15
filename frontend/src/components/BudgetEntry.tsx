import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Target, Upload, Download, Plus, Trash2, Save } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

interface Row {
  category: string;
  amount: number;
}

const MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];

const BudgetEntry: React.FC<Props> = ({ darkMode }) => {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [rows, setRows] = useState<Row[]>([
    { category: 'sales', amount: 0 },
    { category: 'materials', amount: 0 },
    { category: 'rent', amount: 0 },
    { category: 'salaries', amount: 0 },
  ]);
  const [message, setMessage] = useState<string | null>(null);

  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';
  const input = `px-3 py-2 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`;

  const saveMutation = useMutation({
    mutationFn: () => apiService.saveBudgetsBulk(
      rows.filter(r => r.category.trim()).map(r => ({ category: r.category.trim(), year, month, amount: r.amount || 0 }))
    ),
    onSuccess: (res: any) => setMessage(`נשמרו ${res?.data?.saved ?? rows.length} שורות תקציב`),
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בשמירה'),
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => apiService.importBudgetExcel(file),
    onSuccess: (res: any) => setMessage(`יובאו ${res?.data?.saved ?? 0} שורות (${res?.data?.skipped ?? 0} דולגו)`),
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בייבוא'),
  });

  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Target className="w-8 h-8 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold">הזנת תקציב</h1>
          <p className="text-sm text-gray-500">הזנה ידנית נוחה או ייבוא מקובץ Excel</p>
        </div>
      </div>

      {message && <div className={`p-3 rounded-lg border ${card}`}>{message}</div>}

      <div className={`rounded-xl border p-5 ${card} flex flex-wrap items-end gap-4`}>
        <div>
          <label className="block text-sm mb-1">שנה</label>
          <input type="number" className={input} value={year} onChange={(e) => setYear(parseInt(e.target.value) || year)} />
        </div>
        <div>
          <label className="block text-sm mb-1">חודש</label>
          <select className={input} value={month} onChange={(e) => setMonth(parseInt(e.target.value))}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
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
        <table className="w-full text-sm">
          <thead>
            <tr className="text-right border-b">
              <th className="py-2">קטגוריה</th>
              <th>סכום מתוכנן</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b">
                <td className="py-2">
                  <input className={input + ' w-full'} value={r.category}
                    onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, category: e.target.value } : x))} />
                </td>
                <td>
                  <input type="number" className={input + ' w-40'} value={r.amount}
                    onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, amount: parseFloat(e.target.value) || 0 } : x))} />
                </td>
                <td>
                  <button onClick={() => setRows(rows.filter((_, j) => j !== i))} className="text-red-500 p-1">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between mt-4">
          <button onClick={() => setRows([...rows, { category: '', amount: 0 }])}
            className="px-3 py-2 border border-gray-400 rounded-lg flex items-center gap-2 hover:bg-gray-50">
            <Plus className="w-4 h-4" /> הוספת שורה
          </button>
          <div className="text-lg font-bold">סה"כ: ₪{total.toLocaleString()}</div>
        </div>
        <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}
          className="mt-4 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2">
          <Save className="w-4 h-4" /> {saveMutation.isPending ? 'שומר...' : 'שמירת תקציב'}
        </button>
      </div>
    </div>
  );
};

export default BudgetEntry;
