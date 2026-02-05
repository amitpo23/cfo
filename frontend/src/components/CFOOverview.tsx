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
  DollarSign, Activity, Shield,
} from 'lucide-react';
import apiService from '../services/api';

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

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  } shadow-sm`;

  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

  return (
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">CFO Command Center</h1>
          <p className={`text-sm mt-1 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            {lastSync
              ? `Last synced: ${new Date(lastSync).toLocaleString()}`
              : 'No sync data yet'}
          </p>
        </div>
        <button
          type="button"
          onClick={handleSyncNow}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSyncNow(); }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition font-medium"
        >
          <RefreshCw size={18} />
          Sync Now
        </button>
      </div>

      {/* Top KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPICard
          darkMode={darkMode}
          icon={<Wallet size={24} />}
          label="Cash Balance"
          value={fmt(cashBalance)}
          sublabel={runwayMonths != null ? `${runwayMonths} months runway` : 'Positive cash flow'}
          color="blue"
        />
        <KPICard
          darkMode={darkMode}
          icon={<TrendingUp size={24} />}
          label="Month Revenue"
          value={fmt(monthRevenue)}
          sublabel={`Net profit: ${fmt(monthNetProfit)}`}
          color="green"
        />
        <KPICard
          darkMode={darkMode}
          icon={<FileCheck size={24} />}
          label="AR Outstanding"
          value={fmt(arTotal)}
          sublabel={arOverdue > 0 ? `${fmt(arOverdue)} overdue` : 'Nothing overdue'}
          color={arOverdue > 0 ? 'red' : 'green'}
        />
        <KPICard
          darkMode={darkMode}
          icon={<Receipt size={24} />}
          label="AP Outstanding"
          value={fmt(apTotal)}
          sublabel={`${fmt(apDue7)} due in 7 days`}
          color="yellow"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* P&L Trend */}
        <div className={cardClass}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">P&L Trend</h2>
            <Link to="/pnl" className="text-blue-500 text-sm hover:text-blue-600 flex items-center gap-1">
              Details <ArrowRight size={14} />
            </Link>
          </div>
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
        </div>

        {/* Cash Flow Projection */}
        <div className={cardClass}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Cash Flow Projection</h2>
            <Link to="/cashflow" className="text-blue-500 text-sm hover:text-blue-600 flex items-center gap-1">
              Details <ArrowRight size={14} />
            </Link>
          </div>
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
        </div>
      </div>

      {/* Bottom Row: Alerts + Cash Accounts + Quick Links */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Alerts */}
        <div className={cardClass}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <AlertTriangle size={20} className="text-yellow-500" />
              Alerts
            </h2>
            <Link to="/alerts" className="text-blue-500 text-sm hover:text-blue-600">View all</Link>
          </div>
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
        </div>

        {/* Cash by Account */}
        <div className={cardClass}>
          <h2 className="text-lg font-semibold mb-4">Cash by Account</h2>
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
        </div>

        {/* Quick Navigation */}
        <div className={cardClass}>
          <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
          <div className="space-y-2">
            {[
              { to: '/ar', label: 'AR Aging Report', icon: <FileCheck size={18} />, color: 'text-blue-500' },
              { to: '/ap', label: 'AP Due Bills', icon: <Receipt size={18} />, color: 'text-green-500' },
              { to: '/cashflow', label: 'Cash Flow Forecast', icon: <Activity size={18} />, color: 'text-purple-500' },
              { to: '/budget', label: 'Budget vs Actual', icon: <DollarSign size={18} />, color: 'text-yellow-500' },
              { to: '/tasks', label: 'Task Board', icon: <Clock size={18} />, color: 'text-red-500' },
              { to: '/sync', label: 'Sync Runs', icon: <RefreshCw size={18} />, color: 'text-cyan-500' },
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
        </div>
      </div>
    </div>
  );
};


// KPI Card sub-component
interface KPICardProps {
  darkMode: boolean;
  icon: React.ReactNode;
  label: string;
  value: string;
  sublabel: string;
  color: string;
}

const KPICard: React.FC<KPICardProps> = ({ darkMode, icon, label, value, sublabel, color }) => {
  const colorMap: Record<string, string> = {
    blue: 'bg-blue-100 text-blue-600',
    green: 'bg-green-100 text-green-600',
    yellow: 'bg-yellow-100 text-yellow-600',
    red: 'bg-red-100 text-red-600',
    purple: 'bg-purple-100 text-purple-600',
  };

  return (
    <div className={`p-6 rounded-2xl ${
      darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
    } shadow-sm hover:shadow-lg transition-shadow`}>
      <div className="flex items-start justify-between mb-4">
        <div className={`p-3 rounded-xl ${colorMap[color] || colorMap.blue}`}>
          {icon}
        </div>
      </div>
      <p className={`text-2xl font-bold mb-1 ${darkMode ? 'text-white' : 'text-gray-900'}`}>{value}</p>
      <p className={`text-sm font-medium ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>{label}</p>
      <p className={`text-xs mt-1 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>{sublabel}</p>
    </div>
  );
};

export default CFOOverview;
