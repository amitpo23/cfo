/**
 * Stored checking-balance diagnostic for the active organization.
 * Reads GET /api/cashflow/balance-diagnostic and, for a super admin,
 * /balance-diagnostic/all. No provider call and no write.
 */
import { useCallback, useEffect, useState } from 'react';
import { Landmark, Loader2, RefreshCw } from 'lucide-react';
import api from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

interface AccountRow {
  name: string | null;
  source: string | null;
  raw_account_type: string | null;
  balance: number | null;
  as_of: string | null;
  credit_limit: number | null;
  available_limit: number | null;
}

interface StaleRow {
  name?: string;
  as_of?: string | null;
  observed_balance?: number | null;
  reason?: string;
}

interface OrgDiagnostic {
  organization_id: number;
  name: string | null;
  as_of_today: string;
  snapshot_balance: number | null;
  snapshot_as_of: string | null;
  snapshot_source: string;
  transactions_through: string | null;
  transactions_missing_after: string | null;
  stale_balances: StaleRow[];
  status: string;
  accounts: AccountRow[];
  scheduled_open_finance_enabled: boolean;
  scheduled_open_finance_includes_org: boolean;
  import_notes_he: string[];
  provider_calls: number;
}

interface AllDiagnostic {
  organizations: OrgDiagnostic[];
  provider_calls: number;
}

const STATUS_HE: Record<string, string> = {
  ready: 'מוכן',
  partial: 'חלקי — יש תנועות חסרות',
  unknown: 'לא ידוע',
};

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'לא ידוע';
  return new Intl.NumberFormat('he-IL', {
    style: 'currency',
    currency: 'ILS',
    maximumFractionDigits: 2,
  }).format(value);
}

function text(value: string | null | undefined): string {
  return value || 'לא ידוע';
}

function OrgCard({ report }: { report: OrgDiagnostic }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">{report.name || `ארגון ${report.organization_id}`}</h2>
        <span className="text-sm text-slate-500">ארגון {report.organization_id}</span>
      </header>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="text-xs text-slate-500">יתרת עו״ש לשימוש</dt>
          <dd className="text-xl font-semibold">{money(report.snapshot_balance)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">נכון ל</dt>
          <dd>{text(report.snapshot_as_of)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">סטטוס</dt>
          <dd>{STATUS_HE[report.status] || report.status}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">מקור הנתון</dt>
          <dd>{report.snapshot_source}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">תנועות עד</dt>
          <dd>{text(report.transactions_through)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">תנועות חסרות אחרי</dt>
          <dd>{text(report.transactions_missing_after)}</dd>
        </div>
      </dl>
      {report.stale_balances.length > 0 ? (
        <p className="mt-3 text-sm text-amber-800">
          יתרת Open Finance ישנה מיומיים לא נכנסת ליתרה לשימוש.
          {' '}
          {report.stale_balances.map((row) => row.reason).filter(Boolean).join(' · ')}
        </p>
      ) : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-right text-slate-500">
            <tr>
              <th className="py-2 font-medium">חשבון</th>
              <th className="py-2 font-medium">מקור</th>
              <th className="py-2 font-medium">סוג</th>
              <th className="py-2 font-medium">יתרה שמורה</th>
              <th className="py-2 font-medium">נכון ל</th>
              <th className="py-2 font-medium">מסגרת</th>
              <th className="py-2 font-medium">פנוי</th>
            </tr>
          </thead>
          <tbody>
            {report.accounts.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-3 text-slate-500">אין חשבון בנק שמור</td>
              </tr>
            ) : report.accounts.map((account, index) => (
              <tr key={`${report.organization_id}-${index}`} className="border-t border-slate-100">
                <td className="py-2">{account.name || 'ללא שם'}</td>
                <td className="py-2">{text(account.source)}</td>
                <td className="py-2">{text(account.raw_account_type)}</td>
                <td className="py-2">{money(account.balance)}</td>
                <td className="py-2">{text(account.as_of)}</td>
                <td className="py-2">{money(account.credit_limit)}</td>
                <td className="py-2">{money(account.available_limit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-4 list-disc space-y-1 pr-5 text-sm text-slate-600">
        {report.import_notes_he.map((note) => <li key={note}>{note}</li>)}
      </ul>
      <p className="mt-3 text-xs text-slate-400">
        רענון לילה של Open Finance: {report.scheduled_open_finance_enabled ? 'הדגל דולק' : 'הדגל כבוי'}
        {' · '}
        הארגון ברשימה: {report.scheduled_open_finance_includes_org ? 'כן' : 'לא'}
        {' · '}
        קריאות ספק: {report.provider_calls}
      </p>
    </article>
  );
}

export default function BalanceDiagnosticPage({ currentUser }: { currentUser: CurrentUser | null }) {
  const [scope, setScope] = useState<'org' | 'all'>('org');
  const [report, setReport] = useState<OrgDiagnostic | null>(null);
  const [all, setAll] = useState<AllDiagnostic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (next: 'org' | 'all') => {
    setLoading(true);
    setError(null);
    try {
      if (next === 'all') {
        const data = await api.get<AllDiagnostic>('/cashflow/balance-diagnostic/all');
        setAll(data);
        setReport(null);
      } else {
        const data = await api.get<OrgDiagnostic>('/cashflow/balance-diagnostic');
        setReport(data);
        setAll(null);
      }
    } catch (requestError: unknown) {
      const detail = (requestError as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'טעינת האבחון נכשלה');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (currentUser?.role === 'super_admin') void load(scope);
  }, [currentUser, scope, load]);

  if (currentUser === null) {
    return <div dir="rtl" className="p-8 text-slate-500">טוען הרשאות…</div>;
  }
  if (currentUser.role !== 'super_admin') {
    return (
      <div dir="rtl" className="m-8 rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">
        המסך זמין למנהל־על בלבד.
      </div>
    );
  }

  const rows = scope === 'all' ? (all?.organizations || []) : (report ? [report] : []);

  return (
    <div dir="rtl" className="min-h-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto max-w-6xl space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold">
              <Landmark className="text-sky-700" /> אבחון יתרות
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              מה ששמור בטבלת החשבונות. אין כאן קריאה ל־Open Finance או ל־SUMIT, ואין שמירה.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setScope('org')}
              className={`rounded-lg border px-3 py-2 text-sm ${scope === 'org' ? 'bg-slate-900 text-white' : 'bg-white'}`}
            >
              הארגון הפעיל
            </button>
            <button
              type="button"
              onClick={() => setScope('all')}
              className={`rounded-lg border px-3 py-2 text-sm ${scope === 'all' ? 'bg-slate-900 text-white' : 'bg-white'}`}
            >
              כל הארגונים
            </button>
            <button
              type="button"
              onClick={() => void load(scope)}
              className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2 text-sm hover:bg-slate-100"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              רענון
            </button>
          </div>
        </header>
        {error ? <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
        {loading && rows.length === 0 ? <p className="text-sm text-slate-500">טוען אבחון…</p> : null}
        {rows.map((item) => <OrgCard key={item.organization_id} report={item} />)}
      </div>
    </div>
  );
}
