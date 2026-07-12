/**
 * ספקים שנדרש להשלים מהם חשבוניות — ספקים ששולם להם בבנק/אשראי בלי
 * שקיים כנגד התשלום מסמך הוצאה/חשבונית, ולכן מע"מ התשומות לא נקלט.
 * מקבץ ברמת ספק מעל מנוע הפער (bank_expense_gap.suppliers_missing_invoices).
 */
import { useEffect, useState } from 'react';
import { FileX, Loader2, AlertTriangle } from 'lucide-react';
import api from '../services/api';

interface Supplier {
  name: string;
  transactions_count: number;
  total: number;
  estimated_vat: number;
  first_date: string | null;
  last_date: string | null;
  sample_descriptions: string[];
}

interface UnidentifiedTransfer {
  date: string | null;
  description: string | null;
  amount: number;
}

interface UnidentifiedTransfers {
  count: number;
  total: number;
  transactions: UnidentifiedTransfer[];
}

interface Report {
  suppliers: Supplier[];
  unidentified_transfers: UnidentifiedTransfers;
  totals: { suppliers_count: number; total: number; estimated_vat: number };
}

const fmt = (n: number) => `₪${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const todayIso = () => new Date().toISOString().slice(0, 10);
const daysAgoIso = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
};

export default function SuppliersMissingInvoices() {
  const [dateFrom, setDateFrom] = useState(daysAgoIso(90));
  const [dateTo, setDateTo] = useState(todayIso());
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Report>(
        `/api/daily-reports/suppliers-missing-invoices?date_from=${dateFrom}&date_to=${dateTo}`
      );
      setReport(res);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת ספקים חסרי חשבונית');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-2">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileX className="text-indigo-600" /> ספקים חסרי חשבונית
        </h1>
        <div className="flex items-center gap-2">
          <div>
            <label className="block text-xs text-slate-500 mb-1">מתאריך</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="border rounded-lg px-2 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">עד תאריך</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="border rounded-lg px-2 py-2 text-sm" />
          </div>
          <button onClick={load} disabled={loading}
            className="mt-4 inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700 disabled:opacity-50">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            רענן
          </button>
        </div>
      </div>
      <p className="text-xs text-slate-400 mb-5">
        ספקים ששולם להם בבנק/כרטיס אשראי אך אין כנגד התשלום מסמך הוצאה/חשבונית — מע"מ התשומות לא נקלט.
      </p>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : report ? (
        <>
          <div className="mb-6 border rounded-xl p-4 bg-indigo-50/40">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm items-center">
              <span>ספקים: {report.totals.suppliers_count}</span>
              <span className="font-bold text-rose-600">סה"כ ששולם ללא חשבונית: {fmt(report.totals.total)}</span>
              <span className="font-bold text-rose-600">מע"מ משוער אבוד: {fmt(report.totals.estimated_vat)}</span>
            </div>
          </div>

          <div className="border rounded-xl p-4 mb-6 overflow-x-auto">
            <h2 className="font-semibold mb-3">ספקים</h2>
            {report.suppliers.length === 0 ? (
              <div className="text-slate-400 text-sm py-6 text-center">אין ספקים חסרי חשבונית בטווח שנבחר.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-slate-500 border-b">
                  <tr>
                    <th className="text-right py-2">ספק</th>
                    <th className="text-right py-2">מס' תשלומים</th>
                    <th className="text-right py-2">סה"כ ששולם</th>
                    <th className="text-right py-2">מע"מ משוער אבוד</th>
                    <th className="text-right py-2">טווח תאריכים</th>
                    <th className="text-right py-2">דוגמאות</th>
                  </tr>
                </thead>
                <tbody>
                  {report.suppliers.map((s) => (
                    <tr key={s.name} className="border-b last:border-0 align-top">
                      <td className="py-2 font-medium">{s.name}</td>
                      <td className="py-2">{s.transactions_count}</td>
                      <td className="py-2 font-medium">{fmt(s.total)}</td>
                      <td className="py-2 text-rose-600">{fmt(s.estimated_vat)}</td>
                      <td className="py-2 text-slate-500 whitespace-nowrap">
                        {s.first_date} — {s.last_date}
                      </td>
                      <td className="py-2 text-slate-500 max-w-xs">
                        {s.sample_descriptions.map((d, i) => <div key={i} className="truncate">{d}</div>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {report.unidentified_transfers.count > 0 && (
            <div className="border rounded-xl p-4 bg-amber-50/40">
              <h2 className="font-semibold flex items-center gap-2 mb-2 text-amber-800">
                <AlertTriangle className="w-4 h-4" /> העברות ללא זיהוי נמען
              </h2>
              <p className="text-xs text-slate-500 mb-3">
                תנועות בנק כלליות (העברה לבנק אחר / הוראת קבע וכד') שלא ניתן לזהות בהן שם ספק ספציפי —
                דורשות בדיקה ידנית ולא מוצגות כ"ספק".
              </p>
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm items-center mb-3">
                <span>מס' תנועות: {report.unidentified_transfers.count}</span>
                <span className="font-bold text-amber-800">סה"כ: {fmt(report.unidentified_transfers.total)}</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-slate-500 border-b">
                    <tr>
                      <th className="text-right py-2">תאריך</th>
                      <th className="text-right py-2">תיאור</th>
                      <th className="text-right py-2">סכום</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.unidentified_transfers.transactions.map((t, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="py-2 text-slate-500 whitespace-nowrap">{t.date}</td>
                        <td className="py-2">{t.description}</td>
                        <td className="py-2 font-medium">{fmt(t.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
