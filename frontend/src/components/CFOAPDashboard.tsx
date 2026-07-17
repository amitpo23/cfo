import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { FileCheck } from 'lucide-react';
import apiService from '../services/api';
import ExportButtons from './ExportButtons';

interface Props {
  darkMode: boolean;
}

interface ApBuckets {
  current?: number;
  '1_30'?: number;
  '31_60'?: number;
  '61_90'?: number;
  '90_plus'?: number;
}

interface ApItem {
  due_date: string | null;
  overdue_days: number;
  balance: number;
  bucket: string;
}

interface ApAgingResponse {
  as_of?: string;
  buckets?: ApBuckets;
  total?: number;
  items?: ApItem[];
  derived?: boolean;
  disclaimer?: string;
}

// Mirrors the AR dashboard, but bound to the real /daily-reports/ap-aging shape:
// { as_of, buckets:{current,1_30,31_60,61_90,90_plus}, total, items:[...], derived, disclaimer }
const CFOAPDashboard: React.FC<Props> = ({ darkMode }) => {
  const { data, isLoading } = useQuery({
    queryKey: ['ap-aging'],
    queryFn: () => apiService.get<ApAgingResponse>('/daily-reports/ap-aging'),
  });

  const num = (v: unknown) => (typeof v === 'number' ? v : 0);
  const buckets = (data?.buckets ?? {}) as ApBuckets;
  const items = (data?.items ?? []) as ApItem[];

  const notDue = num(buckets.current);
  const b1_30 = num(buckets['1_30']);
  const b31_60 = num(buckets['31_60']);
  const b61_90 = num(buckets['61_90']);
  const b90_plus = num(buckets['90_plus']);
  const total = num(data?.total);

  const fmt = (n: number) =>
    new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(n);

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  }`;

  if (isLoading) {
    return (
      <div className={`p-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
        <div className="animate-pulse h-8 bg-gray-300 rounded w-1/3" />
      </div>
    );
  }

  const bucketChart = [
    { name: 'Not due', amount: notDue },
    { name: '1-30', amount: b1_30 },
    { name: '31-60', amount: b31_60 },
    { name: '61-90', amount: b61_90 },
    { name: '90+', amount: b90_plus },
  ];

  return (
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">AP / ספקים — גיול חובות לתשלום</h1>
        <ExportButtons
          title="גיול ספקים לתשלום"
          meta={data?.as_of ? `נכון לתאריך: ${data.as_of}` : undefined}
          columns={[
            { key: 'due_date', label: 'תאריך לפרעון' },
            { key: 'balance', label: 'יתרה' },
            { key: 'overdue_days', label: 'ימי איחור' },
            { key: 'bucket', label: 'קבוצה' },
          ]}
          rows={items.map((it) => ({
            due_date: it.due_date ?? '',
            balance: num(it.balance),
            overdue_days: num(it.overdue_days),
            bucket: it.bucket,
          }))}
          summary={[{ label: 'סה"כ לתשלום', value: fmt(total) }]}
        />
      </div>
      {data?.disclaimer && (
        <p className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>{data.disclaimer}</p>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Total Payable</p>
          <p className="text-2xl font-bold mt-1">{fmt(total)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Not Due</p>
          <p className="text-2xl font-bold mt-1 text-green-500">{fmt(notDue)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Overdue (1-90)</p>
          <p className="text-2xl font-bold mt-1 text-yellow-500">{fmt(b1_30 + b31_60 + b61_90)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Severely Overdue (90+)</p>
          <p className="text-2xl font-bold mt-1 text-red-500">{fmt(b90_plus)}</p>
        </div>
      </div>

      {/* Aging Chart */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Aging Buckets</h2>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={bucketChart}>
            <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? '#374151' : '#e5e7eb'} />
            <XAxis dataKey="name" stroke={darkMode ? '#9ca3af' : '#6b7280'} />
            <YAxis stroke={darkMode ? '#9ca3af' : '#6b7280'} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip formatter={(value: number) => fmt(value)} />
            <Bar dataKey="amount" fill="#f59e0b" radius={[8, 8, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Bills Table */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Open Payables ({items.length})</h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="text-left py-3 px-2 text-sm font-medium">Due Date</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Balance</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Days Overdue</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Bucket</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => (
                <tr key={`${it.due_date ?? 'na'}-${idx}`} className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                  <td className="py-3 px-2 text-sm">{it.due_date ?? 'N/A'}</td>
                  <td className="py-3 px-2 text-sm text-right font-semibold">{fmt(num(it.balance))}</td>
                  <td className="py-3 px-2 text-sm text-right">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      num(it.overdue_days) > 60
                        ? 'bg-red-100 text-red-700'
                        : num(it.overdue_days) > 30
                          ? 'bg-yellow-100 text-yellow-700'
                          : 'bg-green-100 text-green-700'
                    }`}>
                      {num(it.overdue_days)} days
                    </span>
                  </td>
                  <td className="py-3 px-2 text-sm">{it.bucket}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <FileCheck size={48} className="mx-auto mb-3 opacity-50" />
              <p>No open payables</p>
              <p className="text-sm mt-1">Sync data to see AP aging</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CFOAPDashboard;
