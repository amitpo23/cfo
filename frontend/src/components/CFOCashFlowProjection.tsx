import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, AreaChart, Area,
} from 'recharts';
import { Download } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode: boolean;
}

const CFOCashFlowProjection: React.FC<Props> = ({ darkMode }) => {
  const [scenario, setScenario] = useState('base');
  const [weeks, setWeeks] = useState(12);

  const { data: projection } = useQuery({
    queryKey: ['cashflow-projection', scenario, weeks],
    queryFn: () => apiService.get(`/dashboard/cashflow?weeks=${weeks}&scenario=${scenario}`),
  });

  const { data: conservative } = useQuery({
    queryKey: ['cashflow-conservative', weeks],
    queryFn: () => apiService.get(`/dashboard/cashflow?weeks=${weeks}&scenario=conservative`),
  });

  const { data: aggressive } = useQuery({
    queryKey: ['cashflow-aggressive', weeks],
    queryFn: () => apiService.get(`/dashboard/cashflow?weeks=${weeks}&scenario=aggressive`),
  });

  const handleExport = () => {
    window.open('/api/reports/cashflow?format=csv', '_blank');
  };

  const fmt = (n: number) =>
    new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(n);

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  }`;

  const projData = (projection as Array<Record<string, number>>) || [];
  const consData = (conservative as Array<Record<string, number>>) || [];
  const aggrData = (aggressive as Array<Record<string, number>>) || [];

  // Merge scenarios for comparison chart
  const comparisonData = projData.map((item, idx) => ({
    week: item.week,
    base: item.cumulative_balance,
    conservative: consData[idx]?.cumulative_balance ?? item.cumulative_balance,
    aggressive: aggrData[idx]?.cumulative_balance ?? item.cumulative_balance,
  }));

  // Summary stats
  const totalInflows = projData.reduce((s, w) => s + (w.expected_inflows || 0), 0);
  const totalOutflows = projData.reduce((s, w) => s + (w.expected_outflows || 0), 0);
  const endBalance = projData[projData.length - 1]?.cumulative_balance ?? 0;
  const startBalance = projData[0]?.cumulative_balance ?? 0;

  return (
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Cash Flow Projection</h1>
        <div className="flex items-center gap-3">
          <select
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className={`px-3 py-2 rounded-xl border text-sm ${
              darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'
            }`}
          >
            <option value={8}>8 weeks</option>
            <option value={12}>12 weeks</option>
            <option value={26}>26 weeks</option>
          </select>
          <button
            type="button"
            onClick={handleExport}
            onKeyDown={(e) => { if (e.key === 'Enter') handleExport(); }}
            className="flex items-center gap-2 px-4 py-2 border rounded-xl hover:bg-gray-50 transition"
          >
            <Download size={18} />
            Export
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Starting Balance</p>
          <p className="text-2xl font-bold mt-1">{fmt(startBalance)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Expected Inflows</p>
          <p className="text-2xl font-bold mt-1 text-green-500">{fmt(totalInflows)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Expected Outflows</p>
          <p className="text-2xl font-bold mt-1 text-red-500">{fmt(totalOutflows)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Projected End Balance</p>
          <p className={`text-2xl font-bold mt-1 ${endBalance >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {fmt(endBalance)}
          </p>
        </div>
      </div>

      {/* Scenario Toggle */}
      <div className="flex gap-2">
        {(['conservative', 'base', 'aggressive'] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setScenario(s)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition capitalize ${
              scenario === s
                ? 'bg-blue-600 text-white'
                : darkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Main Chart */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Weekly Cash Flow ({scenario})</h2>
        <ResponsiveContainer width="100%" height={350}>
          <AreaChart data={projData}>
            <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? '#374151' : '#e5e7eb'} />
            <XAxis
              dataKey="week"
              stroke={darkMode ? '#9ca3af' : '#6b7280'}
              fontSize={12}
              tickFormatter={(v) => {
                const d = new Date(v);
                return `${d.getMonth() + 1}/${d.getDate()}`;
              }}
            />
            <YAxis stroke={darkMode ? '#9ca3af' : '#6b7280'} fontSize={12} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{
                backgroundColor: darkMode ? '#1f2937' : '#fff',
                border: `1px solid ${darkMode ? '#374151' : '#e5e7eb'}`,
                borderRadius: '8px',
              }}
              formatter={(value: number) => fmt(value)}
            />
            <Legend />
            <Area type="monotone" dataKey="expected_inflows" fill="#10b98133" stroke="#10b981" name="Inflows" />
            <Area type="monotone" dataKey="expected_outflows" fill="#ef444433" stroke="#ef4444" name="Outflows" />
            <Line type="monotone" dataKey="cumulative_balance" stroke="#3b82f6" strokeWidth={3} dot={false} name="Balance" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Scenario Comparison */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Scenario Comparison</h2>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={comparisonData}>
            <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? '#374151' : '#e5e7eb'} />
            <XAxis
              dataKey="week"
              stroke={darkMode ? '#9ca3af' : '#6b7280'}
              fontSize={12}
              tickFormatter={(v) => {
                const d = new Date(v);
                return `${d.getMonth() + 1}/${d.getDate()}`;
              }}
            />
            <YAxis stroke={darkMode ? '#9ca3af' : '#6b7280'} fontSize={12} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{
                backgroundColor: darkMode ? '#1f2937' : '#fff',
                border: `1px solid ${darkMode ? '#374151' : '#e5e7eb'}`,
                borderRadius: '8px',
              }}
              formatter={(value: number) => fmt(value)}
            />
            <Legend />
            <Line type="monotone" dataKey="conservative" stroke="#ef4444" strokeWidth={2} dot={false} strokeDasharray="5 5" />
            <Line type="monotone" dataKey="base" stroke="#3b82f6" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="aggressive" stroke="#10b981" strokeWidth={2} dot={false} strokeDasharray="5 5" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Weekly Detail Table */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Weekly Detail</h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="text-left py-3 px-2 text-sm font-medium">Week</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Inflows</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Outflows</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Net</th>
                <th className="text-right py-3 px-2 text-sm font-medium">Balance</th>
              </tr>
            </thead>
            <tbody>
              {projData.map((w) => (
                <tr key={w.week} className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                  <td className="py-2 px-2 text-sm">{new Date(w.week).toLocaleDateString()}</td>
                  <td className="py-2 px-2 text-sm text-right text-green-500">{fmt(w.expected_inflows)}</td>
                  <td className="py-2 px-2 text-sm text-right text-red-500">{fmt(w.expected_outflows)}</td>
                  <td className={`py-2 px-2 text-sm text-right font-medium ${w.net_flow >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {fmt(w.net_flow)}
                  </td>
                  <td className="py-2 px-2 text-sm text-right font-bold">{fmt(w.cumulative_balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default CFOCashFlowProjection;
