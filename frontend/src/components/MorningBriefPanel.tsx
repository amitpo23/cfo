/**
 * Morning-brief panel (PR6 of the bookkeeper daily-cycle plan — frontend
 * surface for PR5's /api/daily-reports/morning-brief + PR6's
 * /api/daily-reports/scorecard). RTL Hebrew. Honesty contract: every
 * missing/absent value renders "—", never 0 — see
 * services/morning_brief_service.py module docstring.
 */
import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import api from '../services/api';

interface RedItem {
  type: string;
  severity: string;
  title: string;
  message?: string | null;
  detail?: string | null;
}

interface DebtorTop {
  customer?: string | null;
  amount?: number | null;
  days_overdue?: number | null;
}

interface BriefPayload {
  organization_id: number;
  organization_name?: string | null;
  date: string;
  status: string;
  reds: RedItem[];
  cash: {
    balance: number | null;
    as_of: string | null;
    credit_headroom: number | null;
    breach_date: string | null;
    reason?: string | null;
  };
  queues: {
    drafts: number | null;
    exceptions_over_48h: number | null;
    unreconciled: number | null;
  };
  debtors: { total_overdue: number | null; top: DebtorTop[] };
  parity: { status: string | null };
  deadline: { next_date: string | null; days_left: number | null };
  freshness: { as_of: string | null; reason?: string | null };
  collapsed_greens: string[];
}

interface BriefResponse {
  exists: boolean;
  organization_id: number;
  brief_date?: string;
  status?: string;
  payload?: BriefPayload | null;
  delivered_channels?: Record<string, unknown>;
  created_at?: string | null;
}

interface ScorecardRow {
  date: string;
  cycle_status: string | null;
  unreconciled_count: number | null;
  open_expense_drafts: number | null;
  exceptions_over_48h: number | null;
  parity_status: string | null;
  credit_headroom: number | null;
  cash_balance: number | null;
}

interface ScorecardResponse { organization_id: number; days: number; scorecard: ScorecardRow[]; }

const STATUS_LABEL: Record<string, string> = {
  green: 'תקין', yellow: 'דורש תשומת לב', red: 'דרוש טיפול היום',
};
const STATUS_EMOJI: Record<string, string> = { green: '🟢', yellow: '🟡', red: '🔴' };
const STATUS_BADGE: Record<string, string> = {
  green: 'bg-emerald-50 text-emerald-700',
  yellow: 'bg-amber-50 text-amber-700',
  red: 'bg-rose-50 text-rose-700',
};
const STATUS_DOT: Record<string, string> = {
  green: 'bg-emerald-500', yellow: 'bg-amber-500', red: 'bg-rose-500',
};

const fmtMoney = (n: number | null | undefined) =>
  n == null ? '—' : new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(n);
const fmtNum = (n: number | null | undefined) => (n == null ? '—' : String(n));
const fmtDate = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit', year: 'numeric' });
};
const fmtDateTime = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('he-IL');
};

