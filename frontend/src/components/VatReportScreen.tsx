/**
 * דיווח מע"מ מרצף — דוח תקופתי (חודשי/דו-חודשי) לפי בסיס מסמך או בסיס קליטה,
 * עם הורדת קובץ PCN874 להגשה ויצוא "מבנה אחיד" (INI+BKMVDATA) לחשבשבת
 * ותוכנות הנה"ח אחרות. הקבצים מסומנים טיוטה עד אימות חד-פעמי מול בודק
 * הקבצים של רשות המסים — המספרים עצמם מתואמים 1:1 לדוח המע"מ הקנוני.
 */
import { useEffect, useState } from 'react';
import { Landmark, Loader2, Download, FileArchive } from 'lucide-react';
import api from '../services/api';
import ExportButtons, { ExportSheet } from './ExportButtons';

interface BreakdownRow {
  period: string;
  output_vat: number;
  input_vat: number;
  net_vat: number;
  sales_documents: number;
  purchase_documents: number;
}

interface VatDocument {
  type: string;
  number: string | null;
  doc_date: string | null;
  captured_date: string | null;
  counterparty: string | null;
  amount: number;
  vat: number;
}

interface VerificationCheck {
  name: string;
  label: string;
  passed: boolean | null; // null = אזהרה
  details: string;
  pending_drafts?: number;
}

interface Verification {
  status: 'pass' | 'warn' | 'fail';
  checks: VerificationCheck[];
}

interface VatReport {
  period: string;
  months: number;
  basis: string;
  due_date: string;
  output_vat: number;
  input_vat: number;
  net_vat: number;
  direction: string;
  amount_to_report: number;
  sales_documents: number;
  purchase_documents: number;
  breakdown: BreakdownRow[];
  documents: VatDocument[];
  disclaimer: string;
}

const fmt = (n: number) => `₪${n.toLocaleString('he-IL', { maximumFractionDigits: 2 })}`;

const MONTH_NAMES = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני',
  'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];

const DOC_TYPE_LABELS: Record<string, string> = {
  invoice: 'חשבונית מכירה',
  bill: 'חשבונית ספק',
  expense: 'הוצאה',
};

