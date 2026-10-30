import { useEffect, useState } from 'react';
import { candidateKey, defaultCandidate, entityLabel, type MatchReport, type MatchRow, type MatchStatus } from './bankMatchModel';

function money(value: number): string {
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 2 }).format(value);
}

const FILTERS: { id: MatchStatus | 'all'; label: string }[] = [
  { id: 'open', label: 'ממתין להחלטה' },
  { id: 'check', label: 'בבדיקה' },
  { id: 'missing_doc', label: 'חסר מסמך' },
  { id: 'approved', label: 'אושר' },
  { id: 'all', label: 'הכול' },
];

type Action = 'approve' | 'check' | 'missing_doc' | 'reopen';

export default function BankMatch({ dashboardId, slug, start, end }: { dashboardId?: number; slug?: string; start: string; end: string }) {
  const token = localStorage.getItem('auth_token') || '';
  const query = `start=${start}&end=${end}`;
  const listUrl = dashboardId
    ? `/api/dashboards/${dashboardId}/bank-match?${query}`
    : `/api/public/d/${slug}/bank-match?${query}`;
  const [report, setReport] = useState<MatchReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<MatchStatus | 'all'>('open');
  const [picked, setPicked] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
    fetch(listUrl, { headers, credentials: 'include' })
      .then((response) => response.json().then((body) => ({ ok: response.ok, body })))
      .then(({ ok, body }) => {
        if (cancelled) return;
        if (!ok) {
          setError(body.error?.message_he || 'לא ניתן לטעון את ההתאמות');
          return;
        }
        setReport(body);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError('לא ניתן לטעון את ההתאמות');
      });
    return () => {
      cancelled = true;
    };
  }, [listUrl, token, reload]);

  async function decide(row: MatchRow, action: Action) {
    if (!dashboardId) return;
    const body: Record<string, unknown> = { transaction_id: row.id, action };
    if (action === 'approve') {
      const key = picked[row.id] || (defaultCandidate(row) ? candidateKey(defaultCandidate(row)!) : '');
      const candidate = row.candidates.find((item) => candidateKey(item) === key);
      if (!candidate) {
        setNotice('אין מסמך לאשר. סמנו בדיקה או חסר מסמך.');
        return;
      }
      body.entity_type = candidate.entity_type;
      body.entity_id = candidate.entity_id;
    }
    const note = (notes[row.id] || '').trim();
    if (note && action !== 'approve' && action !== 'reopen') body.note = note;
    setBusy(row.id);
    const response = await fetch(`/api/dashboards/${dashboardId}/bank-match`, {
      method: 'POST',
      credentials: 'include',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const saved = await response.json().catch(() => ({}));
    setBusy(null);
    if (!response.ok) {
      setNotice(saved.error?.message_he || 'השמירה נכשלה');
      return;
    }
    setNotice(null);
    setReload((value) => value + 1);
  }

  const summary = report?.summary;
  const rows = (report?.rows || []).filter((row) => filter === 'all' || row.status === filter);
  const canWrite = Boolean(dashboardId) && report?.read_only === false;

  return (
    <section className="d-card" dir="rtl">
      <h2>התאמת בנק</h2>
      <p className="mt-1 text-sm text-stone-600">
        כל תנועת בנק מול מסמך בספרים. מסמך מוצע הוא הצעה בלבד: רק «אשר» מתאים. התאמה אוטומטית ממתינה לאישור. כלום לא נשלח לסאמיט.
      </p>
      {report?.partial_banner?.text_he ? <p className="mt-2 text-sm text-amber-900">{report.partial_banner.text_he}</p> : null}
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
      {notice ? <p className="mt-2 text-sm text-amber-800" role="status">{notice}</p> : null}
      {summary ? (
        <p className="mt-3 text-sm">
          אושר {summary.approved.count} ({money(summary.approved.amount)})
          {' · '}בבדיקה {summary.check.count} ({money(summary.check.amount)})
          {' · '}חסר מסמך {summary.missing_doc.count} ({money(summary.missing_doc.amount)})
          {' · '}ממתין {summary.open.count} ({money(summary.open.amount)})
          {' = '}סה״כ {summary.total.count} ({money(summary.total.amount)})
          {summary.done ? ' · כל התנועות הוכרעו' : ' · עדיין לא מאוזן'}
        </p>
      ) : null}
      {!canWrite && report ? <p className="mt-1 text-xs text-stone-500">צפייה בלבד. ההחלטות נרשמות על ידי בעלי הדשבורד.</p> : null}
      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        {FILTERS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={filter === item.id ? 'font-semibold underline' : 'text-stone-600'}
            onClick={() => setFilter(item.id)}
          >
            {item.label}{summary && item.id !== 'all' ? ` (${summary[item.id].count})` : ''}
          </button>
        ))}
      </div>
      {report ? (
        <table className="mt-3 d-table">
          <thead>
            <tr><th>תאריך</th><th>סכום</th><th>צד נגדי</th><th>תיאור</th><th>מסמך בספרים</th><th>סטטוס</th>{canWrite ? <th>פעולה</th> : null}</tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const fallback = defaultCandidate(row);
              const selected = picked[row.id] || (fallback ? candidateKey(fallback) : '');
              return (
                <tr key={row.id}>
                  <td>{row.date}</td>
                  <td>{money(row.amount)}</td>
                  <td>{row.counterparty || '—'}</td>
                  <td>{row.description}</td>
                  <td className="text-sm">
                    {row.matched ? entityLabel(row.matched.entity_type, row.matched.entity_id) : null}
                    {row.status === 'open' && row.candidates.length === 0 ? <span className="text-stone-500">אין מסמך מתאים — לא מנחשים</span> : null}
                    {row.status === 'open' && row.candidates.length > 0 ? (
                      <select
                        value={selected}
                        disabled={!canWrite}
                        onChange={(event) => setPicked({ ...picked, [row.id]: event.target.value })}
                      >
                        {row.candidates.map((item) => (
                          <option key={candidateKey(item)} value={candidateKey(item)}>
                            {entityLabel(item.entity_type, item.entity_id)} · {item.name || 'ללא שם'} · {money(item.amount)} · {item.date || 'תאריך חסר'}
                            {item.score === null ? ' · התאמה אוטומטית' : ''}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    {row.status === 'open' && row.auto_match ? <span className="block text-xs text-amber-800">התאמה אוטומטית — ממתינה לאישור</span> : null}
                  </td>
                  <td>
                    {row.status_he}
                    {row.note ? <span className="block text-xs text-stone-600">{row.note}</span> : null}
                  </td>
                  {canWrite ? (
                    <td className="whitespace-nowrap text-sm">
                      {row.status === 'open' ? (
                        <>
                          <input
                            className="mb-1 block w-40 border px-1 text-xs"
                            placeholder="הערה (לא חובה)"
                            maxLength={300}
                            value={notes[row.id] || ''}
                            onChange={(event) => setNotes({ ...notes, [row.id]: event.target.value })}
                          />
                          <button type="button" className="underline disabled:opacity-40" disabled={busy === row.id || row.candidates.length === 0} onClick={() => void decide(row, 'approve')}>אשר</button>
                          <button type="button" className="mr-2 underline" disabled={busy === row.id} onClick={() => void decide(row, 'check')}>בדיקה</button>
                          <button type="button" className="mr-2 underline" disabled={busy === row.id} onClick={() => void decide(row, 'missing_doc')}>חסר מסמך</button>
                        </>
                      ) : (
                        <button type="button" className="underline" disabled={busy === row.id} onClick={() => void decide(row, 'reopen')}>פתח מחדש</button>
                      )}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      {report && rows.length === 0 ? <p className="mt-2 text-sm text-stone-600">אין תנועות בסינון הזה בחלון {report.start}–{report.end}.</p> : null}
    </section>
  );
}
