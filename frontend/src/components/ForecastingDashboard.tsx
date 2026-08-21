import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AlertCircle, Calendar, Database, RefreshCw } from 'lucide-react';
import api from '../services/api';

interface ForecastComponent {
  source: string;
  label: string;
  direction: 'inflow' | 'outflow';
  amount: number;
  count: number;
}

interface ForecastMonth {
  month: string;
  inflow_total: number;
  outflow_total: number;
  net_flow: number;
  components: ForecastComponent[];
}

interface HistoricalBankContext {
  available: boolean;
  window_days?: number;
  inflow?: number;
  outflow?: number;
  net?: number;
  count?: number;
  label?: string;
}

interface LiveForecastResponse {
  as_of: string;
  data_sources: string[];
  months: ForecastMonth[];
  historical_context: HistoricalBankContext;
  message: string | null;
}

// תיוג עברי למקורות הנתונים — מוצג כתגית "נכון לתאריך + מקורות" מעל התחזית,
// כך שרואים בדיוק על אילו ספרים חיים התחזית מבוססת (לא ML, לא ניחוש).
const SOURCE_LABELS: Record<string, string> = {
  invoices_open_ar: 'חשבוניות פתוחות (לקוחות)',
  invoices_overdue_ar: 'חשבוניות באיחור פירעון',
  bills_open_ap: 'חשבונות ספק פתוחים',
  bills_overdue_ap: 'חשבונות ספק באיחור פירעון',
  expenses_recurring_avg: 'הוצאות חוזרות (ממוצע היסטורי)',
  bank_transactions_actual: 'תזרים בנק בפועל (היסטורי)',
};

