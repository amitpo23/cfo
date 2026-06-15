import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  TrendingUp, Building2, AlertTriangle, Target, PieChart,
  Lightbulb, Percent, Brain,
} from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

interface Panel {
  ok: boolean;
  data?: any;
  error?: string;
}

const fmt = (v: number) => `₪${Math.round(v || 0).toLocaleString()}`;
const pct = (v: number) => `${((v || 0) * 100).toFixed(1)}%`;

const ExecutiveDashboard: React.FC<Props> = ({ darkMode }) => {
  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';

  const { data, isLoading } = useQuery({
    queryKey: ['executive-dashboard'],
    queryFn: async () => {
      const res: any = await apiService.getExecutiveDashboard();
      return res.data;
    },
  });

  const panels: Record<string, Panel> = data?.panels || {};

  const Card: React.FC<{ icon: any; title: string; panel?: Panel; children: (d: any) => React.ReactNode }> =
    ({ icon: Icon, title, panel, children }) => (
      <div className={`rounded-xl border p-5 ${card}`}>
        <div className="flex items-center gap-2 mb-3">
          <Icon className="w-5 h-5 text-blue-600" />
          <h2 className="font-semibold">{title}</h2>
        </div>
        {!panel ? (
          <div className="text-gray-400 text-sm">—</div>
        ) : !panel.ok ? (
          <div className="text-amber-600 text-sm">לא ניתן לטעון פאנל זה</div>
        ) : (
          children(panel.data)
        )}
      </div>
    );

  const Row: React.FC<{ label: string; value: string; warn?: boolean }> = ({ label, value, warn }) => (
    <div className="flex justify-between py-1 border-b last:border-0 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={`font-medium ${warn ? 'text-red-600' : ''}`}>{value}</span>
    </div>
  );

  if (isLoading) {
    return <div dir="rtl" className="p-6 text-center text-gray-500">טוען דשבורד...</div>;
  }

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">דשבורד מנהלים</h1>
        <p className="text-sm text-gray-500">תמונת מצב מלאה של העסק במבט אחד</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 1. רווח והפסד */}
        <Card icon={TrendingUp} title="1. רווח והפסד" panel={panels.profit_loss}>
          {(d) => (<>
            <Row label="הכנסות" value={fmt(d.total_revenue)} />
            <Row label="הוצאות" value={fmt(d.total_expenses)} />
            <Row label="רווח נקי" value={fmt(d.net_income)} warn={d.net_income < 0} />
            <Row label="שולי רווח נקי" value={pct(d.net_margin)} />
          </>)}
        </Card>

        {/* 2. פערי התאמת בנקים */}
        <Card icon={Building2} title="2. פערי התאמת בנקים" panel={panels.bank_reconciliation}>
          {(d) => (<>
            <Row label="תנועות לא מותאמות" value={String(d.unreconciled_count ?? 0)}
              warn={(d.unreconciled_count ?? 0) > 0} />
            <Row label="חשבוניות באיחור" value={fmt(d.overdue_invoices_amount ?? 0)} />
            <Row label="תשלומים קרובים (14 י')" value={fmt(d.upcoming_bills_amount_14d ?? 0)} />
          </>)}
        </Card>

        {/* 3. הוצאות שחרגו */}
        <Card icon={AlertTriangle} title="3. הוצאות שחרגו מהתקציב" panel={panels.expense_overruns}>
          {(d) => (
            Array.isArray(d) && d.length ? (
              <div className="space-y-1">
                {d.slice(0, 5).map((a: any, i: number) => (
                  <Row key={i} label={a.category_hebrew || a.category} value={fmt(a.actual_amount || 0)} warn />
                ))}
              </div>
            ) : <div className="text-green-600 text-sm">אין חריגות תקציב</div>
          )}
        </Card>

        {/* 4. ביצוע מול תקציב */}
        <Card icon={Target} title="4. ביצוע מול תקציב" panel={panels.budget_vs_actual}>
          {(d) => (<>
            <Row label="תקציב" value={fmt(d.total_budget)} />
            <Row label="ביצוע בפועל" value={fmt(d.total_actual)} />
            <Row label="סטייה" value={`${(d.variance_percentage || 0).toFixed(1)}%`}
              warn={(d.variance_percentage || 0) < -5} />
          </>)}
        </Card>

        {/* 5. בדיקת רווחיות */}
        <Card icon={PieChart} title="5. בדיקת רווחיות (לפי לקוח)" panel={panels.profitability}>
          {(d) => (
            Array.isArray(d.items) && d.items.length ? (
              <div className="space-y-1">
                {d.items.slice(0, 5).map((it: any, i: number) => (
                  <Row key={i} label={it.name}
                    value={`${pct((it.gross_margin || 0) / 100)} · ${fmt(it.revenue || 0)}`} />
                ))}
              </div>
            ) : <div className="text-gray-400 text-sm">אין נתוני רווחיות</div>
          )}
        </Card>

        {/* 6. שיפור רווחיות */}
        <Card icon={Lightbulb} title="6. בדיקת שיפור רווחיות" panel={panels.profitability_improvement}>
          {(d) => (
            Array.isArray(d) && d.length ? (
              <ul className="space-y-2 text-sm">
                {d.slice(0, 4).map((ins: any, i: number) => (
                  <li key={i} className="border-r-2 border-blue-400 pr-2">
                    <div className="font-medium">{ins.title}</div>
                    <div className="text-gray-500 text-xs">{ins.description}</div>
                  </li>
                ))}
              </ul>
            ) : <div className="text-gray-400 text-sm">אין המלצות כרגע</div>
          )}
        </Card>

        {/* 7. דוח עמלות */}
        <Card icon={Percent} title="7. עמלות (בנק / אשראי / הלוואות)" panel={panels.fees}>
          {(d) => (<>
            <Row label="סך עמלות" value={fmt(d.total_fees)} warn={d.fees_pct_of_expenses > 5} />
            <Row label="אחוז מההוצאות" value={`${(d.fees_pct_of_expenses || 0).toFixed(1)}%`} />
            {(d.by_type || []).map((t: any, i: number) => (
              <Row key={i} label={t.label} value={fmt(t.amount)} />
            ))}
          </>)}
        </Card>

        {/* 8. מיפוי שיפור באמצעות AI */}
        <Card icon={Brain} title="8. מיפוי לשיפור (AI)" panel={panels.ai_opportunities}>
          {(d) => (
            <div className="space-y-3 text-sm">
              {Array.isArray(d.risks) && d.risks.length > 0 && (
                <div>
                  <div className="font-medium text-red-600 mb-1">סיכונים</div>
                  {d.risks.slice(0, 3).map((r: any, i: number) => (
                    <div key={i} className="text-gray-500 text-xs">• {r.title}</div>
                  ))}
                </div>
              )}
              {Array.isArray(d.insights) && d.insights.length > 0 && (
                <div>
                  <div className="font-medium text-blue-600 mb-1">הזדמנויות</div>
                  {d.insights.slice(0, 3).map((ins: any, i: number) => (
                    <div key={i} className="text-gray-500 text-xs">• {ins.title}</div>
                  ))}
                </div>
              )}
              {(!d.risks?.length && !d.insights?.length) && (
                <div className="text-green-600">לא זוהו סיכונים או הזדמנויות מהותיות</div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

export default ExecutiveDashboard;