export default function MorningBriefPanel() {
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [scorecard, setScorecard] = useState<ScorecardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [b, s] = await Promise.all([
          api.get<BriefResponse>('/api/daily-reports/morning-brief'),
          api.get<ScorecardResponse>('/api/daily-reports/scorecard?days=30'),
        ]);
        if (!cancelled) {
          setBrief(b);
          setScorecard(s.scorecard || []);
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.response?.data?.detail || 'שגיאה בטעינת בריף הבוקר');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div id="morning-brief" className="border rounded-xl p-6 mb-6 flex justify-center text-slate-400" dir="rtl">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div id="morning-brief" className="mb-6 p-3 rounded-lg bg-red-50 text-red-800 text-sm" dir="rtl">{error}</div>
    );
  }

  if (!brief || !brief.exists || !brief.payload) {
    return (
      <div id="morning-brief" className="border rounded-xl p-4 mb-6 text-sm text-slate-400" dir="rtl">
        אין עדיין בריף בוקר להיום — ירוץ אוטומטית במחזור-הבוקר הבא.
      </div>
    );
  }

  const p = brief.payload;
  const status = p.status || 'unknown';
  const emoji = STATUS_EMOJI[status] || '⚪';
  const label = STATUS_LABEL[status] || 'לא ידוע';
  const badgeClass = STATUS_BADGE[status] || 'bg-slate-100 text-slate-600';

  return (
    <div id="morning-brief" className="border rounded-xl p-4 mb-6" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
        <h2 className="font-semibold text-lg">בריף בוקר · {fmtDate(p.date)}</h2>
        <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${badgeClass}`}>
          {emoji} {label}
        </span>
      </div>

      {p.reds.length > 0 ? (
        <div className="mb-4 space-y-2">
          {p.reds.map((r, i) => (
            <div key={i} className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-sm">
              <div className="font-semibold text-rose-800">{r.title}</div>
              {r.message && <div className="text-rose-700 mt-0.5">{r.message}</div>}
              {r.detail && <div className="text-rose-600 text-xs mt-0.5">{r.detail}</div>}
            </div>
          ))}
        </div>
      ) : (
        <div className="mb-4 text-sm text-emerald-700">✅ אין פריטים אדומים הדורשים טיפול היום.</div>
      )}

      <div className="grid md:grid-cols-2 gap-3 text-sm mb-3">
        <div className="border rounded-lg p-3">
          <div className="font-medium mb-1">מזומן</div>
          <div>יתרה: {fmtMoney(p.cash.balance)}</div>
          <div className="text-xs text-slate-500 mt-0.5">
            {p.cash.as_of
              ? `נכון ל-${fmtDateTime(p.cash.as_of)}`
              : `נכון ל-— ${p.cash.reason ? `(${p.cash.reason})` : ''}`}
          </div>
          <div className="mt-1">מרווח אשראי: {fmtMoney(p.cash.credit_headroom)}</div>
          {p.cash.breach_date && (
            <div className="text-rose-600 mt-1">תאריך חריגה צפוי: {fmtDate(p.cash.breach_date)}</div>
          )}
        </div>
        <div className="border rounded-lg p-3">
          <div className="font-medium mb-1">תורים</div>
          <div>טיוטות פתוחות: {fmtNum(p.queues.drafts)}</div>
          <div>חריגים מעל 48 שעות: {fmtNum(p.queues.exceptions_over_48h)}</div>
          <div>לא מותאם בבנק: {fmtNum(p.queues.unreconciled)}</div>
        </div>
      </div>

      <div className="border rounded-lg p-3 mb-3 text-sm">
        <div className="font-medium mb-1">חייבים — 5 הגדולים באיחור</div>
        {p.debtors.top && p.debtors.top.length > 0 ? (
          <table className="w-full text-sm mt-1">
            <tbody>
              {p.debtors.top.map((t, i) => (
                <tr key={i} className="border-t first:border-0">
                  <td className="py-1">{t.customer ?? '—'}</td>
                  <td className="py-1 text-left font-medium">{fmtMoney(t.amount)}</td>
                  <td className="py-1 text-xs text-slate-500 text-left">
                    {t.days_overdue != null ? `${t.days_overdue} ימי איחור` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-slate-400">אין חייבים בפיגור</div>
        )}
        <div className="text-xs text-slate-500 mt-2">סה"כ באיחור: {fmtMoney(p.debtors.total_overdue)}</div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm mb-3">
        <span>
          {/* 'unknown'/'stale' זוהו ב-18/08/2026 כמתמוטטים ל-'—' הגנרי —
              אותו תג בדיוק כמו ארגון בלי שום נתון. ההבחנה חשובה:
              'unknown' פירושו שהבדיקה רצה ולא הייתה לה בסיס להשוואה
              (honest-null), לא ש"עדיין לא נבדק כלום". */}
          התאמה משולשת:{' '}
          {p.parity.status === 'ok'
            ? 'תקינה'
            : p.parity.status === 'mismatch'
            ? 'אי-התאמה'
            : p.parity.status === 'stale'
            ? 'נתונים לא-טריים'
            : p.parity.status === 'unknown'
            ? 'אין בסיס להשוואה'
            : '—'}
        </span>
        <span>
          {p.deadline.days_left != null
            ? `${p.deadline.days_left} ימים למועד הדיווח הבא (${fmtDate(p.deadline.next_date)})`
            : '—'}
        </span>
      </div>

      {p.collapsed_greens.length > 0 && (
        <div className="text-xs text-slate-500 mb-3">{p.collapsed_greens.join(' · ')}</div>
      )}

      {scorecard.length > 0 && (
        <div className="pt-3 border-t">
          <div className="text-xs text-slate-500 mb-1.5">מגמת 30 הימים האחרונים</div>
          <div className="flex items-center gap-1 flex-wrap">
            {scorecard.map((row) => (
              <span
                key={row.date}
                title={`${row.date}: ${row.cycle_status ?? 'לא ידוע'}`}
                className={`inline-block w-2.5 h-2.5 rounded-full ${STATUS_DOT[row.cycle_status || ''] || 'bg-slate-300'}`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
