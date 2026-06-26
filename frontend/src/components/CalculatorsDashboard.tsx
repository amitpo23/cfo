/**
 * Deterministic calculators — fields in, a number out. No chat, no tokens.
 * Renders a grid of calculator cards from /api/calculators and a generic form per
 * calculator; submitting posts the inputs and shows the number + breakdown.
 */
import { useEffect, useMemo, useState } from 'react';
import { Calculator, Loader2, ArrowRight, Plus, Trash2 } from 'lucide-react';
import api from '../services/api';

interface Field {
  name: string;
  label: string;
  type: 'number' | 'boolean' | 'select' | 'subjects';
  default?: any;
  unit?: string;
  options?: string[];
}
interface Calc { id: string; title: string; category: string; fields: Field[]; }
interface CalcResult {
  result: number; unit: string;
  breakdown: Array<{ label: string; value: number; unit: string }>;
  note: string;
}

export default function CalculatorsDashboard() {
  const [calcs, setCalcs] = useState<Calc[]>([]);
  const [active, setActive] = useState<Calc | null>(null);
  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [subjects, setSubjects] = useState<Array<{ grade: number; units: number }>>([{ grade: 90, units: 5 }]);
  const [result, setResult] = useState<CalcResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ calculators: Calc[] }>('/api/calculators')
      .then((r) => setCalcs(r.calculators || []))
      .catch(() => setError('שגיאה בטעינת המחשבונים'));
  }, []);

  const byCategory = useMemo(() => {
    const m: Record<string, Calc[]> = {};
    for (const c of calcs) (m[c.category] ||= []).push(c);
    return m;
  }, [calcs]);

  const openCalc = (c: Calc) => {
    setActive(c);
    setResult(null);
    setError(null);
    const init: Record<string, any> = {};
    c.fields.forEach((f) => { if (f.default !== undefined && f.default !== null) init[f.name] = f.default; });
    setInputs(init);
    setSubjects([{ grade: 90, units: 5 }]);
  };

  const submit = async () => {
    if (!active) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const payload: Record<string, any> = { ...inputs };
      if (active.fields.some((f) => f.type === 'subjects')) payload.subjects = subjects;
      const r = await api.post<CalcResult>(`/api/calculators/${active.id}`, payload);
      setResult(r);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בחישוב');
    } finally { setBusy(false); }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Calculator className="text-indigo-600" /> מחשבונים
        </h1>
        <p className="text-slate-500 text-sm mt-1">חישוב דטרמיניסטי — ממלאים שדות, מקבלים מספר. בלי צ'אט, בלי טוקנים.</p>
      </div>

      {error && !active && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {!active ? (
        <div className="space-y-6">
          {Object.entries(byCategory).map(([cat, list]) => (
            <section key={cat}>
              <h2 className="text-sm font-semibold text-slate-500 mb-2">{cat}</h2>
              <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-3">
                {list.map((c) => (
                  <button key={c.id} onClick={() => openCalc(c)}
                    className="text-right border rounded-xl p-4 bg-white hover:border-indigo-400 hover:shadow-sm transition">
                    <div className="flex items-center justify-between">
                      <Calculator className="w-5 h-5 text-indigo-500" />
                      <ArrowRight className="w-4 h-4 text-slate-300" />
                    </div>
                    <div className="font-semibold mt-2">{c.title}</div>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="max-w-xl">
          <button onClick={() => setActive(null)} className="text-sm text-slate-500 mb-3">→ חזרה לכל המחשבונים</button>
          <div className="border rounded-xl p-5 bg-white">
            <h2 className="font-bold text-lg mb-4">{active.title}</h2>
            <div className="space-y-3">
              {active.fields.map((f) => (
                <div key={f.name}>
                  {f.type === 'boolean' ? (
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={!!inputs[f.name]}
                        onChange={(e) => setInputs({ ...inputs, [f.name]: e.target.checked })} />
                      {f.label}
                    </label>
                  ) : f.type === 'select' ? (
                    <label className="block text-sm">
                      <span className="text-slate-600">{f.label}</span>
                      <select className="mt-1 w-full border rounded-lg px-3 py-2"
                        value={inputs[f.name] ?? f.default}
                        onChange={(e) => setInputs({ ...inputs, [f.name]: e.target.value })}>
                        {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </label>
                  ) : f.type === 'subjects' ? (
                    <SubjectsEditor subjects={subjects} setSubjects={setSubjects} />
                  ) : (
                    <label className="block text-sm">
                      <span className="text-slate-600">{f.label}{f.unit ? ` (${f.unit})` : ''}</span>
                      <input type="number" className="mt-1 w-full border rounded-lg px-3 py-2"
                        value={inputs[f.name] ?? ''}
                        onChange={(e) => setInputs({ ...inputs, [f.name]: e.target.value === '' ? '' : Number(e.target.value) })} />
                    </label>
                  )}
                </div>
              ))}
            </div>

            <button onClick={submit} disabled={busy}
              className="mt-4 inline-flex items-center gap-1 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700 disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Calculator className="w-4 h-4" />} חשב
            </button>

            {error && <div className="mt-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

            {result && (
              <div className="mt-5 border-t pt-4">
                <div className="text-3xl font-bold text-indigo-700">
                  {result.result.toLocaleString()} <span className="text-base text-slate-500">{result.unit}</span>
                </div>
                <table className="w-full text-sm mt-3">
                  <tbody>
                    {result.breakdown.map((b, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="py-1 text-slate-600">{b.label}</td>
                        <td className="py-1 text-left font-medium">
                          {b.value.toLocaleString()} <span className="text-xs text-slate-400">{b.unit}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {result.note && <p className="text-xs text-slate-400 mt-3">ℹ️ {result.note}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SubjectsEditor({ subjects, setSubjects }: {
  subjects: Array<{ grade: number; units: number }>;
  setSubjects: (s: Array<{ grade: number; units: number }>) => void;
}) {
  const update = (i: number, key: 'grade' | 'units', v: number) => {
    const next = [...subjects];
    next[i] = { ...next[i], [key]: v };
    setSubjects(next);
  };
  return (
    <div>
      <span className="text-slate-600 text-sm">מקצועות (ציון / יחידות)</span>
      <div className="space-y-2 mt-1">
        {subjects.map((s, i) => (
          <div key={i} className="flex gap-2 items-center">
            <input type="number" className="border rounded-lg px-2 py-1 w-24" placeholder="ציון"
              value={s.grade} onChange={(e) => update(i, 'grade', Number(e.target.value))} />
            <input type="number" className="border rounded-lg px-2 py-1 w-24" placeholder="יח'"
              value={s.units} onChange={(e) => update(i, 'units', Number(e.target.value))} />
            <button onClick={() => setSubjects(subjects.filter((_, j) => j !== i))}
              className="text-slate-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
          </div>
        ))}
        <button onClick={() => setSubjects([...subjects, { grade: 90, units: 5 }])}
          className="inline-flex items-center gap-1 text-xs text-indigo-600"><Plus className="w-3 h-3" /> הוסף מקצוע</button>
      </div>
    </div>
  );
}
