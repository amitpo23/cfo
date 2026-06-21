/**
 * Accounting-office dashboard (ניהול משרד) — manage many client files, each with
 * its own authentication, sync them, and view the cross-company (רוחבי) synthesis:
 * required reconciliations and VAT position aggregated across all clients.
 */
import { useEffect, useState } from 'react';
import {
  Building2, Plus, Loader2, FolderSync, AlertCircle, CheckCircle2,
} from 'lucide-react';
import api from '../services/api';

interface ClientFile {
  id: number;
  company_id: string;
  name: string;
  status: string;
  connections: string[];
  last_synced_at: string | null;
}

interface Rollup {
  totals: {
    clients: number;
    required_actions: number;
    output_vat: number;
    input_vat: number;
    net_vat: number;
    actions_by_type: Record<string, number>;
  };
  clients: Array<{
    company_id: string;
    name: string;
    required_actions: number;
    net_vat: number;
    reconciliation: { matched: number; txn_count: number; unmatched_txns: number };
  }>;
}

const ACTION_LABEL: Record<string, string> = {
  file_expense: 'תיוק הוצאה',
  record_income: 'רישום הכנסה',
  collect_receivable: 'גביית חוב',
  pay_payable: 'תשלום התחייבות',
};

const emptyForm = { name: '', company_id: '', api_key: '', of_client_id: '', of_client_secret: '', of_user_id: '' };

