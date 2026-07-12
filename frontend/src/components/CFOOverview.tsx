import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts';
import {
  Wallet, TrendingUp, AlertTriangle,
  FileCheck, Receipt, ArrowRight, RefreshCw, Clock,
  DollarSign, Activity, Shield, Gauge, Sparkles, Landmark, CheckCircle2,
  FileWarning,
} from 'lucide-react';
import apiService from '../services/api';
import { AgentPanel, FinanceCard, FinancePageShell, MetricCard, NoDataYet, formatILS } from './finance-ui';

interface CFOOverviewProps {
  darkMode: boolean;
}

/**
 * Honesty contract (docs/REZEF_DATA_INTEGRITY_PLAN.md, section ד): every
 * field is number|null (or an object|null). `null`/`undefined` means "no
 * data yet" and must NEVER be rendered as 0. All new fields are optional so
 * this screen keeps working while the backend half of the plan ships.
 */
interface DashboardOverview {
  // Cash (Open Finance)
  cash_balance?: number | null;
  cash_as_of?: string | null;
  savings_balance?: number | null;
  loans_total?: number | null;
  card_outstanding?: number | null;

  // P&L (books) + bank-actual parallel track
  month_revenue?: number | null;
  month_expenses?: number | null;
  month_net_profit?: number | null;
  pnl_month?: string | null;
  pnl_is_current_month?: boolean | null;
  bank_month_inflow?: number | null;
  bank_month_outflow?: number | null;
  bank_month_net?: number | null;

  runway_months?: number | null;

  ar_total?: number | null;
  ar_overdue?: number | null;

  ap_total?: number | null;
  ap_due_7_days?: number | null;
  ap_due_30_days?: number | null;

  undocumented_expenses?: { count: number; total: number; potential_vat: number } | null;
  data_quality?: { status: string; issues_count: number; last_check_at: string | null } | null;

  alerts?: Array<{ id: number; title: string; message: string; severity: string }>;
  // Legacy shape: string|null. New contract shape: { sumit, open_finance }.
  // Both are handled at render time so this screen survives the backend cutover.
  last_sync?: string | { sumit: string | null; open_finance: string | null } | null;
  cash_by_account?: Array<{ id: number; name: string; balance: number }>;
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

const HEBREW_MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];

function formatMonthLabel(monthStr?: string | null): string | null {
  if (!monthStr) return null;
  const [y, m] = monthStr.split('-');
  const idx = Number(m) - 1;
  if (!y || Number.isNaN(idx) || idx < 0 || idx > 11) return monthStr;
  return `${HEBREW_MONTHS[idx]} ${y}`;
}

function formatShortDate(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit' });
}

function formatDateTime(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString('he-IL');
}

function formatTime(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
}

function isSyncObject(v: unknown): v is { sumit: string | null; open_finance: string | null } {
  return !!v && typeof v === 'object' && ('sumit' in (v as object) || 'open_finance' in (v as object));
}

