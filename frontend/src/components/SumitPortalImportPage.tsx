import { useEffect, useState, type FormEvent } from 'react';

type UnmappedLine = { code: string | null; name: string; reason: string | null; amount?: number | null };

type ImportResult = {
  kind: string;
  as_of: string;
  as_of_source: string;
  imported_at: string;
  filename: string;
  inserted: number;
  updated: number;
  unchanged: number;
  removed: number;
  mapped_count: number;
  unmapped_count: number;
  unmapped: UnmappedLine[];
  provider_calls: number;
};

type SnapshotSummary = {
  kind: string;
  as_of: string | null;
  imported_at: string | null;
  filename: string | null;
  line_count: number;
  mapped_count: number;
  unmapped_count: number;
  unmapped: UnmappedLine[];
} | null;

type SnapshotList = {
  balance_sheet: SnapshotSummary;
  profit_loss: SnapshotSummary;
  ledger_cards: SnapshotSummary;
};

const KIND_LABELS: Record<string, string> = {
  balance_sheet: 'מאזן',
  profit_loss: 'רווח והפסד',
  ledger_cards: 'כרטיסי הנה״ח',
};

function authHeaders(): HeadersInit {
  const headers: Record<string, string> = {};
  const token = localStorage.getItem('auth_token');
  if (token) headers.Authorization = `Bearer ${token}`;
  const activeOrg = localStorage.getItem('active_org_id');
  if (activeOrg) headers['X-Active-Org-Id'] = activeOrg;
  return headers;
}

function detailOf(body: { detail?: unknown }): string {
  const detail = body.detail;
  if (typeof detail === 'string') return detail;
  return 'הייבוא נכשל';
}

export default function SumitPortalImportPage({ darkMode = false }: { darkMode?: boolean }) {
  const [kind, setKind] = useState('');
  const [asOf, setAsOf] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [stored, setStored] = useState<SnapshotList | null>(null);
  const card = darkMode ? 'border-gray-700 bg-gray-800 text-gray-100' : 'border-gray-200 bg-white text-gray-900';
  const muted = darkMode ? 'text-gray-400' : 'text-gray-600';

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const response = await fetch('/api/admin/sumit-portal-imports', { headers: authHeaders() });
      const body = await response.json().catch(() => ({}));
      if (!cancelled && response.ok) setStored(body as SnapshotList);
    })();
    return () => {
      cancelled = true;
    };
  }, [result]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setPending(true);
    setError(null);
    const form = new FormData();
    form.append('file', file);
    if (kind) form.append('kind', kind);
    if (asOf) form.append('as_of', asOf);
    const response = await fetch('/api/admin/sumit-portal-imports', {
      method: 'POST',
      headers: authHeaders(),
      body: form,
    });
    const body = await response.json().catch(() => ({}));
    setPending(false);
    if (!response.ok) {
      setError(detailOf(body));
      return;
    }
    setResult(body as ImportResult);
  }

  return (
    <div dir="rtl" className="mx-auto max-w-3xl p-4 sm:p-6">
      <h1 className="text-xl font-semibold">ייבוא ייצוא מפורטל SUMIT</h1>
      <p className={`mt-2 text-sm ${muted}`}>
        מייצאים מהפורטל לקובץ CSV או xlsx: מאזן, רווח והפסד, או כרטיסי הנה״ח.
        העמודות: מפתח, שם חשבון, סעיף (נכסים / התחייבויות / הון / הכנסות / הוצאות), ויתרה או סכום.
        בכרטיס אפשר גם תאריך, אסמכתא, חובה וזכות. שורה בלי סכום נשארת לא ידועה, לא אפס.
        ייבוא חוזר של אותו דוח ואותו תאריך לא מכפיל שורות. אין קריאה לסאמית.
      </p>
      <form onSubmit={onSubmit} className={`mt-4 grid gap-3 rounded-lg border p-4 ${card}`} aria-busy={pending}>
        <label className="grid gap-1 text-sm">
          סוג הדוח
          <select className="rounded-md border px-2 py-2" value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="">זיהוי לפי הקובץ</option>
            <option value="balance_sheet">מאזן</option>
            <option value="profit_loss">רווח והפסד</option>
            <option value="ledger_cards">כרטיסי הנה״ח</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          תאריך הדוח
          <input className="rounded-md border px-2 py-2" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          קובץ
          <input
            className="text-sm"
            type="file"
            accept=".csv,.xlsx,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button
          type="submit"
          className="rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={pending || !file}
        >
          {pending ? 'מייבא…' : 'ייבוא'}
        </button>
      </form>
      {error ? <p className="mt-3 text-sm text-red-700" role="alert">{error}</p> : null}
      {result ? (
        <section className={`mt-4 rounded-lg border p-4 text-sm ${card}`} role="status">
          <h2 className="font-medium">{KIND_LABELS[result.kind] || result.kind} · {result.as_of}</h2>
          <p className={`mt-2 ${muted}`}>תאריך ייבוא {result.imported_at.slice(0, 10)} · {result.filename}</p>
          <p className="mt-2">
            חדשות {result.inserted} · עודכנו {result.updated} · ללא שינוי {result.unchanged} · הוסרו {result.removed}
            · מופו {result.mapped_count} · לא מופו {result.unmapped_count}
          </p>
          {result.unmapped.length > 0 ? (
            <ul className="mt-2">
              {result.unmapped.map((line) => (
                <li key={`${line.code || ''}-${line.name}`}>{line.code} {line.name}: {line.reason}</li>
              ))}
            </ul>
          ) : null}
          <p className={`mt-2 ${muted}`}>התוצאה מופיעה בלשונית מאזן בדשבורד הלקוח, עם תאריך הסנכרון.</p>
        </section>
      ) : null}
      <section className="mt-6 grid gap-3">
        <h2 className="text-sm font-medium">מה שמור עכשיו</h2>
        {(['balance_sheet', 'profit_loss', 'ledger_cards'] as const).map((key) => {
          const row = stored?.[key];
          return (
            <p key={key} className={`rounded-lg border p-3 text-sm ${card}`}>
              {KIND_LABELS[key]}: {row ? `${row.line_count} שורות · ${row.as_of || 'תאריך לא ידוע'} · יובא ${row.imported_at ? row.imported_at.slice(0, 10) : 'בתאריך לא ידוע'}` : 'לא ידוע'}
              {row && row.unmapped_count > 0 ? ` · ${row.unmapped_count} לא מופו` : ''}
            </p>
          );
        })}
      </section>
    </div>
  );
}
