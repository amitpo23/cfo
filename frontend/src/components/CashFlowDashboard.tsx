import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  LineChart,
  Line,
  Legend,
} from 'recharts';
import {
  ArrowUpRight,
  ArrowDownRight,
  DollarSign,
  Calendar,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  Wallet,
  Activity,
  BarChart3,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  Database,
} from 'lucide-react';
import api from '../services/api';
import { AgentPanel, FinanceCard, FinancePageShell, MetricCard } from './finance-ui';
import ExportButtons, { ExportSheet } from './ExportButtons';

const COLORS = ['#10B981', '#EF4444', '#3B82F6', '#F59E0B', '#8B5CF6', '#EC4899'];

// תיוג עברי למקורות הנתונים החיים — אותה מוסכמה כמו ForecastingDashboard
// (מסך התחזית, משימה 1): "נכון לתאריך" + תגיות מקור מעל התוכן.
const SOURCE_LABELS: Record<string, string> = {
  bank_transactions_actual: 'תזרים בנק בפועל',
  invoices_open_ar: 'חשבוניות פתוחות (לקוחות)',
  bills_open_ap: 'חשבונות ספק פתוחים',
};

interface MonthlyCashFlow {
  month: string;
  month_name: string;
  inflows: number;
  outflows: number;
  net_flow: number;
  cumulative: number;
}

interface LiveMonthlyResponse {
  as_of: string;
  data_sources: string[];
  months: MonthlyCashFlow[];
  message: string | null;
}

interface DailyCashPosition {
  date: string;
  inflows: number;
  outflows: number;
  net_flow: number;
  closing_balance: number | null;
}

interface LiveDailyResponse {
  as_of: string;
  data_sources: string[];
  days: DailyCashPosition[];
  balance_basis: 'account_balance' | 'unavailable' | 'no_bank_data';
  message: string | null;
}

interface BurnRate {
  as_of?: string;
  data_sources?: string[];
  monthly_burn_rate: number;
  monthly_income: number;
  net_monthly_burn: number;
  current_balance: number;
  current_balance_available?: boolean;
  runway_months: number;
  analysis_period_months: number;
  expected_receivables_30d?: number;
  expected_receivables_30d_count?: number;
  expected_payables_30d?: number;
  expected_payables_30d_count?: number;
  message?: string | null;
}

interface LiquidityRatios {
  current_ratio: number;
  quick_ratio: number;
  cash_ratio: number;
  working_capital: number;
  current_assets: number;
  current_liabilities: number;
}

interface CategoryBreakdownResponse {
  as_of: string;
  data_sources: string[];
  categories: Record<string, { inflows: number; outflows: number; net: number }>;
  coverage?: { categorized_count: number; total_count: number; categorized_share: number };
  message: string | null;
}