const CFOOverview: React.FC<CFOOverviewProps> = ({ darkMode }) => {
  const navigate = useNavigate();

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

  // Default fallback keeps every field null (never 0) — honesty contract.
  const ov: DashboardOverview = overview || {
    cash_balance: null,
    cash_as_of: null,
    savings_balance: null,
    loans_total: null,
    card_outstanding: null,
    month_revenue: null,
    month_expenses: null,
    month_net_profit: null,
    pnl_month: null,
    pnl_is_current_month: null,
    bank_month_inflow: null,
    bank_month_outflow: null,
    bank_month_net: null,
    runway_months: null,
    ar_total: null,
    ar_overdue: null,
    ap_total: null,
    ap_due_7_days: null,
    ap_due_30_days: null,
    undocumented_expenses: null,
    data_quality: null,
    alerts: [],
    last_sync: null,
    cash_by_account: [],
  };

  const cashBalance = ov.cash_balance ?? null;
  const cashAsOf = ov.cash_as_of ?? null;
  const savingsBalance = ov.savings_balance ?? null;
  const loansTotal = ov.loans_total ?? null;
  const cardOutstanding = ov.card_outstanding ?? null;

  const monthRevenue = ov.month_revenue ?? null;
  const monthNetProfit = ov.month_net_profit ?? null;
  const pnlMonth = ov.pnl_month ?? null;
  const pnlIsCurrentMonth = ov.pnl_is_current_month ?? null;
  const bankInflow = ov.bank_month_inflow ?? null;
  const bankOutflow = ov.bank_month_outflow ?? null;
  const bankNet = ov.bank_month_net ?? null;

  const runwayMonths = ov.runway_months ?? null;

  const arTotal = ov.ar_total ?? null;
  const arOverdue = ov.ar_overdue ?? null;

  const apTotalRaw = ov.ap_total ?? null;
  const apTotal = apTotalRaw == null ? null : Math.max(0, apTotalRaw);
  const apDue7 = ov.ap_due_7_days ?? null;

  const undocumentedExpenses = ov.undocumented_expenses ?? null;
  const dataQuality = ov.data_quality ?? null;

  const alerts = ov.alerts || [];
  const lastSyncRaw = ov.last_sync ?? null;
  const cashByAccount = ov.cash_by_account || [];

  const sumitSyncIso = isSyncObject(lastSyncRaw) ? lastSyncRaw.sumit ?? null : null;
  const ofSyncIso = isSyncObject(lastSyncRaw) ? lastSyncRaw.open_finance ?? null : null;
  const legacySyncIso = typeof lastSyncRaw === 'string' ? lastSyncRaw : null;
  const hasAnySync = Boolean(sumitSyncIso || ofSyncIso || legacySyncIso);

  const fmt = (n: number) =>
    new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(n);
  const fmtOrText = (n: number | null | undefined) => (n === null || n === undefined ? 'אין נתונים עדיין' : fmt(n));
  const Amount = (n: number | null | undefined): React.ReactNode =>
    n === null || n === undefined ? <NoDataYet darkMode={darkMode} /> : fmt(n);

  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

  const pnlMonthLabel = formatMonthLabel(pnlMonth);
  const cashFootnote = cashAsOf
    ? `מקור: בנק · נכון ל-${formatShortDate(cashAsOf)}`
    : (cashBalance != null ? 'מקור: בנק' : undefined);
  const pnlFootnote = pnlMonthLabel ? `מקור: ספרים · ${pnlMonthLabel}` : (monthRevenue != null ? 'מקור: ספרים' : undefined);
  const arApFootnote = sumitSyncIso
    ? `מקור: ספרים (SUMIT) · עודכן ${formatTime(sumitSyncIso)}`
    : 'מקור: ספרים (SUMIT)';

  const hasBankActuals = bankInflow != null || bankOutflow != null || bankNet != null;
  const bankVsBooksGap = bankNet != null && monthNetProfit != null ? bankNet - monthNetProfit : null;

  return (
    <FinancePageShell
      darkMode={darkMode}
      eyebrow="Command Center"
      title="מרכז שליטה פיננסי"
      description="תמונה יומית של הכסף: יתרות, גבייה, ספקים, רווחיות, תזרים וסיכונים. המטרה היא להחליף עבודת מעקב ידנית בפעולות מוכנות לאישור."
      icon={Gauge}
      metrics={[
        { label: 'יתרת מזומן', value: fmtOrText(cashBalance), tone: cashBalance == null ? 'slate' : 'blue' },
        { label: 'רווח נקי חודש', value: fmtOrText(monthNetProfit), tone: monthNetProfit == null ? 'slate' : (monthNetProfit >= 0 ? 'emerald' : 'rose') },
        { label: 'חובות באיחור', value: fmtOrText(arOverdue), tone: arOverdue == null ? 'slate' : (arOverdue > 0 ? 'amber' : 'emerald') },
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
            {hasAnySync ? (
              isSyncObject(lastSyncRaw) ? (
                <span>
                  סונכרן לאחרונה: SUMIT {sumitSyncIso ? formatTime(sumitSyncIso) : '—'} · בנק {ofSyncIso ? formatTime(ofSyncIso) : '—'}
                </span>
              ) : (
                <span>עדכון אחרון: {formatDateTime(legacySyncIso)}</span>
              )
            ) : (
              <span>עדיין אין נתוני סנכרון. הרץ סנכרון כדי לקבל תמונה מלאה.</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {dataQuality?.status === 'issues' && (
              <Link
                to="/sync"
                title={dataQuality.last_check_at ? `בדיקה אחרונה: ${formatDateTime(dataQuality.last_check_at)}` : undefined}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${darkMode ? 'bg-amber-500/15 text-amber-200' : 'bg-amber-50 text-amber-700'}`}
              >
                <AlertTriangle size={12} />
                בדיקות נתונים: {dataQuality.issues_count} ממצאים
              </Link>
            )}
            {dataQuality?.status === 'ok' && (
              <span
                title={dataQuality.last_check_at ? `בדיקה אחרונה: ${formatDateTime(dataQuality.last_check_at)}` : undefined}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${darkMode ? 'bg-emerald-500/15 text-emerald-200' : 'bg-emerald-50 text-emerald-700'}`}
              >
                <CheckCircle2 size={12} />
                תקין
              </span>
            )}
            <div className="text-sm font-medium">המערכת מזהה פערים ומייצרת משימות גבייה, תשלום והתאמה.</div>
          </div>
        </div>
      </div>

      {/* Top KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-6">
        <MetricCard
          darkMode={darkMode}
          icon={Wallet}
          label="יתרה זמינה (עו״ש)"
          value={Amount(cashBalance)}
          detail={
            <div className="space-y-1">
              <div>{runwayMonths != null ? `${runwayMonths} חודשי runway` : 'אין נתונים עדיין ל-runway'}</div>
              {savingsBalance != null && <div>פיקדונות: {fmt(savingsBalance)}</div>}
              {loansTotal != null && (
                <div className={darkMode ? 'text-rose-300' : 'text-rose-600'}>הלוואות/מסגרות: {fmt(loansTotal)}</div>
              )}
              {cardOutstanding != null && <div>חוב כרטיס פתוח: {fmt(cardOutstanding)}</div>}
            </div>
          }
          footnote={cashFootnote}
          tone="blue"
        />
        <MetricCard
          darkMode={darkMode}
          icon={TrendingUp}
          label="הכנסות החודש"
          value={Amount(monthRevenue)}
          detail={
            <div className="space-y-1">
              <div>רווח נקי: {Amount(monthNetProfit)}</div>
              {pnlIsCurrentMonth === false && pnlMonthLabel && (
                <div className={darkMode ? 'text-amber-300' : 'text-amber-700'}>
                  מציג את {pnlMonthLabel} — החודש הסגור האחרון עם נתונים
                </div>
              )}
              {hasBankActuals && (
                <div className={darkMode ? 'text-slate-400' : 'text-slate-500'}>
                  מהבנק בפועל: נכנס {fmtOrText(bankInflow)} · יצא {fmtOrText(bankOutflow)} · נטו {fmtOrText(bankNet)}
                  {bankVsBooksGap != null && ` (פער: ${fmt(bankVsBooksGap)})`}
                </div>
              )}
            </div>
          }
          footnote={pnlFootnote}
          tone="emerald"
        />
        <MetricCard
          darkMode={darkMode}
          icon={FileCheck}
          label="לקוחות חייבים"
          value={Amount(arTotal)}
          detail={arOverdue != null ? (arOverdue > 0 ? `${fmt(arOverdue)} באיחור` : 'אין איחור מהותי') : 'אין נתונים עדיין'}
          footnote={arApFootnote}
          tone={arOverdue != null && arOverdue > 0 ? 'rose' : 'emerald'}
        />
        <MetricCard
          darkMode={darkMode}
          icon={Receipt}
          label="ספקים לתשלום"
          value={Amount(apTotal)}
          detail={apDue7 != null ? `מזה לתשלום 7 ימים: ${fmt(apDue7)}` : 'אין נתונים עדיין'}
          footnote={arApFootnote}
          tone="amber"
        />
        <MetricCard
          darkMode={darkMode}
          icon={FileWarning}
          label="הוצאות ללא חשבונית"
          value={undocumentedExpenses ? fmt(undocumentedExpenses.total) : 'אין נתונים עדיין'}
          detail={
            undocumentedExpenses
              ? `${undocumentedExpenses.count} מסמכים · מע״מ תשומות שלא נקלט: ${fmt(undocumentedExpenses.potential_vat)}`
              : 'לחצו כדי לבדוק ספקים חסרי חשבונית'
          }
          footnote="מקור: התאמת בנק×ספרים · לחצו למסך המלא"
          tone={undocumentedExpenses && undocumentedExpenses.count > 0 ? 'rose' : 'slate'}
          onClick={() => navigate('/suppliers-missing-invoices')}
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
                <span>{cashBalance != null ? fmt(cashBalance) : <NoDataYet darkMode={darkMode} />}</span>
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
              { to: '/suppliers-missing-invoices', label: 'ספקים חסרי חשבונית', icon: <FileWarning size={18} />, color: 'text-rose-500' },
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
            text: (arOverdue ?? arTotal) != null
              ? `${formatILS((arOverdue ?? arTotal) as number)} עומדים לגבייה. הסוכן ממליץ לתעדף לקוחות באיחור לפני תשלומי השבוע.`
              : 'אין עדיין נתוני גבייה — לאחר סנכרון SUMIT תופיע כאן תעדוף לקוחות באיחור.',
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
