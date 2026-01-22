import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileSignature,
  TrendingUp,
  TrendingDown,
  Calendar,
  Plus,
  X,
  RefreshCw,
  DollarSign,
  BarChart3,
  PieChart,
  LineChart,
  AlertTriangle,
  CheckCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  Filter,
  Download,
  Users,
  Repeat,
  Target,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  BarChart,
  Bar,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  ComposedChart,
  Line
} from 'recharts';
import api from '../services/api';

// Types
interface Agreement {
  agreement_id: string;
  customer_id: string;
  customer_name: string;
  agreement_type: string;
  title: string;
  total_value: number;
  billing_cycle: string;
  billing_amount: number;
  start_date: string;
  end_date?: string;
  status: string;
  auto_renew: boolean;
  invoiced_total: number;
  paid_total: number;
}

interface CashFlowProjection {
  period: string;
  total_inflows: number;
  total_outflows: number;
  net_flow: number;
  opening_balance: number;
  closing_balance: number;
  weighted_inflows: number;
  weighted_outflows: number;
}

interface CashFlowSummary {
  period_start: string;
  period_end: string;
  total_inflows: number;
  total_outflows: number;
  net_change: number;
  avg_monthly_inflow: number;
  avg_monthly_outflow: number;
  income_by_source: Record<string, number>;
  income_by_agreement_type: Record<string, number>;
  outflows_by_category: Record<string, number>;
  projections: CashFlowProjection[];
  min_balance: number;
  max_balance: number;
  low_balance_months: string[];
  outstanding_invoices_total: number;
  outstanding_invoices_count: number;
  overdue_invoices_total: number;
  overdue_invoices_count: number;
}

interface Forecast {
  dates: string[];
  inflows: {
    forecast: number[];
    confidence_lower: number[];
    confidence_upper: number[];
  };
  outflows: {
    forecast: number[];
  };
  net_cash_flow: {
    forecast: number[];
    trend: string;
  };
  metrics: {
    total_forecast_inflow: number;
    total_forecast_outflow: number;
    avg_monthly_net: number;
    best_month: string;
    worst_month: string;
  };
}

// Colors
const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#14B8A6'];

