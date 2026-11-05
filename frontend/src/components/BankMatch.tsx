import { Fragment, useEffect, useState } from 'react';
import {
  candidateKey, defaultCandidate, documentsNear, entityLabel, gapAccepted, matchGap,
  type Candidate, type MatchReport, type MatchRow, type MatchStatus,
} from './bankMatchModel';

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

type Action = 'approve' | 'approve_many' | 'approve_category' | 'check' | 'missing_doc' | 'reopen';
type Panel = 'many' | 'category' | null;

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
  const [panel, setPanel] = useState<{ row: number; kind: Panel }>({ row: 0, kind: null });
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  const [fee, setFee] = useState('');
  const [category, setCategory] = useState('');
  const [account, setAccount] = useState('');

  function openPanel(row: MatchRow, kind: Panel) {
    setPanel(panel.row === row.id && panel.kind === kind ? { row: 0, kind: null } : { row: row.id, kind });
    setChosen({});
    setFee('');
    setCategory('');
    setAccount('');
  }

  function pickedFor(row: MatchRow): Candidate[] {
    return documentsNear(report?.documents || [], row).filter((doc) => chosen[candidateKey(doc)]);
  }

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
    if (action === 'approve_many') {
      const docs = pickedFor(row);
      if (docs.length === 0) {
        setNotice('בחרו לפחות מסמך אחד.');
        return;
      }
      body.action = 'approve';
      body.documents = docs.map((doc) => ({ entity_type: doc.entity_type, entity_id: doc.entity_id }));
      const feeValue = Number(fee || 0);
      if (feeValue > 0) body.fee = feeValue;
    }
    if (action === 'approve_category') {
      if (!category || !account.trim()) {
        setNotice('אישור לפי קטגוריה דורש קטגוריה וכרטיס יעד.');
        return;
      }
      body.category = category;
      body.target_account = account.trim();
    }
    const note = (notes[row.id] || '').trim();
    if (note && action !== 'reopen') body.note = note;
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
    setPanel({ row: 0, kind: null });
    setReload((value) => value + 1);
  }

  function manyPanel(row: MatchRow) {
    const near = documentsNear(report?.documents || [], row);
    const picked = pickedFor(row);
    const gap = matchGap(row.amount, picked, Number(fee || 0));
    return (
      <div className="text-sm">
        {near.length === 0 ? <p className="text-stone-500">אין מסמכים פתוחים סביב התאריך הזה — לא מנחשים.</p> : null}
        <ul className="max-h-60 overflow-auto">
          {near.map((doc) => (
            <li key={candidateKey(doc)}>
              <label>
                <input
                  type="checkbox"
                  checked={Boolean(chosen[candidateKey(doc)])}
                  onChange={(event) => setChosen({ ...chosen, [candidateKey(doc)]: event.target.checked })}
                />{' '}
                {entityLabel(doc.entity_type, doc.entity_id)} · {doc.name || 'ללא שם'} · {money(doc.amount)} · {doc.date || 'תאריך חסר'}
                {doc.credit ? ' · זיכוי/החזר' : ''}
              </label>
            </li>
          ))}
        </ul>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label>
            עמלה{' '}
            <input className="w-24 border px-1" inputMode="decimal" value={fee} onChange={(event) => setFee(event.target.value)} placeholder="0" />
          </label>
          <span>נבחרו {picked.length} · הפרש מול הבנק {money(gap)}</span>
          <button
            type="button"
            className="underline disabled:opacity-40"
            disabled={busy === row.id || picked.length === 0 || !gapAccepted(gap)}
            onClick={() => void decide(row, 'approve_many')}
          >
            אשר {picked.length} מסמכים
          </button>
          {picked.length > 0 && !gapAccepted(gap) ? <span className="text-xs text-amber-800">הסכום חייב להתאים עד ₪1, או להגדיר עמלה.</span> : null}
        </div>
      </div>
    );
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
      {error ?<p className="mt-2 text-sm text-red-700">{error}</p> : null}
      {notice ? <p className="mt-2 text-sm text-amber-800" role="status">{notice}</p> : null}
      {summary ? (
        <p className="mt-3 text-sm">
          אושר {summary.approved.count} ({money(summary.approved.amount)})
          {' · '}בבדיקה {summary.check.count} ({money(summary.check.amount)})
          {' · '}חסר מסמך {summary.missing_doc.count} ({money(summary.missing_doc.amount)})
          {' · '}ממתין {summary.open.count} ({money(summary.open.amount)})
          {' = '}סה״כ {summary.total.count} ({money(summary.total.amount)})
        </p>
      ) : null}
      {report?.closing ? (
        <p className={`mt-1 text-sm font-semibold ${report.closing.done ? 'text-emerald-800' : 'text-amber-800'}`} role="status">
          {report.closing.label_he}
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
              const panelOpen = canWrite && panel.row === row.id && row.status === 'open';
              return (
                <Fragment key={row.id}>
                <tr>
                  <td>{row.date}</td>
                  <td>{money(row.amount)}</td>
                  <td>{row.counterparty || '—'}</td>
                  <td>
                    {row.description}
                    {row.warning ? <span className="block text-xs font-semibold text-red-700" role="alert">{row.warning.label_he}</span> : null}
                  </td>
                  <td className="text-sm">
                    {row.matched?.kind === 'category' ? (
                      <span>{row.matched.category_he || row.matched.category} → כרטיס {row.matched.target_account}</span>
                    ) : null}
                    {row.matched?.kind === 'documents' ? (
                      <span>
                        {row.matched.documents.map((line) => `${entityLabel(line.entity_type, line.entity_id)} ${money(line.amount)}`).join(' · ')}
                        {row.matched.fee ? ` · עמלה ${money(row.matched.fee)}` : ''}
                      </span>
                    ) : null}
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
                          <button type="button" className="mr-2 underline" disabled={busy === row.id} onClick={() => openPanel(row, 'many')}>כמה מסמכים</button>
                          <button type="button" className="mr-2 underline" disabled={busy === row.id} onClick={() => openPanel(row, 'category')}>לפי קטגוריה</button>
                          <button type="button" className="mr-2 underline" disabled={busy === row.id} onClick={() => void decide(row, 'check')}>בדיקה</button>
                          <button type="button" className="mr-2 underline" disabled={busy === row.id} onClick={() => void decide(row, 'missing_doc')}>חסר מסמך</button>
                        </>
                      ) : (
                        <button type="button" className="underline" disabled={busy === row.id} onClick={() => void decide(row, 'reopen')}>פתח מחדש</button>
                      )}
                    </td>
                  ) : null}
                </tr>
                {panelOpen && panel.kind === 'many' ? (
                  <tr>
                    <td colSpan={7}>{manyPanel(row)}</td>
                  </tr>
                ) : null}
                {panelOpen && panel.kind === 'category' ? (
                  <tr>
                    <td colSpan={7}>
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <select value={category} onChange={(event) => setCategory(event.target.value)}>
                          <option value="">קטגוריה…</option>
                          {Object.entries(report.categories || {}).map(([id, label]) => (
                            <option key={id} value={id}>{label}</option>
                          ))}
                        </select>
                        <input
                          className="w-32 border px-1"
                          placeholder="כרטיס יעד"
                          maxLength={40}
                          value={account}
                          onChange={(event) => setAccount(event.target.value)}
                        />
                        <button type="button" className="underline" disabled={busy === row.id} onClick={() => void decide(row, 'approve_category')}>אשר לפי קטגוריה</button>
                        <span className="text-xs text-stone-500">בלי מסמך: חו״ז בעלים, שכר, הלוואה, ניכיון, סליקה. הכרטיס נקבע על ידכם.</span>
                      </div>
                    </td>
                  </tr>
                ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      ) : null}
      {report && rows.length === 0 ? <p className="mt-2 text-sm text-stone-600">אין תנועות בסינון הזה בחלון {report.start}–{report.end}.</p> : null}
    </section>
  );
}
