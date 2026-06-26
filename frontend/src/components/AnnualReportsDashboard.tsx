/**
 * Annual tax-return DRAFTS — 1301 (יחיד) / 1214 (חברה).
 * Draft-only, derived from the shadow ledger. Prominent "לבדיקת רו"ח" banner.
 */
import { useEffect, useState } from 'react';
import { FileWarning, Loader2 } from 'lucide-react';
import api from '../services/api';

type FormKey = '1301' | '1214';
interface ReportDraft {
  form: string; title: string; year: number;
  fields: Record<string, number>; draft: boolean; disclaimer: string; notes: string[];
}

const now = new Date();
const fmt = (n: number) =>
  typeof n === 'number' && Math.abs(n) >= 1
    ? `₪${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : String(n);

const FIELD_LABELS: Record<string, string> = {
  business_revenue: 'הכנסות מעסק', business_expenses: 'הוצאות מעסק', business_income: 'הכנסה חייבת מעסק',
  gross_income_tax: 'מס הכנסה (ברוטו)', credit_points: 'נקודות זיכוי', credit_points_value: 'ערך נקודות זיכוי',
  income_tax_due: 'מס הכנסה לתשלום', revenue: 'הכנסות', expenses: 'הוצאות',
  net_profit_before_tax: 'רווח לפני מס', taxable_income: 'הכנסה חייבת', corporate_tax_rate: 'שיעור מס חברות',
  corporate_tax_due: 'מס חברות לתשלום', net_profit_after_tax: 'רווח לאחר מס',
};

export default function AnnualReportsDashboard() {
  const [form, setForm] = useState<FormKey>('1214');
  const [year, setYear] = useState(now.getFullYear() - 1);
  const [data, setData] = useState<ReportDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      setData(await api.get<ReportDraft>(`/api/annual-reports/${form}?year=${year}`));
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת הטיוטה');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [form, year]);

  return (
    <div className="p-6 max-w-3xl mx-auto" dir="rtl">
      <h1 className="text-2xl font-bold flex items-center gap-2 mb-3">
        <FileWarning className="text-amber-500" /> דוחות שנתיים — טיוטה
      </h1>

      <div className="mb-5 p-4 rounded-lg bg-amber-100 border border-amber-300 text-amber-900 text-sm">
        <b>טיוטה אוטומטית בלבד.</b> נגזרת מהמסמכים, ללא התאמות מס. <b>אינה דוח להגשה</b> —
        חובה בדיקה והשלמה ע"י רו"ח.
      </div>

      <div className="flex gap-2 mb-5 flex-wrap items-center">
        {(['1214', '1301'] as FormKey[]).map((k) => (
          <button key={k} onClick={() => setForm(k)}
            className={`px-3 py-2 rounded-lg text-sm ${form === k ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
            {k === '1214' ? '1214 — חברה' : '1301 — יחיד'}
          </button>
        ))}
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm w-24" />
      </div>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : data && (
        <div className="border rounded-xl overflow-hidden">
          <div className="bg-slate-100 px-4 py-3 font-semibold">{data.title} ({data.form}) — {data.year}</div>
          <table className="w-full text-sm">
            <tbody>
              {Object.entries(data.fields).map(([k, v]) => (
                <tr key={k} className="border-t">
                  <td className="px-4 py-2 text-slate-600">{FIELD_LABELS[k] || k}</td>
                  <td className="px-4 py-2 text-left font-medium">
                    {k.includes('rate') ? `${(v * 100).toFixed(0)}%` : k === 'credit_points' ? v : fmt(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.notes?.length > 0 && (
            <ul className="px-6 py-3 text-xs text-slate-500 list-disc space-y-1 bg-slate-50">
              {data.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
