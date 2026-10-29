/**
 * Hebrew document issuance. SUMIT writes go through the existing
 * /financial/documents approval gate. Local drafts do not call SUMIT.
 */
import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import apiService from '../services/api';

type DocType = { value: string; label: string };
type ContactSuggestion = {
  id: number;
  name: string;
  email?: string | null;
  external_id?: string | null;
};
type Line = { description: string; quantity: number; price: number; vatRate: number };
type Created = {
  id: number;
  document_label?: string;
  document_number?: string | null;
  external_id?: string | null;
  total?: number;
  sumit?: { pdf_url?: string | null } | null;
};
type IssuedRow = {
  id?: number;
  external_id?: string;
  document_number?: string;
  document_type: string;
  document_label?: string;
  total?: number;
  total_amount?: number;
  status: string;
  issue_date?: string;
};

const FALLBACK_TYPES: DocType[] = [
  { value: 'invoice', label: 'חשבונית מס' },
  { value: 'receipt', label: 'קבלה' },
  { value: 'invoice_receipt', label: 'חשבונית מס קבלה' },
  { value: 'credit_note', label: 'חשבונית זיכוי' },
  { value: 'quote', label: 'הצעת מחיר' },
  { value: 'proforma', label: 'חשבונית עסקה' },
  { value: 'order', label: 'הזמנה' },
  { value: 'purchase_order', label: 'הזמנת רכש' },
  { value: 'work_order', label: 'הזמנת עבודה' },
  { value: 'delivery_note', label: 'תעודת משלוח' },
  { value: 'payment_request', label: 'דרישת תשלום' },
];

function money(value: number): string {
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 2 }).format(value);
}

function lineMath(line: Line) {
  const net = line.quantity * line.price;
  const tax = net * (line.vatRate / 100);
  return { net, tax, total: net + tax };
}

function hebrewError(err: unknown): string {
  const response = (err as { response?: { status?: number; data?: { detail?: unknown; code?: string } } })?.response;
  const code = response?.data?.code;
  if (code === 'request_budget_exceeded') return 'נגמרה מכסת הקריאות ל-SUMIT. המסמך לא הופק.';
  if (code === 'request_budget_unavailable') return 'לא ניתן לאמת את מכסת SUMIT, ולכן ההפקה נעצרה.';
  if (response?.status === 409) return 'הפקה ב-SUMIT דורשת אישור. אשרו את הסיכום, או שמרו טיוטה מקומית בלי שליחה.';
  if (response?.status === 403) return 'אין הרשאה להפיק את המסמך.';
  if (response?.status === 502) return 'SUMIT לא אישר את המסמך. לא נשמר מסמך כאילו הופק.';
  const detail = response?.data?.detail;
  if (typeof detail === 'string' && /[\u0590-\u05FF]/.test(detail)) return detail;
  return 'הפקת המסמך נכשלה.';
}

