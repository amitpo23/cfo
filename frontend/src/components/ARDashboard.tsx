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
  Legend,
} from 'recharts';
import api from '../services/api';

interface AgingBucket {
  bucket: string;
  amount: number;
  count: number;
  percentage: number;
}

interface CustomerAging {
  customer_id: string;
  customer_name: string;
  current: number;
  days_31_60: number;
  days_61_90: number;
  days_91_120: number;
  over_120: number;
  total: number;
}

interface PaymentReminder {
  customer_id: string;
  customer_name: string;
  invoice_id: string;
  amount: number;
  days_overdue: number;
  reminder_type: string;
  message: string;
}

const AGING_COLORS = ['#10B981', '#3B82F6', '#F59E0B', '#EF4444', '#7C3AED'];

export const ARDashboard: React.FC = () => {
  const [selectedCustomer, setSelectedCustomer] = useState<string | null>(null);

  // Fetch aging report
  const { data: agingData, isLoading: loadingAging } = useQuery({
    queryKey: ['ar-aging'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ar/aging');
      return response.data.data;
    },
  });

  // Fetch payment reminders
  const { data: reminders, isLoading: loadingReminders } = useQuery({
    queryKey: ['payment-reminders'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ar/payment-reminders');
      return response.data.data as PaymentReminder[];
    },
  });

  // Fetch collection forecast
  const { data: forecast, isLoading: loadingForecast } = useQuery({
    queryKey: ['collection-forecast'],
    queryFn: async () => {
      const response = await api.get('/api/financial/ar/collection-forecast');
      return response.data.data;
    },
  });

  const formatCurrency = (value: number) => `₪${value.toLocaleString()}`;

  const getBucketColor = (bucket: string) => {
    const colors: Record<string, string> = {
      'current': 'bg-green-100 text-green-800',
      '31-60': 'bg-blue-100 text-blue-800',
      '61-90': 'bg-yellow-100 text-yellow-800',
      '91-120': 'bg-orange-100 text-orange-800',
      '120+': 'bg-red-100 text-red-800',
    };
    return colors[bucket] || 'bg-gray-100 text-gray-800';
  };

  const getReminderTypeIcon = (type: string) => {
    switch (type) {
      case 'first': return '📧';
      case 'second': return '⚠️';
      case 'final': return '🔴';
      default: return '📝';
    }
  };

  if (loadingAging || loadingReminders) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  const bucketData = agingData?.buckets ? Object.entries(agingData.buckets).map(([bucket, data]: [string, any]) => ({
    name: bucket === 'current' ? 'שוטף' :
          bucket === '31-60' ? '31-60 יום' :
          bucket === '61-90' ? '61-90 יום' :
          bucket === '91-120' ? '91-120 יום' : 'מעל 120',
    bucket,
    ...data,
  })) : [];

  const overdue = agingData?.total_receivables - (agingData?.buckets?.current?.amount || 0);
  const overduePercentage = agingData?.total_receivables ? (overdue / agingData.total_receivables * 100) : 0;

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">ניהול חייבים</h1>
          <p className="text-gray-600 mt-1">גיול חובות וגבייה</p>
        </div>
        <div className="flex gap-4">
          <button className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
            שלח תזכורות
          </button>
          <button className="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700">
            ייצא דוח
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">סה"כ חייבים</h3>
          <p className="text-2xl font-bold text-gray-900 mt-2">
            {formatCurrency(agingData?.total_receivables || 0)}
          </p>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">שוטף (עד 30 יום)</h3>
          <p className="text-2xl font-bold text-green-600 mt-2">
            {formatCurrency(agingData?.buckets?.current?.amount || 0)}
          </p>
        </div>
        <div className="bg-red-50 rounded-xl shadow-sm p-6 border border-red-200">
          <h3 className="text-sm font-medium text-gray-500">חוב באיחור</h3>
          <p className="text-2xl font-bold text-red-600 mt-2">
            {formatCurrency(overdue)}
          </p>
          <p className="text-sm text-red-500">{overduePercentage.toFixed(1)}% מסה"כ</p>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">תזכורות ממתינות</h3>
          <p className="text-2xl font-bold text-orange-600 mt-2">
            {reminders?.length || 0}
          </p>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Aging Breakdown Chart */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">גיול חובות</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={bucketData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} />
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Bar dataKey="amount" fill="#3B82F6">
                {bucketData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={AGING_COLORS[index % AGING_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Aging Distribution Pie */}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">התפלגות גיול</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={bucketData}
                dataKey="amount"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={100}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
              >
                {bucketData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={AGING_COLORS[index % AGING_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Aging Summary by Bucket */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 mb-4">סיכום גיול לפי תקופה</h2>
        <div className="grid grid-cols-5 gap-4">
          {bucketData.map((bucket, index) => (
            <div
              key={bucket.bucket}
              className={`p-4 rounded-lg border ${getBucketColor(bucket.bucket)}`}
            >
              <h4 className="font-semibold text-sm">{bucket.name}</h4>
              <p className="text-2xl font-bold mt-2">{formatCurrency(bucket.amount)}</p>
              <p className="text-sm opacity-70">{bucket.count} חשבוניות</p>
              <p className="text-sm opacity-70">{bucket.percentage?.toFixed(1)}%</p>
            </div>
          ))}
        </div>
      </div>

      {/* Customers Aging Table */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 mb-4">גיול לפי לקוח</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">לקוח</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">שוטף</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">31-60</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">61-90</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">91-120</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">120+</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">סה"כ</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">פעולות</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {agingData?.customers?.map((customer: CustomerAging) => (
                <tr key={customer.customer_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900">
                    {customer.customer_name}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-green-600">
                    {formatCurrency(customer.current)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-blue-600">
                    {formatCurrency(customer.days_31_60)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-yellow-600">
                    {formatCurrency(customer.days_61_90)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-orange-600">
                    {formatCurrency(customer.days_91_120)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-red-600">
                    {formatCurrency(customer.over_120)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm font-bold text-gray-900">
                    {formatCurrency(customer.total)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                    <button 
                      onClick={() => setSelectedCustomer(customer.customer_id)}
                      className="text-blue-600 hover:text-blue-800"
                    >
                      פרטים
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Payment Reminders */}
      {reminders && reminders.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">תזכורות תשלום</h2>
          <div className="space-y-3">
            {reminders.slice(0, 10).map((reminder, index) => (
              <div
                key={index}
                className="p-4 rounded-lg border border-gray-200 hover:border-blue-300 transition-colors"
              >
                <div className="flex justify-between items-start">
                  <div className="flex items-start gap-3">
                    <span className="text-2xl">{getReminderTypeIcon(reminder.reminder_type)}</span>
                    <div>
                      <h4 className="font-semibold text-gray-900">{reminder.customer_name}</h4>
                      <p className="text-sm text-gray-500">חשבונית: {reminder.invoice_id}</p>
                      <p className="text-sm text-red-600">{reminder.days_overdue} ימים באיחור</p>
                    </div>
                  </div>
                  <div className="text-left">
                    <p className="text-lg font-bold text-gray-900">{formatCurrency(reminder.amount)}</p>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      reminder.reminder_type === 'final' ? 'bg-red-100 text-red-800' :
                      reminder.reminder_type === 'second' ? 'bg-yellow-100 text-yellow-800' :
                      'bg-blue-100 text-blue-800'
                    }`}>
                      {reminder.reminder_type === 'final' ? 'אחרון' :
                       reminder.reminder_type === 'second' ? 'שני' : 'ראשון'}
                    </span>
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button className="text-sm bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700">
                    שלח תזכורת
                  </button>
                  <button className="text-sm bg-gray-200 text-gray-700 px-3 py-1 rounded hover:bg-gray-300">
                    התקשר
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Collection Forecast */}
      {forecast && (
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">תחזית גבייה</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 bg-green-50 rounded-lg">
              <h4 className="text-sm text-gray-500">צפי 30 יום</h4>
              <p className="text-2xl font-bold text-green-700">
                {formatCurrency(forecast.expected_30_days || 0)}
              </p>
            </div>
            <div className="p-4 bg-blue-50 rounded-lg">
              <h4 className="text-sm text-gray-500">צפי 60 יום</h4>
              <p className="text-2xl font-bold text-blue-700">
                {formatCurrency(forecast.expected_60_days || 0)}
              </p>
            </div>
            <div className="p-4 bg-purple-50 rounded-lg">
              <h4 className="text-sm text-gray-500">צפי 90 יום</h4>
              <p className="text-2xl font-bold text-purple-700">
                {formatCurrency(forecast.expected_90_days || 0)}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ARDashboard;
