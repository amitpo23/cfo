/**
 * Admin — all clients view. A single table across every client file in the office,
 * showing connections, sync state, required reconciliations and VAT position, with
 * office-wide totals. Backed by /api/office/admin/clients.
 */
import { useEffect, useMemo, useState } from 'react';
import { ShieldCheck, Loader2, AlertCircle, Search, RefreshCw, ExternalLink } from 'lucide-react';
import api from '../services/api';
import { ACTIVE_ORG_KEY } from './OrgSwitcher';

interface AdminClient {
  id: number;
  organization_id?: number;
  company_id: string;
  name: string;
  is_active?: boolean;
  connections: string[];
  connection_statuses?: Record<string, string>;
  automation?: {
    state?: string;
    account_scope?: string;
    loop?: string;
  };
  finance?: {
    invoice_count: number;
    bill_count: number;
    bank_transaction_count: number;
    revenue: number;
    expenses: number;
    net_profit: number;
    has_activity: boolean;
  };
  last_synced_at: string | null;
  last_sync?: {
    id: number;
    source: string;
    status: string;
    finished_at: string | null;
    error_summary: string | null;
  } | null;
  users_count?: number;
  required_actions: number;
  net_vat: number;
  reconciliation?: { matched: number; txn_count: number; unmatched_txns: number };
}

interface AdminResponse {
  totals: {
    clients?: number;
    organizations?: number;
    required_actions: number;
    connected_sumit?: number;
    connected_open_finance?: number;
    with_sync_errors?: number;
    total_revenue?: number;
    total_expenses?: number;
    net_profit?: number;
    with_financial_activity?: number;
    output_vat: number;
    input_vat: number;
    net_vat: number;
  };
  clients: AdminClient[];
}

