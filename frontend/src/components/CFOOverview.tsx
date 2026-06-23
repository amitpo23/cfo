import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts';
import {
  Wallet, TrendingUp, AlertTriangle,
  FileCheck, Receipt, ArrowRight, RefreshCw, Clock,
  DollarSign, Activity, Shield, Gauge, Sparkles, Landmark, CheckCircle2,
} from 'lucide-react';
import apiService from '../services/api';
import { AgentPanel, FinanceCard, FinancePageShell, MetricCard, formatILS } from './finance-ui';

interface CFOOverviewProps {
  darkMode: boolean;
}

interface DashboardOverview {
  cash_balance: number;
  month_revenue: number;
  month_expenses: number;
  month_net_profit: number;
  runway_months: number | null;
  ar_total: number;
  ar_overdue: number;
  ap_total: number;
  ap_due_7_days: number;
  ap_due_30_days: number;
  alerts: Array<{ id: number; title: string; message: string; severity: string }>;
  last_sync: string | null;
  cash_by_account: Array<{ id: number; name: string; balance: number }>;
}

interface PNLDataPoint {
  month: string;
  revenue: number;
  net_profit: number;
}

interface CashflowDataPoint {
  week: string;
  cumulative_balance: number;
  expected_inflows: number;
  expected_outflows: number;
}

