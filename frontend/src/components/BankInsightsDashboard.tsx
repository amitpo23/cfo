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
      setNotice(`הותאמו ${res.matched_count} מתוך ${res.txn_count} תנועות בנק.`);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בהתאמת בנקים');
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
            ניתוח דפי הבנק — חיובים כפולים, מנויים, עמלות, חריגות והזדמנויות חיסכון.
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
        </div>
      </div>

      {notice && <div className="mb-4 p-3 rounded-lg bg-emerald-50 text-emerald-800 text-sm">{notice}</div>}
      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

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