export default function AdminClientsDashboard() {
  const [data, setData] = useState<AdminResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [syncingOrg, setSyncingOrg] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const control = await api.get<any>('/admin/control/clients');
      setData({
        totals: {
          clients: control.totals.organizations,
          organizations: control.totals.organizations,
          connected_sumit: control.totals.connected_sumit,
          connected_open_finance: control.totals.connected_open_finance,
          with_sync_errors: control.totals.with_sync_errors,
          total_revenue: control.totals.total_revenue,
          total_expenses: control.totals.total_expenses,
          net_profit: control.totals.net_profit,
          with_financial_activity: control.totals.with_financial_activity,
          required_actions: control.totals.with_sync_errors,
          output_vat: 0,
          input_vat: 0,
          net_vat: 0,
        },
        clients: control.clients.map((c: any) => ({
          id: c.organization_id,
          organization_id: c.organization_id,
          company_id: c.tax_id || String(c.organization_id),
          name: c.name,
          is_active: c.is_active,
          connections: c.connections || [],
          connection_statuses: c.connection_statuses || {},
          automation: c.automation || {},
          finance: c.finance,
          last_synced_at: c.last_sync?.finished_at || null,
          last_sync: c.last_sync,
          users_count: c.users_count,
          required_actions: c.last_sync?.error_summary ? 1 : 0,
          net_vat: 0,
          reconciliation: undefined,
        })),
      });
    } catch (e: any) {
      try {
        setData(await api.get<AdminResponse>('/api/office/admin/clients'));
      } catch (fallbackError: any) {
        setError(fallbackError?.response?.data?.detail || e?.response?.data?.detail || 'שגיאה בטעינת נתוני האדמין');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    if (!data) return [];
    const term = q.trim().toLowerCase();
    if (!term) return data.clients;
    return data.clients.filter(
      (c) => c.name?.toLowerCase().includes(term) || c.company_id.includes(term)
    );
  }, [data, q]);

  const openClient = (orgId?: number) => {
    if (!orgId) return;
    localStorage.setItem(ACTIVE_ORG_KEY, String(orgId));
    window.location.href = '/';
  };

  const fmtMoney = (n?: number) => `₪${Math.round(n || 0).toLocaleString('he-IL')}`;
  const statusLabel = (c: AdminClient) => {
    const state = c.automation?.state;
    if (state === 'pending_credentials') return 'ממתין לחיבור';
    if (c.last_sync?.error_summary) return 'שגיאת sync';
    if (state === 'active' || c.last_sync?.status === 'completed') return 'פעיל';
    return c.is_active === false ? 'לא פעיל' : 'טרם סונכרן';
  };
  const statusClass = (c: AdminClient) => {
    const label = statusLabel(c);
    if (label === 'פעיל') return 'bg-emerald-50 text-emerald-700 border-emerald-200';
    if (label === 'ממתין לחיבור') return 'bg-amber-50 text-amber-700 border-amber-200';
    if (label === 'שגיאת sync') return 'bg-red-50 text-red-700 border-red-200';
    return 'bg-slate-50 text-slate-600 border-slate-200';
  };

  const syncClient = async (orgId?: number) => {
    if (!orgId) return;
    setSyncingOrg(orgId);
    setError(null);
    try {
      await api.post(`/admin/control/clients/${orgId}/sync`);
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'סנכרון הלקוח נכשל');
    } finally {
      setSyncingOrg(null);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>;
  }

  return (
    <div className="p-6 max-w-7xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldCheck className="text-indigo-600" /> אדמין — כל הלקוחות
        </h1>
        <div className="relative">
          <Search className="w-4 h-4 absolute right-3 top-2.5 text-slate-400" />
          <input className="border rounded-lg pr-9 pl-3 py-2 text-sm" placeholder="חיפוש לפי שם/תיק"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {data && (
        <div className="grid sm:grid-cols-4 gap-3 mb-6">
          <Stat label="סה״כ לקוחות" value={data.totals.clients} />
          {data.totals.with_financial_activity !== undefined && (
            <Stat label="לקוחות עם פעילות" value={data.totals.with_financial_activity} />
          )}
          {data.totals.connected_sumit !== undefined && (
            <Stat label="חיבורי הנה״ח" value={data.totals.connected_sumit} />
          )}
          {data.totals.connected_open_finance !== undefined && (
            <Stat label="חיבורי בנק" value={data.totals.connected_open_finance} />
          )}
          {data.totals.total_revenue !== undefined && (
            <Stat label="הכנסות מצטברות" value={fmtMoney(data.totals.total_revenue)} accent="text-emerald-700" />
          )}
          {data.totals.total_expenses !== undefined && (
            <Stat label="הוצאות מצטברות" value={fmtMoney(data.totals.total_expenses)} accent="text-rose-600" />
          )}
          {data.totals.net_profit !== undefined && (
            <Stat label="רווח / הפסד נטו" value={fmtMoney(data.totals.net_profit)}
              accent={data.totals.net_profit >= 0 ? 'text-emerald-700' : 'text-rose-600'} />
          )}
          <Stat label="התאמות נדרשות (סה״כ)" value={data.totals.required_actions}
            accent={data.totals.required_actions ? 'text-orange-600' : ''} />
          {data.totals.organizations === undefined && (
            <>
              <Stat label='מע"מ נטו (סה״כ)' value={`₪${data.totals.net_vat.toLocaleString()}`}
                accent={data.totals.net_vat >= 0 ? 'text-rose-600' : 'text-emerald-600'} />
              <Stat label='עסקאות / תשומות' value={`₪${data.totals.output_vat.toLocaleString()} / ₪${data.totals.input_vat.toLocaleString()}`} />
            </>
          )}
        </div>
      )}

      <div className="border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="text-right px-4 py-2">לקוח</th>
              <th className="text-right px-4 py-2">תיק</th>
              <th className="text-right px-4 py-2">משתמשים</th>
              <th className="text-right px-4 py-2">חיבורים</th>
              <th className="text-right px-4 py-2">פעילות כספית</th>
              <th className="text-right px-4 py-2">רווח/הפסד</th>
              <th className="text-right px-4 py-2">התאמות בנק</th>
              <th className="text-right px-4 py-2">סטטוס sync</th>
              <th className="text-right px-4 py-2">סנכרון אחרון</th>
              <th className="text-right px-4 py-2">פעולות</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={10} className="text-center py-10 text-slate-400">אין לקוחות.</td></tr>
            ) : filtered.map((c) => (
              <tr key={c.id} className="border-t hover:bg-slate-50">
                <td className="px-4 py-2 font-medium">{c.name}</td>
                <td className="px-4 py-2 text-slate-500">{c.company_id}</td>
                <td className="px-4 py-2 text-slate-600">{c.users_count ?? '—'}</td>
                <td className="px-4 py-2">
                  {c.connections.length
                    ? c.connections.map((s) => (
                        <span key={s} className="inline-block text-xs bg-slate-100 rounded px-2 py-0.5 ml-1">{s}</span>))
                    : <span className="text-slate-400">—</span>}
                </td>
                <td className="px-4 py-2 text-xs text-slate-600">
                  {c.finance ? (
                    <div className="space-y-0.5">
                      <div>הכנסות: {fmtMoney(c.finance.revenue)} · {c.finance.invoice_count} מסמכים</div>
                      <div>הוצאות: {fmtMoney(c.finance.expenses)} · {c.finance.bill_count} מסמכים</div>
                      <div>בנק: {c.finance.bank_transaction_count} תנועות</div>
                    </div>
                  ) : '—'}
                </td>
                <td className={`px-4 py-2 font-semibold ${(c.finance?.net_profit || 0) >= 0 ? 'text-emerald-700' : 'text-rose-600'}`}>
                  {c.finance ? fmtMoney(c.finance.net_profit) : '—'}
                </td>
                <td className="px-4 py-2 text-slate-600">
                  {c.reconciliation ? `${c.reconciliation.matched}/${c.reconciliation.txn_count}` : '—'}
                </td>
                <td className="px-4 py-2">
                  {c.last_sync?.error_summary ? (
                    <span className="inline-flex items-center gap-1 text-orange-600" title={c.last_sync.error_summary}>
                      <AlertCircle className="w-4 h-4" /> שגיאה
                    </span>
                  ) : c.last_sync?.status ? (
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${statusClass(c)}`}>{statusLabel(c)}</span>
                  ) : (
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${statusClass(c)}`}>{statusLabel(c)}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-500 text-xs">
                  {c.last_synced_at ? new Date(c.last_synced_at).toLocaleString('he-IL') : 'טרם'}
                </td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => openClient(c.organization_id)}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs hover:bg-slate-100"
                    >
                      <ExternalLink className="w-3 h-3" /> פתח
                    </button>
                    <button
                      onClick={() => syncClient(c.organization_id)}
                      disabled={syncingOrg === c.organization_id}
                      className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2 py-1 text-xs text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      <RefreshCw className={`w-3 h-3 ${syncingOrg === c.organization_id ? 'animate-spin' : ''}`} />
                      סנכרן
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, accent = '' }: { label: string; value: any; accent?: string }) {
  return (
    <div className="border rounded-xl p-4 bg-white">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-xl font-bold mt-1 ${accent}`}>{value}</div>
    </div>
  );
}
