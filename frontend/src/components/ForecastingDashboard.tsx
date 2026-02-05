import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  AreaChart,
  Area,
  ComposedChart,
  Bar,
} from 'recharts';
import {
  TrendingUp,
  TrendingDown,
  Brain,
  Target,
  AlertCircle,
  RefreshCw,
  Zap,
  BarChart3,
  Minus,
} from 'lucide-react';
import api from '../services/api';

interface ForecastResult {
  date: string;
  predicted_value: number;
  lower_bound: number;
  upper_bound: number;
  confidence: number;
}

interface CashFlowForecast {
  date: string;
  projected_inflows: number;
  projected_outflows: number;
  projected_net_flow: number;
  projected_balance: number;
  confidence: number;
}

interface ScenarioData {
  expected: CashFlowForecast[];
  optimistic: CashFlowForecast[];
  pessimistic: CashFlowForecast[];
}

interface TrendAnalysis {
  revenue: {
    trend: string;
    growth_rate: number;
    average: number;
    volatility: number;
  };
  expenses: {
    trend: string;
    growth_rate: number;
    average: number;
    volatility: number;
  };
  seasonality: {
    detected: boolean;
    peak_quarter?: number;
    low_quarter?: number;
  };
  profit_margin_trend: number[];
}

interface MLForecast {
  ensemble: Array<{
    date: string;
    predicted_value: number;
    lower_bound: number;
    upper_bound: number;
    model_name: string;
    confidence: number;
  }>;
  lstm: Array<any>;
  prophet: Array<any>;
  xgboost: Array<any>;
  weights: {
    lstm: number;
    prophet: number;
    xgboost: number;
  };
}

