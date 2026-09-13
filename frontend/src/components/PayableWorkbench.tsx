import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

type Request = { request_id: number; bill_id: number; amount: string; currency: string; approval_status: string;
  approval_payload: Record<string, unknown>; money_status: string; settled_amount: string; remaining_request_amount: string;
  remaining_balance: string; payment_url: string | null; error: string | null;
  settlement_history: { bank_transaction_id: number; bank_external_id: string; amount: string; status: string }[] };
type Workbench = {
  bills: { id: number; external_id: string; number: string | null; vendor_name: string | null; balance: string; currency: string; status: string }[];
  requests: Request[];
  funding_accounts: { id: number; name: string; has_provider_account_identity: boolean }[];
  bank_movements: { id: number; external_id: string; date: string; amount: string; currency: string; provisional: boolean; source_status: string; reconciled: boolean }[];
  pagination: { has_more: boolean }; limitations: string[];
};
const field = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm';
const button = 'rounded-lg bg-blue-700 px-4 py-2 text-sm text-white disabled:opacity-40';
function safeUrl(value: string | null) {
  try { const url = new URL(value || ''); return url.protocol === 'https:' ? url.href : undefined; } catch { return undefined; }
}

export default function PayableWorkbench({ currentUser }: { currentUser: CurrentUser | null }) {
  const [data, setData] = useState<Workbench | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [bill, setBill] = useState('');
  const [amount, setAmount] = useState('');
  const [name, setName] = useState('');
  const [account, setAccount] = useState('');
  const [accountType, setAccountType] = useState('bban');
  const [beneficiaryEvidence, setBeneficiaryEvidence] = useState('');
  const [withholding, setWithholding] = useState('');
  const [withholdingEvidence, setWithholdingEvidence] = useState('');
  const [funding, setFunding] = useState('');
  const [fundingType, setFundingType] = useState('bban');
  const [requestId, setRequestId] = useState('');
  const [bank, setBank] = useState('');
  const [reason, setReason] = useState('');
  const keys = useRef(new Map<string, string>());
  const canReview = currentUser?.role === 'admin' || currentUser?.role === 'super_admin';
  const reportError = (e: unknown) => {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    setError(typeof detail === 'string' ? detail : 'The action could not be completed. Review its recorded status before another attempt.');
  };
  const load = useCallback(async () => {
    try { setData(await api.get<Workbench>('/financial/payables/workbench', { params: { limit: 100, offset } })); }
    catch (e) { reportError(e); }
  }, [offset]);
  useEffect(() => { void load(); }, [load]);
  const act = async (path: string, payload: Record<string, unknown>, message: string, idempotent = false) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const fingerprint = JSON.stringify({ path, payload });
      if (idempotent && !keys.current.has(fingerprint)) keys.current.set(fingerprint, crypto.randomUUID());
      await api.post(path, idempotent ? { ...payload, idempotency_key: keys.current.get(fingerprint) } : payload);
      setNotice(message);
    } catch (e) { reportError(e); }
    finally { await load(); setBusy(false); }
  };
  return <div dir="ltr" className="min-h-full bg-slate-50 p-4 text-slate-900 md:p-8"><div className="mx-auto max-w-6xl space-y-6">
    <header><h1 className="text-2xl font-bold">Supplier payments and bank evidence</h1><p className="mt-2 text-sm text-slate-600">Review the bill, beneficiary and withholding evidence before signing a payment request.</p><Link to="/ap" className="text-sm text-blue-700 underline">Supplier aging</Link></header>
    <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">Signing approval, bank authorization, money settlement and official SUMIT posting are separate steps. This workflow records local bank decisions; official posting remains pending.</p>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {notice && <p role="status" className="rounded-lg bg-green-50 p-3 text-green-800">{notice}</p>}
    {!data ? <p>Loading saved evidence…</p> : <>
      <section className="rounded-xl border bg-white p-5"><h2 className="text-lg font-semibold">Supplier balances</h2><div className="mt-3 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Bill</th><th>Supplier</th><th>Remaining</th><th>Status</th></tr></thead><tbody>{data.bills.map(b => <tr id={`bill-${b.id}`} key={b.id} className="border-t"><td className="py-3">{b.number || b.external_id}</td><td>{b.vendor_name || 'Identity missing'}</td><td>{b.balance} {b.currency}</td><td>{b.status}</td></tr>)}</tbody></table></div></section>
      {canReview && <section className="rounded-xl border bg-white p-5"><h2 className="text-lg font-semibold">Prepare a supplier payment</h2><p className="my-2 text-sm text-slate-600">Use reviewed supporting records. A zero withholding rate in imported contact data is insufficient evidence of exemption.</p>
        <div className="grid gap-4 md:grid-cols-2">
          <label>Bill<select aria-label="Bill" className={field} value={bill} onChange={e => setBill(e.target.value)}><option value="">Choose bill</option>{data.bills.map(b => <option key={b.id} value={b.id}>{b.number || b.external_id} · {b.balance} {b.currency}</option>)}</select></label>
          <label>Payment amount<input className={field} inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} /></label>
          <label>Beneficiary name<input className={field} value={name} onChange={e => setName(e.target.value)} /></label>
          <label>Beneficiary account<input className={field} value={account} onChange={e => setAccount(e.target.value)} /></label>
          <label>Beneficiary account format<select aria-label="Beneficiary account format" className={field} value={accountType} onChange={e => setAccountType(e.target.value)}><option value="bban">BBAN</option><option value="iban">IBAN</option></select></label>
          <label>Beneficiary evidence<textarea className={field} value={beneficiaryEvidence} onChange={e => setBeneficiaryEvidence(e.target.value)} /></label>
          <label>Withholding decision<select aria-label="Withholding decision" className={field} value={withholding} onChange={e => setWithholding(e.target.value)}><option value="">Choose reviewed decision</option><option value="not_required">Payer obligation reviewed: not required</option><option value="valid_exemption">Valid supplier exemption reviewed</option></select></label>
          <label>Withholding evidence<textarea className={field} value={withholdingEvidence} onChange={e => setWithholdingEvidence(e.target.value)} placeholder="Supporting record, validity date and scope of review" /></label>
          <label>Funding account<select aria-label="Funding account" className={field} value={funding} onChange={e => setFunding(e.target.value)}><option value="">Choose in bank (Open Finance platform only)</option>{data.funding_accounts.map(a => <option key={a.id} value={a.id} disabled={!a.has_provider_account_identity}>{a.name} · {a.id}</option>)}</select></label>
          {funding && <label>Funding account format<select aria-label="Funding account format" className={field} value={fundingType} onChange={e => setFundingType(e.target.value)}><option value="bban">BBAN</option><option value="iban">IBAN</option></select></label>}
        </div><button className={`${button} mt-4`} disabled={busy || !bill || !amount || !name || !account || !withholding || beneficiaryEvidence.trim().length < 20 || withholdingEvidence.trim().length < 20} onClick={() => void act('/financial/payables/requests', { bill_id: Number(bill), amount, creditor: { name, account_number: account, account_type: accountType }, beneficiary_evidence: beneficiaryEvidence, withholding_decision: withholding, withholding_evidence: withholdingEvidence, ...(funding ? { funding_account_id: Number(funding), funding_account_type: fundingType } : {}) }, 'Supplier proposal prepared for signing review.', true)}>Prepare supplier proposal</button>
      </section>}
      <section className="rounded-xl border bg-white p-5"><h2 className="text-lg font-semibold">Supplier requests</h2><div className="mt-3 space-y-4">{data.requests.map(r => <article key={r.request_id} className="rounded-lg border p-4"><p className="font-medium">Request {r.request_id} · bill <a href={`#bill-${r.bill_id}`} className="text-blue-700 underline">{r.bill_id}</a> · {r.amount} {r.currency}</p><p className="mt-2 text-sm">Approval: {r.approval_status} · Money: {r.money_status}</p><p className="text-sm">Settled locally: {r.settled_amount} {r.currency} · Awaiting bank evidence: {r.remaining_request_amount} {r.currency}</p>{r.error && <p className="mt-2 text-sm text-red-800">{r.error}</p>}<details className="mt-2 text-sm"><summary>Exact proposal and review evidence</summary><pre className="overflow-x-auto whitespace-pre-wrap break-words">{JSON.stringify(r.approval_payload, null, 2)}</pre></details><div className="mt-3 flex flex-wrap gap-3">
        {canReview && r.approval_status === 'proposed' && <button className={button} disabled={busy} onClick={() => void act(`/approvals/${r.request_id}/approve`, {}, 'Signing approval recorded under organization policy.')}>Approve exact proposal</button>}
        {canReview && r.approval_status === 'approved' && <button className={button} disabled={busy} onClick={() => void act(`/financial/payables/requests/${r.request_id}/execute`, {}, 'Provider request created. Bank authorization and settlement still require evidence.')}>Execute approved request</button>}
        {safeUrl(r.payment_url) && <a href={safeUrl(r.payment_url)} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-700 underline">Open provider request</a>}</div>
        {r.settlement_history.map(h => <div key={h.bank_transaction_id} className="mt-4 border-t pt-3"><p className="text-sm">{h.bank_external_id} · {h.amount} {r.currency} · {h.status}</p>{canReview && h.status === 'active' && <button className={`${button} mt-2`} disabled={busy || reason.trim().length < 20} onClick={() => void act(`/financial/payables/requests/${r.request_id}/reverse`, { bank_transaction_id: h.bank_transaction_id, reason }, 'Local settlement reversed with history retained. No refund was initiated.')}>Reverse local settlement</button>}</div>)}
      </article>)}</div></section>
      {canReview && <section className="rounded-xl border bg-white p-5"><h2 className="text-lg font-semibold">Review booked bank evidence</h2><div className="mt-3 grid gap-4 md:grid-cols-2"><label>Request<select aria-label="Request" className={field} value={requestId} onChange={e => setRequestId(e.target.value)}><option value="">Choose supplier request</option>{data.requests.map(r => <option key={r.request_id} value={r.request_id}>{r.request_id} · bill {r.bill_id} · {r.money_status}</option>)}</select></label><label>Bank outflow<select aria-label="Bank outflow" className={field} value={bank} onChange={e => setBank(e.target.value)}><option value="">Choose exact bank evidence</option>{data.bank_movements.map(b => <option key={b.id} value={b.id} disabled={b.provisional || b.source_status !== 'BOOKED' || b.reconciled}>{b.external_id} · {b.date} · {b.amount} {b.currency} · {b.provisional ? 'provisional' : b.source_status}</option>)}</select></label><label className="md:col-span-2">Bank decision evidence<textarea className={field} value={reason} onChange={e => setReason(e.target.value)} placeholder="Exact supplier and bank reference evidence; also used for reversal decisions" /></label></div><button className={`${button} mt-4`} disabled={busy || !requestId || !bank || reason.trim().length < 20} onClick={() => void act(`/financial/payables/requests/${requestId}/settle`, { bank_transaction_id: Number(bank), reason }, 'Reviewed settlement recorded locally; bill balance updated.')}>Record reviewed settlement</button></section>}
      <details className="rounded-xl border bg-white p-5 text-sm"><summary>Remaining requirements</summary>{data.limitations.map(text => <p className="mt-2" key={text}>{text}</p>)}</details>
      <nav className="flex justify-between gap-3"><button className={button} disabled={!offset || busy} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous page</button><span>Page {offset / 100 + 1}</span><button className={button} disabled={!data.pagination.has_more || busy} onClick={() => setOffset(offset + 100)}>Next page</button></nav>
    </>}
  </div></div>;
}
