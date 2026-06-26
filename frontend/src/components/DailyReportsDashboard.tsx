/**
 * Daily-cumulative intra-month reports — P&L מצטבר יומי, גיול חובות/ספקים, ופירוט ספקים.
 * Derived from synced SUMIT documents.
 */
import { useEffect, useState } from 'react';
import { TrendingUp, Loader2, Clock, Building2, Download } from 'lucide-react';
import api from '../services/api';

interface PLDay { date: string; revenue_cum: number; expense_cum: number; profit_cum: number; }
interface PLReport { period: string; days: PLDay[]; totals: { revenue: number; expense: number; profit: number }; }
interface Aging { buckets: Record<string, number>; total: number; as_of: string; }
interface Suppliers { suppliers: { supplier: string; total: number }[]; total: number; }
interface VatReport {
  period: string; due_date: string; output_vat: number; input_vat: number;
  net_vat: number; direction: string; amount_to_report: number;
  sales_documents: number; purchase_documents: number; disclaimer: string;
}

const now = new Date();
const fmt = (n: number) => `₪${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const BUCKET_LABELS: Record<string, string> = {
  current: 'שוטף', '1_30': '1–30 יום', '31_60': '31–60', '61_90': '61–90', '90_plus': '90+ יום',
};

export default function DailyReportsDashboard() {
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [pl, setPl] = useState<PLReport | null>(null);
  const [ar, setAr] = useState<Aging | null>(null);
  const [ap, setAp] = useState<Aging | null>(null);
  const [sup, setSup] = useState<Suppliers | null>(null);
  const [vat, setVat] = useState<VatReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [p, a, b, s, v] = await Promise.all([
        api.get<PLReport>(`/api/daily-reports/cumulative-pl?year=${year}&month=${month}`),
        api.get<Aging>('/api/daily-reports/ar-aging'),
        api.get<Aging>('/api/daily-reports/ap-aging'),
        api.get<Suppliers>(`/api/daily-reports/suppliers?year=${year}&month=${month}`),
        api.get<VatReport>(`/api/daily-reports/vat?year=${year}&month=${month}`),
      ]);
      setPl(p); setAr(a); setAp(b); setSup(s); setVat(v);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת הדוחות');
    } finally { setLoading(false); }
  };

  const downloadPcn874 = async () => {
    try {
      const r = await api.get<{ content: string; filename: string }>(
        `/api/daily-reports/pcn874?year=${year}&month=${month}`);
      const blob = new Blob([r.content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = r.filename; a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בהפקת PCN874');
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [year, month]);

  const maxProfit = pl ? Math.max(1, ...pl.days.map((d) => Math.abs(d.profit_cum))) : 1;

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-2">
        <h1 className="text-2xl font-bold flex items-center gap-2"><TrendingUp className="text-indigo-600" /> דוחות מצטברים-יומיים</h1>
        <div className="flex items-center gap-2">
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm">
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm w-24" />
        </div>
      </div>
      <p className="text-xs text-slate-400 mb-5">נגזר ממסמכי SUMIT — לבדיקת רו"ח.</p>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : (
        <>
          {vat && (
            <div className="mb-6 border rounded-xl p-4 bg-indigo-50/40">
              <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
                <h2 className="font-semibold">דוח מע"מ — {vat.period}</h2>
                <span className="text-xs text-slate-400">להגשה עד {vat.due_date}</span>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm items-center">
                <span>עסקאות: {fmt(vat.output_vat)} ({vat.sales_documents} מסמכים)</span>
                <span>תשומות: {fmt(vat.input_vat)} ({vat.purchase_documents} מסמכים)</span>
                <span className={`font-bold ${vat.net_vat >= 0 ? 'text-rose-600' : 'text-emerald-700'}`}>
                  {vat.direction} {fmt(vat.amount_to_report)}
                </span>
                <button onClick={downloadPcn874}
                  className="ms-auto inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs hover:bg-indigo-700">
                  <Download className="w-3.5 h-3.5" /> הורד PCN874 (טיוטה)
                </button>
              </div>
              <p className="text-xs text-slate-400 mt-2">{vat.disclaimer}</p>
            </div>
          )}

          {pl && (
            <div className="mb-6 border rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-semibold">רווח/הפסד מצטבר — {pl.period}</h2>
                <div className="text-sm flex gap-4">
                  <span className="text-emerald-700">הכנסות {fmt(pl.totals.revenue)}</span>
                  <span className="text-rose-600">הוצאות {fmt(pl.totals.expense)}</span>
                  <span className={`font-bold ${pl.totals.profit >= 0 ? 'text-emerald-700' : 'text-rose-600'}`}>רווח {fmt(pl.totals.profit)}</span>
                </div>
              </div>
              {/* lightweight cumulative bars */}
              <div className="flex items-end gap-0.5 h-28">
                {pl.days.map((d) => (
                  <div key={d.date} title={`${d.date}: ${fmt(d.profit_cum)}`}
                    className={`flex-1 rounded-t ${d.profit_cum >= 0 ? 'bg-emerald-400' : 'bg-rose-400'}`}
                    style={{ height: `${Math.max(2, (Math.abs(d.profit_cum) / maxProfit) * 100)}%` }} />
                ))}
              </div>
            </div>
          )}

          <div className="grid md:grid-cols-2 gap-4 mb-6">
            {[{ title: 'גיול חובות לקוחות (AR)', data: ar }, { title: 'גיול ספקים (AP)', data: ap }].map(({ title, data }) => (
              <div key={title} className="border rounded-xl p-4">
                <h2 className="font-semibold flex items-center gap-2 mb-3"><Clock className="w-4 h-4 text-indigo-600" /> {title}</h2>
                {data ? (
                  <>
                    <table className="w-full text-sm">
                      <tbody>
                        {Object.entries(data.buckets).map(([k, v]) => (
                          <tr key={k} className="border-t first:border-0">
                            <td className="py-1.5 text-slate-600">{BUCKET_LABELS[k] || k}</td>
                            <td className="py-1.5 text-left font-medium">{fmt(v)}</td>
                          </tr>
                        ))}
                        <tr className="border-t font-bold"><td className="py-1.5">סה"כ</td><td className="py-1.5 text-left">{fmt(data.total)}</td></tr>
                      </tbody>
                    </table>
                  </>
                ) : <div className="text-slate-400 text-sm">אין נתונים</div>}
              </div>
            ))}
          </div>

          {sup && sup.suppliers.length > 0 && (
            <div className="border rounded-xl p-4">
              <h2 className="font-semibold flex items-center gap-2 mb-3"><Building2 className="w-4 h-4 text-indigo-600" /> ספקים — {pl?.period}</h2>
              <table className="w-full text-sm">
                <tbody>
                  {sup.suppliers.map((s) => (
                    <tr key={s.supplier} className="border-t first:border-0">
                      <td className="py-1.5">{s.supplier}</td>
                      <td className="py-1.5 text-left font-medium">{fmt(s.total)}</td>
                    </tr>
                  ))}
                  <tr className="border-t font-bold"><td className="py-1.5">סה"כ</td><td className="py-1.5 text-left">{fmt(sup.total)}</td></tr>
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
