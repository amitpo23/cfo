/**
 * Ledger dashboard — derived double-entry shadow ledger (מאזן בוחן + פקודות יומן + כרטסת).
 * All data is DERIVED from synced documents, NOT SUMIT's official books.
 */
import { useEffect, useState } from 'react';
import { BookOpen, Loader2, Scale, AlertTriangle, FileText } from 'lucide-react';
import api from '../services/api';
import ExportButtons, { ExportSheet } from './ExportButtons';

type TabKey = 'trial' | 'journal' | 'balance';

interface TBAccount {
  account: string; name: string; type: string;
  debit: number; credit: number; balance: number;
}
interface TrialBalance {
  accounts: TBAccount[]; total_debit: number; total_credit: number;
  balanced: boolean; entry_count: number; derived: boolean; disclaimer: string;
}
interface JournalLine { account: string; account_name: string; debit: number; credit: number; }
interface JournalEntry {
  date: string | null; memo: string; source_ref: string;
  lines: JournalLine[]; total_debit: number; total_credit: number; balanced: boolean;
}
interface BalanceSheet {
  assets: { account: string; name: string; balance: number }[]; total_assets: number;
  liabilities: { account: string; name: string; balance: number }[]; total_liabilities: number;
  equity: { opening_equity?: number; retained_earnings: number; total_equity?: number };
  total_equity_and_liabilities: number; balanced: boolean; disclaimer: string;
}

