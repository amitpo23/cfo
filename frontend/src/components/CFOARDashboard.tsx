import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { FileCheck, Download } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode: boolean;
}

interface CustomerAging {
  customer_id: string;
  customer_name: string;
  current: number;
  days_31_60: number;
  days_61_90: number;
  days_91_120: number;
  over_120: number;
  total_outstanding: number;
  credit_risk: string;
  oldest_invoice_days: number;
  collection_status: string;
}

interface AgingBuckets {
  current?: number;
  days_31_60?: number;
  days_61_90?: number;
  days_91_120?: number;
  over_120?: number;
}

interface AgingResponse {
  status?: string;
  data?: {
    total_receivables?: number;
    buckets?: AgingBuckets;
    customers?: CustomerAging[];
  };
}

const CFOARDashboard: React.FC<Props> = ({ darkMode }) => {
  const [noteText, setNoteText] = useState('');
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);

  const { data: aging, isLoading } = useQuery({
    queryKey: ['ar-aging'],
    queryFn: () => apiService.get<AgingResponse>('/ar/aging'),
  });

  // API shape: { status, data: { total_receivables, buckets: {current, days_31_60,
  // days_61_90, days_91_120, over_120}, customers: [...] } }
  const d = aging?.data;
  const buckets = (d?.buckets ?? {}) as AgingBuckets;
  const num = (v: unknown) => (typeof v === 'number' ? v : 0);

  const handleExport = () => {
    window.open('/api/reports/ar_aging?format=csv', '_blank');
  };

  const handleAddNote = async (customerId: string) => {
    if (!noteText.trim()) return;
    await apiService.post('/notes', {
      entity_type: 'customer',
      entity_id: customerId,
      text: noteText,
    });
    setNoteText('');
    setSelectedCustomerId(null);
  };

  const handleCreateTask = async (customerId: string, customerName: string) => {
    await apiService.post('/tasks', {
      title: `Follow up on receivable — ${customerName}`,
      entity_type: 'customer',
      entity_id: customerId,
    });
  };

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

  const bucket0_30 = num(buckets.current);
  const bucket31_60 = num(buckets.days_31_60);
  const bucket61_90 = num(buckets.days_61_90);
  const bucket90_plus = num(buckets.days_91_120) + num(buckets.over_120);
  const totalReceivables = num(d?.total_receivables);
  const customers = (d?.customers ?? []) as CustomerAging[];

  const bucketChart = [
    { name: '0-30', amount: bucket0_30 },
    { name: '31-60', amount: bucket31_60 },
    { name: '61-90', amount: bucket61_90 },
    { name: '90+', amount: bucket90_plus },
  ];

  return (
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Accounts Receivable</h1>
        <button
          type="button"
          onClick={handleExport}
          onKeyDown={(e) => { if (e.key === 'Enter') handleExport(); }}
          className="flex items-center gap-2 px-4 py-2 border rounded-xl hover:bg-gray-50 transition"
        >
          <Download size={18} />
          Export CSV
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Total Outstanding</p>
          <p className="text-2xl font-bold mt-1">{fmt(totalReceivables)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Current (0-30)</p>
          <p className="text-2xl font-bold mt-1 text-green-500">{fmt(bucket0_30)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Overdue (31-90)</p>
          <p className="text-2xl font-bold mt-1 text-yellow-500">
            {fmt(bucket31_60 + bucket61_90)}
          </p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Severely Overdue (90+)</p>
          <p className="text-2xl font-bold mt-1 text-red-500">{fmt(bucket90_plus)}</p>
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
            <Bar dataKey="amount" fill="#3b82f6" radius={[8, 8, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Customer Table */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Outstanding by Customer ({customers.length})</h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="text-left py-3 px-2 text-sm font-medium">Customer</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Outstanding</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Current (0-30)</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Overdue</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Oldest (days)</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Risk</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Collection</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => {
                const overdue = num(c.total_outstanding) - num(c.current);
                return (
                  <React.Fragment key={c.customer_id}>
                    <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'} hover:${darkMode ? 'bg-gray-700' : 'bg-gray-50'}`}>
                      <td className="py-3 px-2 text-sm">{c.customer_name || c.customer_id}</td>
                      <td className="py-3 px-2 text-sm text-right font-semibold">{fmt(num(c.total_outstanding))}</td>
                      <td className="py-3 px-2 text-sm text-right">{fmt(num(c.current))}</td>
                      <td className="py-3 px-2 text-sm text-right">{fmt(overdue)}</td>
                      <td className="py-3 px-2 text-sm text-right">
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                          num(c.oldest_invoice_days) > 60
                            ? 'bg-red-100 text-red-700'
                            : num(c.oldest_invoice_days) > 30
                              ? 'bg-yellow-100 text-yellow-700'
                              : 'bg-green-100 text-green-700'
                        }`}>
                          {num(c.oldest_invoice_days)} days
                        </span>
                      </td>
                      <td className="py-3 px-2 text-sm capitalize">{c.credit_risk}</td>
                      <td className="py-3 px-2 text-sm capitalize">{c.collection_status}</td>
                      <td className="py-3 px-2 text-sm">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => setSelectedCustomerId(
                              selectedCustomerId === c.customer_id ? null : c.customer_id
                            )}
                            className="text-blue-500 hover:text-blue-600 text-xs"
                          >
                            Note
                          </button>
                          <button
                            type="button"
                            onClick={() => handleCreateTask(c.customer_id, c.customer_name || c.customer_id)}
                            className="text-green-500 hover:text-green-600 text-xs"
                          >
                            Task
                          </button>
                        </div>
                      </td>
                    </tr>
                    {selectedCustomerId === c.customer_id && (
                      <tr>
                        <td colSpan={8} className="py-2 px-4">
                          <div className="flex gap-2">
                            <input
                              type="text"
                              value={noteText}
                              onChange={(e) => setNoteText(e.target.value)}
                              placeholder="Add a note..."
                              className={`flex-1 px-3 py-2 rounded-lg border text-sm ${
                                darkMode ? 'bg-gray-700 border-gray-600' : 'border-gray-300'
                              }`}
                            />
                            <button
                              type="button"
                              onClick={() => handleAddNote(c.customer_id)}
                              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm"
                            >
                              Save
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          {customers.length === 0 && (
            <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <FileCheck size={48} className="mx-auto mb-3 opacity-50" />
              <p>No outstanding receivables</p>
              <p className="text-sm mt-1">Sync data to see AR aging</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CFOARDashboard;
