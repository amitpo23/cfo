import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  TrendingUp, Building2, AlertTriangle, Target, PieChart,
  Lightbulb, Percent, Brain, Gauge,
} from 'lucide-react';
import apiService from '../services/api';
import { AgentPanel, FinanceCard, FinancePageShell, MetricCard } from './finance-ui';

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
  const { data, isLoading } = useQuery({
    queryKey: ['executive-dashboard'],
    queryFn: async () => {
      const res: any = await apiService.getExecutiveDashboard();
      return res.data;
    },
  });

  const panels: Record<string, Panel> = data?.panels || {};
  const profitLoss = panels.profit_loss?.data || {};
  const bank = panels.bank_reconciliation?.data || {};
  const budget = panels.budget_vs_actual?.data || {};
  const fees = panels.fees?.data || {};
  // ה-API מחזיר unreconciled_bank_transactions; שומרים fallback לשם הישן ליתר ביטחון.
  const unreconciledCount = (v: any) => v?.unreconciled_bank_transactions ?? v?.unreconciled_count ?? 0;

  const period = data?.period;
  const formatDate = (iso?: string) => {
    if (!iso) return null;
    const [y, m, d] = iso.split('-');
    return d && m && y ? `${d}/${m}/${y}` : iso;
  };
  const periodLabel = period?.start && period?.end
    ? `תקופה: ${formatDate(period.start)}–${formatDate(period.end)} (מתחילת שנה)`
    : null;

  const Card: React.FC<{ icon: any; title: string; panel?: Panel; children: (d: any) => React.ReactNode }> =
    ({ icon: Icon, title, panel, children }) => (
      <FinanceCard darkMode={darkMode} icon={Icon} title={title}>
        {!panel ? (
          <div className="text-gray-400 text-sm">—</div>
        ) : !panel.ok ? (
          <div className="text-amber-600 text-sm">לא ניתן לטעון פאנל זה</div>
        ) : (
          children(panel.data)
        )}
      </FinanceCard>
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
    <FinancePageShell
      darkMode={darkMode}
      eyebrow="Executive Control"
      title="דשבורד מנהלים"
      description={
        <>
          מסך הנהלה שמחליף דוח סטטי: רווח והפסד, התאמות בנק, תקציב, עמלות, חריגות והמלצות פעולה בזמן אמת.
          {periodLabel && (
            <span className={darkMode ? 'mt-1 block text-slate-400' : 'mt-1 block text-slate-500'}>
              {periodLabel}
            </span>
          )}
        </>
      }
      icon={Gauge}
      metrics={[
        { label: 'רווח נקי', value: fmt(profitLoss.net_income || 0), tone: (profitLoss.net_income || 0) >= 0 ? 'emerald' : 'rose' },
        { label: 'תנועות לא מותאמות', value: String(unreconciledCount(bank)), tone: unreconciledCount(bank) > 0 ? 'amber' : 'emerald' },
        { label: 'סטיית תקציב', value: `${(budget.variance_percentage || 0).toFixed(1)}%`, tone: (budget.variance_percentage || 0) < -5 ? 'rose' : 'blue' },
        { label: 'עמלות', value: fmt(fees.total_fees || 0), tone: 'slate' },
      ]}
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <MetricCard
          darkMode={darkMode}
          icon={TrendingUp}
          label="רווחיות"
          value={fmt(profitLoss.total_revenue || 0)}
          detail={`הוצאות: ${fmt(profitLoss.total_expenses || 0)}`}
          tone="emerald"
        />
        <MetricCard
          darkMode={darkMode}
          icon={Building2}
          label="התאמות"
          value={String(unreconciledCount(bank))}
          detail={`חשבוניות באיחור: ${fmt(bank.overdue_invoices_amount || 0)}`}
          tone={unreconciledCount(bank) > 0 ? 'amber' : 'emerald'}
        />
        <MetricCard
          darkMode={darkMode}
          icon={Target}
          label="תקציב"
          value={fmt(budget.total_actual || 0)}
          detail={`תקציב: ${fmt(budget.total_budget || 0)}`}
          tone="blue"
        />
        <MetricCard
          darkMode={darkMode}
          icon={Brain}
          label="הזדמנויות"
          value={String((panels.ai_opportunities?.data?.insights || []).length)}
          detail="תובנות לשיפור רווחיות ותפעול"
          tone="slate"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 1. רווח והפסד */}
        <Card icon={TrendingUp} title="1. רווח והפסד" panel={panels.profit_loss}>
          {(d) => (<>
            <Row label="הכנסות" value={fmt(d.total_revenue)} />
            <Row label="הוצאות" value={fmt(d.total_expenses)} />
            <Row label="רווח נקי" value={fmt(d.net_income)} warn={d.net_income < 0} />
            <Row label="שולי רווח נקי" value={pct((d.net_margin || 0) / 100)} />
          </>)}
        </Card>

        {/* 2. פערי התאמת בנקים */}
        <Card icon={Building2} title="2. פערי התאמת בנקים" panel={panels.bank_reconciliation}>
          {(d) => (<>
            <Row label="תנועות לא מותאמות" value={String(unreconciledCount(d))}
              warn={unreconciledCount(d) > 0} />
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

      <AgentPanel
        darkMode={darkMode}
        insights={[
          {
            title: 'פחות תלות בסגירת חודש',
            text: 'הדשבורד מציג רווחיות, התאמות וחריגות תוך כדי עבודה, כדי לקבל החלטות לפני שהחודש נסגר.',
          },
          {
            title: 'המלצות לשיפור רווחיות',
            text: `${fmt(fees.total_fees || 0)} בעמלות מזוהות. הסוכן בודק עמלות, חריגות תקציב ושחיקת מרווחים.`,
          },
        ]}
      />
    </FinancePageShell>
  );
};

export default ExecutiveDashboard;
