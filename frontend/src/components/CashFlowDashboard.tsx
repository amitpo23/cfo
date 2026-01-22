import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
} from 'recharts';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
  Calendar,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
} from 'lucide-react';
import { api } from '../services/api';

const COLORS = ['#10B981', '#EF4444', '#3B82F6', '#F59E0B', '#8B5CF6', '#EC4899'];

interface MonthlyCashFlow {
  month: string;
  month_name: string;
  inflows: number;
  outflows: number;
  net_flow: number;
  cumulative: number;
}

interface DailyCashPosition {
  date: string;
  inflows: number;
  outflows: number;
  net_flow: number;
  closing_balance: number;
}

interface BurnRate {
  monthly_burn_rate: number;
  monthly_income: number;
  net_monthly_burn: number;
  current_balance: number;
  runway_months: number;
  analysis_period_months: number;
}

interface LiquidityRatios {
  current_ratio: number;
  quick_ratio: number;
  cash_ratio: number;
  working_capital: number;
  current_assets: number;
  current_liabilities: number;
}

const CashFlowDashboard: React.FC = () => {
  const [timeRange, setTimeRange] = useState(12);

  // Fetch monthly cash flow
  const { data: monthlyCashFlow, isLoading: loadingMonthly } = useQuery<MonthlyCashFlow[]>({
    queryKey: ['monthly-cashflow', timeRange],
    queryFn: async () => {
      const response = await api.get(`/cashflow/monthly?months=${timeRange}`);
      return response.data;
    },
  });

  // Fetch daily cash position
  const { data: dailyCashPosition, isLoading: loadingDaily } = useQuery<DailyCashPosition[]>({
    queryKey: ['daily-cashflow'],
    queryFn: async () => {
      const response = await api.get('/cashflow/daily?days=30');
      return response.data;
    },
  });

  // Fetch burn rate
  const { data: burnRate, isLoading: loadingBurn } = useQuery<BurnRate>({
    queryKey: ['burn-rate'],
    queryFn: async () => {
      const response = await api.get('/cashflow/burn-rate?months=3');
      return response.data;
    },
  });

  // Fetch liquidity ratios
  const { data: liquidityRatios, isLoading: loadingRatios } = useQuery<LiquidityRatios>({
    queryKey: ['liquidity-ratios'],
    queryFn: async () => {
      const response = await api.get('/cashflow/liquidity-ratios');
      return response.data;
    },
  });

  // Fetch cash flow by category
  const { data: categoryData, isLoading: loadingCategory } = useQuery({
    queryKey: ['cashflow-category'],
    queryFn: async () => {
      const today = new Date();
      const startDate = new Date(today.getFullYear(), today.getMonth() - 6, 1);
      const response = await api.get(
        `/cashflow/by-category?start_date=${startDate.toISOString().split('T')[0]}&end_date=${today.toISOString().split('T')[0]}`
      );
      return response.data;
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

  const formatPercent = (value: number) => {
    return `${value.toFixed(2)}%`;
  };

  // Calculate summary stats
  const totalInflows = monthlyCashFlow?.reduce((sum, m) => sum + m.inflows, 0) || 0;
  const totalOutflows = monthlyCashFlow?.reduce((sum, m) => sum + m.outflows, 0) || 0;
  const netCashFlow = totalInflows - totalOutflows;

  // Prepare category pie chart data
  const categoryPieData = categoryData
    ? Object.entries(categoryData).map(([key, value]: [string, any]) => ({
        name: key === 'operating' ? 'פעילות שוטפת' : key === 'investing' ? 'השקעות' : 'מימון',
        value: Math.abs(value.net),
        isPositive: value.net >= 0,
      }))
    : [];

  return (
    <div className="container mx-auto px-4 py-8" dir="rtl">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-800">תזרים מזומנים</h1>
          <p className="text-gray-600 mt-1">ניתוח ומעקב תזרים מזומנים</p>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value={6}>6 חודשים</option>
            <option value={12}>12 חודשים</option>
            <option value={24}>24 חודשים</option>
          </select>
          <button className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition">
            <RefreshCw size={18} />
            רענון
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className="p-3 bg-green-100 rounded-lg">
              <ArrowUpRight className="text-green-600" size={24} />
            </div>
            <span className="text-sm text-gray-500">סה"כ כניסות</span>
          </div>
          <p className="text-2xl font-bold text-gray-800">{formatCurrency(totalInflows)}</p>
          <p className="text-sm text-green-600 mt-2">+12% מהתקופה הקודמת</p>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className="p-3 bg-red-100 rounded-lg">
              <ArrowDownRight className="text-red-600" size={24} />
            </div>
            <span className="text-sm text-gray-500">סה"כ יציאות</span>
          </div>
          <p className="text-2xl font-bold text-gray-800">{formatCurrency(totalOutflows)}</p>
          <p className="text-sm text-red-600 mt-2">+5% מהתקופה הקודמת</p>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className={`p-3 ${netCashFlow >= 0 ? 'bg-green-100' : 'bg-red-100'} rounded-lg`}>
              <DollarSign className={netCashFlow >= 0 ? 'text-green-600' : 'text-red-600'} size={24} />
            </div>
            <span className="text-sm text-gray-500">תזרים נקי</span>
          </div>
          <p className={`text-2xl font-bold ${netCashFlow >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {formatCurrency(netCashFlow)}
          </p>
          <p className="text-sm text-gray-500 mt-2">{timeRange} חודשים אחרונים</p>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className={`p-3 ${(burnRate?.runway_months || 0) > 6 ? 'bg-green-100' : 'bg-yellow-100'} rounded-lg`}>
              <Calendar className={(burnRate?.runway_months || 0) > 6 ? 'text-green-600' : 'text-yellow-600'} size={24} />
            </div>
            <span className="text-sm text-gray-500">Runway</span>
          </div>
          <p className="text-2xl font-bold text-gray-800">
            {burnRate?.runway_months === Infinity ? '∞' : `${(burnRate?.runway_months || 0).toFixed(1)} חודשים`}
          </p>
          <p className="text-sm text-gray-500 mt-2">
            {burnRate?.net_monthly_burn && burnRate.net_monthly_burn > 0
              ? `שריפה: ${formatCurrency(burnRate.net_monthly_burn)}/חודש`
              : 'ללא שריפת מזומנים'}
          </p>
        </div>
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Monthly Cash Flow Chart */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">תזרים מזומנים חודשי</h3>
          {loadingMonthly ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
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
        </div>

        {/* Cumulative Cash Flow */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">תזרים מצטבר</h3>
          {loadingMonthly ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
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
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Daily Cash Position */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 lg:col-span-2">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">מצב מזומנים יומי (30 ימים אחרונים)</h3>
          {loadingDaily ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
          ) : (
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
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Category Breakdown */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">התפלגות לפי קטגוריה</h3>
          {loadingCategory ? (
            <div className="h-64 flex items-center justify-center">
              <RefreshCw className="animate-spin text-gray-400" size={32} />
            </div>
          ) : (
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
                  {categoryPieData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.isPositive ? COLORS[0] : COLORS[1]}
                    />
                  ))}
                </Pie>
                <Tooltip formatter={(value: number) => formatCurrency(value)} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Liquidity Ratios */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 mb-8">
        <h3 className="text-lg font-semibold text-gray-800 mb-6">יחסי נזילות</h3>
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
      </div>

      {/* Burn Rate Details */}
      {burnRate && (
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800 mb-6">ניתוח קצב שריפה</h3>
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
            </div>
          </div>

          {burnRate.net_monthly_burn > 0 && (
            <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg flex items-start gap-3">
              <AlertTriangle className="text-yellow-600 flex-shrink-0 mt-0.5" size={20} />
              <div>
                <p className="font-medium text-yellow-800">שים לב לקצב השריפה</p>
                <p className="text-sm text-yellow-700 mt-1">
                  בקצב הנוכחי, המזומנים יספיקו ל-{burnRate.runway_months.toFixed(1)} חודשים.
                  מומלץ לבחון דרכים להגדלת הכנסות או צמצום הוצאות.
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
        </div>
      )}
    </div>
  );
};

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
