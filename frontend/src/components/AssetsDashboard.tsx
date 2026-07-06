/**
 * Fixed assets & depreciation (רכוש קבוע ופחת) — Wave 2 addition E.
 * List + create form + per-asset schedule + annual total + form 1342 draft.
 * All depreciation output is DERIVED/DRAFT — decision support for an accountant.
 */
import { useEffect, useState } from 'react';
import { Warehouse, Loader2, Plus, Trash2, FileWarning, TrendingDown } from 'lucide-react';
import api from '../services/api';

const CATEGORY_LABELS: Record<string, string> = {
  buildings: 'מבנים', equipment: 'ציוד ומכונות', computers: 'מחשבים ותוכנה',
  vehicles: 'כלי רכב', furniture: 'ריהוט וציוד משרדי', other: 'אחר',
};

interface FixedAssetDto {
  id: number; name: string; category: string; cost: number; purchase_date: string;
  depreciation_rate: number; salvage_value: number; notes: string | null; created_at: string | null;
}
interface ScheduleRow { year: number; annual_depreciation: number; accumulated: number; book_value: number; }
interface Form1342Row {
  asset_id: number; name: string; category: string; cost: number; purchase_date: string;
  rate: number; opening_accumulated: number; depreciation_this_year: number;
  accumulated_depreciation: number; book_value: number;
}
interface Form1342 {
  form: string; title: string; year: number; rows: Form1342Row[];
  totals: { cost: number; depreciation_this_year: number; accumulated_depreciation: number; book_value: number };
  draft: boolean; disclaimer: string;
}

