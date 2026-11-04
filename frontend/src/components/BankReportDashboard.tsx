import React from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Landmark, Download, TrendingUp, Wallet, Receipt, CreditCard } from 'lucide-react';
import apiService from '../services/api';
import { formatReportMoney } from './dailyReportsMoney';
import CreditLinesPanel from './CreditLinesPanel';
import { PartialDataBanner } from './dashboardUi';

interface Props {
  darkMode?: boolean;
}

const BankReportDashboard: React.FC<Props> = ({ darkMode }) => {
  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';

  const { data, isLoading } = useQuery({
    queryKey: ['bank-status-report'],
    queryFn: async () => {
      const res: any = await apiService.getBankStatusReport();
      return res.data;
    },
  });

  const downloadMutation = useMutation({
    mutationFn: () => apiService.downloadBankStatusReport(),
  });

  // Missing is חסר, never ₪0. The margin arrives as a percent (48.7), not a fraction.
  const fmt = (v: number | null | undefined) => formatReportMoney(v);
  const pct = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? 'חסר' : `${v.toFixed(1)}%`);

  const Section: React.FC<{ icon: any; title: string; rows: [string, string][] }> = ({ icon: Icon, title, rows }) => (
    <div className={`rounded-xl border p-5 ${card}`}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-5 h-5 text-blue-600" />
        <h2 className="font-semibold">{title}</h2>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([label, value], i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-1.5 text-gray-500">{label}</td>
              <td className="py-1.5 text-left font-medium">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Landmark className="w-8 h-8 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold">דוח מצב עסקי לבנק</h1>
            <p className="text-sm text-gray-500">תמונת מצב מלאה: רווחיות, מאזן, מזומנים וחובות</p>
          </div>
        </div>
        <button
          onClick={() => downloadMutation.mutate()}
          disabled={downloadMutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
        >
          <Download className="w-4 h-4" />
          {downloadMutation.isPending ? 'מייצר...' : 'הורדת דוח Excel לבנק'}
        </button>
      </div>

      {isLoading || !data ? (
        <div className="text-center py-12 text-gray-500">טוען נתונים...</div>
      ) : (
        <>
          <div className="text-sm text-gray-500">
            {data.company_name} · לתקופה {data.period.start} עד {data.period.end}
          </div>
          <PartialDataBanner text={data.partial_banner?.text_he} />
          <CreditLinesPanel lines={data.credit_lines} />
          {data.profit_loss.missing_label_he ? (
            <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950" role="status">
              רווח והפסד: {data.profit_loss.missing_label_he}
            </p>
          ) : null}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Section icon={TrendingUp} title="רווח והפסד" rows={[
              ['סך הכנסות', fmt(data.profit_loss.total_revenue)],
              ['סך הוצאות', fmt(data.profit_loss.total_expenses)],
              ['רווח גולמי', fmt(data.profit_loss.gross_profit)],
              ['רווח נקי', fmt(data.profit_loss.net_income)],
              ['שולי רווח נקי', pct(data.profit_loss.net_margin)],
            ]} />
            <Section icon={Wallet} title="מאזן ומזומנים" rows={[
              ['סך נכסים', fmt(data.balance_sheet.total_assets)],
              ['סך התחייבויות', fmt(data.balance_sheet.total_liabilities)],
              ['הון עצמי', fmt(data.balance_sheet.total_equity)],
              ['יחס שוטף', data.balance_sheet.current_ratio ? data.balance_sheet.current_ratio.toFixed(2) : 'חסר'],
              ['הלוואות (יתרה)', fmt(data.loans_total)],
            ]} />
            <Section icon={Receipt} title="חייבים (לקוחות)" rows={[
              ['סך חוב לקוחות', fmt(data.receivables.total)],
              ['שוטף', fmt(data.receivables.current)],
              ['61-90 יום', fmt(data.receivables.days_61_90)],
              ['מעל 120 יום', fmt(data.receivables.over_120)],
            ]} />
            <Section icon={CreditCard} title="זכאים (ספקים)" rows={[
              ['סך חוב לספקים', fmt(data.payables.total)],
            ]} />
          </div>
        </>
      )}
    </div>
  );
};

export default BankReportDashboard;
