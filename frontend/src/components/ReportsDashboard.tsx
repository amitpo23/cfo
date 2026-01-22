import React, { useState } from 'react';
import {
  FileText,
  Download,
  Calendar,
  TrendingUp,
  TrendingDown,
  DollarSign,
  PieChart,
  BarChart3,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  FileSpreadsheet,
  Building2,
  Wallet,
  AlertCircle
} from 'lucide-react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  LineChart,
  Line,
  Legend
} from 'recharts';
import api from '../services/api';

type ReportType = 'profit-loss' | 'balance-sheet' | 'cash-flow-projection';
type ReportPeriod = 'monthly' | 'quarterly' | 'yearly' | 'custom';

interface ProfitLossItem {
  category: string;
  category_hebrew: string;
  amount: number;
  percentage: number;
  previous_amount: number;
  change_percentage: number;
}

interface ProfitLossReport {
  period_start: string;
  period_end: string;
  revenue: ProfitLossItem[];
  cost_of_goods_sold: ProfitLossItem[];
  gross_profit: number;
  gross_margin: number;
  operating_expenses: ProfitLossItem[];
  operating_income: number;
  operating_margin: number;
  net_income_before_tax: number;
  tax_expense: number;
  net_income: number;
  net_margin: number;
  total_revenue: number;
  total_expenses: number;
}

interface BalanceSheetItem {
  name: string;
  name_hebrew: string;
  amount: number;
  previous_amount: number;
}

interface BalanceSheetReport {
  as_of_date: string;
  current_assets: BalanceSheetItem[];
  total_current_assets: number;
  fixed_assets: BalanceSheetItem[];
  total_fixed_assets: number;
  total_assets: number;
  current_liabilities: BalanceSheetItem[];
  total_current_liabilities: number;
  long_term_liabilities: BalanceSheetItem[];
  total_long_term_liabilities: number;
  total_liabilities: number;
  equity: BalanceSheetItem[];
  total_equity: number;
  is_balanced: boolean;
}

interface CashFlowProjectionItem {
  month: string;
  opening_balance: number;
  inflows: number;
  outflows: number;
  net_flow: number;
  closing_balance: number;
}

interface CashFlowProjectionReport {
  generated_date: string;
  projection_months: number;
  company_name: string;
  historical_average_inflows: number;
  historical_average_outflows: number;
  projections: CashFlowProjectionItem[];
  total_projected_inflows: number;
  total_projected_outflows: number;
  ending_balance: number;
  minimum_balance: number;
  runway_months: number;
}

const formatCurrency = (amount: number) => {
  return new Intl.NumberFormat('he-IL', {
    style: 'currency',
    currency: 'ILS',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  }).format(amount);
};

const formatPercent = (value: number) => `${value.toFixed(1)}%`;

