/**
 * Bank Intelligence dashboard — surfaces Open Finance bank-statement insights:
 * duplicate charges, subscriptions, bank fees, category spikes, cash-flow forecast,
 * savings opportunities, anomalies and risk signals. Also launches the bank consent
 * journey and triggers bank reconciliation.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, RefreshCw, Banknote, Repeat, TrendingUp, PiggyBank,
  Copy, ShieldAlert, Sparkles, Link2, CheckCircle2, XCircle, Loader2,
  Scale, LineChart, Briefcase, Send, FileCheck2,
} from 'lucide-react';
import api from '../services/api';

interface Insight {
  id: number;
  type: string;
  severity: 'info' | 'low' | 'medium' | 'high' | 'critical';
  title: string;
  message: string;
  evidence: Record<string, any>;
  recommended_action: string;
  status: string;
  created_at: string | null;
}

interface ReconciliationResult {
  matched_count: number;
  txn_count: number;
  unmatched_txns?: number[];
  unmatched_docs?: Array<Record<string, any>>;
}

interface SumitDispatchResult {
  local_reconciliation: ReconciliationResult;
  dry_run: boolean;
  dispatched: number;
  confirmed: number;
  failed: number;
  unsupported: number;
  items: Array<{
    bank_transaction_id: number;
    matched_entity_type?: string;
    matched_entity_id?: number;
    status: 'pending' | 'confirmed' | 'failed' | 'unsupported' | string;
    error?: string;
    skipped?: boolean;
  }>;
}

const TYPE_ICON: Record<string, any> = {
  duplicate_charge: Copy,
  subscription: Repeat,
  installment_ending: CheckCircle2,
  bank_fees: Banknote,
  category_spike: TrendingUp,
  cashflow_forecast: Sparkles,
  savings_opportunity: PiggyBank,
  anomaly: AlertTriangle,
  risk_signal: ShieldAlert,
  aggregate_balance: Scale,
  portfolio_summary: Briefcase,
  portfolio_position: LineChart,
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: 'border-red-500 bg-red-50',
  high: 'border-orange-400 bg-orange-50',
  medium: 'border-amber-400 bg-amber-50',
  low: 'border-sky-300 bg-sky-50',
  info: 'border-slate-200 bg-slate-50',
};

const SEVERITY_LABEL: Record<string, string> = {
  critical: 'קריטי', high: 'גבוה', medium: 'בינוני', low: 'נמוך', info: 'מידע',
};

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'];

export default function BankInsightsDashboard() {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reconciliation, setReconciliation] = useState<ReconciliationResult | null>(null);
  const [sumitDispatch, setSumitDispatch] = useState<SumitDispatchResult | null>(null);

  const loadInsights = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<{ items: Insight[] }>('/api/open-finance/insights?status=active');
      setInsights(res.items || []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת התובנות');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadInsights(); }, []);

  const generate = async () => {
    setBusy('generate');
    setError(null);
    setNotice(null);
    try {
      const res = await api.post<{ generated: number; transactions_analyzed: number }>(
        '/api/open-finance/insights/generate'
      );
      setNotice(`נותחו ${res.transactions_analyzed} תנועות, נוצרו ${res.generated} תובנות.`);
      await loadInsights();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בהפקת תובנות');
    } finally {
      setBusy(null);
    }
  };

  const connectBank = async () => {
    setBusy('connect');
    setError(null);
    try {
      const res = await api.post<{ connect_url: string }>('/api/open-finance/connections', {
        language: 'he',
      });
      if (res.connect_url) {
        window.open(res.connect_url, '_blank', 'noopener');
        setNotice('נפתח מסע חיבור הבנק בחלון חדש. לאחר ההשלמה — הפק תובנות מחדש.');
      } else {
        setError('לא התקבל קישור חיבור');
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בפתיחת חיבור בנק');
    } finally {
      setBusy(null);
    }
  };

  const reconcile = async () => {
    setBusy('reconcile');
    setError(null);
    setNotice(null);
    try {
      const res = await api.post<{ matched_count: number; txn_count: number }>(
        '/api/open-finance/reconcile'
      );
      setReconciliation(res);
      setNotice(`הותאמו ${res.matched_count} מתוך ${res.txn_count} תנועות בנק.`);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בהתאמת בנקים');
    } finally {
      setBusy(null);
    }
  };

  const dispatchToSumit = async (dryRun = false) => {
    setBusy(dryRun ? 'dispatch-dry-run' : 'dispatch');
    setError(null);
    setNotice(null);
    try {
      const res = await api.post<SumitDispatchResult>(
        `/api/open-finance/reconcile/sumit-dispatch?dry_run=${dryRun ? 'true' : 'false'}`
      );
      setSumitDispatch(res);
      setReconciliation(res.local_reconciliation);
      if (dryRun) {
        setNotice(`בדיקה בלבד: נמצאו ${res.local_reconciliation.matched_count} התאמות מוכנות לשליחה.`);
      } else if (res.unsupported) {
        setNotice(`ההתאמות נשמרו אצלנו. ${res.unsupported} התאמות דורשות חיבור write-back רשמי ל-SUMIT.`);
      } else {
        setNotice(`נשלחו ${res.dispatched} התאמות ל-SUMIT, אושרו ${res.confirmed}.`);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בשליחת התאמות ל-SUMIT');
    } finally {
      setBusy(null);
    }
  };

  const setStatus = async (id: number, status: string) => {
    setInsights((prev) => prev.filter((i) => i.id !== id));
    try {
      await api.post(`/api/open-finance/insights/${id}/status`, { status });
    } catch {
      loadInsights();
    }
  };

  const grouped = useMemo(() => {
    const by: Record<string, Insight[]> = {};
    for (const ins of insights) (by[ins.severity] ||= []).push(ins);
    return SEVERITY_ORDER.filter((s) => by[s]?.length).map((s) => ({ severity: s, items: by[s] }));
  }, [insights]);

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="text-indigo-600" /> תובנות בנק
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            ניתוח דפי הבנק — חיובים כפולים, מנויים, עמלות, חריגות, מאזן חודשי ותיק השקעות.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={connectBank} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700 disabled:opacity-50">
            {busy === 'connect' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />}
            חבר בנק
          </button>
          <button onClick={generate} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm hover:bg-emerald-700 disabled:opacity-50">
            {busy === 'generate' ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            הפק תובנות
          </button>
          <button onClick={reconcile} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-slate-700 text-white text-sm hover:bg-slate-800 disabled:opacity-50">
            {busy === 'reconcile' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Banknote className="w-4 h-4" />}
            התאמת בנקים
          </button>
          <button onClick={() => dispatchToSumit(true)} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-white border border-slate-300 text-slate-700 text-sm hover:bg-slate-50 disabled:opacity-50">
            {busy === 'dispatch-dry-run' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileCheck2 className="w-4 h-4" />}
            בדיקת שליחה
          </button>
          <button onClick={() => dispatchToSumit(false)} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-blue-700 text-white text-sm hover:bg-blue-800 disabled:opacity-50">
            {busy === 'dispatch' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            שלח ל-SUMIT
          </button>
        </div>
      </div>

      {notice && <div className="mb-4 p-3 rounded-lg bg-emerald-50 text-emerald-800 text-sm">{notice}</div>}
      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}
      {(reconciliation || sumitDispatch) && (
        <section className="mb-6 border border-slate-200 rounded-xl bg-white p-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
                <Banknote className="w-4 h-4 text-blue-700" />
                סטטוס התאמות Open Finance מול SUMIT
              </h2>
              <p className="text-xs text-slate-500 mt-1">
                התאמות נשמרות קודם בבסיס הנתונים שלנו, ואז מקבלות סטטוס dispatch מול SUMIT.
              </p>
            </div>
            {sumitDispatch?.dry_run && (
              <span className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-600">בדיקה בלבד</span>
            )}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mt-4 text-sm">
            <StatusStat label="תנועות" value={reconciliation?.txn_count ?? 0} />
            <StatusStat label="הותאמו" value={reconciliation?.matched_count ?? 0} tone="emerald" />
            <StatusStat label="נשלחו" value={sumitDispatch?.dispatched ?? 0} tone="blue" />
            <StatusStat label="אושרו" value={sumitDispatch?.confirmed ?? 0} tone="emerald" />
            <StatusStat label="נכשלו" value={sumitDispatch?.failed ?? 0} tone="red" />
            <StatusStat label="לא נתמך" value={sumitDispatch?.unsupported ?? 0} tone="amber" />
          </div>
          {!!sumitDispatch?.items?.length && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-slate-500 border-b">
                  <tr>
                    <th className="text-right py-2">תנועת בנק</th>
                    <th className="text-right py-2">התאמה</th>
                    <th className="text-right py-2">סטטוס SUMIT</th>
                    <th className="text-right py-2">הערה</th>
                  </tr>
                </thead>
                <tbody>
                  {sumitDispatch.items.slice(0, 8).map((item) => (
                    <tr key={`${item.bank_transaction_id}-${item.status}`} className="border-b last:border-0">
                      <td className="py-2 text-slate-700">#{item.bank_transaction_id}</td>
                      <td className="py-2 text-slate-600">
                        {item.matched_entity_type || '—'} {item.matched_entity_id ? `#${item.matched_entity_id}` : ''}
                      </td>
                      <td className="py-2">
                        <DispatchBadge status={item.status} />
                      </td>
                      <td className="py-2 text-slate-500 max-w-sm truncate">{item.error || (item.skipped ? 'כבר אושר' : '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : insights.length === 0 ? (
        <div className="text-center py-20 text-slate-400">
          <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p>אין תובנות עדיין. חבר בנק והפק תובנות.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.map(({ severity, items }) => (
            <section key={severity}>
              <h2 className="text-sm font-semibold text-slate-500 mb-2">
                {SEVERITY_LABEL[severity]} · {items.length}
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {items.map((ins) => {
                  const Icon = TYPE_ICON[ins.type] || AlertTriangle;
                  return (
                    <div key={ins.id} className={`border rounded-xl p-4 ${SEVERITY_STYLE[ins.severity]}`}>
                      <div className="flex items-start gap-3">
                        <Icon className="w-5 h-5 mt-0.5 text-slate-700 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <h3 className="font-semibold text-slate-800">{ins.title}</h3>
                          <p className="text-sm text-slate-600 mt-1">{ins.message}</p>
                          {ins.recommended_action && (
                            <p className="text-xs text-slate-500 mt-2">💡 {ins.recommended_action}</p>
                          )}
                          <div className="flex gap-2 mt-3">
                            <button onClick={() => setStatus(ins.id, 'acknowledged')}
                              className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900">
                              <CheckCircle2 className="w-3.5 h-3.5" /> טופל
                            </button>
                            <button onClick={() => setStatus(ins.id, 'resolved')}
                              className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700">
                              <XCircle className="w-3.5 h-3.5" /> התעלם
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusStat({ label, value, tone = 'slate' }: { label: string; value: number; tone?: 'slate' | 'emerald' | 'blue' | 'red' | 'amber' }) {
  const colors = {
    slate: 'bg-slate-50 text-slate-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    blue: 'bg-blue-50 text-blue-700',
    red: 'bg-red-50 text-red-700',
    amber: 'bg-amber-50 text-amber-700',
  };
  return (
    <div className={`rounded-lg px-3 py-2 ${colors[tone]}`}>
      <div className="text-xs opacity-80">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

function DispatchBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    confirmed: 'bg-emerald-100 text-emerald-700',
    pending: 'bg-blue-100 text-blue-700',
    failed: 'bg-red-100 text-red-700',
    unsupported: 'bg-amber-100 text-amber-800',
  };
  const labels: Record<string, string> = {
    confirmed: 'אושר',
    pending: 'ממתין',
    failed: 'נכשל',
    unsupported: 'לא נתמך',
  };
  return (
    <span className={`inline-flex px-2 py-1 rounded-full text-xs ${styles[status] || 'bg-slate-100 text-slate-700'}`}>
      {labels[status] || status}
    </span>
  );
}