const now = new Date();
const fmt = (n: number) => `₪${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function LedgerDashboard() {
  const [tab, setTab] = useState<TabKey>('trial');
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState<number | 0>(0); // 0 = whole year
  const [tb, setTb] = useState<TrialBalance | null>(null);
  const [bs, setBs] = useState<BalanceSheet | null>(null);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const qs = () => `?year=${year}${month ? `&month=${month}` : ''}`;

  const load = async () => {
    setLoading(true); setError(null);
    try {
      if (tab === 'trial') {
        setTb(await api.get<TrialBalance>(`/api/ledger/trial-balance${qs()}`));
      } else if (tab === 'balance') {
        setBs(await api.get<BalanceSheet>(`/api/ledger/balance-sheet${qs()}`));
      } else {
        const r = await api.get<{ entries: JournalEntry[] }>(`/api/ledger/journal${qs()}`);
        setEntries(r.entries || []);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'שגיאה בטעינת הנתונים');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab, year, month]);

  const periodLabel = `תקופה: ${month ? `${month}/${year}` : `שנת ${year}`}`;

  const exportSheets: ExportSheet[] = (() => {
    if (tab === 'trial' && tb) {
      return [{
        name: 'מאזן בוחן',
        columns: [
          { key: 'account', label: 'חשבון' },
          { key: 'name', label: 'שם' },
          { key: 'debit', label: 'חובה' },
          { key: 'credit', label: 'זכות' },
          { key: 'balance', label: 'יתרה' },
        ],
        rows: tb.accounts.map((a) => ({ account: a.account, name: a.name, debit: a.debit, credit: a.credit, balance: a.balance })),
        summary: [
          { label: 'סה"כ חובה', value: fmt(tb.total_debit) },
          { label: 'סה"כ זכות', value: fmt(tb.total_credit) },
          { label: 'מאוזן', value: tb.balanced ? 'כן' : 'לא' },
        ],
      }];
    }
    if (tab === 'balance' && bs) {
      return [
        {
          name: 'נכסים',
          columns: [{ key: 'name', label: 'שם' }, { key: 'balance', label: 'יתרה' }],
          rows: bs.assets.map((a) => ({ name: a.name, balance: a.balance })),
          summary: [{ label: 'סה"כ נכסים', value: fmt(bs.total_assets) }],
        },
        {
          name: 'התחייבויות והון',
          columns: [{ key: 'name', label: 'שם' }, { key: 'balance', label: 'יתרה' }],
          rows: [
            ...bs.liabilities.map((l) => ({ name: l.name, balance: l.balance })),
            ...(bs.equity.opening_equity ? [{ name: 'הון/יתרות פתיחה', balance: bs.equity.opening_equity }] : []),
            { name: 'עודפים (רווח/הפסד)', balance: bs.equity.retained_earnings },
          ],
          summary: [{ label: 'סה"כ', value: fmt(bs.total_equity_and_liabilities) }],
        },
      ];
    }
    if (tab === 'journal' && entries.length > 0) {
      return [{
        name: 'פקודות יומן',
        columns: [
          { key: 'date', label: 'תאריך' },
          { key: 'memo', label: 'תיאור' },
          { key: 'source_ref', label: 'מסמך מקור' },
          { key: 'account', label: 'חשבון' },
          { key: 'account_name', label: 'שם חשבון' },
          { key: 'debit', label: 'חובה' },
          { key: 'credit', label: 'זכות' },
        ],
        rows: entries.flatMap((e) => e.lines.map((l) => ({
          date: e.date || '',
          memo: e.memo,
          source_ref: e.source_ref,
          account: l.account,
          account_name: l.account_name,
          debit: l.debit,
          credit: l.credit,
        }))),
      }];
    }
    return [];
  })();

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <h1 className="text-2xl font-bold flex items-center gap-2 mb-2">
        <BookOpen className="text-indigo-600" /> הנהלת חשבונות כפולה
      </h1>
      <div className="mb-4 p-3 rounded-lg bg-amber-50 text-amber-800 text-sm flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
        <span>נגזר מהמסמכים (SUMIT) — <b>אינו הספרים הרשמיים</b>. לבדיקת רו"ח.</span>
      </div>

      <div className="flex gap-2 mb-5 flex-wrap items-center">
        <button onClick={() => setTab('trial')}
          className={`inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm ${
            tab === 'trial' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
          <Scale className="w-4 h-4" /> מאזן בוחן
        </button>
        <button onClick={() => setTab('journal')}
          className={`inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm ${
            tab === 'journal' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
          <FileText className="w-4 h-4" /> פקודות יומן
        </button>
        <button onClick={() => setTab('balance')}
          className={`inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm ${
            tab === 'balance' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
          <Scale className="w-4 h-4" /> מאזן
        </button>
        <span className="mx-2 h-6 w-px bg-slate-200" />
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm">
          <option value={0}>כל השנה</option>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} className="border rounded-lg px-2 py-2 text-sm w-24" />
        {exportSheets.length > 0 && (
          <ExportButtons title="הנהלת חשבונות כפולה" meta={periodLabel} sheets={exportSheets} />
        )}
      </div>

      {error && <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-800 text-sm">{error}</div>}

      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : tab === 'trial' ? (
        tb && (
          <>
            <div className={`mb-4 p-3 rounded-lg text-sm font-semibold ${
              tb.balanced ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>
              {tb.balanced ? '✓ מאוזן' : '✗ לא מאוזן'} — סה"כ חובה {fmt(tb.total_debit)} · סה"כ זכות {fmt(tb.total_credit)} · {tb.entry_count} פקודות
            </div>
            <div className="border rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-slate-600">
                  <tr>
                    <th className="text-right px-4 py-2">חשבון</th>
                    <th className="text-right px-4 py-2">שם</th>
                    <th className="text-right px-4 py-2">חובה</th>
                    <th className="text-right px-4 py-2">זכות</th>
                    <th className="text-right px-4 py-2">יתרה</th>
                  </tr>
                </thead>
                <tbody>
                  {tb.accounts.map((a) => (
                    <tr key={a.account} className="border-t hover:bg-slate-50">
                      <td className="px-4 py-2 font-mono text-xs text-slate-500">{a.account}</td>
                      <td className="px-4 py-2 font-medium">{a.name}</td>
                      <td className="px-4 py-2">{a.debit ? fmt(a.debit) : '—'}</td>
                      <td className="px-4 py-2">{a.credit ? fmt(a.credit) : '—'}</td>
                      <td className={`px-4 py-2 font-semibold ${a.balance >= 0 ? 'text-slate-700' : 'text-rose-600'}`}>{fmt(a.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )
      ) : tab === 'balance' ? (
        bs && (
          <>
            <div className={`mb-4 p-3 rounded-lg text-sm font-semibold ${
              bs.balanced ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>
              {bs.balanced ? '✓ מאזן מאוזן' : '✗ לא מאוזן'} — נכסים {fmt(bs.total_assets)} = התחייבויות+הון {fmt(bs.total_equity_and_liabilities)}
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="border rounded-xl overflow-hidden">
                <div className="bg-slate-100 px-4 py-2 font-semibold">נכסים</div>
                <table className="w-full text-sm">
                  <tbody>
                    {bs.assets.map((a) => (
                      <tr key={a.account} className="border-t"><td className="px-4 py-2">{a.name}</td>
                        <td className={`px-4 py-2 text-left ${a.balance < 0 ? 'text-rose-600' : ''}`}>{fmt(a.balance)}</td></tr>
                    ))}
                    <tr className="border-t font-bold bg-slate-50"><td className="px-4 py-2">סה"כ נכסים</td><td className="px-4 py-2 text-left">{fmt(bs.total_assets)}</td></tr>
                  </tbody>
                </table>
              </div>
              <div className="border rounded-xl overflow-hidden">
                <div className="bg-slate-100 px-4 py-2 font-semibold">התחייבויות והון</div>
                <table className="w-full text-sm">
                  <tbody>
                    {bs.liabilities.map((l) => (
                      <tr key={l.account} className="border-t"><td className="px-4 py-2">{l.name}</td>
                        <td className="px-4 py-2 text-left">{fmt(l.balance)}</td></tr>
                    ))}
                    {bs.equity.opening_equity ? (
                      <tr className="border-t"><td className="px-4 py-2">הון/יתרות פתיחה</td>
                        <td className="px-4 py-2 text-left">{fmt(bs.equity.opening_equity)}</td></tr>
                    ) : null}
                    <tr className="border-t"><td className="px-4 py-2">עודפים (רווח/הפסד)</td>
                      <td className={`px-4 py-2 text-left ${bs.equity.retained_earnings < 0 ? 'text-rose-600' : ''}`}>{fmt(bs.equity.retained_earnings)}</td></tr>
                    <tr className="border-t font-bold bg-slate-50"><td className="px-4 py-2">סה"כ</td><td className="px-4 py-2 text-left">{fmt(bs.total_equity_and_liabilities)}</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
            <p className="text-xs text-slate-400 mt-3">{bs.disclaimer}</p>
          </>
        )
      ) : (
        entries.length === 0 ? (
          <div className="text-center py-16 text-slate-400">אין פקודות יומן לתקופה.</div>
        ) : (
          <div className="space-y-3">
            {entries.map((e, i) => (
              <div key={i} className="border rounded-xl overflow-hidden">
                <div className="flex items-center justify-between bg-slate-50 px-4 py-2 text-sm">
                  <span className="font-medium">{e.memo}</span>
                  <span className="text-slate-400 text-xs font-mono">{e.date} · {e.source_ref}</span>
                </div>
                <table className="w-full text-sm">
                  <tbody>
                    {e.lines.map((l, j) => (
                      <tr key={j} className="border-t">
                        <td className="px-4 py-1.5 font-mono text-xs text-slate-500 w-16">{l.account}</td>
                        <td className="px-4 py-1.5">{l.account_name}</td>
                        <td className="px-4 py-1.5 w-32 text-left">{l.debit ? fmt(l.debit) : ''}</td>
                        <td className="px-4 py-1.5 w-32 text-left">{l.credit ? fmt(l.credit) : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