export const ReportsDashboard: React.FC = () => {
  const [activeReport, setActiveReport] = useState<ReportType>('profit-loss');
  const [period, setPeriod] = useState<ReportPeriod>('monthly');
  const [startDate, setStartDate] = useState(
    new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]
  );
  const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);
  const [projectionMonths, setProjectionMonths] = useState(12);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    revenue: true,
    cogs: false,
    operating: true,
    assets: true,
    liabilities: true,
    equity: true
  });

  // שליפת דוח רווח והפסד
  const { data: plReport, isLoading: plLoading, refetch: refetchPL } = useQuery({
    queryKey: ['profitLoss', startDate, endDate],
    queryFn: async () => {
      const response = await api.get('/api/reports/profit-loss', {
        params: { start_date: startDate, end_date: endDate }
      });
      return response.data as ProfitLossReport;
    },
    enabled: activeReport === 'profit-loss'
  });

  // שליפת מאזן
  const { data: bsReport, isLoading: bsLoading, refetch: refetchBS } = useQuery({
    queryKey: ['balanceSheet', endDate],
    queryFn: async () => {
      const response = await api.get('/api/reports/balance-sheet', {
        params: { as_of_date: endDate }
      });
      return response.data as BalanceSheetReport;
    },
    enabled: activeReport === 'balance-sheet'
  });

  // שליפת תזרים חזוי
  const { data: cfReport, isLoading: cfLoading, refetch: refetchCF } = useQuery({
    queryKey: ['cashFlowProjection', projectionMonths],
    queryFn: async () => {
      const response = await api.get('/api/reports/cash-flow-projection', {
        params: { months: projectionMonths }
      });
      return response.data as CashFlowProjectionReport;
    },
    enabled: activeReport === 'cash-flow-projection'
  });

  // ייצוא ל-Excel
  const exportMutation = useMutation({
    mutationFn: async (type: ReportType) => {
      let url = '';
      let filename = '';
      
      if (type === 'profit-loss') {
        url = `/api/reports/profit-loss/export?start_date=${startDate}&end_date=${endDate}`;
        filename = `profit_loss_${startDate}_${endDate}.xlsx`;
      } else if (type === 'balance-sheet') {
        url = `/api/reports/balance-sheet/export?as_of_date=${endDate}`;
        filename = `balance_sheet_${endDate}.xlsx`;
      } else {
        url = `/api/reports/cash-flow-projection/export?months=${projectionMonths}`;
        filename = `cash_flow_projection.xlsx`;
      }
      
      const response = await api.get(url, { responseType: 'blob' });
      
      // הורדת הקובץ
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(downloadUrl);
    }
  });

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const renderReportTabs = () => (
    <div className="flex gap-2 mb-6">
      <button
        onClick={() => setActiveReport('profit-loss')}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
          activeReport === 'profit-loss'
            ? 'bg-blue-600 text-white'
            : 'bg-white text-gray-700 hover:bg-gray-100'
        }`}
      >
        <TrendingUp className="w-4 h-4" />
        רווח והפסד
      </button>
      <button
        onClick={() => setActiveReport('balance-sheet')}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
          activeReport === 'balance-sheet'
            ? 'bg-blue-600 text-white'
            : 'bg-white text-gray-700 hover:bg-gray-100'
        }`}
      >
        <Building2 className="w-4 h-4" />
        מאזן
      </button>
      <button
        onClick={() => setActiveReport('cash-flow-projection')}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
          activeReport === 'cash-flow-projection'
            ? 'bg-blue-600 text-white'
            : 'bg-white text-gray-700 hover:bg-gray-100'
        }`}
      >
        <Wallet className="w-4 h-4" />
        תזרים חזוי לבנק
      </button>
    </div>
  );

  const renderFilters = () => (
    <div className="bg-white rounded-xl shadow-sm p-4 mb-6">
      <div className="flex flex-wrap items-center gap-4">
        {activeReport !== 'cash-flow-projection' && (
          <>
            <div>
              <label className="block text-sm text-gray-600 mb-1">מתאריך</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1">עד תאריך</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1">תקופה מהירה</label>
              <select
                value={period}
                onChange={(e) => {
                  const val = e.target.value as ReportPeriod;
                  setPeriod(val);
                  const today = new Date();
                  if (val === 'monthly') {
                    setStartDate(new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0]);
                  } else if (val === 'quarterly') {
                    const qStart = Math.floor(today.getMonth() / 3) * 3;
                    setStartDate(new Date(today.getFullYear(), qStart, 1).toISOString().split('T')[0]);
                  } else if (val === 'yearly') {
                    setStartDate(new Date(today.getFullYear(), 0, 1).toISOString().split('T')[0]);
                  }
                  setEndDate(today.toISOString().split('T')[0]);
                }}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="monthly">חודשי</option>
                <option value="quarterly">רבעוני</option>
                <option value="yearly">שנתי</option>
                <option value="custom">מותאם</option>
              </select>
            </div>
          </>
        )}
        
        {activeReport === 'cash-flow-projection' && (
          <div>
            <label className="block text-sm text-gray-600 mb-1">חודשי תחזית</label>
            <select
              value={projectionMonths}
              onChange={(e) => setProjectionMonths(Number(e.target.value))}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
            >
              <option value={6}>6 חודשים</option>
              <option value={12}>12 חודשים</option>
              <option value={18}>18 חודשים</option>
              <option value={24}>24 חודשים</option>
            </select>
          </div>
        )}
        
        <div className="flex-1" />
        
        <button
          onClick={() => {
            if (activeReport === 'profit-loss') refetchPL();
            else if (activeReport === 'balance-sheet') refetchBS();
            else refetchCF();
          }}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
        >
          <RefreshCw className="w-4 h-4" />
          רענן
        </button>
        
        <button
          onClick={() => exportMutation.mutate(activeReport)}
          disabled={exportMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
        >
          {exportMutation.isPending ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          ייצוא Excel
        </button>
      </div>
    </div>
  );

  const renderProfitLoss = () => {
    if (plLoading) {
      return (
        <div className="flex justify-center py-12">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
        </div>
      );
    }

    if (!plReport) {
      return (
        <div className="text-center py-12 text-gray-500">
          <FileText className="w-16 h-16 mx-auto mb-4" />
          <p>לא נמצאו נתונים לתקופה המבוקשת</p>
        </div>
      );
    }

    const chartData = [
      { name: 'הכנסות', value: plReport.total_revenue, fill: '#22c55e' },
      { name: 'עלות מכר', value: Math.abs(plReport.cost_of_goods_sold.reduce((s, i) => s + i.amount, 0)), fill: '#ef4444' },
      { name: 'הוצאות תפעול', value: Math.abs(plReport.operating_expenses.reduce((s, i) => s + i.amount, 0)), fill: '#f59e0b' },
      { name: 'רווח נקי', value: plReport.net_income, fill: plReport.net_income >= 0 ? '#3b82f6' : '#dc2626' }
    ];

    return (
      <div className="space-y-6">
        {/* סיכום */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-xl shadow-sm p-4">
            <div className="flex items-center gap-2 text-green-600 mb-2">
              <TrendingUp className="w-5 h-5" />
              <span className="text-sm">סה"כ הכנסות</span>
            </div>
            <p className="text-2xl font-bold text-gray-900">{formatCurrency(plReport.total_revenue)}</p>
          </div>
          
          <div className="bg-white rounded-xl shadow-sm p-4">
            <div className="flex items-center gap-2 text-orange-600 mb-2">
              <TrendingDown className="w-5 h-5" />
              <span className="text-sm">סה"כ הוצאות</span>
            </div>
            <p className="text-2xl font-bold text-gray-900">{formatCurrency(plReport.total_expenses)}</p>
          </div>
          
          <div className="bg-white rounded-xl shadow-sm p-4">
            <div className="flex items-center gap-2 text-blue-600 mb-2">
              <BarChart3 className="w-5 h-5" />
              <span className="text-sm">רווח גולמי</span>
            </div>
            <p className="text-2xl font-bold text-gray-900">{formatCurrency(plReport.gross_profit)}</p>
            <p className="text-sm text-gray-500">{formatPercent(plReport.gross_margin)} מרווח</p>
          </div>
          
          <div className={`bg-white rounded-xl shadow-sm p-4 ${plReport.net_income < 0 ? 'border-2 border-red-300' : ''}`}>
            <div className={`flex items-center gap-2 mb-2 ${plReport.net_income >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              <DollarSign className="w-5 h-5" />
              <span className="text-sm">רווח נקי</span>
            </div>
            <p className={`text-2xl font-bold ${plReport.net_income >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {formatCurrency(plReport.net_income)}
            </p>
            <p className="text-sm text-gray-500">{formatPercent(plReport.net_margin)} מרווח נקי</p>
          </div>
        </div>

        {/* גרף */}
        <div className="bg-white rounded-xl shadow-sm p-6">
          <h3 className="text-lg font-semibold mb-4">תרשים רווח והפסד</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis tickFormatter={(v) => `₪${(v/1000).toFixed(0)}K`} />
                <Tooltip formatter={(v: number) => formatCurrency(v)} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {chartData.map((entry, index) => (
                    <Cell key={index} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* פירוט */}
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          {/* הכנסות */}
          <div className="border-b">
            <button
              onClick={() => toggleSection('revenue')}
              className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-semibold text-green-700">הכנסות</span>
              <div className="flex items-center gap-4">
                <span className="font-bold text-green-700">{formatCurrency(plReport.total_revenue)}</span>
                {expandedSections.revenue ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
              </div>
            </button>
            {expandedSections.revenue && (
              <div className="px-4 pb-4">
                <table className="w-full">
                  <tbody>
                    {plReport.revenue.map((item, i) => (
                      <tr key={i} className="border-t">
                        <td className="py-2 pr-4">{item.category_hebrew}</td>
                        <td className="py-2 text-left">{formatCurrency(item.amount)}</td>
                        <td className="py-2 text-left text-gray-500">{formatPercent(item.percentage)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* עלות מכר */}
          <div className="border-b">
            <button
              onClick={() => toggleSection('cogs')}
              className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-semibold text-red-700">עלות המכר</span>
              <div className="flex items-center gap-4">
                <span className="font-bold text-red-700">
                  {formatCurrency(plReport.cost_of_goods_sold.reduce((s, i) => s + i.amount, 0))}
                </span>
                {expandedSections.cogs ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
              </div>
            </button>
            {expandedSections.cogs && (
              <div className="px-4 pb-4">
                <table className="w-full">
                  <tbody>
                    {plReport.cost_of_goods_sold.map((item, i) => (
                      <tr key={i} className="border-t">
                        <td className="py-2 pr-4">{item.category_hebrew}</td>
                        <td className="py-2 text-left">{formatCurrency(item.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* רווח גולמי */}
          <div className="bg-blue-50 p-4 flex justify-between">
            <span className="font-semibold">רווח גולמי</span>
            <span className="font-bold">{formatCurrency(plReport.gross_profit)} ({formatPercent(plReport.gross_margin)})</span>
          </div>

          {/* הוצאות תפעוליות */}
          <div className="border-b">
            <button
              onClick={() => toggleSection('operating')}
              className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-semibold text-orange-700">הוצאות תפעוליות</span>
              <div className="flex items-center gap-4">
                <span className="font-bold text-orange-700">
                  {formatCurrency(plReport.operating_expenses.reduce((s, i) => s + i.amount, 0))}
                </span>
                {expandedSections.operating ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
              </div>
            </button>
            {expandedSections.operating && (
              <div className="px-4 pb-4">
                <table className="w-full">
                  <tbody>
                    {plReport.operating_expenses.map((item, i) => (
                      <tr key={i} className="border-t">
                        <td className="py-2 pr-4">{item.category_hebrew}</td>
                        <td className="py-2 text-left">{formatCurrency(item.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* רווח תפעולי */}
          <div className="bg-blue-50 p-4 flex justify-between">
            <span className="font-semibold">רווח תפעולי</span>
            <span className="font-bold">{formatCurrency(plReport.operating_income)} ({formatPercent(plReport.operating_margin)})</span>
          </div>

          {/* מס ורווח נקי */}
          <div className="p-4 border-t">
            <div className="flex justify-between py-2">
              <span>רווח לפני מס</span>
              <span>{formatCurrency(plReport.net_income_before_tax)}</span>
            </div>
            <div className="flex justify-between py-2 border-t">
              <span>מס</span>
              <span className="text-red-600">({formatCurrency(plReport.tax_expense)})</span>
            </div>
          </div>

          {/* רווח נקי */}
          <div className={`p-4 ${plReport.net_income >= 0 ? 'bg-green-100' : 'bg-red-100'}`}>
            <div className="flex justify-between items-center">
              <span className="text-lg font-bold">רווח נקי</span>
              <span className={`text-2xl font-bold ${plReport.net_income >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                {formatCurrency(plReport.net_income)}
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderBalanceSheet = () => {
    if (bsLoading) {
      return (
        <div className="flex justify-center py-12">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
        </div>
      );
    }

    if (!bsReport) {
      return (
        <div className="text-center py-12 text-gray-500">
          <Building2 className="w-16 h-16 mx-auto mb-4" />
          <p>לא נמצאו נתונים</p>
        </div>
      );
    }

    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* נכסים */}
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="bg-blue-600 text-white p-4">
            <h3 className="text-lg font-bold">נכסים</h3>
          </div>
          
          {/* נכסים שוטפים */}
          <div className="border-b">
            <button
              onClick={() => toggleSection('assets')}
              className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-semibold">נכסים שוטפים</span>
              <div className="flex items-center gap-4">
                <span className="font-bold">{formatCurrency(bsReport.total_current_assets)}</span>
                {expandedSections.assets ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
              </div>
            </button>
            {expandedSections.assets && (
              <div className="px-4 pb-4">
                {bsReport.current_assets.map((item, i) => (
                  <div key={i} className="flex justify-between py-2 border-t">
                    <span>{item.name_hebrew}</span>
                    <span>{formatCurrency(item.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* נכסים קבועים */}
          <div className="p-4 border-b">
            <div className="flex justify-between font-semibold">
              <span>נכסים קבועים</span>
              <span>{formatCurrency(bsReport.total_fixed_assets)}</span>
            </div>
            {bsReport.fixed_assets.map((item, i) => (
              <div key={i} className="flex justify-between py-1 text-sm text-gray-600">
                <span>{item.name_hebrew}</span>
                <span>{formatCurrency(item.amount)}</span>
              </div>
            ))}
          </div>

          {/* סה"כ נכסים */}
          <div className="bg-blue-100 p-4">
            <div className="flex justify-between items-center">
              <span className="text-lg font-bold text-blue-800">סה"כ נכסים</span>
              <span className="text-2xl font-bold text-blue-800">{formatCurrency(bsReport.total_assets)}</span>
            </div>
          </div>
        </div>

        {/* התחייבויות והון */}
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="bg-purple-600 text-white p-4">
            <h3 className="text-lg font-bold">התחייבויות והון עצמי</h3>
          </div>
          
          {/* התחייבויות שוטפות */}
          <div className="border-b">
            <button
              onClick={() => toggleSection('liabilities')}
              className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-semibold text-red-700">התחייבויות שוטפות</span>
              <div className="flex items-center gap-4">
                <span className="font-bold text-red-700">{formatCurrency(bsReport.total_current_liabilities)}</span>
                {expandedSections.liabilities ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
              </div>
            </button>
            {expandedSections.liabilities && (
              <div className="px-4 pb-4">
                {bsReport.current_liabilities.map((item, i) => (
                  <div key={i} className="flex justify-between py-2 border-t">
                    <span>{item.name_hebrew}</span>
                    <span>{formatCurrency(item.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* התחייבויות לז"א */}
          <div className="p-4 border-b">
            <div className="flex justify-between font-semibold text-red-700">
              <span>התחייבויות לזמן ארוך</span>
              <span>{formatCurrency(bsReport.total_long_term_liabilities)}</span>
            </div>
          </div>

          {/* סה"כ התחייבויות */}
          <div className="bg-red-50 p-4 border-b">
            <div className="flex justify-between">
              <span className="font-semibold">סה"כ התחייבויות</span>
              <span className="font-bold text-red-700">{formatCurrency(bsReport.total_liabilities)}</span>
            </div>
          </div>

          {/* הון עצמי */}
          <div className="border-b">
            <button
              onClick={() => toggleSection('equity')}
              className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-semibold text-green-700">הון עצמי</span>
              <div className="flex items-center gap-4">
                <span className="font-bold text-green-700">{formatCurrency(bsReport.total_equity)}</span>
                {expandedSections.equity ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
              </div>
            </button>
            {expandedSections.equity && (
              <div className="px-4 pb-4">
                {bsReport.equity.map((item, i) => (
                  <div key={i} className="flex justify-between py-2 border-t">
                    <span>{item.name_hebrew}</span>
                    <span>{formatCurrency(item.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* סה"כ */}
          <div className="bg-purple-100 p-4">
            <div className="flex justify-between items-center">
              <span className="text-lg font-bold text-purple-800">סה"כ התחייבויות והון</span>
              <span className="text-2xl font-bold text-purple-800">{formatCurrency(bsReport.total_liabilities + bsReport.total_equity)}</span>
            </div>
            {!bsReport.is_balanced && (
              <div className="mt-2 flex items-center gap-2 text-red-600">
                <AlertCircle className="w-4 h-4" />
                <span className="text-sm">המאזן אינו מאוזן</span>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderCashFlowProjection = () => {
    if (cfLoading) {
      return (
        <div className="flex justify-center py-12">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
        </div>
      );
    }

    if (!cfReport) {
      return (
        <div className="text-center py-12 text-gray-500">
          <Wallet className="w-16 h-16 mx-auto mb-4" />
          <p>לא נמצאו נתונים</p>
        </div>
      );
    }

    // נתונים לגרף
    const chartData = cfReport.projections.map(p => ({
      month: p.month,
      inflows: p.inflows,
      outflows: p.outflows,
      balance: p.closing_balance
    }));

    return (
      <div className="space-y-6">
        {/* סיכום */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-xl shadow-sm p-4">
            <p className="text-sm text-gray-500 mb-1">יתרת סגירה צפויה</p>
            <p className={`text-2xl font-bold ${cfReport.ending_balance >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {formatCurrency(cfReport.ending_balance)}
            </p>
          </div>
          <div className="bg-white rounded-xl shadow-sm p-4">
            <p className="text-sm text-gray-500 mb-1">יתרה מינימלית</p>
            <p className={`text-2xl font-bold ${cfReport.minimum_balance >= 0 ? 'text-blue-600' : 'text-red-600'}`}>
              {formatCurrency(cfReport.minimum_balance)}
            </p>
            {cfReport.minimum_balance < 0 && (
              <p className="text-xs text-red-500 mt-1">⚠️ צפוי גירעון</p>
            )}
          </div>
          <div className="bg-white rounded-xl shadow-sm p-4">
            <p className="text-sm text-gray-500 mb-1">Runway</p>
            <p className="text-2xl font-bold text-purple-600">
              {cfReport.runway_months > 0 ? `${cfReport.runway_months} חודשים` : '∞'}
            </p>
          </div>
          <div className="bg-white rounded-xl shadow-sm p-4">
            <p className="text-sm text-gray-500 mb-1">שריפה חודשית ממוצעת</p>
            <p className="text-2xl font-bold text-orange-600">
              {formatCurrency(cfReport.average_monthly_burn)}
            </p>
          </div>
        </div>

        {/* גרף */}
        <div className="bg-white rounded-xl shadow-sm p-6">
          <h3 className="text-lg font-semibold mb-4">תחזית תזרים מזומנים</h3>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis tickFormatter={(v) => `₪${(v/1000).toFixed(0)}K`} />
                <Tooltip formatter={(v: number) => formatCurrency(v)} />
                <Legend />
                <Line type="monotone" dataKey="inflows" name="כניסות" stroke="#22c55e" strokeWidth={2} />
                <Line type="monotone" dataKey="outflows" name="יציאות" stroke="#ef4444" strokeWidth={2} />
                <Line type="monotone" dataKey="balance" name="יתרה" stroke="#3b82f6" strokeWidth={3} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* טבלת תחזית */}
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="bg-gradient-to-r from-blue-600 to-blue-800 text-white p-4">
            <h3 className="text-lg font-bold">תזרים מזומנים חזוי - {cfReport.company_name}</h3>
            <p className="text-sm opacity-80">תאריך הפקה: {cfReport.generated_date}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-100">
                  <th className="text-right p-3 font-medium">חודש</th>
                  <th className="text-right p-3 font-medium">יתרת פתיחה</th>
                  <th className="text-right p-3 font-medium">כניסות</th>
                  <th className="text-right p-3 font-medium">יציאות</th>
                  <th className="text-right p-3 font-medium">תזרים נקי</th>
                  <th className="text-right p-3 font-medium">יתרת סגירה</th>
                </tr>
              </thead>
              <tbody>
                {cfReport.projections.map((proj, i) => (
                  <tr key={i} className={`border-t ${proj.closing_balance < 0 ? 'bg-red-50' : ''}`}>
                    <td className="p-3 font-medium">{proj.month}</td>
                    <td className="p-3">{formatCurrency(proj.opening_balance)}</td>
                    <td className="p-3 text-green-600">{formatCurrency(proj.inflows)}</td>
                    <td className="p-3 text-red-600">({formatCurrency(proj.outflows)})</td>
                    <td className={`p-3 font-medium ${proj.net_flow >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {formatCurrency(proj.net_flow)}
                    </td>
                    <td className={`p-3 font-bold ${proj.closing_balance >= 0 ? '' : 'text-red-600'}`}>
                      {formatCurrency(proj.closing_balance)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-gray-100 font-bold">
                  <td className="p-3">סה"כ</td>
                  <td className="p-3"></td>
                  <td className="p-3 text-green-600">{formatCurrency(cfReport.total_projected_inflows)}</td>
                  <td className="p-3 text-red-600">({formatCurrency(cfReport.total_projected_outflows)})</td>
                  <td className="p-3">{formatCurrency(cfReport.total_projected_inflows - cfReport.total_projected_outflows)}</td>
                  <td className="p-3">{formatCurrency(cfReport.ending_balance)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">דוחות כספיים</h1>
          <p className="text-gray-500 mt-1">הפקת דוחות רווח והפסד, מאזן ותזרים חזוי</p>
        </div>
      </div>

      {/* Tabs */}
      {renderReportTabs()}

      {/* Filters */}
      {renderFilters()}

      {/* Report Content */}
      {activeReport === 'profit-loss' && renderProfitLoss()}
      {activeReport === 'balance-sheet' && renderBalanceSheet()}
      {activeReport === 'cash-flow-projection' && renderCashFlowProjection()}
    </div>
  );
};

export default ReportsDashboard;