/** הורדת קובץ מה-API עם אימות (axios blob) — קישור ישיר לא נושא JWT. */
async function downloadAuthenticated(url: string, filename: string) {
  const blob = await api.get<Blob>(url, { responseType: 'blob' });
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

export default function VatReportScreen() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  // עוגן דו-חודשי: חודש אי-זוגי (1,3,5...) — ברירת מחדל: התקופה הקודמת שהסתיימה.
  const [month, setMonth] = useState(() => {
    const m = now.getMonth() + 1; // 1..12
    const anchor = m % 2 === 0 ? m - 1 : m - 2;
    return anchor >= 1 ? anchor : 11;
  });
  const [months, setMonths] = useState<1 | 2>(2);
  const [basis, setBasis] = useState<'document' | 'captured'>('document');
  const [vatId, setVatId] = useState(() => localStorage.getItem('vat_report_company_vat_id') || '');
  const [report, setReport] = useState<VatReport | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<VatReport>(
        `/api/daily-reports/vat?year=${year}&month=${month}&months=${months}&basis=${basis}`
      );
      setReport(res);
      // אימות משולש — כלל מחייב: שלוש בדיקות בלתי-תלויות לכל פלט דיווח.
      setVerification(null);
      api.get<Verification>(
        `/api/daily-reports/vat/verify?year=${year}&month=${month}&months=${months}&basis=${basis}`
      ).then(setVerification).catch(() => setVerification({
        status: 'fail',
        checks: [{ name: 'error', label: 'אימות', passed: false, details: 'הרצת האימות נכשלה — אין להגיש ללא אימות.' }],
      }));
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת דוח המע"מ');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [year, month, months, basis]);

  const saveVatId = (v: string) => {
    setVatId(v);
    localStorage.setItem('vat_report_company_vat_id', v);
  };

  const periodLabel = months === 2
    ? `${MONTH_NAMES[month - 1]}-${MONTH_NAMES[Math.min(month, 11)]} ${year}`
    : `${MONTH_NAMES[month - 1]} ${year}`;

  const periodDates = () => {
    const start = `${year}-${String(month).padStart(2, '0')}-01`;
    const endMonth = months === 2 ? month + 1 : month;
    const lastDay = new Date(year, endMonth, 0).getDate();
    const end = `${year}-${String(endMonth).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
    return { start, end };
  };

  const downloadPcn = async () => {
    setDownloading('pcn');
    try {
      await downloadAuthenticated(
        `/api/daily-reports/pcn874/file?year=${year}&month=${month}&months=${months}&basis=${basis}&company_vat_id=${encodeURIComponent(vatId || '000000000')}`,
        `PCN874_${report?.period || `${year}-${month}`}.txt`,
      );
    } catch (e: any) {
      setError('הורדת PCN874 נכשלה');
    } finally {
      setDownloading(null);
    }
  };

  const downloadOpenfrmt = async () => {
    setDownloading('openfrmt');
    const { start, end } = periodDates();
    try {
      await downloadAuthenticated(
        `/api/daily-reports/openfrmt?date_from=${start}&date_to=${end}`,
        `OPENFRMT_${start}_${end}.zip`,
      );
    } catch (e: any) {
      setError('יצוא מבנה אחיד נכשל');
    } finally {
      setDownloading(null);
    }
  };

  const exportSheets: ExportSheet[] = report ? [
    {
      name: 'פירוט חודשי',
      columns: [
        { key: 'period', label: 'חודש' },
        { key: 'output_vat', label: 'מע"מ עסקאות' },
        { key: 'input_vat', label: 'מע"מ תשומות' },
        { key: 'net_vat', label: 'נטו' },
        { key: 'sales_documents', label: 'מסמכי מכירה' },
        { key: 'purchase_documents', label: 'מסמכי תשומות' },
      ],
      rows: report.breakdown.map((b) => ({ ...b })),
      summary: [
        { label: 'עסקאות', value: fmt(report.output_vat) },
        { label: 'תשומות', value: fmt(report.input_vat) },
        { label: report.direction, value: fmt(report.amount_to_report) },
      ],
    },
    {
      name: 'מסמכים שנכללו',
      columns: [
        { key: 'type', label: 'סוג' },
        { key: 'number', label: 'מספר' },
        { key: 'doc_date', label: 'תאריך מסמך' },
        { key: 'captured_date', label: 'תאריך קליטה' },
        { key: 'counterparty', label: 'לקוח/ספק' },
        { key: 'amount', label: 'סכום לפני מע"מ' },
        { key: 'vat', label: 'מע"מ' },
      ],
      rows: report.documents.map((d) => ({
        ...d,
        type: DOC_TYPE_LABELS[d.type] || d.type,
        number: d.number || '',
        doc_date: d.doc_date || '',
        captured_date: d.captured_date || '',
        counterparty: d.counterparty || '',
      })),
    },
  ] : [];

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-2">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Landmark className="text-indigo-600" /> דיווח מע"מ
        </h1>
        <div className="flex items-end gap-2 flex-wrap">
          <div>
            <label className="block text-xs text-slate-500 mb-1">שנה</label>
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}
              className="border rounded-lg px-2 py-2 text-sm">
              {[year - 2, year - 1, year, year + 1].filter((y, i, a) => a.indexOf(y) === i).map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">תקופה</label>
            <select value={month} onChange={(e) => setMonth(Number(e.target.value))}
              className="border rounded-lg px-2 py-2 text-sm">
              {(months === 2 ? [1, 3, 5, 7, 9, 11] : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]).map((m) => (
                <option key={m} value={m}>
                  {months === 2 ? `${MONTH_NAMES[m - 1]}-${MONTH_NAMES[m]}` : MONTH_NAMES[m - 1]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">תדירות</label>
            <select value={months} onChange={(e) => {
              const v = Number(e.target.value) as 1 | 2;
              setMonths(v);
              if (v === 2 && month % 2 === 0) setMonth(month - 1);
            }} className="border rounded-lg px-2 py-2 text-sm">
              <option value={2}>דו-חודשי</option>
              <option value={1}>חודשי</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">בסיס דיווח (תשומות)</label>
            <select value={basis} onChange={(e) => setBasis(e.target.value as 'document' | 'captured')}
              className="border rounded-lg px-2 py-2 text-sm">
              <option value="document">תאריך מסמך</option>
              <option value="captured">מועד קליטה</option>
            </select>
          </div>
        </div>
      </div>
      <p className="text-xs text-slate-400 mb-5">
        עסקאות מדווחות תמיד לפי תאריך המסמך; "מועד קליטה" משפיע על צד התשומות בלבד
        (קיזוז לפי מועד קליטת החשבונית ברצף, עד חצי שנה אחורה כדין).
      </p>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : report ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div className="border rounded-xl p-4">
              <div className="text-xs text-slate-500 mb-1">מע"מ עסקאות</div>
              <div className="text-xl font-bold">{fmt(report.output_vat)}</div>
              <div className="text-xs text-slate-400">{report.sales_documents} מסמכים</div>
            </div>
            <div className="border rounded-xl p-4">
              <div className="text-xs text-slate-500 mb-1">מע"מ תשומות</div>
              <div className="text-xl font-bold">{fmt(report.input_vat)}</div>
              <div className="text-xs text-slate-400">{report.purchase_documents} מסמכים</div>
            </div>
            <div className={`border rounded-xl p-4 ${report.net_vat >= 0 ? 'bg-amber-50/50' : 'bg-emerald-50/50'}`}>
              <div className="text-xs text-slate-500 mb-1">{report.direction}</div>
              <div className={`text-xl font-bold ${report.net_vat >= 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                {fmt(report.amount_to_report)}
              </div>
              <div className="text-xs text-slate-400">מועד דיווח: {report.due_date}</div>
            </div>
            <div className="border rounded-xl p-4 flex flex-col justify-center gap-2">
              <button onClick={downloadPcn} disabled={downloading !== null}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-xs hover:bg-indigo-700 disabled:opacity-50">
                {downloading === 'pcn' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                קובץ PCN874 להגשה
              </button>
              <button onClick={downloadOpenfrmt} disabled={downloading !== null}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-indigo-200 text-indigo-700 text-xs hover:bg-indigo-50 disabled:opacity-50">
                {downloading === 'openfrmt' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileArchive className="w-3.5 h-3.5" />}
                מבנה אחיד (חשבשבת)
              </button>
              {report && (
                <ExportButtons
                  title={`דוח מע"מ ${report.period}`}
                  meta={`תקופה: ${periodLabel} · בסיס: ${basis === 'captured' ? 'מועד קליטה' : 'תאריך מסמך'}`}
                  sheets={exportSheets}
                  className="justify-center"
                />
              )}
            </div>
          </div>

          <div className={`border rounded-xl p-4 mb-4 ${
            !verification ? 'bg-slate-50' :
            verification.status === 'pass' ? 'bg-emerald-50/60 border-emerald-200' :
            verification.status === 'warn' ? 'bg-amber-50/60 border-amber-300' :
            'bg-red-50/70 border-red-300'
          }`}>
            <h2 className="font-semibold mb-2 text-sm">
              אימות משולש לפני הגשה
              {!verification ? ' — רץ...' :
                verification.status === 'pass' ? ' — כל הבדיקות עברו ✓' :
                verification.status === 'warn' ? ' — עבר עם אזהרות ⚠️' :
                ' — נכשל! אין להגיש ✗'}
            </h2>
            {verification && (
              <ul className="space-y-1.5 text-xs">
                {verification.checks.map((c) => (
                  <li key={c.name} className="flex gap-2 items-start">
                    <span className={
                      c.passed === true ? 'text-emerald-600 font-bold' :
                      c.passed === null ? 'text-amber-600 font-bold' : 'text-red-600 font-bold'
                    }>
                      {c.passed === true ? '✓' : c.passed === null ? '⚠️' : '✗'}
                    </span>
                    <span><strong>{c.label}:</strong> {c.details}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="flex items-center gap-2 mb-5">
            <label className="text-xs text-slate-500">מספר עוסק לקובץ PCN874:</label>
            <input value={vatId} onChange={(e) => saveVatId(e.target.value)} placeholder="9 ספרות"
              className="border rounded-lg px-2 py-1.5 text-sm w-32" dir="ltr" />
          </div>

          <div className="border rounded-xl p-4 mb-6 overflow-x-auto">
            <h2 className="font-semibold mb-3">פירוט חודשי</h2>
            <table className="w-full text-sm">
              <thead className="text-slate-500 border-b">
                <tr>
                  <th className="text-right py-2">חודש</th>
                  <th className="text-right py-2">מע"מ עסקאות</th>
                  <th className="text-right py-2">מע"מ תשומות</th>
                  <th className="text-right py-2">נטו</th>
                  <th className="text-right py-2">מסמכי מכירה</th>
                  <th className="text-right py-2">מסמכי תשומות</th>
                </tr>
              </thead>
              <tbody>
                {report.breakdown.map((b) => (
                  <tr key={b.period} className="border-b last:border-0">
                    <td className="py-2 font-medium">{b.period}</td>
                    <td className="py-2">{fmt(b.output_vat)}</td>
                    <td className="py-2">{fmt(b.input_vat)}</td>
                    <td className="py-2">{fmt(b.net_vat)}</td>
                    <td className="py-2">{b.sales_documents}</td>
                    <td className="py-2">{b.purchase_documents}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="border rounded-xl p-4 mb-4 overflow-x-auto">
            <h2 className="font-semibold mb-3">מסמכים שנכללו ({report.documents.length})</h2>
            {report.documents.length === 0 ? (
              <div className="text-slate-400 text-sm py-6 text-center">אין מסמכים בתקופה שנבחרה.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-slate-500 border-b">
                  <tr>
                    <th className="text-right py-2">סוג</th>
                    <th className="text-right py-2">מספר</th>
                    <th className="text-right py-2">תאריך מסמך</th>
                    <th className="text-right py-2">תאריך קליטה</th>
                    <th className="text-right py-2">לקוח/ספק</th>
                    <th className="text-right py-2">סכום לפני מע"מ</th>
                    <th className="text-right py-2">מע"מ</th>
                  </tr>
                </thead>
                <tbody>
                  {report.documents.map((d, i) => (
                    <tr key={`${d.type}-${d.number}-${i}`} className="border-b last:border-0">
                      <td className="py-2">{DOC_TYPE_LABELS[d.type] || d.type}</td>
                      <td className="py-2">{d.number || '—'}</td>
                      <td className="py-2 whitespace-nowrap">{d.doc_date || '—'}</td>
                      <td className="py-2 whitespace-nowrap text-slate-500">{d.captured_date || '—'}</td>
                      <td className="py-2">{d.counterparty || '—'}</td>
                      <td className="py-2">{fmt(d.amount)}</td>
                      <td className="py-2 font-medium">{fmt(d.vat)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <p className="text-xs text-amber-600">{report.disclaimer}</p>
        </>
      ) : null}
    </div>
  );
}