const CashFlowDashboard: React.FC = () => {
  const [timeRange, setTimeRange] = useState(12);

  // Fetch monthly cash flow — ספרים חיים (BankTransaction), honest-null.
  const { data: monthlyResp, isLoading: loadingMonthly } = useQuery<LiveMonthlyResponse>({
    queryKey: ['monthly-cashflow', timeRange],
    queryFn: () => api.get<LiveMonthlyResponse>(`/cashflow/monthly?months=${timeRange}`),
  });
  const monthlyCashFlow = monthlyResp?.months || [];

  // Fetch daily cash position
  const { data: dailyResp, isLoading: loadingDaily } = useQuery<LiveDailyResponse>({
    queryKey: ['daily-cashflow'],
    queryFn: () => api.get<LiveDailyResponse>('/cashflow/daily?days=30'),
  });
  const dailyCashPosition = dailyResp?.days || [];

  // Fetch burn rate — כולל תוספת צפי גבייה/תשלום מ-AR/AP פתוחים.
  const { data: burnRate } = useQuery<BurnRate>({
    queryKey: ['burn-rate'],
    queryFn: () => api.get<BurnRate>('/cashflow/burn-rate?months=3'),
  });

  // Fetch liquidity ratios
  const { data: liquidityRatios, isLoading: loadingRatios } = useQuery<LiquidityRatios>({
    queryKey: ['liquidity-ratios'],
    queryFn: () => api.get<LiquidityRatios>('/cashflow/liquidity-ratios'),
  });

  // Fetch cash flow by category
  const { data: categoryResp, isLoading: loadingCategory } = useQuery<CategoryBreakdownResponse>({
    queryKey: ['cashflow-category'],
    queryFn: () => {
      const today = new Date();
      const startDate = new Date(today.getFullYear(), today.getMonth() - 6, 1);
      return api.get<CategoryBreakdownResponse>(
        `/cashflow/by-category?start_date=${startDate.toISOString().split('T')[0]}&end_date=${today.toISOString().split('T')[0]}`
      );
    },
  });

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('he-IL', {
      style: 'currency',
      currency: 'ILS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  // live_cash_flow_service.burn_rate מחזיר runway_months=999.0 כ"סנטינל"
  // בשלושה מקרים שונים (ר' burn_rate() בקוד): (1) net_burn<=0 וגם יתרה
  // חיובית ממש — runway **אמיתי** אינסופי; (2) net_burn>0 אבל
  // current_balance<=0 — runway אפסי, לא אינסופי; (3)
  // current_balance_available=false — היתרה עצמה לא ידועה
  // (current_balance המספרי הוא 0.0 מלאכותי במקרה הזה, לא יתרה אמיתית).
  // `=== Infinity` המת לא תפס אף אחד מהם (ה-API אף פעם לא שולח Infinity
  // אמיתי — JSON לא תומך בו), אבל מיפוי גורף של runway_months>=999 ל-'∞'
  // באותה מידה שקרי: הוא הופך "אין יתרה חיה + שורפים כסף" ל"runway
  // אינסופי" — honest-null אסור להתחלף בבדיה אופטימית. '∞' מוצג רק
  // כשהתנאי לאינסוף-אמיתי מתקיים בפועל; אחרת — '—' (לא-ידוע-בכנות).
  const formatRunway = (br: BurnRate | undefined | null) => {
    if (!br || br.runway_months == null) return '—';
    const genuinelyInfinite =
      br.current_balance_available === true &&
      br.current_balance > 0 &&
      br.net_monthly_burn <= 0;
    if (br.runway_months >= 999) {
      return genuinelyInfinite ? '∞' : '—';
    }
    return `${br.runway_months.toFixed(1)} חודשים`;
  };

  // אותה סיווג בדיוק כמו formatRunway, כדי שהצבע (tone) לא יסתור את
  // הערך המוצג: לפני התיקון tone חושב ישירות מ-runway_months הגולמי
  // (כולל סנטינל 999), אז מצב לא-ידוע/שריפה-בלי-יתרה — שהערך שלו כבר
  // תוקן ל-'—' — עדיין צבע ירוק "בריא", בדיוק ההפך מהמשמעות.
  const runwayTone = (br: BurnRate | undefined | null): 'emerald' | 'amber' | 'slate' => {
    if (!br || br.runway_months == null) return 'slate';
    const genuinelyInfinite =
      br.current_balance_available === true &&
      br.current_balance > 0 &&
      br.net_monthly_burn <= 0;
    if (br.runway_months >= 999) {
      return genuinelyInfinite ? 'emerald' : 'slate';
    }
    return br.runway_months > 6 ? 'emerald' : 'amber';
  };

  // Calculate summary stats
  const totalInflows = monthlyCashFlow.reduce((sum, m) => sum + m.inflows, 0);
  const totalOutflows = monthlyCashFlow.reduce((sum, m) => sum + m.outflows, 0);
  const netCashFlow = totalInflows - totalOutflows;

  // Prepare category pie chart data — שמות הקטגוריה מגיעים ישירות מהמקור
  // החי (Category.name / "לא מסווג"), לא ממיפוי operating/investing/financing
  // קבוע-מראש שאין לו עוד בסיס נתונים.
  const categoryEntries = Object.entries(categoryResp?.categories || {});
  const categoryPieData = categoryEntries.map(([key, value]) => ({
    name: key,
    value: Math.abs(value.net),
    isPositive: value.net >= 0,
  }));

  const cashFlowExportSheets: ExportSheet[] = [
    {
      name: 'תזרים חודשי',
      columns: [
        { key: 'month_name', label: 'חודש' },
        { key: 'inflows', label: 'כניסות' },
        { key: 'outflows', label: 'יציאות' },
        { key: 'net_flow', label: 'תזרים נקי' },
        { key: 'cumulative', label: 'מצטבר' },
      ],
      rows: monthlyCashFlow.map((m) => ({
        month_name: m.month_name,
        inflows: m.inflows,
        outflows: m.outflows,
        net_flow: m.net_flow,
        cumulative: m.cumulative,
      })),
      summary: [
        { label: 'כניסות', value: formatCurrency(totalInflows) },
        { label: 'יציאות', value: formatCurrency(totalOutflows) },
        { label: 'תזרים נקי', value: formatCurrency(netCashFlow) },
      ],
    },
    {
      name: 'מצב מזומנים יומי',
      columns: [
        { key: 'date', label: 'תאריך' },
        { key: 'inflows', label: 'כניסות' },
        { key: 'outflows', label: 'יציאות' },
        { key: 'net_flow', label: 'תזרים נקי' },
        { key: 'closing_balance', label: 'יתרת סגירה' },
      ],
      rows: dailyCashPosition.map((d) => ({
        date: d.date,
        inflows: d.inflows,
        outflows: d.outflows,
        net_flow: d.net_flow,
        closing_balance: d.closing_balance ?? '',
      })),
    },
  ];

  // מקורות הנתונים המוצגים בתגית העליונה — איחוד המקורות מכל הרכיבים
  // שכבר נטענו, כדי לתת תמונה כנה אחת של "על מה זה מבוסס".
  const asOf = monthlyResp?.as_of || dailyResp?.as_of || burnRate?.as_of;
  const dataSources = Array.from(
    new Set([...(monthlyResp?.data_sources || []), ...(dailyResp?.data_sources || [])])
  );

  return (
    <FinancePageShell
      eyebrow="Cash Flow"
      title="ניהול תזרים מזומנים"
      description="מבט עבודה על הכסף שנכנס, הכסף שיוצא, runway, יחסי נזילות ותחזית יומית. המטרה היא לדעת מראש איפה יהיה לחץ ומה עושים."
      icon={Wallet}
      metrics={[
        { label: 'כניסות', value: formatCurrency(totalInflows), tone: 'emerald' },
        { label: 'יציאות', value: formatCurrency(totalOutflows), tone: 'rose' },
        { label: 'תזרים נקי', value: formatCurrency(netCashFlow), tone: netCashFlow >= 0 ? 'emerald' : 'rose' },
        { label: 'Runway', value: formatRunway(burnRate), tone: runwayTone(burnRate) },
      ]}
      actions={
        <>
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={6}>6 חודשים</option>
            <option value={12}>12 חודשים</option>
            <option value={24}>24 חודשים</option>
          </select>
          <button className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition">
            <RefreshCw size={18} />
            רענון
          </button>
          <ExportButtons title="תזרים מזומנים" meta={`${timeRange} חודשים אחרונים`} sheets={cashFlowExportSheets} />
        </>
      }
    >

      {/* נכון לתאריך + מקורות נתונים חיים — אותה מוסכמה כמו מסך התחזית */}
      {asOf && (
        <div className="flex flex-wrap items-center gap-3 mb-6 text-sm">
          <span className="flex items-center gap-1 text-gray-600">
            <Calendar size={16} />
            נכון לתאריך {asOf}
          </span>
          {dataSources.map((src) => (
            <span
              key={src}
              className="flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full"
            >
              <Database size={14} />
              {SOURCE_LABELS[src] || src}
            </span>
          ))}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <MetricCard icon={ArrowUpRight} label="כניסות" value={formatCurrency(totalInflows)} detail={`${timeRange} חודשים אחרונים`} tone="emerald" />
        <MetricCard icon={ArrowDownRight} label="יציאות" value={formatCurrency(totalOutflows)} detail={`${timeRange} חודשים אחרונים`} tone="rose" />
        <MetricCard icon={DollarSign} label="תזרים נקי" value={formatCurrency(netCashFlow)} detail={`${timeRange} חודשים אחרונים`} tone={netCashFlow >= 0 ? 'emerald' : 'rose'} />
        <MetricCard
          icon={Calendar}
          label="Runway"
          value={formatRunway(burnRate)}
          detail={burnRate?.net_monthly_burn && burnRate.net_monthly_burn > 0 ? `שריפה: ${formatCurrency(burnRate.net_monthly_burn)}/חודש` : 'ללא שריפת מזומנים'}
          tone={runwayTone(burnRate)}
        />
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Monthly Cash Flow Chart */}
        <FinanceCard title="תזרים מזומנים חודשי" subtitle="כניסות ויציאות לפי חודש, לזיהוי עונות ותקופות לחץ" icon={BarChart3}>
          {loadingMonthly ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
          ) : monthlyCashFlow.length === 0 ? (
            <EmptyState message={monthlyResp?.message} />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={monthlyCashFlow}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value: number) => formatCurrency(value)}
                  labelFormatter={(label) => `חודש: ${label}`}
                />
                <Legend />
                <Bar dataKey="inflows" name="כניסות" fill="#10B981" radius={[4, 4, 0, 0]} />
                <Bar dataKey="outflows" name="יציאות" fill="#EF4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </FinanceCard>

        {/* Cumulative Cash Flow */}
        <FinanceCard title="תזרים מצטבר" subtitle="האם העסק צובר או שורף מזומן לאורך התקופה" icon={Activity}>
          {loadingMonthly ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
          ) : monthlyCashFlow.length === 0 ? (
            <EmptyState message={monthlyResp?.message} />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={monthlyCashFlow}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value: number) => formatCurrency(value)} />
                <Area
                  type="monotone"
                  dataKey="cumulative"
                  name="מצטבר"
                  stroke="#3B82F6"
                  fill="#3B82F6"
                  fillOpacity={0.3}
                />
                <Area
                  type="monotone"
                  dataKey="net_flow"
                  name="תזרים נקי"
                  stroke="#10B981"
                  fill="#10B981"
                  fillOpacity={0.3}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </FinanceCard>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Daily Cash Position */}
        <FinanceCard title="מצב מזומנים יומי" subtitle="30 ימים אחרונים, כדי לראות ימים בעייתיים לפני שהם קורים" icon={LineChartIcon} className="lg:col-span-2">
          {loadingDaily ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
          ) : dailyCashPosition.length === 0 ? (
            <EmptyState message={dailyResp?.message} />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={dailyCashPosition}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(value: number) => formatCurrency(value)} />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="closing_balance"
                    name="יתרה"
                    stroke="#3B82F6"
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
              {dailyResp?.balance_basis === 'unavailable' && (
                <p className="text-xs text-amber-600 mt-2">
                  אין חשבון בנק/נכס עם יתרה חיה בארגון — יתרת הסגירה אינה זמינה (מוצגות רק כניסות/יציאות בפועל).
                </p>
              )}
            </>
          )}
        </FinanceCard>

        {/* Category Breakdown */}
        <FinanceCard title="התפלגות לפי קטגוריה" subtitle="איפה נוצר או נשרף המזומן" icon={PieChartIcon}>
          {loadingCategory ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
          ) : categoryPieData.length === 0 ? (
            <EmptyState message={categoryResp?.message} />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={categoryPieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                    label={({ name }) => name}
                  >
                    {categoryPieData.map((_entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={_entry.isPositive ? COLORS[0] : COLORS[1]}
                      />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => formatCurrency(value)} />
                </PieChart>
              </ResponsiveContainer>
              {/* כיסוי חלקי (רוב התנועות "לא מסווג") — הנתון אמיתי, לא
                  מוסתר, אבל ההודעה חייבת להיראות לצד התרשים ולא רק ב-API. */}
              {categoryResp?.message && (
                <p className="text-xs text-amber-600 mt-2">{categoryResp.message}</p>
              )}
            </>
          )}
        </FinanceCard>
      </div>

      {/* Liquidity Ratios */}
      <FinanceCard title="יחסי נזילות" subtitle="חיווי מהיר למצב העסק מול התחייבויות קרובות" icon={CheckCircle} className="mb-8">
        {loadingRatios ? (
          <div className="h-32 flex items-center justify-center">
            <RefreshCw className="animate-spin text-gray-400" size={32} />
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <RatioCard
              title="יחס שוטף"
              value={liquidityRatios?.current_ratio || 0}
              isGood={(liquidityRatios?.current_ratio || 0) >= 1.5}
              format="ratio"
            />
            <RatioCard
              title="יחס מהיר"
              value={liquidityRatios?.quick_ratio || 0}
              isGood={(liquidityRatios?.quick_ratio || 0) >= 1}
              format="ratio"
            />
            <RatioCard
              title="יחס מזומנים"
              value={liquidityRatios?.cash_ratio || 0}
              isGood={(liquidityRatios?.cash_ratio || 0) >= 0.5}
              format="ratio"
            />
            <RatioCard
              title="הון חוזר"
              value={liquidityRatios?.working_capital || 0}
              isGood={(liquidityRatios?.working_capital || 0) > 0}
              format="currency"
            />
            <RatioCard
              title="נכסים שוטפים"
              value={liquidityRatios?.current_assets || 0}
              isGood={true}
              format="currency"
            />
            <RatioCard
              title="התחייבויות שוטפות"
              value={liquidityRatios?.current_liabilities || 0}
              isGood={true}
              format="currency"
            />
          </div>
        )}
      </FinanceCard>

      {/* Burn Rate Details */}
      {burnRate && (
        <FinanceCard title="ניתוח קצב שריפה" subtitle="הסוכן בודק כמה זמן העסק יכול להמשיך בקצב הנוכחי" icon={AlertTriangle}>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-sm text-gray-600 mb-2">הוצאות חודשיות ממוצעות</p>
              <p className="text-xl font-bold text-red-600">{formatCurrency(burnRate.monthly_burn_rate)}</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-sm text-gray-600 mb-2">הכנסות חודשיות ממוצעות</p>
              <p className="text-xl font-bold text-green-600">{formatCurrency(burnRate.monthly_income)}</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <p className="text-sm text-gray-600 mb-2">יתרה נוכחית</p>
              <p className="text-xl font-bold text-blue-600">{formatCurrency(burnRate.current_balance)}</p>
              {burnRate.current_balance_available === false && (
                <p className="text-xs text-amber-600 mt-1">אין חשבון בנק/נכס עם יתרה חיה</p>
              )}
            </div>
          </div>

          {/* תוספת AR/AP: צפי גבייה/תשלום 30 יום — לא מוזרם לתוך הריצה בפועל למעלה */}
          {((burnRate.expected_receivables_30d_count || 0) > 0 || (burnRate.expected_payables_30d_count || 0) > 0) && (
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm">
                <span className="text-green-700 font-medium">צפי גבייה (30 יום): </span>
                <span className="text-green-800">
                  {formatCurrency(burnRate.expected_receivables_30d || 0)} ({burnRate.expected_receivables_30d_count || 0} חשבוניות פתוחות)
                </span>
              </div>
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm">
                <span className="text-red-700 font-medium">צפי תשלום (30 יום): </span>
                <span className="text-red-800">
                  {formatCurrency(burnRate.expected_payables_30d || 0)} ({burnRate.expected_payables_30d_count || 0} חשבונות ספק פתוחים)
                </span>
              </div>
            </div>
          )}

          {burnRate.net_monthly_burn > 0 && (
            <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg flex items-start gap-3">
              <AlertTriangle className="text-yellow-600 flex-shrink-0 mt-0.5" size={20} />
              <div>
                <p className="font-medium text-yellow-800">שים לב לקצב השריפה</p>
                <p className="text-sm text-yellow-700 mt-1">
                  {burnRate.current_balance_available && burnRate.current_balance > 0
                    ? `בקצב הנוכחי, המזומנים יספיקו ל-${formatRunway(burnRate)}.`
                    : 'אין יתרת מזומנים חיובית ידועה — לא ניתן לחשב כמה זמן הכסף יספיק.'}
                  {' '}מומלץ לבחון דרכים להגדלת הכנסות או צמצום הוצאות.
                </p>
              </div>
            </div>
          )}

          {burnRate.net_monthly_burn <= 0 && (
            <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
              <CheckCircle className="text-green-600 flex-shrink-0 mt-0.5" size={20} />
              <div>
                <p className="font-medium text-green-800">מצב תזרים חיובי</p>
                <p className="text-sm text-green-700 mt-1">
                  ההכנסות עולות על ההוצאות. המשיכו כך!
                </p>
              </div>
            </div>
          )}
        </FinanceCard>
      )}

      <AgentPanel
        insights={[
          {
            title: 'פעולה לפני מחסור במזומן',
            text: netCashFlow < 0 ? 'התזרים הנקי שלילי בתקופה שנבחרה. מומלץ לתעדף גבייה ולבדוק דחיית תשלומים לא קריטיים.' : 'התזרים חיובי. מומלץ לנעול תחזית ל-30 יום ולבדוק אם יש כסף פנוי להקדמת תשלומים בהנחה.',
          },
          {
            title: 'החלפת עבודה ידנית',
            text: 'המסך מרכז כניסות, יציאות, runway ויחסי נזילות כך שלא צריך לבנות דוח תזרים ידני באקסל בכל שבוע.',
          },
        ]}
      />
    </FinancePageShell>
  );
};

