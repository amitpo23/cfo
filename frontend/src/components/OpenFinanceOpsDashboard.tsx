/**
 * Open Finance operations (B+C) — tabbed admin over the full client surface:
 * Payments, Credit sessions, Customers, Merchants. Each tab lists records and
 * creates new ones via the dedicated routes. (Requires Open Finance credentials;
 * without them the list shows a clear "not configured" message.)
 */
import { useEffect, useState } from 'react';
import { CreditCard, Banknote, Users, Store, Loader2, Plus, RefreshCw } from 'lucide-react';
import api from '../services/api';

type TabKey = 'payments' | 'credit' | 'customers' | 'merchants';

const TABS: { key: TabKey; label: string; icon: any; list: string; itemsKey: string }[] = [
  { key: 'payments', label: 'תשלומים', icon: Banknote, list: '/api/open-finance/payments', itemsKey: 'items' },
  { key: 'credit', label: 'אשראי', icon: CreditCard, list: '/api/open-finance/credit-sessions', itemsKey: 'items' },
  { key: 'customers', label: 'לקוחות', icon: Users, list: '/api/open-finance/customers', itemsKey: 'items' },
  { key: 'merchants', label: 'סוחרים', icon: Store, list: '/api/open-finance/merchants', itemsKey: 'items' },
];

export default function OpenFinanceOpsDashboard() {
  const [tab, setTab] = useState<TabKey>('payments');
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);

  const current = TABS.find((t) => t.key === tab)!;

  const load = async () => {
    setLoading(true); setError(null); setRows([]);
    try {
      const r = await api.get<any>(current.list);
      const items = r[current.itemsKey] || r.items || (Array.isArray(r) ? r : []);
      setRows(Array.isArray(items) ? items : []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'לא ניתן לטעון — ייתכן ש-Open Finance לא מוגדר.');
    } finally { setLoading(false); }
  };

  useEffect(() => { setForm({}); setNotice(null); load(); /* eslint-disable-next-line */ }, [tab]);

  const create = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      if (tab === 'payments') {
        await api.post('/api/open-finance/payments', {
          paymentInformation: {
            amount: Number(form.amount), currency: form.currency || 'ILS',
            description: form.description || '', creditorName: form.creditorName,
          },
        });
      } else if (tab === 'credit') {
        await api.post('/api/open-finance/credit-sessions', {
          creditRequested: Number(form.amount), customerId: form.customerId,
        });
      } else if (tab === 'customers') {
        await api.post('/api/open-finance/customers', {
          firstName: form.firstName, lastName: form.lastName,
          nationalId: form.nationalId, phoneNumber: form.phone,
        });
      } else if (tab === 'merchants') {
        await api.post('/api/open-finance/merchants', {
          name: form.name, bban: form.bban, displayName: form.displayName,
        });
      }
      setNotice('נוצר בהצלחה.');
      setForm({});
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה ביצירה');
    } finally { setBusy(false); }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <h1 className="text-2xl font-bold flex items-center gap-2 mb-4">
        <CreditCard className="text-indigo-600" /> Open Finance — תפעול
      </h1>

      <div className="flex gap-2 mb-5 flex-wrap">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm ${
              tab === t.key ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
        <button onClick={load} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm bg-slate-100 hover:bg-slate-200">
          <RefreshCw className="w-4 h-4" /> רענן
        </button>
      </div>

      {notice && <div className="mb-4 p-3 rounded-lg bg-emerald-50 text-emerald-800 text-sm">{notice}</div>}
      {error && <div className="mb-4 p-3 rounded-lg bg-amber-50 text-amber-800 text-sm">{error}</div>}

      {/* Create form per tab */}
      <div className="mb-5 p-4 border rounded-xl bg-slate-50 flex flex-wrap gap-3 items-end">
        {tab === 'payments' && <>
          <Field label="סכום" onChange={(v) => setForm({ ...form, amount: v })} value={form.amount} type="number" />
          <Field label="מטבע" onChange={(v) => setForm({ ...form, currency: v })} value={form.currency || 'ILS'} />
          <Field label="תיאור" onChange={(v) => setForm({ ...form, description: v })} value={form.description} />
          <Field label="שם נושה" onChange={(v) => setForm({ ...form, creditorName: v })} value={form.creditorName} />
        </>}
        {tab === 'credit' && <>
          <Field label="סכום אשראי" onChange={(v) => setForm({ ...form, amount: v })} value={form.amount} type="number" />
          <Field label="customer id" onChange={(v) => setForm({ ...form, customerId: v })} value={form.customerId} />
        </>}
        {tab === 'customers' && <>
          <Field label="שם פרטי" onChange={(v) => setForm({ ...form, firstName: v })} value={form.firstName} />
          <Field label="שם משפחה" onChange={(v) => setForm({ ...form, lastName: v })} value={form.lastName} />
          <Field label="ת.ז" onChange={(v) => setForm({ ...form, nationalId: v })} value={form.nationalId} />
          <Field label="טלפון" onChange={(v) => setForm({ ...form, phone: v })} value={form.phone} />
        </>}
        {tab === 'merchants' && <>
          <Field label="שם" onChange={(v) => setForm({ ...form, name: v })} value={form.name} />
          <Field label="שם תצוגה" onChange={(v) => setForm({ ...form, displayName: v })} value={form.displayName} />
          <Field label="חשבון (bban)" onChange={(v) => setForm({ ...form, bban: v })} value={form.bban} />
        </>}
        <button onClick={create} disabled={busy}
          className="inline-flex items-center gap-1 px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm hover:bg-emerald-700 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} צור
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : rows.length === 0 ? (
        <div className="text-center py-16 text-slate-400">אין רשומות להצגה.</div>
      ) : (
        <div className="border rounded-xl overflow-auto">
          <table className="w-full text-sm">
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-2 font-mono text-xs text-slate-500">{row.id || row.sessionId || row.customerId || '—'}</td>
                  <td className="px-4 py-2">{row.name || row.displayName || `${row.firstName || ''} ${row.lastName || ''}`.trim() || row.description || '—'}</td>
                  <td className="px-4 py-2 text-left">{row.amount ? `₪${row.amount}` : row.status || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, type = 'text' }: {
  label: string; value: any; onChange: (v: any) => void; type?: string;
}) {
  return (
    <label className="text-sm">
      <span className="text-slate-600 block mb-1">{label}</span>
      <input type={type} className="border rounded-lg px-3 py-2 w-40"
        value={value ?? ''} onChange={(e) => onChange(type === 'number' ? Number(e.target.value) : e.target.value)} />
    </label>
  );
}