const now = new Date();
const fmt = (n: number) => `₪${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

const emptyForm = {
  name: '', category: 'equipment', cost: '', purchase_date: '',
  depreciation_rate: '', salvage_value: '0', notes: '',
};

export default function AssetsDashboard() {
  const [assets, setAssets] = useState<FixedAssetDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<typeof emptyForm>(emptyForm);
  const [saving, setSaving] = useState(false);

  const [scheduleAssetId, setScheduleAssetId] = useState<number | null>(null);
  const [schedule, setSchedule] = useState<ScheduleRow[] | null>(null);

  const [year, setYear] = useState(now.getFullYear());
  const [annualTotal, setAnnualTotal] = useState<number | null>(null);
  const [form1342, setForm1342] = useState<Form1342 | null>(null);

  const loadAssets = async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.get<{ assets: FixedAssetDto[] }>('/api/assets');
      setAssets(r.assets || []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת נכסים');
    } finally { setLoading(false); }
  };

  const loadYearData = async () => {
    try {
      const [annual, f1342] = await Promise.all([
        api.get<{ total_depreciation: number }>(`/api/assets/depreciation/annual?year=${year}`),
        api.get<Form1342>(`/api/assets/form-1342?year=${year}`),
      ]);
      setAnnualTotal(annual.total_depreciation);
      setForm1342(f1342);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת נתוני שנה');
    }
  };

  useEffect(() => { loadAssets(); }, []);
  useEffect(() => { loadYearData(); /* eslint-disable-next-line */ }, [year, assets.length]);

  const createAsset = async () => {
    if (!form.name.trim() || !form.category || !form.cost || !form.purchase_date) return;
    setSaving(true); setError(null);
    try {
      await api.post('/api/assets', {
        name: form.name.trim(),
        category: form.category,
        cost: Number(form.cost),
        purchase_date: form.purchase_date,
        depreciation_rate: form.depreciation_rate ? Number(form.depreciation_rate) : undefined,
        salvage_value: form.salvage_value ? Number(form.salvage_value) : 0,
        notes: form.notes || undefined,
      });
      setForm(emptyForm);
      setShowForm(false);
      await loadAssets();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה ביצירת הנכס');
    } finally { setSaving(false); }
  };

  const deleteAsset = async (id: number) => {
    try {
      await api.delete(`/api/assets/${id}`);
      if (scheduleAssetId === id) { setScheduleAssetId(null); setSchedule(null); }
      await loadAssets();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה במחיקת הנכס');
    }
  };

  const viewSchedule = async (id: number) => {
    setScheduleAssetId(id);
    setSchedule(null);
    try {
      const r = await api.get<{ schedule: ScheduleRow[] }>(`/api/assets/${id}/schedule`);
      setSchedule(r.schedule);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת לוח פחת');
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Warehouse className="text-indigo-600" /> רכוש קבוע ופחת
        </h1>
        <button onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 border border-indigo-600 text-indigo-600 rounded-lg hover:bg-indigo-50 flex items-center gap-2 text-sm">
          <Plus className="w-4 h-4" /> נכס חדש
        </button>
      </div>

      <div className="mb-5 p-4 rounded-lg bg-amber-100 border border-amber-300 text-amber-900 text-sm flex items-start gap-2">
        <FileWarning className="w-4 h-4 mt-0.5 shrink-0" />
        <span><b>פחת ישר (straight-line) נגזר, לפי תקנות מס הכנסה.</b> אינו דוח להגשה — לבדיקת רו"ח.</span>
      </div>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {showForm && (
        <div className="mb-6 border rounded-xl p-5 bg-white">
          <h2 className="text-lg font-semibold mb-4">הוספת נכס קבוע</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div><label className="block text-sm mb-1">שם הנכס</label>
              <input className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">קטגוריה</label>
              <select className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}>
                {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></div>
            <div><label className="block text-sm mb-1">עלות (₪)</label>
              <input type="number" className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.cost}
                onChange={(e) => setForm({ ...form, cost: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">תאריך רכישה</label>
              <input type="date" className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.purchase_date}
                onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">שיעור פחת שנתי (%) — ריק = ברירת מחדל לקטגוריה</label>
              <input type="number" className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.depreciation_rate}
                onChange={(e) => setForm({ ...form, depreciation_rate: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">ערך גרט (₪)</label>
              <input type="number" className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.salvage_value}
                onChange={(e) => setForm({ ...form, salvage_value: e.target.value })} /></div>
            <div className="col-span-2 md:col-span-3"><label className="block text-sm mb-1">הערות</label>
              <input className="w-full px-3 py-2 rounded-lg border border-gray-300" value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          <button onClick={createAsset} disabled={saving || !form.name || !form.cost || !form.purchase_date}
            className="mt-4 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            {saving ? 'שומר...' : 'שמירה'}
          </button>
        </div>
      )}

      <div className="border rounded-xl overflow-hidden mb-6">
        <div className="bg-slate-100 px-4 py-3 font-semibold">רשימת נכסים</div>
        {loading ? (
          <div className="flex justify-center py-10 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
        ) : assets.length === 0 ? (
          <div className="text-center py-10 text-slate-400">אין נכסים קבועים רשומים.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-right px-4 py-2">שם</th>
                <th className="text-right px-4 py-2">קטגוריה</th>
                <th className="text-right px-4 py-2">עלות</th>
                <th className="text-right px-4 py-2">תאריך רכישה</th>
                <th className="text-right px-4 py-2">שיעור פחת</th>
                <th className="text-right px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id} className="border-t hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium">{a.name}</td>
                  <td className="px-4 py-2">{CATEGORY_LABELS[a.category] || a.category}</td>
                  <td className="px-4 py-2">{fmt(a.cost)}</td>
                  <td className="px-4 py-2">{a.purchase_date}</td>
                  <td className="px-4 py-2">{a.depreciation_rate}%</td>
                  <td className="px-4 py-2 flex gap-2 justify-end">
                    <button onClick={() => viewSchedule(a.id)} title="לוח פחת"
                      className="p-1.5 rounded hover:bg-indigo-50 text-indigo-600"><TrendingDown className="w-4 h-4" /></button>
                    <button onClick={() => deleteAsset(a.id)} title="מחיקה"
                      className="p-1.5 rounded hover:bg-red-50 text-red-600"><Trash2 className="w-4 h-4" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {scheduleAssetId !== null && (
        <div className="border rounded-xl overflow-hidden mb-6">
          <div className="bg-slate-100 px-4 py-3 font-semibold">
            לוח פחת — {assets.find((a) => a.id === scheduleAssetId)?.name}
          </div>
          {!schedule ? (
            <div className="flex justify-center py-8 text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-right px-4 py-2">שנה</th>
                  <th className="text-right px-4 py-2">פחת שנתי</th>
                  <th className="text-right px-4 py-2">פחת מצטבר</th>
                  <th className="text-right px-4 py-2">ערך בספרים</th>
                </tr>
              </thead>
              <tbody>
                {schedule.map((r) => (
                  <tr key={r.year} className="border-t">
                    <td className="px-4 py-2">{r.year}</td>
                    <td className="px-4 py-2">{fmt(r.annual_depreciation)}</td>
                    <td className="px-4 py-2">{fmt(r.accumulated)}</td>
                    <td className="px-4 py-2 font-semibold">{fmt(r.book_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-lg font-semibold">סה"כ פחת שנתי ונספח פחת (טופס 1342)</h2>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))}
          className="border rounded-lg px-2 py-1 text-sm w-24" />
      </div>

      {annualTotal !== null && (
        <div className="mb-4 p-4 rounded-lg bg-indigo-50 text-indigo-900 text-sm font-semibold">
          סה"כ פחת שנת {year}: {fmt(annualTotal)}
        </div>
      )}

      {form1342 && (
        <div className="border rounded-xl overflow-hidden">
          <div className="bg-slate-100 px-4 py-3 font-semibold">{form1342.title} — {form1342.year}</div>
          {form1342.rows.length === 0 ? (
            <div className="text-center py-8 text-slate-400">אין נכסים רשומים לשנה זו.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-right px-4 py-2">שם</th>
                  <th className="text-right px-4 py-2">קטגוריה</th>
                  <th className="text-right px-4 py-2">עלות</th>
                  <th className="text-right px-4 py-2">שיעור</th>
                  <th className="text-right px-4 py-2">פחת פתיחה מצטבר</th>
                  <th className="text-right px-4 py-2">פחת השנה</th>
                  <th className="text-right px-4 py-2">פחת מצטבר סגירה</th>
                  <th className="text-right px-4 py-2">ערך בספרים</th>
                </tr>
              </thead>
              <tbody>
                {form1342.rows.map((r) => (
                  <tr key={r.asset_id} className="border-t">
                    <td className="px-4 py-2">{r.name}</td>
                    <td className="px-4 py-2">{CATEGORY_LABELS[r.category] || r.category}</td>
                    <td className="px-4 py-2">{fmt(r.cost)}</td>
                    <td className="px-4 py-2">{r.rate}%</td>
                    <td className="px-4 py-2">{fmt(r.opening_accumulated)}</td>
                    <td className="px-4 py-2">{fmt(r.depreciation_this_year)}</td>
                    <td className="px-4 py-2">{fmt(r.accumulated_depreciation)}</td>
                    <td className="px-4 py-2 font-semibold">{fmt(r.book_value)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t font-bold bg-slate-50">
                  <td className="px-4 py-2" colSpan={2}>סה"כ</td>
                  <td className="px-4 py-2">{fmt(form1342.totals.cost)}</td>
                  <td className="px-4 py-2"></td>
                  <td className="px-4 py-2"></td>
                  <td className="px-4 py-2">{fmt(form1342.totals.depreciation_this_year)}</td>
                  <td className="px-4 py-2">{fmt(form1342.totals.accumulated_depreciation)}</td>
                  <td className="px-4 py-2">{fmt(form1342.totals.book_value)}</td>
                </tr>
              </tfoot>
            </table>
          )}
          <p className="px-4 py-3 text-xs text-slate-500 bg-slate-50">{form1342.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
