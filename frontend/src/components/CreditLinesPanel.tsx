// Balance, limit, used, available and overrun of each checking account.
// Same `credit_lines` block on every money screen (checking_snapshot).
// An overrun is red. A missing limit is חסר, never 0.
import { formatReportMoney } from './dailyReportsMoney';

export interface CreditLine {
  name?: string | null;
  balance: number | null;
  as_of?: string | null;
  stale?: boolean;
  limit: number | null;
  used: number | null;
  available: number | null;
  available_from_bank?: number | null;
  overrun: number | null;
  status: 'overrun' | 'within' | 'unknown' | string;
  label_he?: string | null;
}

export interface CreditLines {
  accounts: CreditLine[];
  any_overrun: boolean;
}

function ddmm(value?: string | null): string {
  const match = typeof value === 'string' ? value.match(/^(\d{4})-(\d{2})-(\d{2})/) : null;
  return match ? `${match[3]}.${match[2]}` : 'חסר';
}

export default function CreditLinesPanel({ lines }: { lines?: CreditLines | null }) {
  const accounts = lines?.accounts ?? [];
  if (!accounts.length) {
    return (
      <section className="rounded-2xl border border-gray-200 bg-white p-4" dir="rtl">
        <h2 className="text-lg font-semibold">עו״ש ומסגרות</h2>
        <p className="mt-1 text-sm text-gray-600">חסר: אין חשבון עו״ש מחובר עם יתרה.</p>
      </section>
    );
  }
  return (
    <section
      className={`rounded-2xl border p-4 ${lines?.any_overrun ? 'border-red-300 bg-red-50' : 'border-gray-200 bg-white'}`}
      dir="rtl"
      aria-label="עו״ש ומסגרות"
    >
      <h2 className="text-lg font-semibold">עו״ש ומסגרות</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-gray-600">
              <th className="py-2 text-right font-medium">חשבון</th>
              <th className="py-2 text-right font-medium">יתרה</th>
              <th className="py-2 text-right font-medium">נכון ל-</th>
              <th className="py-2 text-right font-medium">מסגרת</th>
              <th className="py-2 text-right font-medium">ניצול</th>
              <th className="py-2 text-right font-medium">פנוי</th>
              <th className="py-2 text-right font-medium">חריגה</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((line, index) => {
              const over = line.status === 'overrun';
              return (
                <tr key={`${line.name ?? 'account'}-${index}`} className="border-b border-gray-100">
                  <td className="py-2">{line.name || 'חשבון עו״ש'}</td>
                  <td className={`py-2 font-medium ${line.balance != null && line.balance < 0 ? 'text-red-700' : ''}`}>
                    {formatReportMoney(line.balance)}
                  </td>
                  <td className={`py-2 ${line.stale ? 'text-amber-700' : 'text-gray-600'}`}>
                    {ddmm(line.as_of)}{line.stale ? ' (לא מהיום)' : ''}
                  </td>
                  <td className="py-2">{formatReportMoney(line.limit)}</td>
                  <td className="py-2">{formatReportMoney(line.used)}</td>
                  <td className={`py-2 ${line.available != null && line.available < 0 ? 'text-red-700' : ''}`}>
                    {formatReportMoney(line.available)}
                  </td>
                  <td className={`py-2 font-bold ${over ? 'text-red-700' : 'text-gray-700'}`}>
                    {over ? `בחריגה ${formatReportMoney(line.overrun)}` : line.status === 'within' ? 'בתוך המסגרת' : 'חסר'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        יתרה סגורה מהבנק (closingBooked). פנוי = מסגרת ועוד יתרה. יתרה שאינה מהיום מוצגת עם תאריכה.
      </p>
    </section>
  );
}