export default function OfficeDashboard() {
  const [clients, setClients] = useState<ClientFile[]>([]);
  const [rollup, setRollup] = useState<Rollup | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [showForm, setShowForm] = useState(false);
  const [officeKey, setOfficeKey] = useState('');
  const [keyConfigured, setKeyConfigured] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = async () => {
    try {
      const [c, r, s] = await Promise.all([
        api.get<{ clients: ClientFile[] }>('/api/office/clients'),
        api.get<Rollup>('/api/office/rollup'),
        api.get<{ sumit_key_configured: boolean }>('/api/office/settings'),
      ]);
      setClients(c.clients || []);
      setRollup(r);
      setKeyConfigured(s.sumit_key_configured);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת נתוני המשרד');
    }
  };

  const saveOfficeKey = async () => {
    setBusy('officekey'); setError(null); setNotice(null);
    try {
      await api.post('/api/office/settings', { sumit_api_key: officeKey });
      setNotice('מפתח המשרד נשמר — כל תיק חדש ישתמש בו עם ה-company id שלו.');
      setOfficeKey('');
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בשמירת מפתח המשרד');
    } finally { setBusy(null); }
  };

  useEffect(() => { load(); }, []);

  const addClient = async () => {
    setBusy('add'); setError(null); setNotice(null);
    try {
      const payload: any = { name: form.name, company_id: form.company_id, api_key: form.api_key };
      if (form.of_client_id && form.of_client_secret && form.of_user_id) {
        payload.open_finance = {
          client_id: form.of_client_id, client_secret: form.of_client_secret, user_id: form.of_user_id,
        };
      }
      await api.post('/api/office/clients', payload);
      setNotice(`תיק "${form.name}" נוסף עם אותנטיקציה משלו.`);
      setForm({ ...emptyForm });
      setShowForm(false);
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בהוספת תיק');
    } finally { setBusy(null); }
  };

  const syncAll = async () => {
    setBusy('sync'); setError(null); setNotice(null);
    try {
      const res = await api.post<{ synced: number }>('/api/office/sync-all');
      setNotice(`סונכרנו ${res.synced} תיקים.`);
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בסנכרון');
    } finally { setBusy(null); }
  };

  const t = rollup?.totals;

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Building2 className="text-indigo-600" /> ניהול משרד
          </h1>
          <p className="text-slate-500 text-sm mt-1">תיקי לקוחות, כל אחד עם אותנטיקציה נפרדת, וסינתזה רוחבית.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowForm((s) => !s)}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700">
            <Plus className="w-4 h-4" /> הוסף תיק
          </button>
          <button onClick={syncAll} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-slate-700 text-white text-sm hover:bg-slate-800 disabled:opacity-50">
            {busy === 'sync' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderSync className="w-4 h-4" />}
            סנכרן הכל
          </button>
        </div>
      </div>

      {notice && <div className="mb-4 p-3 rounded-lg bg-emerald-50 text-emerald-800 text-sm">{notice}</div>}
      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {/* Office-level master key — one key serves all client files */}
      <div className="mb-6 p-4 border rounded-xl bg-white flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <div className="font-semibold text-sm">מפתח SUMIT של המשרד</div>
          <div className="text-xs text-slate-500 mt-0.5">
            מפתח אחד שמשרת את כל התיקים (כל תיק עם ה-company id שלו). אפשר לדרוס פר-לקוח.
            {keyConfigured
              ? <span className="text-emerald-600 mr-1">✓ מוגדר</span>
              : <span className="text-amber-600 mr-1">לא מוגדר</span>}
          </div>
        </div>
        <input className="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]" type="password"
          placeholder={keyConfigured ? 'הזן מפתח חדש להחלפה' : 'SUMIT API key של המשרד'}
          value={officeKey} onChange={(e) => setOfficeKey(e.target.value)} />
        <button onClick={saveOfficeKey} disabled={!!busy || !officeKey}
          className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-slate-700 text-white text-sm hover:bg-slate-800 disabled:opacity-50">
          {busy === 'officekey' ? <Loader2 className="w-4 h-4 animate-spin" /> : null} שמור מפתח משרד
        </button>
      </div>

      {showForm && (
        <div className="mb-6 p-4 border rounded-xl bg-slate-50">
          <h3 className="font-semibold mb-3">תיק לקוח חדש (אותנטיקציה משלו)</h3>
          <div className="grid md:grid-cols-3 gap-3">
            <input className="border rounded-lg px-3 py-2 text-sm" placeholder="שם הלקוח"
              value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input className="border rounded-lg px-3 py-2 text-sm" placeholder="SUMIT company id (תיק)"
              value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })} />
            <input className="border rounded-lg px-3 py-2 text-sm" placeholder="SUMIT API key (ריק = מפתח המשרד)"
              value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
            <input className="border rounded-lg px-3 py-2 text-sm" placeholder="Open Finance client id (אופ׳)"
              value={form.of_client_id} onChange={(e) => setForm({ ...form, of_client_id: e.target.value })} />
            <input className="border rounded-lg px-3 py-2 text-sm" placeholder="Open Finance client secret (אופ׳)"
              value={form.of_client_secret} onChange={(e) => setForm({ ...form, of_client_secret: e.target.value })} />
            <input className="border rounded-lg px-3 py-2 text-sm" placeholder="Open Finance user id (אופ׳)"
              value={form.of_user_id} onChange={(e) => setForm({ ...form, of_user_id: e.target.value })} />
          </div>
          <button onClick={addClient} disabled={!!busy || !form.name || !form.company_id}
            className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm hover:bg-emerald-700 disabled:opacity-50">
            {busy === 'add' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} שמור תיק
          </button>
        </div>
      )}

      {/* Cross-company rollup */}
      {t && (
        <div className="grid sm:grid-cols-4 gap-3 mb-6">
          <Stat label="תיקים" value={t.clients} />
          <Stat label="התאמות נדרשות" value={t.required_actions} accent={t.required_actions ? 'text-orange-600' : ''} />
          <Stat label='מע"מ נטו' value={`₪${t.net_vat.toLocaleString()}`} accent={t.net_vat >= 0 ? 'text-rose-600' : 'text-emerald-600'} />
          <Stat label='מע"מ עסקאות/תשומות' value={`₪${t.output_vat.toLocaleString()} / ₪${t.input_vat.toLocaleString()}`} />
        </div>
      )}

      {/* Client roster */}
      <div className="border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="text-right px-4 py-2">לקוח</th>
              <th className="text-right px-4 py-2">תיק (company id)</th>
              <th className="text-right px-4 py-2">חיבורים</th>
              <th className="text-right px-4 py-2">התאמות נדרשות</th>
              <th className="text-right px-4 py-2">מע"מ נטו</th>
            </tr>
          </thead>
          <tbody>
            {clients.length === 0 ? (
              <tr><td colSpan={5} className="text-center py-10 text-slate-400">אין תיקים עדיין — הוסף תיק לקוח.</td></tr>
            ) : clients.map((c) => {
              const r = rollup?.clients.find((x) => x.company_id === c.company_id);
              return (
                <tr key={c.id} className="border-t">
                  <td className="px-4 py-2 font-medium">{c.name}</td>
                  <td className="px-4 py-2 text-slate-500">{c.company_id}</td>
                  <td className="px-4 py-2">
                    {c.connections.map((s) => (
                      <span key={s} className="inline-flex items-center gap-1 text-xs bg-slate-100 rounded px-2 py-0.5 ml-1">
                        <CheckCircle2 className="w-3 h-3 text-emerald-600" />{s}
                      </span>
                    ))}
                  </td>
                  <td className="px-4 py-2">
                    {r && r.required_actions > 0 ? (
                      <span className="inline-flex items-center gap-1 text-orange-600">
                        <AlertCircle className="w-4 h-4" />{r.required_actions}
                      </span>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-2">{r ? `₪${r.net_vat.toLocaleString()}` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {t && Object.keys(t.actions_by_type).length > 0 && (
        <div className="mt-4 flex gap-2 flex-wrap">
          {Object.entries(t.actions_by_type).map(([type, count]) => (
            <span key={type} className="text-xs bg-amber-50 text-amber-800 rounded-full px-3 py-1">
              {ACTION_LABEL[type] || type}: {count}
            </span>
          ))}
        </div>
      )}
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
