import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

type Invoice = { id: number; external_id: string; number: string | null; contact_id: number; currency: string; balance: string; total: string; status: string };
type Receipt = { id: number; external_id: string; contact_id: number; currency: string; amount: string; unallocated_amount: string; document_external_id: string; date: string };
type Movement = { id: number; external_id: string; currency: string; amount: string; unallocated_amount: string; date: string; provisional: boolean; source_status: string };
type Allocation = { allocation_id: number; invoice_id: number; payment_id: number; bank_transaction_id: number; amount: string; currency: string; status: string; remaining_balance: string; evidence: Record<string, unknown> };
type Request = { request_id: number; invoice_id: number; amount: string; currency: string; channel: string; approval_status: string; money_status: string; remaining_collection_amount: string; payment_url: string | null; provider_reference: string | null; approval_payload: Record<string, unknown> };
type Workbench = {
  invoices: Invoice[]; receipts: Receipt[]; bank_movements: Movement[]; allocations: Allocation[]; requests: Request[];
  event_reviews: { id: number; external_id: string; evidence: Record<string, unknown> }[];
  pagination: { has_more: boolean; counts: Record<string, number> };
};

function errorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return 'The action could not be completed. Review the evidence and try again.';
}

function safePaymentUrl(value: string | null): string | undefined {
  try { const url = new URL(value || ''); return url.protocol === 'https:' ? url.href : undefined; }
  catch { return undefined; }
}

const field = 'w-full rounded-lg border border-slate-300 bg-white p-2 text-sm';
const button = 'rounded-lg bg-blue-700 px-4 py-2 text-sm text-white disabled:opacity-40';

