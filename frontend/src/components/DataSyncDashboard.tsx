import React, { useState } from 'react';
import {
  RefreshCw,
  CheckCircle,
  AlertCircle,
  FileText,
  CreditCard,
  DollarSign,
  Users,
  Clock,
  TrendingUp,
  Database,
  Calendar,
  Package,
  Percent,
  ArrowRightLeft
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

interface SyncResult {
  synced_documents?: number;
  synced_payments?: number;
  synced_billing_transactions?: number;
  total_income?: number;
  total_expenses?: number;
  total_amount?: number;
  error?: string;
  period?: { from: string; to: string };
}

interface DebtItem {
  customer_name: string;
  amount: number;
  due_date: string;
  days_overdue: number;
}

interface IncomeItem {
  id: number;
  name: string;
  price: number;
  description: string;
}

export const DataSyncDashboard: React.FC = () => {
  const [syncDateRange, setSyncDateRange] = useState({
    from_date: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    to_date: new Date().toISOString().split('T')[0]
  });
  
  const queryClient = useQueryClient();

  // שליפת שיעור מע"מ
  const { data: vatData } = useQuery({
    queryKey: ['vatRate'],
    queryFn: async () => {
      const response = await api.get('/api/sync/sumit/vat-rate');
      return response.data;
    }
  });

  // סנכרון מסמכים
  const syncDocumentsMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/api/sync/sumit/documents', syncDateRange);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cashflow'] });
    }
  });

  // סנכרון תשלומים
  const syncPaymentsMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/api/sync/sumit/payments', syncDateRange);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cashflow'] });
    }
  });

  // סנכרון עסקאות סליקה
  const syncBillingMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/api/sync/sumit/billing', syncDateRange);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cashflow'] });
    }
  });

  // שליפת חובות
  const { data: debtsData, refetch: refetchDebts, isLoading: debtsLoading } = useQuery({
    queryKey: ['debts'],
    queryFn: async () => {
      const response = await api.get('/api/sync/sumit/debts');
      return response.data;
    },
    enabled: false
  });

  // שליפת פריטי הכנסה
  const { data: incomeItemsData, refetch: refetchIncomeItems, isLoading: incomeItemsLoading } = useQuery({
    queryKey: ['incomeItems'],
    queryFn: async () => {
      const response = await api.get('/api/sync/sumit/income-items');
      return response.data;
    },
    enabled: false
  });

  // שליפת שער חליפין
  const [exchangeResult, setExchangeResult] = useState<{ from: string; to: string; rate: number } | null>(null);
  const exchangeRateMutation = useMutation({
    mutationFn: async (params: { from: string; to: string }) => {
      const response = await api.get(`/api/sync/sumit/exchange-rate?from_currency=${params.from}&to_currency=${params.to}`);
      return response.data;
    },
    onSuccess: (data) => {
      setExchangeResult({ from: data.from_currency, to: data.to_currency, rate: data.rate });
    }
  });

  // סנכרון מלא
  const fullSyncMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/api/sync/sumit/full', syncDateRange);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cashflow'] });
    }
  });

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('he-IL', {
      style: 'currency',
      currency: 'ILS'
    }).format(amount);
  };

  const renderSyncCard = (
    title: string,
    icon: React.ReactNode,
    mutation: any,
    result?: SyncResult | null
  ) => (
    <div className="bg-white rounded-xl shadow-sm p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-100 rounded-lg text-blue-600">
            {icon}
          </div>
          <h3 className="text-lg font-semibold">{title}</h3>
        </div>
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-2"
        >
          {mutation.isPending ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          סנכרן
        </button>
      </div>

      {mutation.isSuccess && mutation.data && (
        <div className="mt-4 p-4 bg-green-50 rounded-lg">
          <div className="flex items-center gap-2 text-green-700 mb-2">
            <CheckCircle className="w-5 h-5" />
            <span className="font-medium">סנכרון הושלם</span>
          </div>
          <div className="text-sm text-green-600 space-y-1">
            {mutation.data.synced_documents !== undefined && (
              <p>מסמכים שסונכרנו: {mutation.data.synced_documents}</p>
            )}
            {mutation.data.synced_payments !== undefined && (
              <p>תשלומים שסונכרנו: {mutation.data.synced_payments}</p>
            )}
            {mutation.data.synced_billing_transactions !== undefined && (
              <p>עסקאות סליקה: {mutation.data.synced_billing_transactions}</p>
            )}
            {mutation.data.total_income !== undefined && (
              <p>סה"כ הכנסות: {formatCurrency(mutation.data.total_income)}</p>
            )}
            {mutation.data.total_expenses !== undefined && (
              <p>סה"כ הוצאות: {formatCurrency(mutation.data.total_expenses)}</p>
            )}
            {mutation.data.total_amount !== undefined && (
              <p>סה"כ: {formatCurrency(mutation.data.total_amount)}</p>
            )}
          </div>
        </div>
      )}

      {mutation.isError && (
        <div className="mt-4 p-4 bg-red-50 rounded-lg">
          <div className="flex items-center gap-2 text-red-700">
            <AlertCircle className="w-5 h-5" />
            <span>שגיאה בסנכרון</span>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">סנכרון נתונים מ-SUMIT</h1>
          <p className="text-gray-500 mt-1">משיכת נתונים ממערכת הנהלת החשבונות</p>
        </div>
        <div className="flex items-center gap-4">
          {vatData && (
            <div className="bg-white px-4 py-2 rounded-lg shadow-sm">
              <span className="text-sm text-gray-500">מע"מ: </span>
              <span className="font-bold text-gray-900">{vatData.vat_rate}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Date Range Selector */}
      <div className="bg-white rounded-xl shadow-sm p-6">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Calendar className="w-5 h-5 text-blue-600" />
          טווח תאריכים לסנכרון
        </h2>
        <div className="flex items-center gap-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">מתאריך</label>
            <input
              type="date"
              value={syncDateRange.from_date}
              onChange={(e) => setSyncDateRange(prev => ({ ...prev, from_date: e.target.value }))}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">עד תאריך</label>
            <input
              type="date"
              value={syncDateRange.to_date}
              onChange={(e) => setSyncDateRange(prev => ({ ...prev, to_date: e.target.value }))}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex-1" />
          <button
            onClick={() => fullSyncMutation.mutate()}
            disabled={fullSyncMutation.isPending}
            className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            {fullSyncMutation.isPending ? (
              <RefreshCw className="w-5 h-5 animate-spin" />
            ) : (
              <Database className="w-5 h-5" />
            )}
            סנכרון מלא
          </button>
        </div>

        {/* Full Sync Results */}
        {fullSyncMutation.isSuccess && fullSyncMutation.data && (
          <div className="mt-6 p-4 bg-green-50 rounded-lg">
            <h3 className="font-medium text-green-800 mb-3 flex items-center gap-2">
              <CheckCircle className="w-5 h-5" />
              סנכרון מלא הושלם
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {fullSyncMutation.data.documents && (
                <div className="bg-white p-3 rounded-lg">
                  <p className="text-sm text-gray-500">מסמכים</p>
                  <p className="text-xl font-bold">{fullSyncMutation.data.documents.synced_documents || 0}</p>
                </div>
              )}
              {fullSyncMutation.data.payments && (
                <div className="bg-white p-3 rounded-lg">
                  <p className="text-sm text-gray-500">תשלומים</p>
                  <p className="text-xl font-bold">{fullSyncMutation.data.payments.synced_payments || 0}</p>
                </div>
              )}
              {fullSyncMutation.data.billing && (
                <div className="bg-white p-3 rounded-lg">
                  <p className="text-sm text-gray-500">עסקאות סליקה</p>
                  <p className="text-xl font-bold">{fullSyncMutation.data.billing.synced_billing_transactions || 0}</p>
                </div>
              )}
              {fullSyncMutation.data.debts && (
                <div className="bg-white p-3 rounded-lg">
                  <p className="text-sm text-gray-500">חובות</p>
                  <p className="text-xl font-bold">{fullSyncMutation.data.debts.count || 0}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Sync Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {renderSyncCard(
          'מסמכים וחשבוניות',
          <FileText className="w-5 h-5" />,
          syncDocumentsMutation
        )}
        
        {renderSyncCard(
          'תשלומים',
          <DollarSign className="w-5 h-5" />,
          syncPaymentsMutation
        )}
        
        {renderSyncCard(
          'עסקאות סליקה',
          <CreditCard className="w-5 h-5" />,
          syncBillingMutation
        )}
      </div>

      {/* Additional Data Sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Debts */}
        <div className="bg-white rounded-xl shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Users className="w-5 h-5 text-orange-600" />
              דוח חובות
            </h3>
            <button
              onClick={() => refetchDebts()}
              disabled={debtsLoading}
              className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-colors flex items-center gap-2"
            >
              {debtsLoading ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              טען
            </button>
          </div>

          {debtsData && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-green-50 p-4 rounded-lg">
                  <p className="text-sm text-green-600">לגבייה</p>
                  <p className="text-2xl font-bold text-green-700">
                    {formatCurrency(debtsData.total_receivable || 0)}
                  </p>
                </div>
                <div className="bg-red-50 p-4 rounded-lg">
                  <p className="text-sm text-red-600">לתשלום</p>
                  <p className="text-2xl font-bold text-red-700">
                    {formatCurrency(debtsData.total_payable || 0)}
                  </p>
                </div>
              </div>

              {debtsData.debt_items?.length > 0 && (
                <div className="max-h-60 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-right py-2">לקוח</th>
                        <th className="text-right py-2">סכום</th>
                        <th className="text-right py-2">ימי פיגור</th>
                      </tr>
                    </thead>
                    <tbody>
                      {debtsData.debt_items.slice(0, 10).map((item: DebtItem, index: number) => (
                        <tr key={index} className="border-b">
                          <td className="py-2">{item.customer_name}</td>
                          <td className={`py-2 ${item.amount > 0 ? 'text-green-600' : 'text-red-600'}`}>
                            {formatCurrency(item.amount)}
                          </td>
                          <td className="py-2">
                            {item.days_overdue > 0 && (
                              <span className="text-red-600">{item.days_overdue} ימים</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Income Items */}
        <div className="bg-white rounded-xl shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Package className="w-5 h-5 text-purple-600" />
              פריטי הכנסה
            </h3>
            <button
              onClick={() => refetchIncomeItems()}
              disabled={incomeItemsLoading}
              className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors flex items-center gap-2"
            >
              {incomeItemsLoading ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              טען
            </button>
          </div>

          {incomeItemsData?.income_items?.length > 0 && (
            <div className="max-h-60 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-right py-2">שם</th>
                    <th className="text-right py-2">מחיר</th>
                    <th className="text-right py-2">תיאור</th>
                  </tr>
                </thead>
                <tbody>
                  {incomeItemsData.income_items.map((item: IncomeItem) => (
                    <tr key={item.id} className="border-b hover:bg-gray-50">
                      <td className="py-2 font-medium">{item.name}</td>
                      <td className="py-2">{formatCurrency(item.price)}</td>
                      <td className="py-2 text-gray-500 truncate max-w-xs">{item.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Exchange Rate */}
      <div className="bg-white rounded-xl shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <ArrowRightLeft className="w-5 h-5 text-teal-600" />
          שער חליפין
        </h3>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <select
              className="px-3 py-2 border border-gray-300 rounded-lg"
              defaultValue="USD"
              id="from-currency"
            >
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="GBP">GBP</option>
            </select>
            <span className="text-gray-500">→</span>
            <span className="px-3 py-2 bg-gray-100 rounded-lg">ILS</span>
          </div>
          <button
            onClick={() => {
              const fromSelect = document.getElementById('from-currency') as HTMLSelectElement;
              exchangeRateMutation.mutate({ from: fromSelect.value, to: 'ILS' });
            }}
            disabled={exchangeRateMutation.isPending}
            className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 transition-colors"
          >
            {exchangeRateMutation.isPending ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              'קבל שער'
            )}
          </button>
          {exchangeResult && (
            <div className="bg-teal-50 px-4 py-2 rounded-lg">
              <span className="text-teal-700">
                1 {exchangeResult.from} = <strong>{exchangeResult.rate.toFixed(4)}</strong> {exchangeResult.to}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DataSyncDashboard;
