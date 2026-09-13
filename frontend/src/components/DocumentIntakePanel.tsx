import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

interface SourceDocument {
  id: number; filename: string; media_type: string; status: string; version: number;
  attempts: number; amount: string | null; expense_id: number | null; updated_at: string;
  sources: { channel: string; filename: string }[];
  result: { message?: string; extracted?: Record<string, unknown> } | null;
}
const states: Record<string, string> = { queued: 'ממתין לחילוץ', processing: 'בטיפול — אין להפעיל שוב',
  created: 'טיוטת הוצאה נוצרה', duplicate: 'כפילות לבדיקה', error: 'החילוץ נכשל',
  unreadable: 'מקור לא קריא', needs_review: 'נדרשת השלמת ראיות', non_accounting: 'אינו מסמך הוצאה',
  disabled: 'החילוץ אינו מופעל', limit_reached: 'המכסה מוצתה' };
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
  const query = useQuery({ queryKey: ['document-intake', offset],
    queryFn: () => api.get<{ documents: SourceDocument[]; total: number }>('/expenses/intake', { params: { limit: 25, offset } }) });
  const document = query.data?.documents.find(row => row.id === selected);
  useEffect(() => { setPreview(null); }, [selected]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const refresh = () => {
    cache.invalidateQueries({ queryKey: ['document-intake'] });
    cache.invalidateQueries({ queryKey: ['expenses'] });
  };
  const process = useMutation({
    mutationFn: (row: SourceDocument) => api.post<{ message?: string }>(`/expenses/intake/${row.id}/process`,
      { version: row.version, retry: row.status !== 'queued' }),
    onSuccess: result => { setMessage(result.message || 'מצב הטיפול עודכן'); refresh(); },
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
        <button className="border rounded p-2" onClick={() => showSource(document)}>הצגת המקור</button>
        {preview && (document.media_type.startsWith('image/') ? <img src={preview} alt="המסמך המקורי" className="max-w-full" /> :
          <iframe title="המסמך המקורי" src={preview} sandbox="" className="w-full h-80 border" />)}
        <dl className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(fields).map(([key, label]) => <div key={key} className="min-w-0 break-words">
            <dt className="font-semibold">{label}</dt><dd>{String(document.result?.extracted?.[key] ?? 'לא ידוע')}</dd>
          </div>)}
        </dl>
        <p>{document.result?.message}</p>
        <p>אישור וקליטה בספרים: טרם אומתו כאן. תשלום: אין ראיה מקושרת.</p>
        {document.expense_id && <a href={`#expense-${document.expense_id}`} className="underline">מעבר לטיוטת הוצאה #{document.expense_id}</a>}
        {['queued', 'error', 'unreadable', 'disabled', 'limit_reached'].includes(document.status) &&
          <button disabled={process.isPending || document.attempts >= 3} onClick={() => process.mutate(document)} className="border rounded p-2 disabled:opacity-50">
            {process.isPending ? 'מחלץ…' : document.status === 'queued' ? 'חילוץ נתונים לפי מכסת הארגון' : 'ניסיון חילוץ נוסף'}
          </button>}
        {document.status === 'processing' && <p role="alert">אם הטיפול נקטע, נדרשת בדיקה לפני ניסיון נוסף כדי למנוע ביצוע כפול.</p>}
      </article>}
    </div>
  </section>;
}
