import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

type Payload = { expense_id: number; document_id: number; amount: string; currency: string;
  provider_target: { company_id: string; connection_id: number | null };
  source_fields: { supplier_name: string; supplier_tax_id: string; invoice_number: string; expense_date: string;
    amount: string; vat_amount: string; category: string; doc_kind: string; filename: string; media_type: string } };
type FilingState = { approval_request_id: number | null; approval_status: string; approval_payload: Payload | null;
  provider_document_id: string | null; error: string | null; blocking_reason: string | null; official_books_verified: boolean };
const states: Record<string, string> = { not_proposed: 'טרם הוכנה הצעה', proposed: 'ממתין לאישור מורשה חתימה', approved: 'אושר לביצוע',
  executing: 'בקשת הספק בטיפול — אין להפעיל שוב', executed: 'הספק החזיר מזהה — נדרש אימות מסמך וספרים',
  failed: 'התוצאה אינה ידועה — נדרשת בדיקה לפני כל פעולה נוספת', verification_failed: 'אימות הספק לא הושלם', rejected: 'ההצעה נדחתה', verified: 'נשמרה ראיית אימות לפעולה; אינה אישור סגירת ספרים' };
const kinds: Record<string, string> = { tax_invoice: 'חשבונית מס', receipt: 'קבלה', unknown: 'דורש בירור' };
export default function ExpenseFilingWorkbench({ expenseId, onClose }: { expenseId: number; onClose: () => void }) {
  const cache = useQueryClient();
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['expense-filing', expenseId],
    queryFn: () => api.get<FilingState>(`/expenses/${expenseId}/filing-status`) });
  const state = query.data, payload = state?.approval_payload, fields = payload?.source_fields;
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const refresh = () => {
    cache.invalidateQueries({ queryKey: ['expense-filing', expenseId] });
    cache.invalidateQueries({ queryKey: ['expenses'] });
    cache.invalidateQueries({ queryKey: ['document-intake'] });
  };
  const errorMessage = (error: unknown) => {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    return typeof detail === 'string' ? detail : 'הפעולה לא הושלמה. יש לבדוק הרשאה, גרסת מקור ותוצאת ספק.';
  };
  async function act(path: string, body: object, success: string, approvalId?: number) {
    setBusy(true);
    try {
      await api.post(path, body, approvalId ? { headers: { 'X-Rezef-Approval-Id': String(approvalId) } } : undefined);
      setMessage(success); refresh();
    } catch (error) { setMessage(errorMessage(error)); refresh(); }
    finally { setBusy(false); }
  }
  async function showSource() {
    if (!payload) return;
    try { setPreview(URL.createObjectURL(await api.get<Blob>(`/expenses/intake/${payload.document_id}/source`, { responseType: 'blob' }))); }
    catch (error) { setMessage(errorMessage(error)); }
  }
  return <section dir="rtl" aria-label="אישור תיוק מקור" className="rounded-xl border p-4 space-y-3 min-w-0">
    <div className="flex flex-wrap gap-3 justify-between"><h2 className="text-xl font-semibold">מסלול תיוק הוצאה #{expenseId}</h2><button onClick={onClose}>סגירת התצוגה</button></div>
    <p>ההצעה מבקשת לשמור טיוטת הוצאה אצל הספק. אישור ההצעה, קבלת מזהה, בדיקה חשבונאית וקליטה בספרים הם שלבים נפרדים. אין כאן ביצוע תשלום.</p>
    {query.isLoading && <p role="status">טוען הצעה וראיות…</p>}
    {query.isError && <p role="alert">לא ניתן לטעון את ההוצאה. <button onClick={() => query.refetch()}>ניסיון נוסף</button></p>}
    {state && <>
      <p className="font-semibold">{states[state.approval_status] || state.approval_status}</p>
      {state.blocking_reason && <p role="alert">{state.blocking_reason}</p>}
      {state.error && <p role="alert">{state.error}</p>}
      {payload && fields && <div className="grid md:grid-cols-2 gap-4 min-w-0">
        <dl className="grid grid-cols-2 gap-2 break-words">
          <div><dt>ספק במקור</dt><dd>{fields.supplier_name}</dd></div><div><dt>מספר עוסק</dt><dd>{fields.supplier_tax_id}</dd></div>
          <div><dt>חברת היעד ב-SUMIT</dt><dd><bdi>{payload.provider_target.company_id}</bdi></dd></div>
          <div><dt>מספר מסמך</dt><dd>{fields.invoice_number}</dd></div><div><dt>תאריך מקור</dt><dd>{fields.expense_date}</dd></div>
          <div><dt>סכום כולל</dt><dd>{payload.amount} {payload.currency}</dd></div><div><dt>לפני מע״מ</dt><dd>{fields.amount}</dd></div>
          <div><dt>מע״מ במקור</dt><dd>{fields.vat_amount}</dd></div><div><dt>סוג מקור</dt><dd>{kinds[fields.doc_kind] || fields.doc_kind}</dd></div>
          <div><dt>סיווג ההוצאה</dt><dd>{fields.category}</dd></div><div><dt>קובץ מקור</dt><dd><bdi>{fields.filename}</bdi></dd></div>
        </dl>
        <div className="space-y-2 min-w-0"><button className="border rounded p-2" onClick={() => void showSource()}>הצגת המקור להצעה</button>
          {preview && (fields.media_type.startsWith('image/') ? <img src={preview} alt="מקור להצעת תיוק" className="max-w-full" /> :
            <iframe sandbox="" title="מקור להצעת תיוק" src={preview} className="w-full h-80 border" />)}</div>
      </div>}
      {state.provider_document_id && <p>מזהה שהספק החזיר: {state.provider_document_id}. קיום המסמך, הסיווג והספרים עדיין דורשים ראיה.</p>}
      {['not_proposed', 'rejected'].includes(state.approval_status) && !state.blocking_reason && <form className="space-y-2" onSubmit={event => {
        event.preventDefault(); void act(`/expenses/${expenseId}/filing-proposal`, { reason }, 'ההצעה נשמרה. נדרש אישור מורשה חתימה לפי מדיניות הארגון.');
      }}><label className="block">סיבת הצעת התיוק<textarea className="block border rounded p-2 w-full" required minLength={20} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
        <button disabled={busy} className="border rounded p-2">שמירת הצעה לאישור תיוק</button></form>}
      {state.approval_request_id && <div className="flex flex-wrap gap-2">
        {state.approval_status === 'proposed' && <>
          <button disabled={busy || !!state.blocking_reason} className="border rounded p-2" onClick={() => void act(`/approvals/${state.approval_request_id}/approve`, {}, 'אישור החתימה נשמר; בקשת הספק טרם בוצעה.')}>אישור ההצעה המדויקת</button>
          <button disabled={busy} className="border rounded p-2" onClick={() => void act(`/approvals/${state.approval_request_id}/reject`, {}, 'ההצעה נדחתה ללא בקשת ספק.')}>דחיית ההצעה</button>
        </>}
        {state.approval_status === 'approved' && <button disabled={busy || !!state.blocking_reason} className="border rounded p-2" onClick={() => void act(`/expenses/${expenseId}/file`, {}, 'הבקשה נשלחה והספק החזיר מזהה. זה אינו אישור קליטה בספרים.', state.approval_request_id || undefined)}>ביצוע בקשת הטיוטה המאושרת</button>}
        {state.approval_status === 'approved' && <div className="w-full space-y-2">
          <label>סיבת ביטול האישור לפני ביצוע<textarea className="block border rounded p-2 w-full" minLength={20} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
          <button disabled={busy || reason.trim().length < 20} className="border rounded p-2" onClick={() => void act(`/approvals/${state.approval_request_id}/reject`, { reason }, 'האישור בוטל לפני ביצוע. לא בוטל מסמך ספק ולא בוצע החזר.')}>ביטול האישור בידי מורשה חתימה</button>
        </div>}
      </div>}
    </>}
    {message && <p role="status" className="break-words">{message}</p>}
    <button onClick={() => query.refetch()} className="underline">רענון מצב שמור</button>
  </section>;
}
