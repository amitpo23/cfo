import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Legend,
} from 'recharts';
import api from '../services/api';

interface KPI {
  name: string;
  hebrew_name: string;
  value: number;
  target: number;
  unit: string;
  status: string;
  trend: string;
  category: string;
}

interface ExecutiveSummary {
  period: string;
  revenue: number;
  expenses: number;
  net_income: number;
  gross_margin: number;
  net_margin: number;
  cash_balance: number;
  highlights: string[];
  concerns: string[];
  recommendations: string[];
}

const KPI_CATEGORIES = [
  { id: 'profitability', name: 'רווחיות', icon: '💰' },
  { id: 'liquidity', name: 'נזילות', icon: '💧' },
  { id: 'efficiency', name: 'יעילות', icon: '⚡' },
  { id: 'leverage', name: 'מינוף', icon: '📊' },
  { id: 'growth', name: 'צמיחה', icon: '📈' },
];

export const KPIDashboard: React.FC = () => {
  const [selectedCategory, setSelectedCategory] = useState<string>('all');

  // Fetch KPI dashboard
  const { data: kpiData, isLoading: loadingKPIs } = useQuery({
    queryKey: ['kpi-dashboard'],
    queryFn: async () => {
      const response = await api.get<{ data: { kpis: KPI[] } }>('/api/financial/kpis');
      return response.data;
    },
  });

  // Fetch executive summary
  const { data: execSummary, isLoading: loadingSummary } = useQuery({
    queryKey: ['executive-summary'],
    queryFn: async () => {
      const response = await api.get<{ data: ExecutiveSummary }>('/api/financial/kpis/executive-summary');
      return response.data;
    },
  });

  // Fetch KPI trends
  const { data: kpiTrends } = useQuery({
    queryKey: ['kpi-trends'],
    queryFn: async () => {
      const response = await api.get<{ data: Record<string, Array<{ month: string; value: number }>> }>('/api/financial/kpis/trends', {
        params: { kpi_names: ['revenue_growth', 'gross_margin', 'net_margin'] }
      });
      return response.data;
    },
  });

  // Fetch industry comparison
  const { data: benchmarkData } = useQuery({
    queryKey: ['industry-benchmark'],
    queryFn: async () => {
      const response = await api.get<{ data: { comparisons: Array<{ kpi_name: string; company_value: number; industry_avg: number }> } }>('/api/financial/kpis/benchmark');
      return response.data;
    },
  });

  const formatCurrency = (value: number) => `₪${value.toLocaleString()}`;
  const formatPercent = (value: number) => `${value.toFixed(1)}%`;

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'above_target': return 'text-green-600 bg-green-100';
      case 'on_target': return 'text-blue-600 bg-blue-100';
      case 'below_target': return 'text-yellow-600 bg-yellow-100';
      case 'critical': return 'text-red-600 bg-red-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'up': return '↗️';
      case 'down': return '↘️';
      case 'stable': return '➡️';
      default: return '•';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'above_target': return 'מעל היעד';
      case 'on_target': return 'ביעד';
      case 'below_target': return 'מתחת ליעד';
      case 'critical': return 'קריטי';
      default: return status;
    }
  };

  if (loadingKPIs || loadingSummary) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  const kpis = kpiData?.kpis || [];
  const filteredKPIs = selectedCategory === 'all' 
    ? kpis 
    : kpis.filter((kpi: KPI) => kpi.category === selectedCategory);

  // Prepare radar data for benchmark comparison
  const radarData = benchmarkData?.comparisons?.slice(0, 6).map((item: any) => ({
    subject: item.kpi_name,
    company: item.company_value,
    industry: item.industry_avg,
  })) || [];

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">דשבורד KPI</h1>
          <p className="text-gray-600 mt-1">מדדי ביצוע מרכזיים</p>
        </div>
        <div className="flex gap-4">
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="rounded-lg border-gray-300 shadow-sm px-4 py-2"
          >
            <option value="all">כל הקטגוריות</option>
            {KPI_CATEGORIES.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.icon} {cat.name}
              </option>
            ))}
          </select>
          <button className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
            ייצא דוח
          </button>
        </div>
      </div>

      {/* Executive Summary */}
      {execSummary && (
        <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-xl shadow-lg p-6 text-white">
          <h2 className="text-xl font-bold mb-4">סיכום מנהלים - {execSummary.period}</h2>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
            <div>
              <p className="text-blue-100 text-sm">הכנסות</p>
              <p className="text-2xl font-bold">{formatCurrency(execSummary.revenue)}</p>
            </div>
            <div>
              <p className="text-blue-100 text-sm">הוצאות</p>
              <p className="text-2xl font-bold">{formatCurrency(execSummary.expenses)}</p>
            </div>
            <div>
              <p className="text-blue-100 text-sm">רווח נקי</p>
              <p className={`text-2xl font-bold ${execSummary.net_income >= 0 ? 'text-green-300' : 'text-red-300'}`}>
                {formatCurrency(execSummary.net_income)}
              </p>
            </div>
            <div>
              <p className="text-blue-100 text-sm">רווח גולמי</p>
              <p className="text-2xl font-bold">{formatPercent(execSummary.gross_margin)}</p>
            </div>
            <div>
              <p className="text-blue-100 text-sm">רווח נקי %</p>
              <p className="text-2xl font-bold">{formatPercent(execSummary.net_margin)}</p>
            </div>
            <div>
              <p className="text-blue-100 text-sm">יתרת מזומן</p>
              <p className="text-2xl font-bold">{formatCurrency(execSummary.cash_balance)}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Highlights */}
            <div className="bg-white bg-opacity-10 rounded-lg p-4">
              <h4 className="font-semibold mb-2">🌟 נקודות חיוביות</h4>
              <ul className="space-y-1 text-sm">
                {execSummary.highlights?.map((item, i) => (
                  <li key={i}>• {item}</li>
                ))}
              </ul>
            </div>
            {/* Concerns */}
            <div className="bg-white bg-opacity-10 rounded-lg p-4">
              <h4 className="font-semibold mb-2">⚠️ נקודות לתשומת לב</h4>
              <ul className="space-y-1 text-sm">
                {execSummary.concerns?.map((item, i) => (
                  <li key={i}>• {item}</li>
                ))}
              </ul>
            </div>
            {/* Recommendations */}
            <div className="bg-white bg-opacity-10 rounded-lg p-4">
              <h4 className="font-semibold mb-2">💡 המלצות</h4>
              <ul className="space-y-1 text-sm">
                {execSummary.recommendations?.map((item, i) => (
                  <li key={i}>• {item}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Category Tabs */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setSelectedCategory('all')}
          className={`px-4 py-2 rounded-lg font-medium transition-colors ${
            selectedCategory === 'all'
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-700 hover:bg-gray-100'
          }`}
        >
          הכל
        </button>
        {KPI_CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setSelectedCategory(cat.id)}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              selectedCategory === cat.id
                ? 'bg-blue-600 text-white'
                : 'bg-white text-gray-700 hover:bg-gray-100'
            }`}
          >
            {cat.icon} {cat.name}
          </button>
        ))}
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {filteredKPIs.map((kpi: KPI) => (
          <div
            key={kpi.name}
            className="bg-white rounded-xl shadow-sm p-5 border border-gray-100 hover:border-blue-300 hover:shadow-md transition-all cursor-pointer"
          >
            <div className="flex justify-between items-start mb-3">
              <div>
                <h4 className="font-bold text-gray-900">{kpi.hebrew_name}</h4>
                <p className="text-xs text-gray-500">{kpi.name}</p>
              </div>
              <span className="text-xl">{getTrendIcon(kpi.trend)}</span>
            </div>
            
            <div className="flex items-baseline gap-2 mb-2">
              <span className="text-3xl font-bold text-gray-900">
                {kpi.unit === '%' ? formatPercent(kpi.value) : 
                 kpi.unit === 'currency' ? formatCurrency(kpi.value) :
                 kpi.value.toFixed(1)}
              </span>
              {kpi.unit !== '%' && kpi.unit !== 'currency' && (
                <span className="text-gray-500 text-sm">{kpi.unit}</span>
              )}
            </div>

            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-500">
                יעד: {kpi.unit === '%' ? formatPercent(kpi.target) : 
                      kpi.unit === 'currency' ? formatCurrency(kpi.target) :
                      kpi.target}
              </span>
              <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(kpi.status)}`}>
                {getStatusLabel(kpi.status)}
              </span>
            </div>

            {/* Progress bar */}
            <div className="mt-3">
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    kpi.status === 'above_target' || kpi.status === 'on_target' 
                      ? 'bg-green-500' 
                      : kpi.status === 'critical' 
                        ? 'bg-red-500' 
                        : 'bg-yellow-500'
                  }`}
                  style={{ width: `${Math.min((kpi.value / kpi.target) * 100, 100)}%` }}
                ></div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* KPI Trends Chart */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">מגמות KPI</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={kpiTrends?.revenue_growth || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(value: number) => `${value.toFixed(1)}%`} />
              <Legend />
              <Line 
                type="monotone" 
                dataKey="value" 
                stroke="#3B82F6" 
                strokeWidth={2}
                name="צמיחת הכנסות"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Industry Comparison Radar */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">השוואה לענף</h2>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={radarData}>
              <PolarGrid />
              <PolarAngleAxis dataKey="subject" />
              <PolarRadiusAxis />
              <Radar
                name="החברה"
                dataKey="company"
                stroke="#3B82F6"
                fill="#3B82F6"
                fillOpacity={0.5}
              />
              <Radar
                name="ממוצע ענף"
                dataKey="industry"
                stroke="#10B981"
                fill="#10B981"
                fillOpacity={0.3}
              />
              <Legend />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* KPI Summary Table */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 mb-4">סיכום מדדים</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">מדד</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">קטגוריה</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">ערך נוכחי</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">יעד</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">% מיעד</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">מגמה</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">סטטוס</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {kpis.map((kpi: KPI) => (
                <tr key={kpi.name} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{kpi.hebrew_name}</p>
                      <p className="text-xs text-gray-500">{kpi.name}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                    {KPI_CATEGORIES.find(c => c.id === kpi.category)?.name || kpi.category}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900">
                    {kpi.unit === '%' ? formatPercent(kpi.value) : 
                     kpi.unit === 'currency' ? formatCurrency(kpi.value) :
                     kpi.value.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                    {kpi.unit === '%' ? formatPercent(kpi.target) : 
                     kpi.unit === 'currency' ? formatCurrency(kpi.target) :
                     kpi.target}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                    <span className={kpi.value >= kpi.target ? 'text-green-600' : 'text-red-600'}>
                      {((kpi.value / kpi.target) * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xl">
                    {getTrendIcon(kpi.trend)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(kpi.status)}`}>
                      {getStatusLabel(kpi.status)}
                    </span>
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

export default KPIDashboard;