export const DocumentManager: React.FC = () => {
  const queryClient = useQueryClient();
  const [documentType, setDocumentType] = useState('invoice');
  const [customerName, setCustomerName] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [originalInvoiceId, setOriginalInvoiceId] = useState('');
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<Line[]>([{ description: '', quantity: 1, price: 0, vatRate: 18 }]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Created | null>(null);
  const [filterType, setFilterType] = useState('all');

  const typesQuery = useQuery<{ data: DocType[] }>({
    queryKey: ['document-types'],
    queryFn: () => apiService.get('/financial/documents/types'),
  });
  const types = typesQuery.data?.data?.length ? typesQuery.data.data : FALLBACK_TYPES;
  const typeLabel = types.find((row) => row.value === documentType)?.label || documentType;

  const { data: integrationStatus } = useQuery<{ configured: Record<string, boolean> }>({
    queryKey: ['integration-status'],
    queryFn: () => apiService.get('/integration/status'),
  });
  const sumitReady = integrationStatus?.configured?.sumit === true;

  const { data: contactSuggestions } = useQuery({
    queryKey: ['contacts-search', customerName],
    queryFn: () => apiService.get<{ data: ContactSuggestion[] }>(`/contacts?query=${encodeURIComponent(customerName)}`),
    enabled: customerName.trim().length >= 2 && showSuggestions,
    select: (res) => res.data,
  });

  const documentsQuery = useQuery<IssuedRow[]>({
    queryKey: ['documents', filterType],
    queryFn: async () => {
      const params = filterType !== 'all' ? { document_type: filterType } : {};
      const res = await apiService.listDocuments(params) as { data?: IssuedRow[] } | IssuedRow[];
      return Array.isArray(res) ? res : (res.data || []);
    },
  });

  const totals = useMemo(() => {
    return items.reduce((sum, line) => {
      const row = lineMath(line);
      return { net: sum.net + row.net, tax: sum.tax + row.tax, total: sum.total + row.total };
    }, { net: 0, tax: 0, total: 0 });
  }, [items]);

  const payloadItems = items
    .filter((line) => line.description.trim())
    .map((line) => ({
      description: line.description.trim(),
      quantity: line.quantity,
      unit_price: line.price,
      vat_rate: line.vatRate,
      discount: 0,
    }));

  function requestBody(sendToSumit: boolean) {
    return {
      document_type: documentType,
      customer_id: customerId || customerName.trim(),
      customer_name: customerName.trim(),
      customer_email: customerEmail || null,
      customer_address: null,
      items: payloadItems,
      issue_date: null,
      due_date: null,
      notes: notes.trim() || null,
      send_to_sumit: sendToSumit,
      send_email: Boolean(customerEmail) && sendToSumit,
      original_invoice_id: documentType === 'credit_note' && originalInvoiceId ? Number(originalInvoiceId) : null,
      payments: null,
    };
  }

  const ready = customerName.trim().length > 0 && payloadItems.length > 0 && payloadItems.every((line) => line.quantity > 0);

  async function saveLocal() {
    setBusy(true);
    setError('');
    try {
      const res = await apiService.post<{ data: Created }>('/financial/documents', requestBody(false));
      setResult(res.data);
      await queryClient.invalidateQueries({ queryKey: ['documents'] });
    } catch (err) {
      setError(hebrewError(err));
    } finally {
      setBusy(false);
    }
  }

  async function issueToSumit() {
    setBusy(true);
    setError('');
    const body = requestBody(true);
    try {
      const proposed = await apiService.post<{ id: number }>('/approvals', {
        action_type: 'document_issue',
        idempotency_key: crypto.randomUUID(),
        description: `הפקת ${typeLabel} עבור ${customerName.trim()}`,
        payload: {
          operation: 'financial_operations.create_document',
          arguments: { request: body },
        },
      });
      await apiService.post(`/approvals/${proposed.id}/approve`, {});
      const res = await apiService.post<{ data: Created }>('/financial/documents', body, {
        headers: { 'X-Rezef-Approval-Id': String(proposed.id) },
      });
      setResult(res.data);
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ['documents'] });
    } catch (err) {
      setError(hebrewError(err));
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main dir="rtl" className="mx-auto max-w-5xl px-4 py-8 text-stone-900">
      <h1 className="text-2xl font-semibold">הפקת מסמכים</h1>
      <p className="mt-1 text-sm text-stone-600">
        חשבונית מס, קבלה, זיכוי והצעת מחיר נשלחים ל-SUMIT רק אחרי אישור. טיוטה מקומית לא קוראת ל-SUMIT.
        {sumitReady ? '' : ' חיבור SUMIT לארגון הזה עדיין לא מוגדר.'}
      </p>

      {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}

      {result ? (
        <section className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4" aria-label="מסמך שהופק">
          <h2 className="text-lg font-medium">המסמך נשמר</h2>
          <p>{result.document_label}</p>
          <p>מזהה מקומי: {result.id}</p>
          <p>מספר מסמך: {result.document_number || 'עדיין אין מספר מסאמית'}</p>
          <p>מזהה SUMIT: {result.external_id || 'לא נשלח ל-SUMIT'}</p>
          <p>סכום: {money(Number(result.total || 0))}</p>
          {result.sumit?.pdf_url ? (
            <a className="mt-2 inline-block underline" href={result.sumit.pdf_url} target="_blank" rel="noopener noreferrer">קישור למסמך</a>
          ) : null}
          <button type="button" className="mt-3 block text-sm underline" onClick={() => setResult(null)}>מסמך נוסף</button>
        </section>
      ) : (
        <form className="mt-6 space-y-4 rounded-xl border bg-white p-4" onSubmit={(event) => event.preventDefault()}>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm">סוג מסמך
              <select className="mt-1 w-full rounded-lg border px-3 py-2" value={documentType} onChange={(event) => setDocumentType(event.target.value)} aria-label="סוג מסמך">
                {types.map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}
              </select>
            </label>
            <label className="relative text-sm">לקוח
              <input
                className="mt-1 w-full rounded-lg border px-3 py-2"
                value={customerName}
                placeholder="שם הלקוח"
                aria-label="לקוח"
                autoComplete="off"
                onChange={(event) => {
                  setCustomerName(event.target.value);
                  setCustomerId('');
                  setShowSuggestions(true);
                }}
                onFocus={() => setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
              />
              {showSuggestions && contactSuggestions?.length ? (
                <ul className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border bg-white shadow">
                  {contactSuggestions.map((contact) => (
                    <li key={contact.id}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-right text-sm hover:bg-stone-50"
                        onMouseDown={() => {
                          setCustomerName(contact.name);
                          setCustomerId(contact.external_id || String(contact.id));
                          if (contact.email) setCustomerEmail(contact.email);
                          setShowSuggestions(false);
                        }}
                      >
                        {contact.name}{contact.external_id ? ` · SUMIT ${contact.external_id}` : ''}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </label>
            <label className="text-sm">אימייל
              <input className="mt-1 w-full rounded-lg border px-3 py-2" type="email" value={customerEmail} aria-label="אימייל" onChange={(event) => setCustomerEmail(event.target.value)} />
            </label>
            {documentType === 'credit_note' ? (
              <label className="text-sm">מזהה המסמך המזוכה
                <input className="mt-1 w-full rounded-lg border px-3 py-2" inputMode="numeric" value={originalInvoiceId} aria-label="מסמך מקור לזיכוי" onChange={(event) => setOriginalInvoiceId(event.target.value)} />
              </label>
            ) : null}
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-medium">שורות</h2>
              <button type="button" className="text-sm underline" onClick={() => setItems([...items, { description: '', quantity: 1, price: 0, vatRate: 18 }])}>הוספת שורה</button>
            </div>
            {items.map((line, index) => (
              <div key={index} className="mb-2 grid grid-cols-12 gap-2">
                <input className="col-span-5 rounded-lg border px-3 py-2" placeholder="תיאור" aria-label={`תיאור ${index + 1}`} value={line.description} onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...line, description: event.target.value };
                  setItems(next);
                }} />
                <input className="col-span-2 rounded-lg border px-3 py-2" type="number" min="0" step="0.01" aria-label={`כמות ${index + 1}`} value={line.quantity} onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...line, quantity: Number(event.target.value) };
                  setItems(next);
                }} />
                <input className="col-span-2 rounded-lg border px-3 py-2" type="number" min="0" step="0.01" aria-label={`מחיר ${index + 1}`} value={line.price} onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...line, price: Number(event.target.value) };
                  setItems(next);
                }} />
                <input className="col-span-2 rounded-lg border px-3 py-2" type="number" min="0" step="0.01" aria-label={`מע״מ ${index + 1}`} value={line.vatRate} onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...line, vatRate: Number(event.target.value) };
                  setItems(next);
                }} />
                <button type="button" className="col-span-1 text-sm text-red-700" aria-label={`מחיקת שורה ${index + 1}`} onClick={() => setItems(items.filter((_, itemIndex) => itemIndex !== index))}>✕</button>
              </div>
            ))}
          </div>

          <section className="rounded-lg bg-stone-50 p-3 text-sm" aria-label="סיכום">
            <p>לפני מע״מ: {money(totals.net)}</p>
            <p>מע״מ: {money(totals.tax)}</p>
            <p className="text-lg font-semibold">סה״כ: {money(totals.total)}</p>
          </section>

          <label className="block text-sm">הערה
            <textarea className="mt-1 w-full rounded-lg border px-3 py-2" value={notes} aria-label="הערה" onChange={(event) => setNotes(event.target.value)} />
          </label>

          {confirming ? (
            <section className="rounded-lg border border-amber-300 bg-amber-50 p-3" role="dialog" aria-label="אישור הפקה">
              <p className="font-medium">לאשר הפקה ב-SUMIT?</p>
              <p className="mt-1 text-sm">{typeLabel} עבור {customerName} · {money(totals.total)}. זו שליחה אמיתית לסאמית, לא טיוטה.</p>
              <div className="mt-3 flex gap-2">
                <button type="button" className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-50" disabled={busy} onClick={() => void issueToSumit()}>
                  {busy ? 'שולח…' : 'אישור ושליחה'}
                </button>
                <button type="button" className="rounded-lg border px-4 py-2" disabled={busy} onClick={() => setConfirming(false)}>חזרה</button>
              </div>
            </section>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="rounded-lg border px-4 py-2 disabled:opacity-50" disabled={!ready || busy} onClick={() => void saveLocal()}>שמירת טיוטה מקומית</button>
              <button type="button" className="rounded-lg bg-blue-700 px-4 py-2 text-white disabled:opacity-50" disabled={!ready || busy || !sumitReady} onClick={() => { setError(''); setConfirming(true); }}>הפקה ב-SUMIT</button>
            </div>
          )}
        </form>
      )}

      <section className="mt-8">
        <h2 className="text-lg font-medium">מסמכים שהופקו מכאן</h2>
        <div className="mt-2 flex flex-wrap gap-2 text-sm">
          <button type="button" className={filterType === 'all' ? 'underline' : ''} onClick={() => setFilterType('all')}>הכל</button>
          {types.map((row) => (
            <button key={row.value} type="button" className={filterType === row.value ? 'underline' : ''} onClick={() => setFilterType(row.value)}>{row.label}</button>
          ))}
        </div>
        {documentsQuery.isLoading ? <p className="mt-3 text-sm">טוען…</p> : (
          <ul className="mt-3 divide-y rounded-xl border bg-white">
            {(documentsQuery.data || []).map((row) => (
              <li key={row.id || row.external_id} className="px-3 py-2 text-sm">
                {row.document_label || row.document_type} · {row.document_number || row.external_id || row.id} · {money(Number(row.total ?? row.total_amount ?? 0))} · {row.status}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
};

export default DocumentManager;
