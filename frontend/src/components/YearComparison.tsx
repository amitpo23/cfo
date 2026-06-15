import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { CalendarRange, ArrowUp, ArrowDown } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

const fmt = (v: number) => `₪${Math.round(v || 0).toLocaleString()}`;

const METRIC_LABELS: Record<string, string> = {
  revenue: 'הכנסות',
  expenses: 'הוצאות',
  gross_profit: 'רווח גולמי',
  operating_income: 'רווח תפעולי',
  net_income: 'רווח נקי',
};

const YearComparison: React.FC<Props> = ({ darkMode }) => {
  const [year, setYear] = useState(new Date().getFullYear());
  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';

  const { data, isLoading } = useQuery({
    queryKey: ['year-comparison', year],
    queryFn: async () => {
      const res: any = await apiService.getYearComparison(year);
      return res.data;
    },
  });

  const chartData = (data?.monthly || []).map((m: any) => ({
    name: m.month_name,
    [`הכנסות ${data.current_year}`]: m.current_revenue,
    [`הכנסות ${data.previous_year}`]: m.previous_revenue,
  }));

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <CalendarRange className="w-8 h-8 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold">השוואה לשנה קודמת</h1>
            <p className="text-sm text-gray-500">נתוני השנה מול אותה תקופה אשתקד</p>
          </div>
        </div>
        <input type="number" value={year} onChange={(e) => setYear(parseInt(e.target.value) || year)}
          className={`px-3 py-2 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`} />
      </div>

      {isLoading || !data ? (
        <div className="text-center py-12 text-gray-500">טוען...</div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {Object.entries(data.metrics).map(([key, m]: [string, any]) => {
              const up = m.change >= 0;
              const goodUp = key !== 'expenses';
              const positive = up === goodUp;
              return (
                <div key={key} className={`rounded-xl border p-4 ${card}`}>
                  <div className="text-sm text-gray-500">{METRIC_LABELS[key] || key}</div>
                  <div className="text-xl font-bold">{fmt(m.current)}</div>
                  <div className="text-xs text-gray-400">אשתקד: {fmt(m.previous)}</div>
                  <div className={`text-sm flex items-center gap-1 mt-1 ${positive ? 'text-green-600' : 'text-red-600'}`}>
                    {up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                    {Math.abs(m.change_pct).toFixed(1)}%
                  </div>
                </div>
              );
            })}
          </div>

          <div className={`rounded-xl border p-5 ${card}`}>
            <h2 className="font-semibold mb-4">הכנסות חודשיות: {data.current_year} מול {data.previous_year}</h2>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey={`הכנסות ${data.current_year}`} fill="#2563eb" />
                <Bar dataKey={`הכנסות ${data.previous_year}`} fill="#93c5fd" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
};

export default YearComparison;
