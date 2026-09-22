import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
import DocumentDerivationForm from './DocumentDerivationForm';
import DocumentSourcePreview from './DocumentSourcePreview';

interface SourceDocument {
  id: number; filename: string; media_type: string; status: string; version: number;
  attempts: number; amount: string | null; expense_id: number | null; updated_at: string;
  sources: { channel: string; filename: string }[];
  filing?: { approval_status: string; provider_document_id: string | null; error: string | null } | null;
  lineage?: { reason: string; parents: { document_id: number; pages: number[] }[] } | null;
  result: { message?: string; extracted?: Record<string, unknown>;
    source_review?: { actor_id: number; reason: string; reviewed_at: string } } | null;
}
const states: Record<string, string> = { queued: 'ממתין לחילוץ', processing: 'בטיפול — אין להפעיל שוב',
  created: 'טיוטת הוצאה נוצרה', duplicate: 'כפילות לבדיקה', error: 'החילוץ נכשל',
  unreadable: 'מקור לא קריא', needs_review: 'נדרשת השלמת ראיות', non_accounting: 'אינו מסמך הוצאה',
  disabled: 'החילוץ אינו מופעל', limit_reached: 'המכסה מוצתה', superseded: 'מקור שמור — הטיפול עבר למסמכים הנגזרים' };
const filingStates: Record<string, string> = { not_proposed: 'טרם הוכנה הצעת תיוק', proposed: 'הצעת התיוק ממתינה לחתימה',
  approved: 'הצעת התיוק אושרה, טרם בוצעה', executing: 'בקשת הספק בטיפול', executed: 'התקבל מזהה ספק; נדרש אימות מסמך וספרים',
  failed: 'תוצאת הספק אינה ידועה — נדרשת בדיקה', rejected: 'הצעת התיוק נדחתה' };
const fields: Record<string, string> = { supplier_name: 'ספק', supplier_tax_id: 'מספר עוסק',
  expense_date: 'תאריך המסמך', invoice_number: 'מספר מסמך', amount_total: 'סכום כולל',
  net_amount: 'לפני מע״מ', vat_amount: 'מע״מ במסמך', currency: 'מטבע', document_type: 'סוג מסמך' };
const errorText = (error: unknown) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : 'הפעולה נכשלה. יש לבדוק הרשאות ולרענן את הנתונים.';
};

