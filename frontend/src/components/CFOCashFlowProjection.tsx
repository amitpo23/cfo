import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ComposedChart, Bar, Line,
} from 'recharts';
import apiService from '../services/api';
import CreditLinesPanel, { type CreditLines } from './CreditLinesPanel';
import { PartialDataBanner } from './dashboardUi';
import { formatReportMoney } from './dailyReportsMoney';

interface Props {
  darkMode: boolean;
}

interface ForecastItem {
  date?: string | null;
  label?: string | null;
  amount: number;
}

interface ForecastWeek {
  start: string;
  end: string;
  in: number | null;
  out: number | null;
  net: number | null;
  closing: number | null;
  limit: number | null;
  headroom: number | null;
  unknown?: string[];
  items?: ForecastItem[];
}

interface WeeklyResponse {
  snapshot?: {
    balance: number | null;
    as_of?: string | null;
    credit_lines?: CreditLines | null;
    partial_banner?: { text_he?: string | null } | null;
  } | null;
  forecast?: {
    status?: string;
    opening?: { amount: number | null; as_of?: string | null } | null;
    weeks?: ForecastWeek[];
    missing?: string[];
  } | null;
}

const MISSING_LABELS: Record<string, string> = {
  opening_balance: 'יתרת פתיחה',
  facility_limit: 'מסגרת',
  run_rate: 'קצב תפעולי',
  forecast_rules: 'חלק מהכללים (שכר/ספקים/מע״מ/הכנסה)',
};

/** A side with nothing on it is missing, not 0. */
const flow = (value: number | null | undefined): number | null => (value ? Math.abs(value) : null);

const sumKnown = (values: Array<number | null>): number | null =>
  values.every((value) => value == null) ? null : values.reduce<number>((sum, value) => sum + (value ?? 0), 0);

