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

interface Invoice {
  id: number;
  invoice_number: string;
  customer: string;
  amount: number;
  balance: number;
  due_date: string;
  days_overdue: number;
  status: string;
}

const CFOARDashboard: React.FC<Props> = ({ darkMode }) => {
  const [noteText, setNoteText] = useState('');
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(null);

  const { data: aging, isLoading } = useQuery({
    queryKey: ['ar-aging'],
    queryFn: () => apiService.get('/ar/aging'),
  });

  const agingData = aging as Record<string, unknown> | undefined;

  const handleExport = () => {
    window.open('/api/reports/ar_aging?format=csv', '_blank');
  };

  const handleAddNote = async (invoiceId: number) => {
    if (!noteText.trim()) return;
    await apiService.post('/notes', {
      entity_type: 'invoice',
      entity_id: invoiceId,
      text: noteText,
    });
    setNoteText('');
    setSelectedInvoiceId(null);
  };

  const handleCreateTask = async (invoiceId: number, invoiceNumber: string) => {
    await apiService.post('/tasks', {
      title: `Follow up on invoice #${invoiceNumber}`,
      entity_type: 'invoice',
      entity_id: invoiceId,
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

  const bucketChart = [
    { name: '0-30', amount: (agingData?.bucket_0_30 as number) || 0 },
    { name: '31-60', amount: (agingData?.bucket_31_60 as number) || 0 },
    { name: '61-90', amount: (agingData?.bucket_61_90 as number) || 0 },
    { name: '90+', amount: (agingData?.bucket_90_plus as number) || 0 },
  ];

  const invoices = (agingData?.invoices as Array<Invoice>) || [];

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
          <p className="text-2xl font-bold mt-1">{fmt((agingData?.total as number) || 0)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Current (0-30)</p>
          <p className="text-2xl font-bold mt-1 text-green-500">{fmt((agingData?.bucket_0_30 as number) || 0)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Overdue (31-90)</p>
          <p className="text-2xl font-bold mt-1 text-yellow-500">
            {fmt(((agingData?.bucket_31_60 as number) || 0) + ((agingData?.bucket_61_90 as number) || 0))}
          </p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Severely Overdue (90+)</p>
          <p className="text-2xl font-bold mt-1 text-red-500">{fmt((agingData?.bucket_90_plus as number) || 0)}</p>
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

      {/* Invoice Table */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Open Invoices ({(agingData?.count as number) || 0})</h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="text-left py-3 px-2 text-sm font-medium">Invoice</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Customer</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Amount</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Balance</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Due Date</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Days Overdue</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Status</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <React.Fragment key={inv.id}>
                  <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'} hover:${darkMode ? 'bg-gray-700' : 'bg-gray-50'}`}>
                    <td className="py-3 px-2 text-sm">#{inv.invoice_number || inv.id}</td>
                    <td className="py-3 px-2 text-sm">{inv.customer || 'N/A'}</td>
                    <td className="py-3 px-2 text-sm text-right">{fmt(inv.amount)}</td>
                    <td className="py-3 px-2 text-sm text-right font-semibold">{fmt(inv.balance)}</td>
                    <td className="py-3 px-2 text-sm">{inv.due_date}</td>
                    <td className="py-3 px-2 text-sm text-right">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        inv.days_overdue > 60
                          ? 'bg-red-100 text-red-700'
                          : inv.days_overdue > 30
                            ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-green-100 text-green-700'
                      }`}>
                        {inv.days_overdue} days
                      </span>
                    </td>
                    <td className="py-3 px-2 text-sm capitalize">{inv.status}</td>
                    <td className="py-3 px-2 text-sm">
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => setSelectedInvoiceId(
                            selectedInvoiceId === inv.id ? null : inv.id
                          )}
                          className="text-blue-500 hover:text-blue-600 text-xs"
                        >
                          Note
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCreateTask(inv.id, inv.invoice_number || String(inv.id))}
                          className="text-green-500 hover:text-green-600 text-xs"
                        >
                          Task
                        </button>
                      </div>
                    </td>
                  </tr>
                  {selectedInvoiceId === inv.id && (
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
                            onClick={() => handleAddNote(inv.id)}
                            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm"
                          >
                            Save
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
          {invoices.length === 0 && (
            <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <FileCheck size={48} className="mx-auto mb-3 opacity-50" />
              <p>No outstanding invoices</p>
              <p className="text-sm mt-1">Sync data to see AR aging</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CFOARDashboard;