const ForecastingDashboard: React.FC = () => {
  const [forecastPeriods, setForecastPeriods] = useState(12);
  const [forecastMethod, setForecastMethod] = useState('exponential_smoothing');
  const [showScenarios, setShowScenarios] = useState(false);
  const [selectedModel, setSelectedModel] = useState<'ensemble' | 'lstm' | 'prophet' | 'xgboost'>('ensemble');

  // Fetch revenue forecast
  const { data: revenueForecast, isLoading: loadingRevenue } = useQuery<ForecastResult[]>({
    queryKey: ['revenue-forecast', forecastPeriods, forecastMethod],
    queryFn: async () => {
      const response = await api.get<{ data: ForecastResult[] }>(
        `/cashflow/forecast/revenue?periods=${forecastPeriods}&method=${forecastMethod}`
      );
      return response.data as ForecastResult[];
    },
  });

  // Fetch expense forecast
  const { data: expenseForecast, isLoading: loadingExpense } = useQuery<ForecastResult[]>({
    queryKey: ['expense-forecast', forecastPeriods, forecastMethod],
    queryFn: async () => {
      const response = await api.get<{ data: ForecastResult[] }>(
        `/cashflow/forecast/expenses?periods=${forecastPeriods}&method=${forecastMethod}`
      );
      return response.data as ForecastResult[];
    },
  });

  // Fetch cash flow forecast
  const { data: cashFlowForecast, isLoading: loadingCashFlow } = useQuery<CashFlowForecast[]>({
    queryKey: ['cashflow-forecast', forecastPeriods],
    queryFn: async () => {
      const response = await api.get<{ data: CashFlowForecast[] }>(
        `/cashflow/forecast/cash-flow?periods=${forecastPeriods}&current_balance=0`
      );
      return response.data as CashFlowForecast[];
    },
  });

  // Fetch scenario analysis
  const { data: scenarios, isLoading: loadingScenarios } = useQuery<ScenarioData>({
    queryKey: ['scenarios', forecastPeriods],
    queryFn: async () => {
      const response = await api.get<{ data: ScenarioData }>(
        `/cashflow/forecast/scenarios?periods=${forecastPeriods}&current_balance=0`
      );
      return response.data as ScenarioData;
    },
    enabled: showScenarios,
  });

  // Fetch trend analysis
  const { data: trends } = useQuery<TrendAnalysis>({
    queryKey: ['trends'],
    queryFn: async () => {
      const response = await api.get<{ data: TrendAnalysis }>('/cashflow/forecast/trends?months=12');
      return response.data as TrendAnalysis;
    },
  });

  // Fetch ML ensemble forecast
  const { data: mlForecast, isLoading: loadingML } = useQuery<MLForecast>({
    queryKey: ['ml-forecast', forecastPeriods],
    queryFn: async () => {
      const response = await api.get<{ data: MLForecast }>(`/cashflow/forecast/ml/ensemble?periods=${forecastPeriods}`);
      return response.data as MLForecast;
    },
  });

  // Fetch forecast accuracy
  const { data: accuracy } = useQuery<{ mape: number }>({
    queryKey: ['forecast-accuracy'],
    queryFn: async () => {
      const response = await api.get<{ data: { mape: number } }>('/cashflow/forecast/accuracy?test_months=3');
      return response.data as { mape: number };
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

  // Prepare combined forecast data for chart
  const combinedForecastData = revenueForecast?.map((rev, idx) => ({
    date: rev.date,
    revenue: rev.predicted_value,
    revenue_lower: rev.lower_bound,
    revenue_upper: rev.upper_bound,
    expenses: expenseForecast?.[idx]?.predicted_value || 0,
    expenses_lower: expenseForecast?.[idx]?.lower_bound || 0,
    expenses_upper: expenseForecast?.[idx]?.upper_bound || 0,
    net: rev.predicted_value - (expenseForecast?.[idx]?.predicted_value || 0),
  }));

  // Prepare scenario data for chart
  const scenarioChartData = scenarios?.expected.map((exp, _idx) => ({
    date: exp.date,
    expected: exp.projected_balance,
    optimistic: scenarios.optimistic[_idx]?.projected_balance || 0,
    pessimistic: scenarios.pessimistic[_idx]?.projected_balance || 0,
  }));

  // Prepare ML forecast data
  const mlChartData = mlForecast?.ensemble.map((item, _idx) => ({
    date: item.date,
    ensemble: item.predicted_value,
    ensemble_lower: item.lower_bound,
    ensemble_upper: item.upper_bound,
    lstm: mlForecast.lstm[_idx]?.predicted_value || 0,
    prophet: mlForecast.prophet[_idx]?.predicted_value || 0,
    xgboost: mlForecast.xgboost[_idx]?.predicted_value || 0,
  }));

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'increasing':
        return <TrendingUp className="text-green-500" size={20} />;
      case 'decreasing':
        return <TrendingDown className="text-red-500" size={20} />;
      default:
        return <Minus className="text-gray-500" size={20} />;
    }
  };

  const getTrendLabel = (trend: string) => {
    switch (trend) {
      case 'increasing':
        return 'עולה';
      case 'decreasing':
        return 'יורד';
      case 'stable':
        return 'יציב';
      default:
        return 'לא מספיק נתונים';
    }
  };

  return (
    <div className="container mx-auto px-4 py-8" dir="rtl">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-800">תחזיות פיננסיות</h1>
          <p className="text-gray-600 mt-1">תחזיות הכנסות, הוצאות ותזרים מזומנים</p>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={forecastPeriods}
            onChange={(e) => setForecastPeriods(Number(e.target.value))}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value={6}>6 חודשים</option>
            <option value={12}>12 חודשים</option>
            <option value={18}>18 חודשים</option>
            <option value={24}>24 חודשים</option>
          </select>
          <select
            value={forecastMethod}
            onChange={(e) => setForecastMethod(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="exponential_smoothing">החלקה מעריכית</option>
            <option value="moving_average">ממוצע נע</option>
            <option value="linear_regression">רגרסיה לינארית</option>
            <option value="seasonal">עונתי</option>
            <option value="ensemble">משולב</option>
          </select>
        </div>
      </div>

      {/* Trend Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className="p-3 bg-blue-100 rounded-lg">
              <TrendingUp className="text-blue-600" size={24} />
            </div>
            <span className="text-sm text-gray-500">מגמת הכנסות</span>
          </div>
          <div className="flex items-center gap-2">
            {getTrendIcon(trends?.revenue.trend || '')}
            <p className="text-xl font-bold text-gray-800">{getTrendLabel(trends?.revenue.trend || '')}</p>
          </div>
          <p className="text-sm text-gray-500 mt-2">
            צמיחה: {(trends?.revenue.growth_rate || 0).toFixed(1)}%
          </p>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className="p-3 bg-red-100 rounded-lg">
              <TrendingDown className="text-red-600" size={24} />
            </div>
            <span className="text-sm text-gray-500">מגמת הוצאות</span>
          </div>
          <div className="flex items-center gap-2">
            {getTrendIcon(trends?.expenses.trend || '')}
            <p className="text-xl font-bold text-gray-800">{getTrendLabel(trends?.expenses.trend || '')}</p>
          </div>
          <p className="text-sm text-gray-500 mt-2">
            צמיחה: {(trends?.expenses.growth_rate || 0).toFixed(1)}%
          </p>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className="p-3 bg-purple-100 rounded-lg">
              <BarChart3 className="text-purple-600" size={24} />
            </div>
            <span className="text-sm text-gray-500">עונתיות</span>
          </div>
          <p className="text-xl font-bold text-gray-800">
            {trends?.seasonality.detected ? 'זוהתה' : 'לא זוהתה'}
          </p>
          {trends?.seasonality.detected && (
            <p className="text-sm text-gray-500 mt-2">
              שיא: Q{trends.seasonality.peak_quarter} | שפל: Q{trends.seasonality.low_quarter}
            </p>
          )}
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <div className="flex items-center justify-between mb-4">
            <div className="p-3 bg-green-100 rounded-lg">
              <Target className="text-green-600" size={24} />
            </div>
            <span className="text-sm text-gray-500">דיוק תחזית</span>
          </div>
          <p className="text-xl font-bold text-gray-800">
            {accuracy ? `${(100 - accuracy.mape).toFixed(1)}%` : '-'}
          </p>
          <p className="text-sm text-gray-500 mt-2">
            MAPE: {accuracy?.mape.toFixed(2) || '-'}%
          </p>
        </div>
      </div>

      {/* Revenue & Expense Forecast */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 mb-8">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">תחזית הכנסות והוצאות</h3>
        {loadingRevenue || loadingExpense ? (
          <div className="h-80 flex items-center justify-center">
            <RefreshCw className="animate-spin text-gray-400" size={32} />
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={350}>
            <ComposedChart data={combinedForecastData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Legend />
              <Area
                type="monotone"
                dataKey="revenue_upper"
                stroke="none"
                fill="#10B981"
                fillOpacity={0.1}
                name="טווח הכנסות"
              />
              <Area
                type="monotone"
                dataKey="revenue_lower"
                stroke="none"
                fill="#ffffff"
                fillOpacity={1}
              />
              <Line
                type="monotone"
                dataKey="revenue"
                stroke="#10B981"
                strokeWidth={2}
                name="הכנסות צפויות"
                dot={{ fill: '#10B981', r: 4 }}
              />
              <Area
                type="monotone"
                dataKey="expenses_upper"
                stroke="none"
                fill="#EF4444"
                fillOpacity={0.1}
                name="טווח הוצאות"
              />
              <Area
                type="monotone"
                dataKey="expenses_lower"
                stroke="none"
                fill="#ffffff"
                fillOpacity={1}
              />
              <Line
                type="monotone"
                dataKey="expenses"
                stroke="#EF4444"
                strokeWidth={2}
                name="הוצאות צפויות"
                dot={{ fill: '#EF4444', r: 4 }}
              />
              <Bar dataKey="net" fill="#3B82F6" name="תזרים נקי" opacity={0.5} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Cash Flow Forecast */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 mb-8">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold text-gray-800">תחזית תזרים מזומנים</h3>
          <button
            onClick={() => setShowScenarios(!showScenarios)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              showScenarios
                ? 'bg-primary-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            <Zap size={18} />
            ניתוח תרחישים
          </button>
        </div>
        {loadingCashFlow || (showScenarios && loadingScenarios) ? (
          <div className="h-80 flex items-center justify-center">
            <RefreshCw className="animate-spin text-gray-400" size={32} />
          </div>
        ) : showScenarios && scenarioChartData ? (
          <ResponsiveContainer width="100%" height={350}>
            <AreaChart data={scenarioChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Legend />
              <Area
                type="monotone"
                dataKey="optimistic"
                stroke="#10B981"
                fill="#10B981"
                fillOpacity={0.2}
                name="אופטימי (+20% הכנסות)"
              />
              <Area
                type="monotone"
                dataKey="expected"
                stroke="#3B82F6"
                fill="#3B82F6"
                fillOpacity={0.3}
                name="צפוי"
              />
              <Area
                type="monotone"
                dataKey="pessimistic"
                stroke="#EF4444"
                fill="#EF4444"
                fillOpacity={0.2}
                name="פסימי (-20% הכנסות)"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height={350}>
            <AreaChart data={cashFlowForecast}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Legend />
              <Area
                type="monotone"
                dataKey="projected_inflows"
                stackId="1"
                stroke="#10B981"
                fill="#10B981"
                fillOpacity={0.6}
                name="כניסות צפויות"
              />
              <Area
                type="monotone"
                dataKey="projected_outflows"
                stackId="2"
                stroke="#EF4444"
                fill="#EF4444"
                fillOpacity={0.6}
                name="יציאות צפויות"
              />
              <Line
                type="monotone"
                dataKey="projected_balance"
                stroke="#3B82F6"
                strokeWidth={3}
                name="יתרה צפויה"
                dot={{ fill: '#3B82F6', r: 4 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ML Forecasting */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 mb-8">
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 rounded-lg">
              <Brain className="text-purple-600" size={24} />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-gray-800">תחזית למידת מכונה</h3>
              <p className="text-sm text-gray-500">LSTM + Prophet + XGBoost</p>
            </div>
          </div>
          <div className="flex gap-2">
            {(['ensemble', 'lstm', 'prophet', 'xgboost'] as const).map((model) => (
              <button
                key={model}
                onClick={() => setSelectedModel(model)}
                className={`px-3 py-1 rounded-lg text-sm transition ${
                  selectedModel === model
                    ? 'bg-purple-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {model === 'ensemble' ? 'משולב' : model.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {loadingML ? (
          <div className="h-80 flex items-center justify-center">
            <RefreshCw className="animate-spin text-gray-400" size={32} />
          </div>
        ) : mlChartData ? (
          <>
            <ResponsiveContainer width="100%" height={350}>
              <AreaChart data={mlChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value: number) => formatCurrency(value)} />
                <Legend />
                {selectedModel === 'ensemble' ? (
                  <>
                    <Area
                      type="monotone"
                      dataKey="ensemble_upper"
                      stroke="none"
                      fill="#8B5CF6"
                      fillOpacity={0.2}
                      name="טווח ביטחון"
                    />
                    <Area
                      type="monotone"
                      dataKey="ensemble_lower"
                      stroke="none"
                      fill="#ffffff"
                      fillOpacity={1}
                    />
                    <Line
                      type="monotone"
                      dataKey="ensemble"
                      stroke="#8B5CF6"
                      strokeWidth={3}
                      name="תחזית משולבת"
                      dot={{ fill: '#8B5CF6', r: 4 }}
                    />
                  </>
                ) : (
                  <Line
                    type="monotone"
                    dataKey={selectedModel}
                    stroke={
                      selectedModel === 'lstm'
                        ? '#3B82F6'
                        : selectedModel === 'prophet'
                        ? '#10B981'
                        : '#F59E0B'
                    }
                    strokeWidth={3}
                    name={`תחזית ${selectedModel.toUpperCase()}`}
                    dot={{ r: 4 }}
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>

            {/* Model Weights */}
            {mlForecast?.weights && (
              <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                <h4 className="text-sm font-medium text-gray-700 mb-3">משקולות מודלים</h4>
                <div className="flex gap-4">
                  {Object.entries(mlForecast.weights).map(([model, weight]) => (
                    <div key={model} className="flex items-center gap-2">
                      <div
                        className={`w-3 h-3 rounded-full ${
                          model === 'lstm'
                            ? 'bg-blue-500'
                            : model === 'prophet'
                            ? 'bg-green-500'
                            : 'bg-yellow-500'
                        }`}
                      />
                      <span className="text-sm text-gray-600">
                        {model.toUpperCase()}: {((weight as number) * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="h-80 flex flex-col items-center justify-center text-gray-500">
            <AlertCircle size={48} className="mb-4" />
            <p>אין מספיק נתונים לתחזית ML</p>
            <p className="text-sm">נדרשים לפחות 12 חודשים של נתונים היסטוריים</p>
          </div>
        )}
      </div>

      {/* Forecast Details Table */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">פירוט תחזית</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-right py-3 px-4 font-medium text-gray-600">תקופה</th>
                <th className="text-right py-3 px-4 font-medium text-gray-600">הכנסות צפויות</th>
                <th className="text-right py-3 px-4 font-medium text-gray-600">הוצאות צפויות</th>
                <th className="text-right py-3 px-4 font-medium text-gray-600">תזרים נקי</th>
                <th className="text-right py-3 px-4 font-medium text-gray-600">יתרה צפויה</th>
                <th className="text-right py-3 px-4 font-medium text-gray-600">ביטחון</th>
              </tr>
            </thead>
            <tbody>
              {cashFlowForecast?.map((row, _idx) => (
                <tr key={_idx} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-3 px-4 font-medium">{row.date}</td>
                  <td className="py-3 px-4 text-green-600">{formatCurrency(row.projected_inflows)}</td>
                  <td className="py-3 px-4 text-red-600">{formatCurrency(row.projected_outflows)}</td>
                  <td className={`py-3 px-4 font-medium ${row.projected_net_flow >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {formatCurrency(row.projected_net_flow)}
                  </td>
                  <td className={`py-3 px-4 ${row.projected_balance >= 0 ? 'text-blue-600' : 'text-red-600'}`}>
                    {formatCurrency(row.projected_balance)}
                  </td>
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-green-500 rounded-full"
                          style={{ width: `${row.confidence * 100}%` }}
                        />
                      </div>
                      <span className="text-gray-500">{(row.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default ForecastingDashboard;
