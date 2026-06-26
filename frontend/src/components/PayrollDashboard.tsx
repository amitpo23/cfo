/**
 * Payroll dashboard — employees, monthly payroll run, payslips, and Form 102.
 * Deterministic salary math (backend services/calculators.payslip_components).
 */
import { useEffect, useState } from 'react';
import { Users, Plus, Play, Loader2, FileText } from 'lucide-react';
import api from '../services/api';

interface Employee {
  id: number; name: string; tax_id: string | null;
  gross_salary: number; credit_points: number; pension_pct: number;
}
interface Payslip {
  id: number; employee_id: number; employee_name: string;
  gross: number; income_tax: number; ni_employee: number; health_tax: number;
  pension_employee: number; net: number; employer_cost: number;
}
interface Form102 {
  period: string; employees: number; income_tax: number;
  total_national_insurance: number; grand_total: number; due_date: string;
}

const now = new Date();
const emptyEmp = { name: '', tax_id: '', gross_salary: 0, credit_points: 2.25, pension_pct: 6.0 };

export default function PayrollDashboard() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [payslips, setPayslips] = useState<Payslip[]>([]);
  const [form102, setForm102] = useState<Form102 | null>(null);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [form, setForm] = useState({ ...emptyEmp });
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadEmployees = async () => {
    const r = await api.get<{ employees: Employee[] }>('/api/payroll/employees');
    setEmployees(r.employees || []);
  };
  const loadPeriod = async () => {
    try {
      const [p, f] = await Promise.all([
        api.get<{ payslips: Payslip[] }>(`/api/payroll/payslips?year=${year}&month=${month}`),
        api.get<Form102>(`/api/payroll/reports/102?year=${year}&month=${month}`),
      ]);
      setPayslips(p.payslips || []);
      setForm102(f);
    } catch { /* empty period */ }
  };

  useEffect(() => { loadEmployees().catch(() => setError('שגיאה בטעינת עובדים')); }, []);
  useEffect(() => { loadPeriod(); }, [year, month]);

  const addEmployee = async () => {
    setBusy('add'); setError(null);
    try {
      await api.post('/api/payroll/employees', form);
      setForm({ ...emptyEmp }); setShowForm(false);
      await loadEmployees();
    } catch (e: any) { setError(e?.response?.data?.detail || 'שגיאה בהוספת עובד'); }
    finally { setBusy(null); }
  };

  const runPayroll = async () => {
    setBusy('run'); setError(null); setNotice(null);
    try {
      const r = await api.post<{ employees: number }>(`/api/payroll/run?year=${year}&month=${month}`);
      setNotice(`הופקו תלושים ל-${r.employees} עובדים לתקופה ${month}/${year}.`);
      await loadPeriod();
    } catch (e: any) { setError(e?.response?.data?.detail || 'שגיאה בהרצת שכר'); }
    finally { setBusy(null); }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2"><Users className="text-indigo-600" /> שכר</h1>
        <div className="flex items-center gap-2">
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm">
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm w-24" />
          <button onClick={runPayroll} disabled={!!busy}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm hover:bg-emerald-700 disabled:opacity-50">
            {busy === 'run' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} הרץ שכר
          </button>
          <button onClick={() => setShowForm((s) => !s)}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700">
            <Plus className="w-4 h-4" /> עובד
          </button>
        </div>
      </div>

      {notice && <div className="mb-4 p-3 rounded-lg bg-emerald-50 text-emerald-800 text-sm">{notice}</div>}
      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {showForm && (
        <div className="mb-6 p-4 border rounded-xl bg-slate-50 grid md:grid-cols-5 gap-3">
          <input className="border rounded-lg px-3 py-2 text-sm" placeholder="שם עובד" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="border rounded-lg px-3 py-2 text-sm" placeholder="ת.ז" value={form.tax_id}
            onChange={(e) => setForm({ ...form, tax_id: e.target.value })} />
          <input type="number" className="border rounded-lg px-3 py-2 text-sm" placeholder="ברוטו" value={form.gross_salary || ''}
            onChange={(e) => setForm({ ...form, gross_salary: Number(e.target.value) })} />
          <input type="number" step="0.25" className="border rounded-lg px-3 py-2 text-sm" placeholder="נק' זיכוי" value={form.credit_points}
            onChange={(e) => setForm({ ...form, credit_points: Number(e.target.value) })} />
          <input type="number" className="border rounded-lg px-3 py-2 text-sm" placeholder="% פנסיה" value={form.pension_pct}
            onChange={(e) => setForm({ ...form, pension_pct: Number(e.target.value) })} />
          <button onClick={addEmployee} disabled={!!busy || !form.name}
            className="md:col-span-5 mt-1 px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm hover:bg-emerald-700 disabled:opacity-50">
            שמור עובד
          </button>
        </div>
      )}

      {form102 && form102.employees > 0 && (
        <div className="mb-6 p-4 border rounded-xl bg-white flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2 font-semibold"><FileText className="w-5 h-5 text-indigo-600" /> דוח 102 — {form102.period}</div>
          <div className="text-sm text-slate-600">מס הכנסה: ₪{form102.income_tax.toLocaleString()}</div>
          <div className="text-sm text-slate-600">ביטוח לאומי: ₪{form102.total_national_insurance.toLocaleString()}</div>
          <div className="text-sm font-bold">סה"כ לתשלום: ₪{form102.grand_total.toLocaleString()}</div>
          <div className="text-xs text-slate-400">להגשה עד {form102.due_date}</div>
        </div>
      )}

      <div className="border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="text-right px-4 py-2">עובד</th>
              <th className="text-right px-4 py-2">ברוטו</th>
              <th className="text-right px-4 py-2">מס הכנסה</th>
              <th className="text-right px-4 py-2">ב"ל+בריאות</th>
              <th className="text-right px-4 py-2">פנסיה</th>
              <th className="text-right px-4 py-2">נטו</th>
              <th className="text-right px-4 py-2">עלות מעסיק</th>
            </tr>
          </thead>
          <tbody>
            {payslips.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-10 text-slate-400">
                {employees.length === 0 ? 'הוסף עובדים והרץ שכר.' : 'אין תלושים לתקופה — לחץ "הרץ שכר".'}
              </td></tr>
            ) : payslips.map((p) => (
              <tr key={p.id} className="border-t">
                <td className="px-4 py-2 font-medium">{p.employee_name}</td>
                <td className="px-4 py-2">₪{p.gross.toLocaleString()}</td>
                <td className="px-4 py-2 text-rose-600">₪{p.income_tax.toLocaleString()}</td>
                <td className="px-4 py-2 text-rose-600">₪{(p.ni_employee + p.health_tax).toLocaleString()}</td>
                <td className="px-4 py-2 text-rose-600">₪{p.pension_employee.toLocaleString()}</td>
                <td className="px-4 py-2 font-bold text-emerald-700">₪{p.net.toLocaleString()}</td>
                <td className="px-4 py-2 text-slate-500">₪{p.employer_cost.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {employees.length > 0 && (
        <p className="text-xs text-slate-400 mt-3">{employees.length} עובדים פעילים. דוח 126 שנתי: <code>/api/payroll/reports/126</code></p>
      )}
    </div>
  );
}
