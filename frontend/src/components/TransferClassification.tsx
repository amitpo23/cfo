import { useEffect, useState } from 'react';

type Suggestion = {
  category: string;
  label_he: string;
  suggestion: true;
  source: string;
  reason_he: string;
};

type TransferRow = {
  id: number;
  date: string;
  amount: number;
  counterparty: string;
  description: string;
  suggestion: Suggestion | null;
};

type Category = { category: string; label_he: string };

type Queue = {
  start: string;
  end: string;
  rows: TransferRow[];
  coverage: {
    classified: number;
    unclassified: number;
    total: number;
    balanced: boolean;
    unclassified_count: number;
    by_category: { category: string; label_he: string; amount: number }[];
  };
  categories: Category[];
};

function money(value: number): string {
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(value);
}

export default function TransferClassification({ dashboardId, slug }: { dashboardId?: number; slug?: string }) {
  const token = localStorage.getItem('auth_token') || '';
  const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
  const listUrl = dashboardId
    ? `/api/dashboards/${dashboardId}/unclassified-transfers?start=2026-07-01&end=2026-10-31`
    : `/api/public/d/${slug}/unclassified-transfers?start=2026-07-01&end=2026-10-31`;
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Record<number, string>>({});
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [notice, setNotice] = useState<string | null>(null);

  async function load(nextHeaders: HeadersInit = headers) {
    const response = await fetch(listUrl, { headers: nextHeaders, credentials: 'include' });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(body.error?.message_he || 'לא ניתן לטעון את התנועות');
      return;
    }
    setQueue(body);
    setError(null);
  }

  useEffect(() => {
    let cancelled = false;
    const requestHeaders: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
    fetch(listUrl, { headers: requestHeaders, credentials: 'include' })
      .then((response) => response.json().then((body) => ({ ok: response.ok, body })))
      .then(({ ok, body }) => {
        if (cancelled) return;
        if (!ok) {
          setError(body.error?.message_he || 'לא ניתן לטעון את התנועות');
          return;
        }
        setQueue(body);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError('לא ניתן לטעון את התנועות');
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, token, listUrl]);

  async function accept(rows: TransferRow[]) {
    const accepts = rows.map((row) => ({
      counterparty: row.counterparty,
      category: chosen[row.id] || row.suggestion?.category || '',
    })).filter((item) => item.counterparty && item.category);
    if (!accepts.length) {
      setNotice('בחרו קטגוריה. אין סיווג בלי בחירה.');
      return;
    }
    if (!dashboardId) {
      setNotice('אישור סיווג זמין לבעלים מחובר.');
      return;
    }
    const response = await fetch(`/api/dashboards/${dashboardId}/classification-rules`, {
      method: 'POST', headers: { ...headers as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ accepts }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      setNotice(body.error?.message_he || 'השמירה נכשלה');
      return;
    }
    setNotice('הכלל נשמר. העברות חדשות של אותו צד נגדי יסווגו כך.');
    setPicked({});
    await load();
  }

  const coverage = queue?.coverage;
  return (
    <section className="d-card" dir="rtl">
      <h2>העברות לא מסווגות</h2>
      <p className="mt-1 text-sm text-stone-600">הצעה אינה סיווג. הקטגוריה נשמרת רק כשהבעלים מאשר, ואז ככלל לצד הנגדי.</p>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
      {notice ? <p className="mt-2 text-sm text-amber-800">{notice}</p> : null}
      {coverage ? (
        <p className="mt-3 text-sm">
          מסווג {money(coverage.classified)} + לא מסווג {money(coverage.unclassified)} = סה״כ {money(coverage.total)}
          {coverage.balanced ? ' · הכיסוי מאוזן' : ' · הכיסוי אינו מאוזן'}
          {' · '}{coverage.unclassified_count} תנועות
        </p>
      ) : null}
      {queue ? (
        <>
          <button type="button" className="mt-3 text-sm underline" onClick={() => void accept(queue.rows.filter((row) => picked[row.id]))}>
            אשר את המסומנות
          </button>
          <table className="mt-3 d-table">
            <thead>
              <tr><th></th><th>תאריך</th><th>סכום</th><th>צד נגדי</th><th>תיאור</th><th>הצעה</th><th>קטגוריה</th></tr>
            </thead>
            <tbody>
              {queue.rows.map((row) => (
                <tr key={row.id}>
                  <td><input type="checkbox" checked={picked[row.id] === true} onChange={(event) => setPicked({ ...picked, [row.id]: event.target.checked })} /></td>
                  <td>{row.date}</td>
                  <td>{money(row.amount)}</td>
                  <td>{row.counterparty || '—'}</td>
                  <td>{row.description}</td>
                  <td className="text-xs text-stone-600">{row.suggestion ? row.suggestion.reason_he : 'אין הצעה — לא מנחשים'}</td>
                  <td>
                    <select
                      value={chosen[row.id] ?? row.suggestion?.category ?? ''}
                      onChange={(event) => setChosen({ ...chosen, [row.id]: event.target.value })}
                    >
                      <option value="">בחרו</option>
                      {queue.categories.map((item) => <option key={item.category} value={item.category}>{item.label_he}</option>)}
                    </select>
                    <button type="button" className="mr-2 text-sm underline" onClick={() => void accept([row])}>אשר</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {queue.rows.length === 0 ? <p className="mt-2 text-sm text-stone-600">אין תנועות לא מסווגות בחלון {queue.start}–{queue.end}.</p> : null}
        </>
      ) : null}
    </section>
  );
}