const EmptyState: React.FC<{ message?: string | null }> = ({ message }) => (
  <div className="h-64 flex flex-col items-center justify-center text-gray-400 gap-2 text-center px-4">
    <AlertTriangle size={28} />
    <p className="text-sm text-gray-500">{message || 'אין נתונים חיים להצגה'}</p>
  </div>
);

interface RatioCardProps {
  title: string;
  value: number;
  isGood: boolean;
  format: 'ratio' | 'currency' | 'percent';
}

const RatioCard: React.FC<RatioCardProps> = ({ title, value, isGood, format }) => {
  const formatValue = () => {
    if (format === 'currency') {
      return new Intl.NumberFormat('he-IL', {
        style: 'currency',
        currency: 'ILS',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(value);
    }
    if (format === 'percent') {
      return `${value.toFixed(1)}%`;
    }
    return value.toFixed(2);
  };

  return (
    <div className={`p-4 rounded-lg border ${isGood ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
      <p className="text-xs text-gray-600 mb-1">{title}</p>
      <p className={`text-lg font-bold ${isGood ? 'text-green-700' : 'text-red-700'}`}>
        {formatValue()}
      </p>
      <div className="mt-1">
        {isGood ? (
          <CheckCircle size={14} className="text-green-500" />
        ) : (
          <AlertTriangle size={14} className="text-red-500" />
        )}
      </div>
    </div>
  );
};

export default CashFlowDashboard;