const CFOCashFlowProjection: React.FC<Props> = ({ darkMode }) => {
  const { data, isLoading, isError } = useQuery<WeeklyResponse>({
    queryKey: ['cashflow-weekly'],
    queryFn: () => apiService.get('/cashflow/weekly'),
  });

  const weeks = data?.forecast?.weeks ?? [];
  const first30 = weeks.slice(0, 5);
  const inflow30 = sumKnown(first30.map((week) => flow(week.in)));
  const outflow30 = sumKnown(first30.map((week) => flow(week.out)));
  const incomplete30 = first30.some((week) => (week.unknown ?? []).length > 0);
  const opening = data?.forecast?.opening?.amount ?? null;
  // Today's opening is unknown when the bank balance is stale. The last booked
  // balance is shown with its date instead, never as today's and never as 0.
  const lines = data?.snapshot?.credit_lines?.accounts ?? [];
  const lastBooked = opening == null && lines.length && lines.every((line) => line.balance != null)
    ? { amount: lines.reduce((sum, line) => sum + (line.balance ?? 0), 0), as_of: lines.map((line) => line.as_of ?? '').sort()[0] || null }
    : null;
  /** A week with nothing known on either side has no net: חסר, not ₪0. */
  const weekNet = (week: ForecastWeek) => (flow(week.in) == null && flow(week.out) == null ? null : week.net);
  const closing = weeks.length ? weeks[weeks.length - 1].closing : null;
  const missing = (data?.forecast?.missing ?? []).map((key) => MISSING_LABELS[key] ?? key);

  const chartData = weeks.map((week) => ({
    week: week.start,
    in: flow(week.in),
    out: flow(week.out),
    closing: week.closing,
  }));

  const cardClass = `p-5 rounded-2xl ${darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'}`;
  const muted = darkMode ? 'text-gray-400' : 'text-gray-500';

  return (
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`} dir="rtl">
      <div>
        <h1 className="text-3xl font-bold">תזרים מזומנים חזוי</h1>
        <p className={`mt-1 text-sm ${muted}`}>
          13 שבועות: יתרת פתיחה, הלוואות, שכר, ספקים, מע״מ וקצב תפעולי. ניכיון צ׳קים והלוואות הם מימון ולא הכנסה. חסר אינו 0.
        </p>
      </div>

      <PartialDataBanner
        text={data?.snapshot?.partial_banner?.text_he}
        extra={missing.length ? `חסר בתחזית: ${missing.join(', ')}` : null}
      />

      <CreditLinesPanel lines={data?.snapshot?.credit_lines} />

      {isLoading ? <p className={muted}>טוען…</p> : null}
      {isError ? <p className={muted}>אין תחזית להצגה עד שנבחר ארגון פעיל.</p> : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className={cardClass}>
          <p className={`text-sm ${muted}`}>יתרת פתיחה</p>
          <p className="mt-1 text-2xl font-bold">{formatReportMoney(opening)}</p>
          <p className={`text-xs ${muted}`}>
            {data?.forecast?.opening?.as_of
              ? `נכון ל-${data.forecast.opening.as_of}`
              : lastBooked
                ? `אין יתרה מהיום. אחרונה ידועה: ${formatReportMoney(lastBooked.amount)} נכון ל-${lastBooked.as_of ?? 'חסר'}`
                : 'חסר תאריך'}
          </p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${muted}`}>כניסות צפויות (30 יום)</p>
          <p className="mt-1 text-2xl font-bold text-green-600">{formatReportMoney(inflow30)}</p>
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${muted}`}>יציאות צפויות (30 יום)</p>
          <p className="mt-1 text-2xl font-bold text-red-600">{formatReportMoney(outflow30)}</p>
          {incomplete30 ? <p className="text-xs text-amber-700">חלק מהיציאות חסר. ר׳ פירוט השבועות.</p> : null}
        </div>
        <div className={cardClass}>
          <p className={`text-sm ${muted}`}>יתרה בסוף התקופה</p>
          <p className={`mt-1 text-2xl font-bold ${closing != null && closing < 0 ? 'text-red-600' : ''}`}>
            {formatReportMoney(closing)}
          </p>
        </div>
      </div>

      <div className={cardClass}>
        <h2 className="mb-4 text-lg font-semibold">תזרים שבועי</h2>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? '#374151' : '#e5e7eb'} />
            <XAxis dataKey="week" fontSize={12} tickFormatter={(v: string) => `${v.slice(8, 10)}.${v.slice(5, 7)}`} />
            <YAxis fontSize={12} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip formatter={(value) => formatReportMoney(typeof value === 'number' ? value : null)} />
            <Legend />
            <Bar dataKey="in" fill="#10b981" name="כניסות" />
            <Bar dataKey="out" fill="#ef4444" name="יציאות" />
            <Line type="monotone" dataKey="closing" stroke="#3b82f6" strokeWidth={3} dot={false} name="יתרה" connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className={cardClass}>
        <h2 className="mb-4 text-lg font-semibold">פירוט שבועי</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="px-2 py-3 text-right font-medium">שבוע</th>
                <th className="px-2 py-3 text-right font-medium">כניסות</th>
                <th className="px-2 py-3 text-right font-medium">יציאות</th>
                <th className="px-2 py-3 text-right font-medium">נטו</th>
                <th className="px-2 py-3 text-right font-medium">יתרה</th>
                <th className="px-2 py-3 text-right font-medium">פנוי במסגרת</th>
                <th className="px-2 py-3 text-right font-medium">חסר / פירוט</th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((week) => (
                <tr key={week.start} className={`border-b align-top ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                  <td className="px-2 py-2">{`${week.start.slice(8, 10)}.${week.start.slice(5, 7)}`}</td>
                  <td className="px-2 py-2 text-green-600">{formatReportMoney(flow(week.in))}</td>
                  <td className="px-2 py-2 text-red-600">{formatReportMoney(flow(week.out))}</td>
                  <td className={`px-2 py-2 font-medium ${weekNet(week) != null && (weekNet(week) ?? 0) < 0 ? 'text-red-600' : ''}`}>
                    {formatReportMoney(weekNet(week))}
                  </td>
                  <td className={`px-2 py-2 font-bold ${week.closing != null && week.closing < 0 ? 'text-red-600' : ''}`}>
                    {formatReportMoney(week.closing)}
                  </td>
                  <td className={`px-2 py-2 ${week.headroom != null && week.headroom < 0 ? 'font-bold text-red-700' : ''}`}>
                    {formatReportMoney(week.headroom)}
                  </td>
                  <td className="px-2 py-2 text-xs">
                    {(week.unknown ?? []).map((text) => <div key={text} className="text-amber-700">{text}</div>)}
                    {(week.items ?? []).slice(0, 4).map((item, index) => (
                      <div key={`${item.label}-${index}`} className={muted}>{item.label}: {formatReportMoney(item.amount)}</div>
                    ))}
                  </td>
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