export default function DocumentIntakePanel() {
  const cache = useQueryClient();
  const [selected, select] = useState<number | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [review, setReview] = useState<{ documentId: number; version: number; fields: Record<string, string>; reason: string } | null>(null);
  const query = useQuery({ queryKey: ['document-intake', offset],
    queryFn: () => api.get<{ documents: SourceDocument[]; total: number }>('/expenses/intake', { params: { limit: 25, offset } }) });
  const listed = query.data?.documents.find(row => row.id === selected);
  const selectedQuery = useQuery({ queryKey: ['document-intake-detail', selected],
    queryFn: () => api.get<SourceDocument>(`/expenses/intake/${selected}`), enabled: selected !== null && !listed });
  const document = listed || selectedQuery.data;
  useEffect(() => { setPreview(null); setReview(null); }, [selected]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const refresh = () => {
    cache.invalidateQueries({ queryKey: ['document-intake'] });
    cache.invalidateQueries({ queryKey: ['document-intake-detail'] });
    cache.invalidateQueries({ queryKey: ['expenses'] });
  };
  const process = useMutation({
    mutationFn: (row: SourceDocument) => api.post<{ message?: string }>(`/expenses/intake/${row.id}/process`,
      { version: row.version, retry: row.status !== 'queued' }),
    onSuccess: result => { setMessage(result.message || 'מצב הטיפול עודכן'); refresh(); },
    onError: error => { setMessage(errorText(error)); refresh(); },
  });
  const saveReview = useMutation({
    mutationFn: () => {
      if (!review) throw new Error('Missing review');
      const amounts = ['amount_total', 'net_amount', 'vat_amount'];
      const corrected = Object.fromEntries(Object.entries(review.fields).map(([key, value]) =>
        [key, value === '' ? null : amounts.includes(key) ? Number(value) : value]));
      return api.post<{ message?: string }>(`/expenses/intake/${review.documentId}/review`,
        { version: review.version, reason: review.reason, fields: corrected });
    },
    onSuccess: result => { setMessage(result.message || 'בדיקת המקור נשמרה. הטיוטה עדיין ממתינה לאישור חשבונאי.'); setReview(null); refresh(); },
    onError: error => { setMessage(errorText(error)); refresh(); },
  });
  async function upload(files: FileList | null) {
    if (!files) return;
    setBusy(true);
    const outcomes: string[] = [];
    for (const file of Array.from(files)) {
      try {
        if (file.size > 10 * 1024 * 1024) throw new Error('Source too large');
        const encoded = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = reject; reader.readAsDataURL(file);
        });
        const result = await api.post<{ status: string; document_id: number }>('/expenses/intake',
          { content_base64: encoded, filename: file.name, media_type: file.type });
        outcomes.push(`${file.name}: ${result.status === 'duplicate' ? 'כבר נקלט' : 'נשמר בתור'}`);
        select(result.document_id);
      } catch { outcomes.push(`${file.name}: לא נשמר — יש לבדוק סוג קובץ, גודל והרשאות`); }
    }
    setMessage(outcomes.join(' · ')); setBusy(false); refresh();
  }
  async function showSource(row: SourceDocument) {
    try {
      const blob = await api.get<Blob>(`/expenses/intake/${row.id}/source`, { responseType: 'blob' });
      setPreview(URL.createObjectURL(blob));
    } catch (error) { setMessage(errorText(error)); }
  }
  return <section dir="rtl" className="rounded-xl border p-4 space-y-4 min-w-0" aria-label="תור מסמכי מקור">
    <h2 className="text-xl font-bold">מסמכי מקור ובדיקת ראיות</h2>
    <p className="text-sm">כל קובץ נשמר בנפרד. שמירת מקור ויצירת טיוטה אינן אישור חשבונאי או קליטה בספרים.</p>
    <label className="block">העלאת מסמכים — PDF או תמונה, עד 10MB לקובץ
      <input type="file" multiple accept="application/pdf,image/png,image/jpeg,image/webp,image/tiff"
        disabled={busy} onChange={event => { void upload(event.target.files); event.target.value = ''; }} className="block max-w-full mt-2" />
    </label>
    {busy && <p role="status">שומר מסמכים…</p>}
    {message && <p role="status" className="break-words">{message}</p>}
    {query.isLoading && <p role="status">טוען מסמכים…</p>}
    {query.isError && <div role="alert">טעינת התור נכשלה. <button onClick={() => query.refetch()}>ניסיון נוסף</button></div>}
    <DocumentDerivationForm documents={query.data?.documents || []} onComplete={refresh} />
    <div className="grid md:grid-cols-2 gap-4 min-w-0">
      <div className="space-y-2 min-w-0">
        {query.data?.documents.length === 0 && <p>אין מסמכים בתור.</p>}
        {query.data?.documents.map(row => <button key={row.id} onClick={() => select(row.id)}
          aria-pressed={selected === row.id} className="block w-full text-right border rounded-lg p-3 break-words">
          <strong>{row.filename}</strong><br />{states[row.status] || row.status}
          <span className="block text-sm">סכום: {row.amount ?? 'לא ידוע'} · ניסיונות חילוץ: {row.attempts}</span>
        </button>)}
        <div className="flex gap-3">
          <button disabled={offset === 0} onClick={() => { setOffset(offset - 25); select(null); }}>הקודם</button>
          <button disabled={offset + 25 >= (query.data?.total ?? 0)} onClick={() => { setOffset(offset + 25); select(null); }}>הבא</button>
        </div>
      </div>
      {document && <article className="space-y-3 min-w-0">
        <h3 className="font-bold break-words">בדיקת {document.filename}</h3>
        <p>עדכון: {new Date(document.updated_at).toLocaleString('he-IL')}</p>
        <p>ערוצי מקור: {document.sources.map(s => s.channel).join(', ')}</p>
        {document.lineage && <div className="border rounded p-2 space-y-2">
          <h4 className="font-semibold">מקור העמודים</h4><p>{document.lineage.reason}</p>
          {document.lineage.parents.map(parent => <button key={parent.document_id} className="block underline" onClick={() => select(parent.document_id)}>
            עיון במקור — עמודים {parent.pages.join(', ')}
          </button>)}
        </div>}
        <button className="border rounded p-2" onClick={() => showSource(document)}>הצגת המקור</button>
        {preview && <>
          <a href={preview} download={document.filename} className="block underline">הורדת המקור השמור</a>
          <DocumentSourcePreview key={document.id} documentId={document.id} />
        </>}
        <dl className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(fields).map(([key, label]) => <div key={key} className="min-w-0 break-words">
            <dt className="font-semibold">{label}</dt><dd>{String(document.result?.extracted?.[key] ?? 'לא ידוע')}</dd>
          </div>)}
        </dl>
        <p>{document.result?.message}</p>
        {document.result?.source_review && <div className="border rounded p-2">
          <h4 className="font-semibold">בדיקת מקור מתועדת</h4>
          <p>{document.result.source_review.reason}</p>
          <p>{new Date(document.result.source_review.reviewed_at).toLocaleString('he-IL')}</p>
        </div>}
        <p>אישור וקליטה בספרים: טרם אומתו כאן. תשלום: אין ראיה מקושרת.</p>
        {document.filing && <div className="border rounded p-2 space-y-1">
          <p>{filingStates[document.filing.approval_status] || 'יש לעיין בסטטוס התיוק המפורט'}</p>
          {document.filing.provider_document_id && <p>מזהה ספק: <bdi>{document.filing.provider_document_id}</bdi></p>}
          {document.filing.error && <p role="alert">{document.filing.error}</p>}
        </div>}
        {document.expense_id && <a href={`#expense-${document.expense_id}`} className="underline">מעבר לטיוטת הוצאה #{document.expense_id}</a>}
        {['queued', 'error', 'unreadable', 'disabled', 'limit_reached'].includes(document.status) &&
          <button disabled={process.isPending || document.attempts >= 3} onClick={() => process.mutate(document)} className="border rounded p-2 disabled:opacity-50">
            {process.isPending ? 'מחלץ…' : document.status === 'queued' ? 'חילוץ נתונים לפי מכסת הארגון' : 'ניסיון חילוץ נוסף'}
          </button>}
        {document.status === 'processing' && <p role="alert">אם הטיפול נקטע, נדרשת בדיקה לפני ניסיון נוסף כדי למנוע ביצוע כפול.</p>}
        {!document.expense_id && !['processing', 'created', 'duplicate', 'superseded'].includes(document.status) && !review &&
          <button className="border rounded p-2" onClick={() => setReview({ documentId: document.id, version: document.version,
            reason: '', fields: Object.fromEntries(Object.keys(fields).map(key => [key, String(document.result?.extracted?.[key] ?? '')])) })}>תיקון נתונים מהמקור</button>}
        {review && <form className="space-y-3 border rounded p-3" onSubmit={event => { event.preventDefault(); saveReview.mutate(); }}>
          <p>יש לבדוק מול המקור. השמירה יוצרת טיוטה בלבד, ללא אישור חשבונאי או תשלום.</p>
          <div className="grid sm:grid-cols-2 gap-3">
            {Object.entries(fields).map(([key, label]) => <label key={key} className="min-w-0">תיקון {label}
              {key === 'document_type' ? <select className="block border rounded p-2 w-full" aria-label={`תיקון ${label}`} value={review.fields[key]}
                onChange={event => setReview({ ...review, fields: { ...review.fields, [key]: event.target.value } })}>
                <option value="">לא ידוע</option><option value="unknown">דורש בירור</option>
                <option value="tax_invoice">חשבונית מס</option><option value="invoice">חשבונית</option>
                <option value="invoice_receipt">חשבונית מס קבלה</option><option value="receipt">קבלה</option>
                <option value="not_accounting">אינו מסמך חשבונאי</option>
              </select> : <input className="block border rounded p-2 w-full min-w-0" value={review.fields[key]}
                type={key === 'expense_date' ? 'date' : ['amount_total', 'net_amount', 'vat_amount'].includes(key) ? 'number' : 'text'} step="0.01"
                onChange={event => setReview({ ...review, fields: { ...review.fields, [key]: event.target.value } })} />}
            </label>)}
          </div>
          <label className="block">סיבת התיקון והראיה שנבדקה<textarea className="block border rounded p-2 w-full" minLength={20} maxLength={2000} required
            value={review.reason} onChange={event => setReview({ ...review, reason: event.target.value })} /></label>
          <div className="flex flex-wrap gap-2">
            <button disabled={saveReview.isPending} className="border rounded p-2" type="submit">שמירת בדיקת המקור</button>
            <button type="button" disabled={saveReview.isPending} onClick={() => setReview(null)}>ביטול העריכה</button>
          </div>
        </form>}
      </article>}
    </div>
  </section>;
}
