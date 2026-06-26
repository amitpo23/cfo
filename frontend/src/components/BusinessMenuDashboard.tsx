/**
 * Business capability menu (תפריט יכולות לעסק) — the per-client syllabus of
 * everything the platform does, each with a live readiness status.
 */
import { useEffect, useState } from 'react';
import {
  LayoutGrid, Loader2, CheckCircle2, AlertTriangle, Circle, ArrowLeft,
  BookOpen, TrendingUp, CreditCard, FileSpreadsheet, FileWarning, Users,
  Calculator, Landmark, Banknote, Cpu,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../services/api';

const ICONS: Record<string, any> = {
  BookOpen, TrendingUp, CreditCard, FileSpreadsheet, FileWarning, Users,
  Calculator, Landmark, Banknote, Cpu, AlertTriangle,
};

interface Capability { name: string; route: string; state: string; note: string; }
interface Section { key: string; title: string; icon: string; nature: string; capabilities: Capability[]; }
interface Menu {
  business_name: string; connections: { sumit: boolean; open_finance: boolean };
  bank_data_validated: boolean; sections: Section[];
  summary: { total: number; ready: number; blocked: number };
}

// Map capability backend routes to the in-app dashboard that surfaces them.
const ROUTE_TO_PAGE: Record<string, string> = {
  '/api/ledger/trial-balance': '/ledger', '/api/ledger/journal': '/ledger',
  '/api/ledger/account/{code}': '/ledger', '/api/ledger/balance-sheet': '/ledger',
  '/api/daily-reports/ar-aging': '/daily-reports', '/api/daily-reports/ap-aging': '/daily-reports',
  '/api/daily-reports/suppliers': '/daily-reports', '/api/daily-reports/cumulative-pl': '/daily-reports',
  '/api/daily-reports/vat': '/daily-reports', '/api/ar/aging': '/ar', '/api/reports/profit-loss': '/reports',
  '/api/annual-reports/1301': '/annual-reports', '/api/annual-reports/1214': '/annual-reports',
  '/api/payroll/payslips': '/payroll', '/api/payroll/reports/102': '/payroll', '/api/payroll/reports/126': '/payroll',
  '/api/calculators': '/calculators', '/api/open-finance/insights': '/bank-insights',
  '/api/open-finance/reconcile': '/bank-insights', '/api/masav/generate': '/masav',
  '/api/engine/anomalies': '/engine', '/api/engine/run': '/engine',
};

const STATE: Record<string, { label: string; cls: string; Icon: any }> = {
  ready: { label: 'פעיל', cls: 'text-emerald-700 bg-emerald-50', Icon: CheckCircle2 },
  needs_data: { label: 'דורש נתונים', cls: 'text-slate-500 bg-slate-50', Icon: Circle },
  blocked: { label: 'חסום', cls: 'text-amber-700 bg-amber-50', Icon: AlertTriangle },
  real: { label: 'זמין', cls: 'text-emerald-700 bg-emerald-50', Icon: CheckCircle2 },
};

export default function BusinessMenuDashboard() {
  const [menu, setMenu] = useState<Menu | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try { setMenu(await api.get<Menu>('/api/business/menu')); }
      catch (e: any) { setError(e?.response?.data?.detail || 'שגיאה בטעינת התפריט'); }
      finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <div className="flex justify-center py-24 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>;
  if (error) return <div className="p-6" dir="rtl"><div className="p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div></div>;
  if (!menu) return null;

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-1">
        <h1 className="text-2xl font-bold flex items-center gap-2"><LayoutGrid className="text-indigo-600" /> תפריט יכולות — {menu.business_name}</h1>
        <div className="text-sm text-slate-500">
          {menu.summary.ready}/{menu.summary.total} פעילות · {menu.summary.blocked} חסומות
        </div>
      </div>
      <div className="flex gap-2 mb-6 text-xs">
        <span className={`px-2 py-1 rounded ${menu.connections.sumit ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
          SUMIT {menu.connections.sumit ? '✓' : '—'}
        </span>
        <span className={`px-2 py-1 rounded ${menu.connections.open_finance ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
          Open Finance {menu.connections.open_finance ? '✓' : '—'}
        </span>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {menu.sections.map((s) => {
          const SectionIcon = ICONS[s.icon] || Circle;
          return (
            <div key={s.key} className="border rounded-xl overflow-hidden">
              <div className="bg-slate-100 px-4 py-2.5 font-semibold flex items-center gap-2">
                <SectionIcon className="w-4 h-4 text-indigo-600" /> {s.title}
              </div>
              <div className="divide-y">
                {s.capabilities.map((c, i) => {
                  const st = STATE[c.state] || STATE.needs_data;
                  const page = ROUTE_TO_PAGE[c.route];
                  return (
                    <div key={i} className="px-4 py-2.5 flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-medium text-sm flex items-center gap-1">
                          {page ? <Link to={page} className="hover:text-indigo-600 inline-flex items-center gap-1">{c.name} <ArrowLeft className="w-3 h-3" /></Link> : c.name}
                        </div>
                        <div className="text-xs text-slate-400">{c.note}</div>
                      </div>
                      <span className={`shrink-0 inline-flex items-center gap-1 text-xs px-2 py-1 rounded ${st.cls}`}>
                        <st.Icon className="w-3 h-3" /> {st.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