// Status badge component
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const getStatusStyle = (status: string) => {
    switch (status.toLowerCase()) {
      case 'active':
        return 'bg-green-100 text-green-800';
      case 'pending':
        return 'bg-yellow-100 text-yellow-800';
      case 'completed':
        return 'bg-blue-100 text-blue-800';
      case 'cancelled':
      case 'expired':
        return 'bg-red-100 text-red-800';
      case 'paused':
        return 'bg-gray-100 text-gray-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      draft: 'טיוטה',
      pending: 'ממתין',
      active: 'פעיל',
      paused: 'מושהה',
      completed: 'הושלם',
      cancelled: 'בוטל',
      expired: 'פג תוקף'
    };
    return labels[status.toLowerCase()] || status;
  };

  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusStyle(status)}`}>
      {getStatusLabel(status)}
    </span>
  );
};

// Agreement type labels
const getAgreementTypeLabel = (type: string) => {
  const labels: Record<string, string> = {
    subscription: 'מנוי',
    retainer: 'ריטיינר',
    project: 'פרויקט',
    service: 'שירות',
    license: 'רישיון',
    maintenance: 'תחזוקה',
    lease: 'השכרה',
    consulting: 'ייעוץ'
  };
  return labels[type] || type;
};

// Billing cycle labels
const getBillingCycleLabel = (cycle: string) => {
  const labels: Record<string, string> = {
    one_time: 'חד-פעמי',
    weekly: 'שבועי',
    bi_weekly: 'דו-שבועי',
    monthly: 'חודשי',
    quarterly: 'רבעוני',
    semi_annual: 'חצי-שנתי',
    annual: 'שנתי'
  };
  return labels[cycle] || cycle;
};

// Create Agreement Modal
const CreateAgreementModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: any) => void;
  isLoading: boolean;
}> = ({ isOpen, onClose, onSubmit, isLoading }) => {
  const [formData, setFormData] = useState({
    customer_id: '',
    customer_name: '',
    agreement_type: 'subscription',
    title: '',
    total_value: 0,
    billing_cycle: 'monthly',
    start_date: new Date().toISOString().split('T')[0],
    end_date: '',
    description: '',
    auto_renew: false,
    payment_terms_days: 30
  });

  const agreementTypes = [
    { value: 'subscription', label: 'מנוי' },
    { value: 'retainer', label: 'ריטיינר' },
    { value: 'project', label: 'פרויקט' },
    { value: 'service', label: 'שירות' },
    { value: 'license', label: 'רישיון' },
    { value: 'maintenance', label: 'תחזוקה' },
    { value: 'consulting', label: 'ייעוץ' }
  ];

  const billingCycles = [
    { value: 'one_time', label: 'חד-פעמי' },
    { value: 'monthly', label: 'חודשי' },
    { value: 'quarterly', label: 'רבעוני' },
    { value: 'semi_annual', label: 'חצי-שנתי' },
    { value: 'annual', label: 'שנתי' }
  ];

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold text-gray-800">הסכם חדש</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X className="h-6 w-6" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מזהה לקוח</label>
              <input
                type="text"
                value={formData.customer_id}
                onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">שם לקוח</label>
              <input
                type="text"
                value={formData.customer_name}
                onChange={(e) => setFormData({ ...formData, customer_name: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">כותרת ההסכם</label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              placeholder="תיאור קצר של ההסכם"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">סוג הסכם</label>
              <select
                value={formData.agreement_type}
                onChange={(e) => setFormData({ ...formData, agreement_type: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              >
                {agreementTypes.map(t => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מחזור חיוב</label>
              <select
                value={formData.billing_cycle}
                onChange={(e) => setFormData({ ...formData, billing_cycle: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              >
                {billingCycles.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">ערך ההסכם (₪)</label>
              <input
                type="number"
                value={formData.total_value}
                onChange={(e) => setFormData({ ...formData, total_value: parseFloat(e.target.value) || 0 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="0"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">ימי אשראי</label>
              <input
                type="number"
                value={formData.payment_terms_days}
                onChange={(e) => setFormData({ ...formData, payment_terms_days: parseInt(e.target.value) || 30 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="0"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תאריך התחלה</label>
              <input
                type="date"
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תאריך סיום (אופציונלי)</label>
              <input
                type="date"
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">תיאור</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              rows={2}
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="auto_renew"
              checked={formData.auto_renew}
              onChange={(e) => setFormData({ ...formData, auto_renew: e.target.checked })}
              className="rounded border-gray-300 text-blue-600"
            />
            <label htmlFor="auto_renew" className="text-sm text-gray-700">
              חידוש אוטומטי
            </label>
          </div>

          <div className="flex justify-end gap-3 mt-6">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
            >
              ביטול
            </button>
            <button
              onClick={() => onSubmit(formData)}
              disabled={isLoading || !formData.customer_name || !formData.title}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSignature className="h-4 w-4" />}
              צור הסכם
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Main Component
const AgreementCashFlowDashboard: React.FC = () => {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'overview' | 'agreements' | 'projections' | 'forecast'>('overview');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [forecastMonths, setForecastMonths] = useState(6);
  const [expandedAgreement, setExpandedAgreement] = useState<string | null>(null);

  // Queries
  const { data: agreements = [], isLoading: loadingAgreements } = useQuery({
    queryKey: ['agreements'],
    queryFn: async () => {
      const response = await api.get('/financial/agreements');
      return response.data;
    }
  });

  const { data: revenueSummary } = useQuery({
    queryKey: ['agreement-revenue-summary'],
    queryFn: async () => {
      const response = await api.get('/financial/agreements/revenue-summary');
      return response.data;
    }
  });

  const { data: cashFlowSummary } = useQuery({
    queryKey: ['cashflow-summary'],
    queryFn: async () => {
      const response = await api.get('/financial/cashflow/summary');
      return response.data;
    }
  });

  const { data: projections = [] } = useQuery({
    queryKey: ['cashflow-projections'],
    queryFn: async () => {
      const response = await api.get('/financial/cashflow/projection?periods=12');
      return response.data;
    }
  });

  const { data: forecast, isLoading: loadingForecast } = useQuery({
    queryKey: ['cashflow-forecast', forecastMonths],
    queryFn: async () => {
      const response = await api.post('/financial/cashflow/forecast', {
        historical_months: 12,
        forecast_months: forecastMonths,
        method: 'exponential_smoothing'
      });
      return response.data;
    }
  });

  // Mutations
  const createAgreementMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await api.post('/financial/agreements', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agreements'] });
      queryClient.invalidateQueries({ queryKey: ['agreement-revenue-summary'] });
      setShowCreateModal(false);
    }
  });

  const syncInvoicesMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/financial/cashflow/sync-invoices');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cashflow-summary'] });
      queryClient.invalidateQueries({ queryKey: ['cashflow-projections'] });
    }
  });

  // Prepare chart data
  const projectionChartData = projections.map((p: CashFlowProjection) => ({
    period: p.period,
    inflows: p.total_inflows,
    outflows: p.total_outflows,
    net: p.net_flow,
    balance: p.closing_balance
  }));

  const agreementTypeData = revenueSummary?.by_type 
    ? Object.entries(revenueSummary.by_type).map(([type, data]: [string, any]) => ({
        name: getAgreementTypeLabel(type),
        value: data.value,
        count: data.count
      }))
    : [];

  // Statistics
  const activeAgreements = agreements.filter((a: Agreement) => a.status === 'active');
  const totalValue = activeAgreements.reduce((sum: number, a: Agreement) => sum + a.total_value, 0);
  const monthlyRecurring = revenueSummary?.monthly_recurring || 0;

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">הסכמים ותזרים מזומנים</h1>
          <p className="text-gray-600">ניהול הסכמים, חיזוי תזרים וניתוח פיננסי</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => syncInvoicesMutation.mutate()}
            disabled={syncInvoicesMutation.isPending}
            className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${syncInvoicesMutation.isPending ? 'animate-spin' : ''}`} />
            סנכרן חשבוניות
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
          >
            <Plus className="h-4 w-4" />
            הסכם חדש
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 rounded-lg">
              <FileSignature className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">הסכמים פעילים</p>
              <p className="text-xl font-bold">{activeAgreements.length}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 rounded-lg">
              <DollarSign className="h-5 w-5 text-green-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">ערך הסכמים</p>
              <p className="text-xl font-bold">₪{totalValue.toLocaleString('he-IL')}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 rounded-lg">
              <Repeat className="h-5 w-5 text-purple-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">הכנסה חוזרת/חודש</p>
              <p className="text-xl font-bold">₪{monthlyRecurring.toLocaleString('he-IL')}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${
              (cashFlowSummary?.net_change || 0) >= 0 ? 'bg-green-100' : 'bg-red-100'
            }`}>
              {(cashFlowSummary?.net_change || 0) >= 0 ? (
                <TrendingUp className="h-5 w-5 text-green-600" />
              ) : (
                <TrendingDown className="h-5 w-5 text-red-600" />
              )}
            </div>
            <div>
              <p className="text-sm text-gray-500">תזרים נטו</p>
              <p className={`text-xl font-bold ${
                (cashFlowSummary?.net_change || 0) >= 0 ? 'text-green-600' : 'text-red-600'
              }`}>
                ₪{Math.abs(cashFlowSummary?.net_change || 0).toLocaleString('he-IL')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-8">
          {[
            { id: 'overview', label: 'סקירה כללית', icon: PieChart },
            { id: 'agreements', label: 'הסכמים', icon: FileSignature },
            { id: 'projections', label: 'תחזית תזרים', icon: LineChart },
            { id: 'forecast', label: 'חיזוי AI', icon: BarChart3 }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center gap-2 ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Cash Flow Chart */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">תזרים מזומנים - 12 חודשים</h3>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={projectionChartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="period" />
                <YAxis />
                <Tooltip 
                  formatter={(value: number) => `₪${value.toLocaleString('he-IL')}`}
                />
                <Legend />
                <Bar dataKey="inflows" fill="#10B981" name="כניסות" />
                <Bar dataKey="outflows" fill="#EF4444" name="יציאות" />
                <Line type="monotone" dataKey="balance" stroke="#3B82F6" strokeWidth={2} name="יתרה" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Agreement Types Pie Chart */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">חלוקה לפי סוג הסכם</h3>
            {agreementTypeData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <RechartsPieChart>
                  <Pie
                    data={agreementTypeData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={5}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  >
                    {agreementTypeData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `₪${value.toLocaleString('he-IL')}`} />
                </RechartsPieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-gray-500">
                <p>אין נתונים להצגה</p>
              </div>
            )}
          </div>

          {/* Outstanding Invoices */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">חשבוניות פתוחות</h3>
            <div className="space-y-4">
              <div className="flex justify-between items-center p-3 bg-yellow-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <Clock className="h-5 w-5 text-yellow-600" />
                  <span>ממתינות לתשלום</span>
                </div>
                <div className="text-right">
                  <p className="font-bold">₪{(cashFlowSummary?.outstanding_invoices_total || 0).toLocaleString('he-IL')}</p>
                  <p className="text-sm text-gray-500">{cashFlowSummary?.outstanding_invoices_count || 0} חשבוניות</p>
                </div>
              </div>
              
              <div className="flex justify-between items-center p-3 bg-red-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5 text-red-600" />
                  <span>באיחור</span>
                </div>
                <div className="text-right">
                  <p className="font-bold text-red-600">₪{(cashFlowSummary?.overdue_invoices_total || 0).toLocaleString('he-IL')}</p>
                  <p className="text-sm text-gray-500">{cashFlowSummary?.overdue_invoices_count || 0} חשבוניות</p>
                </div>
              </div>
            </div>
          </div>

          {/* Expiring Agreements */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">הסכמים שעומדים להסתיים</h3>
            {revenueSummary?.expiring_soon?.length > 0 ? (
              <div className="space-y-3">
                {revenueSummary.expiring_soon.map((agreement: any) => (
                  <div key={agreement.agreement_id} className="flex justify-between items-center p-3 bg-orange-50 rounded-lg">
                    <div>
                      <p className="font-medium">{agreement.title}</p>
                      <p className="text-sm text-gray-500">{agreement.customer_name}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-bold">₪{agreement.value.toLocaleString('he-IL')}</p>
                      <p className="text-sm text-orange-600">
                        {new Date(agreement.end_date).toLocaleDateString('he-IL')}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center text-gray-500 py-8">
                <CheckCircle className="h-12 w-12 mx-auto text-green-300 mb-2" />
                <p>אין הסכמים שעומדים להסתיים</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Agreements Tab */}
      {activeTab === 'agreements' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {loadingAgreements ? (
            <div className="p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
            </div>
          ) : agreements.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <FileSignature className="h-12 w-12 mx-auto text-gray-300 mb-3" />
              <p>אין הסכמים</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">הסכם</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">לקוח</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סוג</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">ערך</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">חיוב</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תקופה</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סטטוס</th>
                </tr>
              </thead>
              <tbody>
                {agreements.map((agreement: Agreement) => (
                  <React.Fragment key={agreement.agreement_id}>
                    <tr
                      className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
                      onClick={() => setExpandedAgreement(
                        expandedAgreement === agreement.agreement_id ? null : agreement.agreement_id
                      )}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          {expandedAgreement === agreement.agreement_id ? (
                            <ChevronUp className="h-4 w-4 text-gray-400" />
                          ) : (
                            <ChevronDown className="h-4 w-4 text-gray-400" />
                          )}
                          <span className="font-medium">{agreement.title}</span>
                        </div>
                      </td>
                      <td className="py-3 px-4">{agreement.customer_name}</td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-1 bg-gray-100 rounded-full text-xs">
                          {getAgreementTypeLabel(agreement.agreement_type)}
                        </span>
                      </td>
                      <td className="py-3 px-4 font-medium">
                        ₪{agreement.total_value?.toLocaleString('he-IL')}
                      </td>
                      <td className="py-3 px-4">
                        <div>
                          <p>₪{agreement.billing_amount?.toLocaleString('he-IL')}</p>
                          <p className="text-xs text-gray-500">{getBillingCycleLabel(agreement.billing_cycle)}</p>
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <div className="text-sm">
                          <p>{new Date(agreement.start_date).toLocaleDateString('he-IL')}</p>
                          {agreement.end_date && (
                            <p className="text-gray-500">עד {new Date(agreement.end_date).toLocaleDateString('he-IL')}</p>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={agreement.status} />
                      </td>
                    </tr>
                    {expandedAgreement === agreement.agreement_id && (
                      <tr>
                        <td colSpan={7} className="bg-gray-50 px-6 py-4">
                          <div className="grid grid-cols-3 gap-6">
                            <div>
                              <p className="text-sm text-gray-500">חויב</p>
                              <p className="font-medium">₪{(agreement.invoiced_total || 0).toLocaleString('he-IL')}</p>
                            </div>
                            <div>
                              <p className="text-sm text-gray-500">שולם</p>
                              <p className="font-medium">₪{(agreement.paid_total || 0).toLocaleString('he-IL')}</p>
                            </div>
                            <div>
                              <p className="text-sm text-gray-500">חידוש אוטומטי</p>
                              <p className="font-medium">{agreement.auto_renew ? 'כן' : 'לא'}</p>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Projections Tab */}
      {activeTab === 'projections' && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">תחזית תזרים מזומנים - 12 חודשים</h3>
            <ResponsiveContainer width="100%" height={400}>
              <AreaChart data={projectionChartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="period" />
                <YAxis />
                <Tooltip formatter={(value: number) => `₪${value.toLocaleString('he-IL')}`} />
                <Legend />
                <Area 
                  type="monotone" 
                  dataKey="inflows" 
                  stackId="1"
                  stroke="#10B981" 
                  fill="#10B98133" 
                  name="כניסות"
                />
                <Area 
                  type="monotone" 
                  dataKey="outflows" 
                  stackId="2"
                  stroke="#EF4444" 
                  fill="#EF444433" 
                  name="יציאות"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Alerts */}
          {cashFlowSummary?.low_balance_months?.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-red-600 mt-0.5" />
                <div>
                  <h4 className="font-medium text-red-800">התראה: יתרה שלילית צפויה</h4>
                  <p className="text-sm text-red-600 mt-1">
                    בחודשים הבאים צפויה יתרה שלילית: {cashFlowSummary.low_balance_months.join(', ')}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Forecast Tab */}
      {activeTab === 'forecast' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">חיזוי תזרים מזומנים (AI)</h3>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">חודשים לחיזוי:</span>
              <select
                value={forecastMonths}
                onChange={(e) => setForecastMonths(parseInt(e.target.value))}
                className="border border-gray-300 rounded-lg px-3 py-1"
              >
                <option value="3">3 חודשים</option>
                <option value="6">6 חודשים</option>
                <option value="12">12 חודשים</option>
              </select>
            </div>
          </div>

          {loadingForecast ? (
            <div className="bg-white rounded-xl p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
              <p className="mt-2 text-gray-500">מחשב תחזית...</p>
            </div>
          ) : forecast?.error ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4">
              <p className="text-yellow-800">{forecast.error}</p>
            </div>
          ) : forecast ? (
            <>
              {/* Forecast Chart */}
              <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
                <ResponsiveContainer width="100%" height={400}>
                  <AreaChart
                    data={forecast.dates.map((date: string, i: number) => ({
                      date,
                      forecast: forecast.net_cash_flow.forecast[i],
                      lower: forecast.inflows.confidence_lower[i] - forecast.outflows.forecast[i],
                      upper: forecast.inflows.confidence_upper[i] - forecast.outflows.forecast[i]
                    }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis />
                    <Tooltip formatter={(value: number) => `₪${value.toLocaleString('he-IL')}`} />
                    <Legend />
                    <Area
                      type="monotone"
                      dataKey="upper"
                      stroke="none"
                      fill="#3B82F620"
                      name="גבול עליון"
                    />
                    <Area
                      type="monotone"
                      dataKey="lower"
                      stroke="none"
                      fill="#fff"
                      name="גבול תחתון"
                    />
                    <Area
                      type="monotone"
                      dataKey="forecast"
                      stroke="#3B82F6"
                      fill="#3B82F640"
                      strokeWidth={2}
                      name="תחזית"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Forecast Metrics */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                  <p className="text-sm text-gray-500">סה"כ כניסות צפויות</p>
                  <p className="text-xl font-bold text-green-600">
                    ₪{forecast.metrics.total_forecast_inflow?.toLocaleString('he-IL')}
                  </p>
                </div>
                <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                  <p className="text-sm text-gray-500">סה"כ יציאות צפויות</p>
                  <p className="text-xl font-bold text-red-600">
                    ₪{forecast.metrics.total_forecast_outflow?.toLocaleString('he-IL')}
                  </p>
                </div>
                <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                  <p className="text-sm text-gray-500">החודש הטוב ביותר</p>
                  <p className="text-xl font-bold text-blue-600">
                    {forecast.metrics.best_month}
                  </p>
                </div>
                <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                  <p className="text-sm text-gray-500">מגמה</p>
                  <div className="flex items-center gap-2">
                    {forecast.net_cash_flow.trend === 'up' ? (
                      <>
                        <ArrowUpRight className="h-5 w-5 text-green-500" />
                        <span className="text-xl font-bold text-green-600">עלייה</span>
                      </>
                    ) : (
                      <>
                        <ArrowDownRight className="h-5 w-5 text-red-500" />
                        <span className="text-xl font-bold text-red-600">ירידה</span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Create Agreement Modal */}
      <CreateAgreementModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={createAgreementMutation.mutate}
        isLoading={createAgreementMutation.isPending}
      />
    </div>
  );
};

export default AgreementCashFlowDashboard;