const ForecastingDashboard: React.FC = () => {
  const [forecastPeriods, setForecastPeriods] = useState(6);

  const { data: forecast, isLoading } = useQuery<LiveForecastResponse>({
    queryKey: ['live-monthly-forecast', forecastPeriods],
    queryFn: () => api.get<LiveForecastResponse>(`/cashflow/forecast/live-monthly?periods=${forecastPeriods}`),
  });

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('he-IL', {
      style: 'currency',
      currency: 'ILS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const months = forecast?.months || [];
  const totalInflow = months.reduce((s, m) => s + m.inflow_total, 0);
  const totalOutflow = months.reduce((s, m) => s + m.outflow_total, 0);

  return (
    <div className="container mx-auto px-4 py-8" dir="rtl">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-800">תחזיות פיננסיות</h1>
          <p className="text-gray-600 mt-1">
            תחזית תזרים חודשית מבוססת ספרים חיים — חשבוניות/חשבונות-ספק פתוחים והוצאות חוזרות
          </p>
        </div>
        <select
          value={forecastPeriods}
          onChange={(e) => setForecastPeriods(Number(e.target.value))}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
        >
          <option value={3}>3 חודשים</option>
          <option value={6}>6 חודשים</option>
          <option value={12}>12 חודשים</option>
          <option value={18}>18 חודשים</option>
        </select>
      </div>

      {/* נכון לתאריך + מקורות נתונים */}
      {forecast && (
        <div className="flex flex-wrap items-center gap-3 mb-6 text-sm">
          <span className="flex items-center gap-1 text-gray-600">
            <Calendar size={16} />
            נכון לתאריך {forecast.as_of}
          </span>
          {forecast.data_sources.map((src) => (
            <span
              key={src}
              className="flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full"
            >
              <Database size={14} />
              {SOURCE_LABELS[src] || src}
            </span>
          ))}
        </div>
      )}

      {isLoading ? (
        <div className="h-80 flex items-center justify-center bg-white rounded-xl shadow-sm border border-gray-100">
          <RefreshCw className="animate-spin text-gray-400" size={32} />
        </div>
      ) : !forecast || forecast.months.length === 0 ? (
        <div className="space-y-6">
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-12 flex flex-col items-center justify-center text-gray-500">
            <AlertCircle size={48} className="mb-4" />
            <p className="text-lg font-medium text-gray-700">
              {forecast?.message || 'אין נתונים לתחזית'}
            </p>
            {forecast?.as_of && <p className="text-sm mt-2">נכון לתאריך {forecast.as_of}</p>}
          </div>
          {/* גם בלי תחזית-קדימה אחראית, היסטוריית בנק אמיתית לא מוסתרת */}
          {forecast?.historical_context?.available && (
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
              <h3 className="text-lg font-semibold text-gray-800 mb-1">
                {forecast.historical_context.label || 'תזרים בנק בפועל'}
              </h3>
              <p className="text-xs text-gray-400 mb-4">היסטוריה בפועל — לא תחזית קדימה</p>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-sm text-gray-500">נכנס בפועל</p>
                  <p className="text-xl font-bold text-green-600">
                    {formatCurrency(forecast.historical_context.inflow || 0)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">יוצא בפועל</p>
                  <p className="text-xl font-bold text-red-600">
                    {formatCurrency(forecast.historical_context.outflow || 0)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">נטו</p>
                  <p className="text-xl font-bold text-blue-600">
                    {formatCurrency(forecast.historical_context.net || 0)}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <>
          {/* כרטיסי סיכום — צברים גלויים, לא ML */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
              <p className="text-sm text-gray-500 mb-2">סה"כ תזרים נכנס צפוי</p>
              <p className="text-2xl font-bold text-green-600">{formatCurrency(totalInflow)}</p>
              <p className="text-xs text-gray-400 mt-1">מקור: חשבוניות פתוחות (כולל באיחור) לפי תאריך פירעון</p>
            </div>
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
              <p className="text-sm text-gray-500 mb-2">סה"כ תזרים יוצא צפוי</p>
              <p className="text-2xl font-bold text-red-600">{formatCurrency(totalOutflow)}</p>
              <p className="text-xs text-gray-400 mt-1">מקור: חשבונות ספק פתוחים (כולל באיחור) + הוצאות חוזרות</p>
            </div>
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
              <p className="text-sm text-gray-500 mb-2">תזרים נקי צפוי</p>
              <p className={`text-2xl font-bold ${totalInflow - totalOutflow >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {formatCurrency(totalInflow - totalOutflow)}
              </p>
              <p className="text-xs text-gray-400 mt-1">{months.length} חודשים</p>
            </div>
          </div>

          {/* גרף חודשי */}
          <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 mb-8">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">תזרים חודשי — פירוק גלוי</h3>
            <ResponsiveContainer width="100%" height={350}>
              <ComposedChart data={months}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value: number) => formatCurrency(value)} />
                <Legend />
                <Bar dataKey="inflow_total" fill="#10B981" name="תזרים נכנס (AR)" />
                <Bar dataKey="outflow_total" fill="#EF4444" name="תזרים יוצא (AP + הוצאות חוזרות)" />
                <Line type="monotone" dataKey="net_flow" stroke="#3B82F6" strokeWidth={3} name="נטו" dot={{ fill: '#3B82F6', r: 4 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* טבלת פירוט — כל חודש עם שורת מקור לכל רכיב */}
          <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">פירוט תחזית לפי מקור</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-right py-3 px-4 font-medium text-gray-600">חודש</th>
                    {SOURCE_LABELS.invoices_open_ar && (
                      <th className="text-right py-3 px-4 font-medium text-gray-600">
                        {SOURCE_LABELS.invoices_open_ar}
                      </th>
                    )}
                    <th className="text-right py-3 px-4 font-medium text-gray-600">
                      {SOURCE_LABELS.bills_open_ap}
                    </th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">
                      {SOURCE_LABELS.expenses_recurring_avg}
                    </th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">נטו</th>
                  </tr>
                </thead>
                <tbody>
                  {months.map((row) => {
                    const bySource = Object.fromEntries(row.components.map((c) => [c.source, c]));
                    const arAmount = (bySource.invoices_open_ar?.amount || 0) + (bySource.invoices_overdue_ar?.amount || 0);
                    const arCount = (bySource.invoices_open_ar?.count || 0) + (bySource.invoices_overdue_ar?.count || 0);
                    const apAmount = (bySource.bills_open_ap?.amount || 0) + (bySource.bills_overdue_ap?.amount || 0);
                    const apCount = (bySource.bills_open_ap?.count || 0) + (bySource.bills_overdue_ap?.count || 0);
                    const overdueNote = (bySource.invoices_overdue_ar?.count || 0) + (bySource.bills_overdue_ap?.count || 0) > 0
                      ? ' (כולל באיחור)'
                      : '';
                    return (
                      <tr key={row.month} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="py-3 px-4 font-medium">
                          {row.month}
                          {overdueNote && <span className="text-xs text-amber-600 mr-1">{overdueNote}</span>}
                        </td>
                        <td className="py-3 px-4 text-green-600">
                          {formatCurrency(arAmount)}
                          <span className="text-xs text-gray-400 mr-1">({arCount} מסמכים)</span>
                        </td>
                        <td className="py-3 px-4 text-red-600">
                          {formatCurrency(apAmount)}
                          <span className="text-xs text-gray-400 mr-1">({apCount} מסמכים)</span>
                        </td>
                        <td className="py-3 px-4 text-red-600">
                          {formatCurrency(bySource.expenses_recurring_avg?.amount || 0)}
                        </td>
                        <td className={`py-3 px-4 font-medium ${row.net_flow >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          {formatCurrency(row.net_flow)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* היסטוריית בנק בפועל — להשוואה, לא מוזרמת לתוך התחזית עצמה */}
          {forecast?.historical_context?.available && (
            <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100 mt-8">
              <h3 className="text-lg font-semibold text-gray-800 mb-1">
                {forecast.historical_context.label || 'תזרים בנק בפועל'}
              </h3>
              <p className="text-xs text-gray-400 mb-4">היסטוריה בפועל — לא תחזית קדימה, להשוואה בלבד</p>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-sm text-gray-500">נכנס בפועל</p>
                  <p className="text-xl font-bold text-green-600">
                    {formatCurrency(forecast.historical_context.inflow || 0)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">יוצא בפועל</p>
                  <p className="text-xl font-bold text-red-600">
                    {formatCurrency(forecast.historical_context.outflow || 0)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">נטו</p>
                  <p className="text-xl font-bold text-blue-600">
                    {formatCurrency(forecast.historical_context.net || 0)}
                  </p>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default ForecastingDashboard;