const CFOOverview: React.FC<CFOOverviewProps> = ({ darkMode }) => {
  const { data: overview, isLoading, refetch } = useQuery({
    queryKey: ['dashboard-overview'],
    queryFn: () => apiService.get<DashboardOverview>('/dashboard/overview'),
    refetchInterval: 60000, // refresh every minute
  });

  const { data: pnlData } = useQuery({
    queryKey: ['dashboard-pnl'],
    queryFn: () => apiService.get<PNLDataPoint[]>('/dashboard/pnl?months=6'),
  });

  const { data: cashflowData } = useQuery({
    queryKey: ['dashboard-cashflow'],
    queryFn: () => apiService.get<CashflowDataPoint[]>('/dashboard/cashflow?weeks=8&scenario=base'),
  });

  const handleSyncNow = async () => {
    try {
      await apiService.post('/sync/run');
      refetch();
    } catch (err) {
      // Error handling - sync failed
    }
  };

  if (isLoading) {
    return (
      <div className={`p-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-gray-300 rounded w-1/3" />
          <div className="grid grid-cols-4 gap-6">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-32 bg-gray-200 rounded-2xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  const ov: DashboardOverview = overview || {
    cash_balance: 0,
    month_revenue: 0,
    month_expenses: 0,
    month_net_profit: 0,
    runway_months: null,
    ar_total: 0,
    ar_overdue: 0,
    ap_total: 0,
    ap_due_7_days: 0,
    ap_due_30_days: 0,
    alerts: [],
    last_sync: null,
    cash_by_account: [],
  };
  const cashBalance = ov.cash_balance || 0;
  const monthRevenue = ov.month_revenue || 0;
  const monthNetProfit = ov.month_net_profit || 0;
  const runwayMonths = ov.runway_months;
  const arTotal = ov.ar_total || 0;
  const arOverdue = ov.ar_overdue || 0;
  const apTotal = ov.ap_total || 0;
  const apDue7 = ov.ap_due_7_days || 0;
  const alerts = ov.alerts || [];
  const lastSync = ov.last_sync;
  const cashByAccount = ov.cash_by_account || [];

  const fmt = (n: number) =>
    new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(n);

  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

  return (
    <FinancePageShell
      darkMode={darkMode}
      eyebrow="Command Center"
      title="מרכז שליטה פיננסי"
      description="תמונה יומית של הכסף: יתרות, גבייה, ספקים, רווחיות, תזרים וסיכונים. המטרה היא להחליף עבודת מעקב ידנית בפעולות מוכנות לאישור."
      icon={Gauge}
      metrics={[
        { label: 'יתרת מזומן', value: fmt(cashBalance), tone: 'blue' },
        { label: 'רווח נקי חודש', value: fmt(monthNetProfit), tone: monthNetProfit >= 0 ? 'emerald' : 'rose' },
        { label: 'חובות באיחור', value: fmt(arOverdue), tone: arOverdue > 0 ? 'amber' : 'emerald' },
        { label: 'התראות פעילות', value: String(alerts.length), tone: alerts.length ? 'rose' : 'emerald' },
      ]}
      actions={
        <button
          type="button"
          onClick={handleSyncNow}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSyncNow(); }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition font-medium"
        >
          <RefreshCw size={18} />
          סנכרן עכשיו
        </button>
      }
    >
      <div className={`rounded-2xl border p-4 ${darkMode ? 'border-slate-700 bg-slate-900 text-slate-300' : 'border-slate-200 bg-white text-slate-600'}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            {lastSync ? `עדכון אחרון: ${new Date(lastSync).toLocaleString('he-IL')}` : 'עדיין אין נתוני סנכרון. הרץ סנכרון כדי לקבל תמונה מלאה.'}
          </div>
          <div className="text-sm font-medium">המערכת מזהה פערים ומייצרת משימות גבייה, תשלום והתאמה.</div>
        </div>
      </div>

      {/* Top KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          darkMode={darkMode}
          icon={Wallet}
          label="יתרה זמינה"
          value={fmt(cashBalance)}
          detail={runwayMonths != null ? `${runwayMonths} חודשי runway` : 'תזרים חיובי'}
          tone="blue"
        />
        <MetricCard
          darkMode={darkMode}
          icon={TrendingUp}
          label="הכנסות החודש"
          value={fmt(monthRevenue)}
          detail={`רווח נקי: ${fmt(monthNetProfit)}`}
          tone="emerald"
        />
        <MetricCard
          darkMode={darkMode}
          icon={FileCheck}
          label="לקוחות חייבים"
          value={fmt(arTotal)}
          detail={arOverdue > 0 ? `${fmt(arOverdue)} באיחור` : 'אין איחור מהותי'}
          tone={arOverdue > 0 ? 'rose' : 'emerald'}
        />
        <MetricCard
          darkMode={darkMode}
          icon={Receipt}
          label="ספקים לתשלום"
          value={fmt(apTotal)}
          detail={`${fmt(apDue7)} ל-7 ימים הקרובים`}
          tone="amber"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* P&L Trend */}
        <FinanceCard
          darkMode={darkMode}
          title="רווח והפסד יומי/חודשי"
          subtitle="הכנסות מול רווח נקי, כדי להבין אם העסק באמת מרוויח בזמן אמת"
          icon={TrendingUp}
          action={
            <Link to="/pnl" className="text-blue-500 text-sm hover:text-blue-600 flex items-center gap-1">
              פירוט <ArrowRight size={14} />
            </Link>
          }
        >
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={pnlData || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? '#374151' : '#e5e7eb'} />
              <XAxis dataKey="month" stroke={darkMode ? '#9ca3af' : '#6b7280'} fontSize={12} />
              <YAxis stroke={darkMode ? '#9ca3af' : '#6b7280'} fontSize={12} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip
                contentStyle={{
                  backgroundColor: darkMode ? '#1f2937' : '#fff',
                  border: `1px solid ${darkMode ? '#374151' : '#e5e7eb'}`,
                  borderRadius: '8px',
                }}
                formatter={(value: number) => fmt(value)}
              />
              <Bar dataKey="revenue" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Revenue" />
              <Bar dataKey="net_profit" fill="#10b981" radius={[4, 4, 0, 0]} name="Net Profit" />
            </BarChart>
          </ResponsiveContainer>
        </FinanceCard>

        {/* Cash Flow Projection */}
        <FinanceCard
          darkMode={darkMode}
          title="תחזית תזרים"
          subtitle="יתרה צפויה, כסף נכנס וכסף יוצא כדי לדעת לפני שנוצר לחץ בבנק"
          icon={Landmark}
          action={
            <Link to="/cashflow" className="text-blue-500 text-sm hover:text-blue-600 flex items-center gap-1">
              פירוט <ArrowRight size={14} />
            </Link>
          }
        >
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={cashflowData || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? '#374151' : '#e5e7eb'} />
              <XAxis
                dataKey="week"
                stroke={darkMode ? '#9ca3af' : '#6b7280'}
                fontSize={12}
                tickFormatter={(v: string) => {
                  const d = new Date(v);
                  return `${d.getMonth() + 1}/${d.getDate()}`;
                }}
              />
              <YAxis stroke={darkMode ? '#9ca3af' : '#6b7280'} fontSize={12} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip
                contentStyle={{
                  backgroundColor: darkMode ? '#1f2937' : '#fff',
                  border: `1px solid ${darkMode ? '#374151' : '#e5e7eb'}`,
                  borderRadius: '8px',
                }}
                formatter={(value: number) => fmt(value)}
              />
              <Line type="monotone" dataKey="cumulative_balance" stroke="#3b82f6" strokeWidth={2} dot={false} name="Balance" />
              <Line type="monotone" dataKey="expected_inflows" stroke="#10b981" strokeWidth={1} strokeDasharray="5 5" dot={false} name="Inflows" />
              <Line type="monotone" dataKey="expected_outflows" stroke="#ef4444" strokeWidth={1} strokeDasharray="5 5" dot={false} name="Outflows" />
            </LineChart>
          </ResponsiveContainer>
        </FinanceCard>
      </div>

      {/* Bottom Row: Alerts + Cash Accounts + Quick Links */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Alerts */}
        <FinanceCard
          darkMode={darkMode}
          title="התראות ומשימות"
          subtitle="מה צריך טיפול לפני סוף היום"
          icon={AlertTriangle}
          action={
            <Link to="/alerts" className="text-blue-500 text-sm hover:text-blue-600">View all</Link>
          }
        >
          {alerts.length === 0 ? (
            <div className={`text-center py-8 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <Shield size={32} className="mx-auto mb-2 opacity-50" />
              <p>No active alerts</p>
            </div>
          ) : (
            <div className="space-y-3">
              {alerts.map((alert) => (
                <div
                  key={alert.id}
                  className={`p-3 rounded-xl border ${
                    alert.severity === 'critical'
                      ? darkMode ? 'border-red-800 bg-red-900/20' : 'border-red-200 bg-red-50'
                      : alert.severity === 'warning'
                        ? darkMode ? 'border-yellow-800 bg-yellow-900/20' : 'border-yellow-200 bg-yellow-50'
                        : darkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <p className={`text-sm font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                    {alert.title}
                  </p>
                  <p className={`text-xs mt-1 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    {alert.message}
                  </p>
                </div>
              ))}
            </div>
          )}
        </FinanceCard>

        {/* Cash by Account */}
        <FinanceCard darkMode={darkMode} title="יתרות לפי חשבון" subtitle="פיזור מזומנים ותזרים זמין" icon={DollarSign}>
          {cashByAccount.length === 0 ? (
            <div className={`text-center py-8 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <DollarSign size={32} className="mx-auto mb-2 opacity-50" />
              <p>No account data yet</p>
              <p className="text-xs mt-1">Run a sync to pull account balances</p>
            </div>
          ) : (
            <div className="space-y-3">
              {cashByAccount.map((acct, idx) => (
                <div key={acct.id} className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: COLORS[idx % COLORS.length] }}
                    />
                    <span className={`text-sm ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                      {acct.name}
                    </span>
                  </div>
                  <span className="font-semibold">{fmt(acct.balance)}</span>
                </div>
              ))}
              <div className={`pt-3 mt-3 border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'} flex justify-between font-bold`}>
                <span>Total</span>
                <span>{fmt(cashBalance)}</span>
              </div>
            </div>
          )}
        </FinanceCard>

        {/* Quick Navigation */}
        <FinanceCard darkMode={darkMode} title="פעולות מהירות" subtitle="מעבר למסכים שמחליפים עבודה ידנית" icon={Sparkles}>
          <div className="space-y-2">
            {[
              { to: '/ar', label: 'מי חייב לנו', icon: <FileCheck size={18} />, color: 'text-blue-500' },
              { to: '/ap', label: 'מה אנחנו חייבים', icon: <Receipt size={18} />, color: 'text-green-500' },
              { to: '/cashflow', label: 'תחזית תזרים', icon: <Activity size={18} />, color: 'text-purple-500' },
              { to: '/budget', label: 'תקציב מול ביצוע', icon: <DollarSign size={18} />, color: 'text-yellow-500' },
              { to: '/tasks', label: 'משימות סוכן', icon: <Clock size={18} />, color: 'text-red-500' },
              { to: '/sync', label: 'סטטוס נתונים', icon: <RefreshCw size={18} />, color: 'text-cyan-500' },
            ].map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center justify-between p-3 rounded-xl transition ${
                  darkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className={item.color}>{item.icon}</span>
                  <span className="text-sm font-medium">{item.label}</span>
                </div>
                <ArrowRight size={16} className={darkMode ? 'text-gray-500' : 'text-gray-400'} />
              </Link>
            ))}
          </div>
        </FinanceCard>
      </div>

      <AgentPanel
        darkMode={darkMode}
        insights={[
          {
            title: 'גבייה לפני תשלומי ספקים',
            text: `${formatILS(arOverdue || arTotal)} עומדים לגבייה. הסוכן ממליץ לתעדף לקוחות באיחור לפני תשלומי השבוע.`,
          },
          {
            title: 'שמירה על runway',
            text: runwayMonths != null ? `בקצב הנוכחי יש ${runwayMonths} חודשי runway. בדקו הוצאות חוזרות לפני אישור תשלומים.` : 'לאחר סנכרון נתונים תופיע תחזית runway מלאה.',
          },
        ]}
      />
    </FinancePageShell>
  );
};

export default CFOOverview;
