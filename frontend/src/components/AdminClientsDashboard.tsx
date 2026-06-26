/**
 * Admin — all clients view. A single table across every client file in the office,
 * showing connections, sync state, required reconciliations and VAT position, with
 * office-wide totals. Backed by /api/office/admin/clients.
 */
import { useEffect, useMemo, useState } from 'react';
import { ShieldCheck, Loader2, AlertCircle, Search } from 'lucide-react';
import api from '../services/api';

interface AdminClient {
  id: number;
  company_id: string;
  name: string;
  status: string;
  connections: string[];
  last_synced_at: string | null;
  required_actions: number;
  net_vat: number;
  reconciliation?: { matched: number; txn_count: number; unmatched_txns: number };
}

interface AdminResponse {
  totals: {
    clients: number;
    required_actions: number;
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

  useEffect(() => {
    (async () => {
      try {
        setData(await api.get<AdminResponse>('/api/office/admin/clients'));
      } catch (e: any) {
        setError(e?.response?.data?.detail || 'שגיאה בטעינת נתוני האדמין');
      } finally { setLoading(false); }
    })();
  }, []);

  const filtered = useMemo(() => {
    if (!data) return [];
    const term = q.trim().toLowerCase();
    if (!term) return data.clients;
    return data.clients.filter(
      (c) => c.name?.toLowerCase().includes(term) || c.company_id.includes(term)
    );
  }, [data, q]);

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
          <Stat label="התאמות נדרשות (סה״כ)" value={data.totals.required_actions}
            accent={data.totals.required_actions ? 'text-orange-600' : ''} />
          <Stat label='מע"מ נטו (סה״כ)' value={`₪${data.totals.net_vat.toLocaleString()}`}
            accent={data.totals.net_vat >= 0 ? 'text-rose-600' : 'text-emerald-600'} />
          <Stat label='עסקאות / תשומות' value={`₪${data.totals.output_vat.toLocaleString()} / ₪${data.totals.input_vat.toLocaleString()}`} />
        </div>
      )}

      <div className="border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="text-right px-4 py-2">לקוח</th>
              <th className="text-right px-4 py-2">תיק</th>
              <th className="text-right px-4 py-2">חיבורים</th>
              <th className="text-right px-4 py-2">התאמות בנק</th>
              <th className="text-right px-4 py-2">התאמות נדרשות</th>
              <th className="text-right px-4 py-2">מע"מ נטו</th>
              <th className="text-right px-4 py-2">סנכרון אחרון</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-10 text-slate-400">אין לקוחות.</td></tr>
            ) : filtered.map((c) => (
              <tr key={c.id} className="border-t hover:bg-slate-50">
                <td className="px-4 py-2 font-medium">{c.name}</td>
                <td className="px-4 py-2 text-slate-500">{c.company_id}</td>
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
                  {c.required_actions > 0
                    ? <span className="inline-flex items-center gap-1 text-orange-600"><AlertCircle className="w-4 h-4" />{c.required_actions}</span>
                    : <span className="text-slate-400">—</span>}
                </td>
                <td className="px-4 py-2">₪{(c.net_vat || 0).toLocaleString()}</td>
                <td className="px-4 py-2 text-slate-500 text-xs">
                  {c.last_synced_at ? new Date(c.last_synced_at).toLocaleString('he-IL') : 'טרם'}
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
