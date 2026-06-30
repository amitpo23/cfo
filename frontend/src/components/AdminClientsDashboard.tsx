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
          {data.totals.connected_sumit !== undefined && (
            <Stat label="חיבורי הנה״ח" value={data.totals.connected_sumit} />
          )}
          {data.totals.connected_open_finance !== undefined && (
            <Stat label="חיבורי בנק" value={data.totals.connected_open_finance} />
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
              <th className="text-right px-4 py-2">התאמות בנק</th>
              <th className="text-right px-4 py-2">סטטוס sync</th>
              <th className="text-right px-4 py-2">סנכרון אחרון</th>
              <th className="text-right px-4 py-2">פעולות</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-10 text-slate-400">אין לקוחות.</td></tr>
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
                <td className="px-4 py-2 text-slate-600">
                  {c.reconciliation ? `${c.reconciliation.matched}/${c.reconciliation.txn_count}` : '—'}
                </td>
                <td className="px-4 py-2">
                  {c.last_sync?.error_summary ? (
                    <span className="inline-flex items-center gap-1 text-orange-600" title={c.last_sync.error_summary}>
                      <AlertCircle className="w-4 h-4" /> שגיאה
                    </span>
                  ) : c.last_sync?.status ? (
                    <span className="text-slate-700">{c.last_sync.status}</span>
                  ) : (
                    <span className="text-slate-400">טרם</span>
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
