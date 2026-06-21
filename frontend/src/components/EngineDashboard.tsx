/**
 * The unifying engine — command center. One view over status + the full pipeline,
 * with a state tag on every section (real / derived / unvalidated).
 */
import { useEffect, useState } from 'react';
import { Cpu, Loader2, CheckCircle2, AlertTriangle, Plug } from 'lucide-react';
import api from '../services/api';

interface Status {
  connections: { sumit: boolean; open_finance: boolean };
  counts: Record<string, number>;
  bank_data_validated: boolean; ready: boolean;
}
interface Finding { type: string; severity: string; title: string; message: string; }
interface Stage { stage: string; state: string; summary?: any; error?: string; disclaimer?: string; findings?: Finding[]; }
interface PipelineResult {
  period: string; status: Status; stages: Stage[]; legend: Record<string, string>;
}

const STATE_STYLE: Record<string, string> = {
  real: 'bg-emerald-100 text-emerald-800',
  derived: 'bg-indigo-100 text-indigo-800',
  unvalidated: 'bg-amber-100 text-amber-800',
};
const STATE_LABEL: Record<string, string> = { real: 'אמיתי', derived: 'נגזר', unvalidated: 'לא מאומת' };
const STAGE_LABEL: Record<string, string> = {
  ledger: 'הנהלת חשבונות כפולה', synthesis: 'סינתזה (ספרים מול בנק)',
  aging: 'גיול חובות', cumulative_pl: 'רווח/הפסד מצטבר', anomalies: 'מסמכים חריגים',
};
const SEV_STYLE: Record<string, string> = {
  high: 'bg-red-50 text-red-800 border-red-200',
  medium: 'bg-amber-50 text-amber-800 border-amber-200',
  info: 'bg-slate-50 text-slate-700 border-slate-200',
};
const COUNT_LABEL: Record<string, string> = {
  invoices: 'חשבוניות', bills: 'חשבונות ספק', expenses: 'הוצאות',
  bank_transactions: 'תנועות בנק', employees: 'עובדים', insights: 'תובנות',
};
const fmt = (n: number) => `₪${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export default function EngineDashboard() {
  const [data, setData] = useState<PipelineResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true); setError(null);
    try {
      setData(await api.get<PipelineResult>('/api/engine/run'));
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בהרצת המנוע');
    } finally { setLoading(false); }
  };

  useEffect(() => { run(); /* eslint-disable-next-line */ }, []);

  const st = data?.status;

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <h1 className="text-2xl font-bold flex items-center gap-2"><Cpu className="text-indigo-600" /> המנוע המאחד</h1>
        <button onClick={run} disabled={loading}
          className="inline-flex items-center gap-1 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700 disabled:opacity-50">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />} הרץ
        </button>
      </div>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {st && (
        <div className="grid md:grid-cols-3 gap-4 mb-6">
          <div className="border rounded-xl p-4">
            <h2 className="font-semibold flex items-center gap-2 mb-3"><Plug className="w-4 h-4 text-indigo-600" /> חיבורים</h2>
            <div className="flex items-center gap-2 text-sm mb-1">
              {st.connections.sumit ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <AlertTriangle className="w-4 h-4 text-amber-500" />} SUMIT
            </div>
            <div className="flex items-center gap-2 text-sm">
              {st.connections.open_finance ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <AlertTriangle className="w-4 h-4 text-amber-500" />} Open Finance
              {!st.bank_data_validated && <span className="text-xs text-amber-600">(טרם אומת חי)</span>}
            </div>
          </div>
          <div className="border rounded-xl p-4 md:col-span-2">
            <h2 className="font-semibold mb-3">נתונים זמינים</h2>
            <div className="grid grid-cols-3 gap-2 text-sm">
              {Object.entries(st.counts).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b py-1">
                  <span className="text-slate-600">{COUNT_LABEL[k] || k}</span>
                  <span className="font-semibold">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {loading && !data ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : data && (
        <div className="space-y-3">
          {data.stages.map((s, i) => (
            <div key={i} className="border rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">{STAGE_LABEL[s.stage] || s.stage}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${STATE_STYLE[s.state] || 'bg-slate-100'}`}>
                  {STATE_LABEL[s.state] || s.state}
                </span>
              </div>
              {s.error ? (
                <div className="text-sm text-rose-600">{s.error}</div>
              ) : (
                <div className="text-sm text-slate-600 flex flex-wrap gap-x-6 gap-y-1">
                  {s.stage === 'ledger' && s.summary && (
                    <>
                      <span>{s.summary.balanced ? '✓ מאוזן' : '✗ לא מאוזן'}</span>
                      <span>{s.summary.entry_count} פקודות</span>
                      <span>חובה {fmt(s.summary.total_debit)}</span>
                      <span>זכות {fmt(s.summary.total_credit)}</span>
                    </>
                  )}
                  {s.stage === 'synthesis' && s.summary && (
                    <>
                      <span>{s.summary.required_actions} פעולות נדרשות</span>
                      {s.summary.vat && <span>מע"מ נטו {fmt(s.summary.vat.net_vat)} ({s.summary.vat.direction})</span>}
                    </>
                  )}
                  {s.stage === 'aging' && s.summary && (
                    <>
                      <span>חוב לקוחות {fmt(s.summary.ar)}</span>
                      <span>חוב לספקים {fmt(s.summary.ap)}</span>
                    </>
                  )}
                  {s.stage === 'cumulative_pl' && s.summary && (
                    <>
                      <span>הכנסות {fmt(s.summary.revenue)}</span>
                      <span>הוצאות {fmt(s.summary.expense)}</span>
                      <span className="font-semibold">רווח {fmt(s.summary.profit)}</span>
                    </>
                  )}
                  {s.stage === 'anomalies' && (
                    <span className={s.summary?.count ? 'text-red-700 font-semibold' : 'text-emerald-700'}>
                      {s.summary?.count ? `${s.summary.count} מסמכים חריגים לבדיקה` : 'לא נמצאו חריגים'}
                    </span>
                  )}
                </div>
              )}
              {s.stage === 'anomalies' && s.findings && s.findings.length > 0 && (
                <div className="mt-3 space-y-2">
                  {s.findings.map((f, k) => (
                    <div key={k} className={`p-2 rounded-lg border text-sm ${SEV_STYLE[f.severity] || SEV_STYLE.info}`}>
                      <div className="font-semibold">{f.title}</div>
                      <div className="text-xs opacity-90">{f.message}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div className="text-xs text-slate-400 pt-2 space-y-0.5">
            {Object.entries(data.legend).map(([k, v]) => (
              <div key={k}><span className={`px-1.5 py-0.5 rounded ${STATE_STYLE[k]}`}>{STATE_LABEL[k]}</span> — {v}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