export default function CollectionWorkbench({ currentUser }: { currentUser: CurrentUser | null }) {
  const [data, setData] = useState<Workbench | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [invoiceId, setInvoiceId] = useState('');
  const [receiptId, setReceiptId] = useState('');
  const [bankId, setBankId] = useState('');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [requestId, setRequestId] = useState('');
  const [channel, setChannel] = useState('sumit');
  const [creditorName, setCreditorName] = useState('');
  const [creditorAccount, setCreditorAccount] = useState('');
  const [accountType, setAccountType] = useState('iban');
  const keys = useRef(new Map<string, string>());
  const canReview = currentUser?.role === 'admin' || currentUser?.role === 'super_admin';
  const load = useCallback(async () => {
    try { setData(await api.get<Workbench>('/financial/collection/workbench', { params: { limit: 100, offset } })); }
    catch (e) { setError(errorText(e)); }
  }, [offset]);
  useEffect(() => { void load(); }, [load]);

  const act = async (path: string, payload: Record<string, unknown>, message: string, idempotent = false) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const fingerprint = JSON.stringify({ path, payload });
      if (idempotent && !keys.current.has(fingerprint)) keys.current.set(fingerprint, crypto.randomUUID());
      await api.post(path, idempotent ? { ...payload, idempotency_key: keys.current.get(fingerprint) } : payload);
      setNotice(message); await load();
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const selectedInvoice = data?.invoices.find(i => i.id === Number(invoiceId));

  return <div dir="ltr" className="min-h-full bg-slate-50 p-4 text-slate-900 md:p-8">
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Collections and settlement evidence</h1>
          <p className="mt-2 text-sm text-slate-600">Invoice debt, payment requests, receipts and bank movements in one review.</p></div>
        <Link to="/bank-insights" className="text-sm text-blue-700 underline">Bank insights</Link>
      </header>
      <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">A payment link is a request. Receipt and bank evidence establish settlement. These allocations update Rezef locally; official SUMIT reconciliation still requires operator evidence.</p>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
      {notice && <p role="status" className="rounded-lg bg-green-50 p-3 text-green-800">{notice}</p>}
      {!data ? <p>Loading saved evidence…</p> : <>
        <section className="rounded-xl border bg-white p-5">
          <h2 className="text-lg font-semibold">Invoice balances</h2>
          <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Invoice</th><th>Customer</th><th>Total</th><th>Remaining</th><th>Status</th></tr></thead>
            <tbody>{data.invoices.map(i => <tr key={i.id} id={`invoice-${i.id}`} className="border-t"><td className="py-3"><button className="text-blue-700 underline" onClick={() => { setInvoiceId(String(i.id)); setAmount(i.balance); }}>{i.number || i.external_id}</button></td><td>{i.contact_id}</td><td>{i.total} {i.currency}</td><td>{i.balance} {i.currency}</td><td>{i.status}</td></tr>)}</tbody></table></div>
          {!data.invoices.length && <p className="mt-3 text-sm text-slate-500">No invoice evidence on this page.</p>}
        </section>
        {canReview && <section className="rounded-xl border bg-white p-5">
          <h2 className="text-lg font-semibold">Review a collection or an existing receipt</h2>
          <p className="my-2 text-sm text-slate-600">Use an existing receipt first when money is already recorded. Select the exact source records and explain the identity evidence.</p>
          <div className="grid gap-4 md:grid-cols-2">
            <label>Invoice<select aria-label="Invoice" className={field} value={invoiceId} onChange={e => setInvoiceId(e.target.value)}><option value="">Choose invoice</option>{data.invoices.map(i => <option key={i.id} value={i.id}>{i.number || i.external_id} · {i.balance} {i.currency}</option>)}</select></label>
            <label>Amount ({selectedInvoice?.currency || 'invoice currency'})<input aria-label="Allocation amount" className={field} inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} /></label>
          </div>
          <div className="mt-5 grid gap-6 lg:grid-cols-2">
            <div className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">Propose collection</h3>
              <label className="block">Payment channel<select aria-label="Payment channel" className={field} value={channel} onChange={e => setChannel(e.target.value)}><option value="sumit">SUMIT payment link</option><option value="open_finance">Open Finance bank payment</option></select></label>
              {channel === 'open_finance' && <><label className="block">Creditor name<input className={field} value={creditorName} onChange={e => setCreditorName(e.target.value)} /></label><label className="block">Reviewed creditor account<input className={field} value={creditorAccount} onChange={e => setCreditorAccount(e.target.value)} /></label><label className="block">Account format<select className={field} value={accountType} onChange={e => setAccountType(e.target.value)}><option value="iban">IBAN</option><option value="bban">BBAN</option></select></label></>}
              <button className={button} disabled={busy || !invoiceId || !amount} onClick={() => void act('/financial/collection/requests', { invoice_id: Number(invoiceId), amount, channel, ...(channel === 'open_finance' ? { creditor: { name: creditorName, account_number: creditorAccount, account_type: accountType } } : {}) }, 'Collection proposal prepared. Signing approval is still required.', true)}>Prepare proposal</button>
            </div>
            <div className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">Allocate existing receipt</h3>
              <label className="block">SUMIT receipt<select aria-label="SUMIT receipt" className={field} value={receiptId} onChange={e => setReceiptId(e.target.value)}><option value="">Choose receipt</option>{data.receipts.map(r => <option key={r.id} value={r.id}>{r.external_id} · customer {r.contact_id} · available {r.unallocated_amount} {r.currency}</option>)}</select></label>
              <label className="block">Bank movement<select aria-label="Bank movement" className={field} value={bankId} onChange={e => setBankId(e.target.value)}><option value="">Choose bank evidence</option>{data.bank_movements.map(b => <option key={b.id} value={b.id} disabled={b.provisional || b.source_status !== 'BOOKED'}>{b.external_id} · {b.date} · available {b.unallocated_amount} {b.currency} · {b.provisional ? 'provisional' : b.source_status}</option>)}</select></label>
              <label className="block">Collection request, if applicable<select className={field} value={requestId} onChange={e => setRequestId(e.target.value)}><option value="">Receipt recorded without this request</option>{data.requests.filter(r => r.invoice_id === Number(invoiceId)).map(r => <option key={r.request_id} value={r.request_id}>Request {r.request_id} · {r.money_status}</option>)}</select></label>
              <label className="block">Reviewed identity evidence<textarea aria-label="Reviewed identity evidence" className={field} value={reason} onChange={e => setReason(e.target.value)} placeholder="Payer reference, receipt identity and why these records belong together" /></label>
              <button className={button} disabled={busy || !invoiceId || !receiptId || !bankId || !amount || reason.trim().length < 10} onClick={() => void act('/financial/collection/allocations', { invoice_id: Number(invoiceId), payment_id: Number(receiptId), bank_transaction_id: Number(bankId), amount, reason, ...(requestId ? { request_id: Number(requestId) } : {}) }, 'Allocation recorded locally. The remaining amounts are shown below.', true)}>Record reviewed allocation</button>
            </div>
          </div>
        </section>}
        <section className="rounded-xl border bg-white p-5"><h2 className="text-lg font-semibold">Collection requests</h2>
          <div className="mt-3 space-y-3">{data.requests.map(r => <article key={r.request_id} className="rounded-lg border p-4"><p className="font-medium">Request {r.request_id} · invoice <a href={`#invoice-${r.invoice_id}`} className="text-blue-700 underline">{r.invoice_id}</a> · {r.amount} {r.currency} · {r.channel}</p><p className="mt-1 text-sm">Approval: {r.approval_status} · Money: {r.money_status} · Awaiting allocation: {r.remaining_collection_amount} {r.currency}</p>
            <details className="mt-2 text-sm"><summary>Exact proposal for review</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(r.approval_payload, null, 2)}</pre></details>
            <div className="mt-3 flex flex-wrap gap-3">{canReview && r.approval_status === 'proposed' && <button className={button} disabled={busy} onClick={() => void act(`/approvals/${r.request_id}/approve`, {}, 'Approval recorded under the organization signing policy.')}>Approve exact proposal</button>}{canReview && r.approval_status === 'approved' && <button className={button} disabled={busy} onClick={() => void act(`/financial/collection/requests/${r.request_id}/execute`, {}, 'Provider request submitted. Check its separate money and evidence statuses.')}>Execute approved request</button>}{safePaymentUrl(r.payment_url) && <a href={safePaymentUrl(r.payment_url)} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-700 underline">Open provider payment request</a>}</div>
          </article>)}</div>{!data.requests.length && <p className="mt-2 text-sm text-slate-500">No collection requests on this page.</p>}
        </section>
        <section className="rounded-xl border bg-white p-5"><h2 className="text-lg font-semibold">Allocation history</h2><div className="mt-3 space-y-3">{data.allocations.map(a => <article key={a.allocation_id} className="rounded-lg border p-4"><p>Allocation {a.allocation_id} · invoice <a className="text-blue-700 underline" href={`#invoice-${a.invoice_id}`}>{a.invoice_id}</a> ↔ receipt {a.payment_id} ↔ bank {a.bank_transaction_id}</p><p className="text-sm">{a.amount} {a.currency} · {a.status} · invoice balance {a.remaining_balance}</p><details className="mt-2 text-sm"><summary>Evidence and decision</summary><pre className="overflow-x-auto whitespace-pre-wrap">{JSON.stringify(a.evidence, null, 2)}</pre></details>{canReview && a.status === 'active' && <div className="mt-3"><p className="mb-2 text-xs text-slate-500">Enter the reversal reason in the identity evidence field above. This reverses only the local allocation.</p><button className="rounded border border-red-300 px-3 py-2 text-sm text-red-800 disabled:opacity-40" disabled={busy || reason.trim().length < 10} onClick={() => void act(`/financial/collection/allocations/${a.allocation_id}/reverse`, { reason }, 'Local allocation reversed; original evidence retained.')}>Reverse local allocation</button></div>}</article>)}</div></section>
        {data.event_reviews.length > 0 && <section className="rounded-xl border border-amber-300 bg-amber-50 p-5"><h2 className="font-semibold">Provider events requiring review</h2>{data.event_reviews.map(e => <details key={e.id} className="mt-3"><summary>{e.external_id} · conflicting or unknown provider observation</summary><pre className="overflow-x-auto whitespace-pre-wrap text-sm">{JSON.stringify(e.evidence, null, 2)}</pre></details>)}</section>}
        <nav className="flex items-center justify-between text-sm"><button disabled={!offset || busy} className={button} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous page</button><span>Saved evidence · page {offset / 100 + 1}</span><button disabled={!data.pagination.has_more || busy} className={button} onClick={() => setOffset(offset + 100)}>Next page</button></nav>
      </>}
    </div>
  </div>;
}
