import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, KeyRound, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import api from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

type Role = 'admin' | 'accountant' | 'manager' | 'user' | 'viewer';

interface OrgUser { id: number; full_name: string; email: string; role: Role; membership_status: string }
interface PolicyGrant {
  id: number; action: string; effect: 'allow' | 'deny'; role: Role | null; user_id: number | null;
  max_amount: number | null; daily_limit_amount: number | null; monthly_limit_amount: number | null;
  allowed_channels: string[] | null; required_approvals: number; separation_of_duties: boolean;
  requires_reason: boolean; requires_step_up: boolean; is_active: boolean;
}
interface SigningAuthority { id: number; user_id: number; authority_type: string; action_types: string[]; is_active: boolean }

const ACTIONS = [
  'invoices.draft', 'invoices.issue', 'invoices.credit', 'expenses.review', 'expenses.file',
  'reconciliation.propose', 'reconciliation.approve', 'collections.contact', 'collections.escalate',
  'payment_link.create', 'bank_payment.propose', 'mandate.propose', 'recurring_cancel.propose',
  'refund.propose', 'filing.prepare', 'period_close.propose', 'accounting.writeback.propose',
  'bank_connection.create', 'reports.email', 'moshko.memory.write', 'tasks.write',
];
const ROLES: Role[] = ['admin', 'accountant', 'manager', 'user', 'viewer'];
const IRREVERSIBLE_ACTIONS = ['payment', 'refund', 'mandate', 'recurring_cancel', 'document_issue', 'sumit_writeback', 'filing_submission', 'period_close'];

function errorText(error: any) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
      .filter(Boolean);
    if (messages.length) return messages.join('; ');
  }
  return 'הפעולה נכשלה';
}

export default function PolicyManagementDashboard({ currentUser }: { currentUser: CurrentUser | null }) {
  const [policies, setPolicies] = useState<PolicyGrant[]>([]);
  const [authorities, setAuthorities] = useState<SigningAuthority[]>([]);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [subjectType, setSubjectType] = useState<'role' | 'user'>('role');
  const [role, setRole] = useState<Role>('manager');
  const [userId, setUserId] = useState('');
  const [action, setAction] = useState('bank_payment.propose');
  const [effect, setEffect] = useState<'allow' | 'deny'>('allow');
  const [maxAmount, setMaxAmount] = useState('');
  const [dailyLimit, setDailyLimit] = useState('');
  const [monthlyLimit, setMonthlyLimit] = useState('');
  const [channels, setChannels] = useState<string[]>(['web']);
  const [requiredApprovals, setRequiredApprovals] = useState('1');
  const [separation, setSeparation] = useState(false);
  const [requiresReason, setRequiresReason] = useState(false);
  const [requiresStepUp, setRequiresStepUp] = useState(false);
  const [authorityUserId, setAuthorityUserId] = useState('');
  const [authorityType, setAuthorityType] = useState('authorized_signer');
  const [authorityActions, setAuthorityActions] = useState<string[]>(['payment']);

  const canManage = currentUser?.role === 'admin' || currentUser?.role === 'super_admin';
  const userName = useMemo(() => new Map(users.map((user) => [user.id, user.full_name || user.email])), [users]);

  const load = useCallback(async () => {
    if (!canManage) return;
    setLoading(true);
    setError(null);
    try {
      const [policyData, authorityData, userData] = await Promise.all([
        api.get<{ items: PolicyGrant[] }>('/approvals/policies', { params: { include_inactive: true } }),
        api.get<{ items: SigningAuthority[] }>('/approvals/signing-authorities'),
        api.get<OrgUser[]>('/admin/users'),
      ]);
      setPolicies(policyData.items);
      setAuthorities(authorityData.items);
      setUsers(userData.filter((user) => user.membership_status === 'active'));
    } catch (requestError: any) {
      setError(errorText(requestError));
    } finally {
      setLoading(false);
    }
  }, [canManage]);

  useEffect(() => { void load(); }, [load]);

  const createPolicy = async () => {
    if (subjectType === 'user' && !userId) { setError('יש לבחור משתמש'); return; }
    setSaving(true); setError(null);
    try {
      await api.post('/approvals/policies', {
        action, effect,
        role: subjectType === 'role' ? role : null,
        user_id: subjectType === 'user' ? Number(userId) : null,
        max_amount: maxAmount ? Number(maxAmount) : null,
        daily_limit_amount: dailyLimit ? Number(dailyLimit) : null,
        monthly_limit_amount: monthlyLimit ? Number(monthlyLimit) : null,
        currency: 'ILS', allowed_channels: channels.length ? channels : null,
        required_approvals: Number(requiredApprovals), separation_of_duties: separation,
        requires_reason: requiresReason, requires_step_up: requiresStepUp,
      });
      await load();
    } catch (requestError: any) { setError(errorText(requestError)); }
    finally { setSaving(false); }
  };

  const revokePolicy = async (id: number) => {
    setSaving(true); setError(null);
    try { await api.delete(`/approvals/policies/${id}`); await load(); }
    catch (requestError: any) { setError(errorText(requestError)); }
    finally { setSaving(false); }
  };

  const grantAuthority = async () => {
    if (!authorityUserId || !authorityActions.length) { setError('יש לבחור משתמש ולפחות פעולה אחת'); return; }
    setSaving(true); setError(null);
    try {
      await api.post('/approvals/signing-authorities', {
        user_id: Number(authorityUserId), authority_type: authorityType, action_types: authorityActions,
      });
      await load();
    } catch (requestError: any) { setError(errorText(requestError)); }
    finally { setSaving(false); }
  };

  if (currentUser === null) return <div dir="rtl" className="p-8 text-slate-500">טוען הרשאות…</div>;
  if (!canManage) return <div dir="rtl" className="m-8 rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">המסך זמין למנהל הארגון הפעיל בלבד.</div>;

  return (
    <div dir="rtl" className="min-h-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-6">
        <header><h1 className="flex items-center gap-2 text-2xl font-bold"><ShieldCheck className="text-blue-600" /> הרשאות כספיות ומורשי חתימה</h1><p className="mt-1 text-sm text-slate-500">המדיניות חלה רק על הארגון הפעיל ונבדקת מחדש בהצעה, באישור ובביצוע.</p></header>
        {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><AlertCircle size={18} />{error}</div>}
        {loading ? <div className="flex justify-center p-16"><Loader2 className="animate-spin" /></div> : <>
          <section className="rounded-xl border bg-white p-5 shadow-sm">
            <h2 className="mb-4 text-lg font-semibold">מדיניות חדשה</h2>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
              <select value={action} onChange={(e) => setAction(e.target.value)} className="rounded-lg border p-2">{ACTIONS.map((item) => <option key={item}>{item}</option>)}</select>
              <select value={effect} onChange={(e) => setEffect(e.target.value as 'allow' | 'deny')} className="rounded-lg border p-2"><option value="allow">היתר</option><option value="deny">איסור מפורש</option></select>
              <select value={subjectType} onChange={(e) => setSubjectType(e.target.value as 'role' | 'user')} className="rounded-lg border p-2"><option value="role">לפי תפקיד</option><option value="user">לפי משתמש</option></select>
              {subjectType === 'role' ? <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="rounded-lg border p-2">{ROLES.map((item) => <option key={item}>{item}</option>)}</select> : <select value={userId} onChange={(e) => setUserId(e.target.value)} className="rounded-lg border p-2"><option value="">בחר משתמש</option>{users.map((user) => <option key={user.id} value={user.id}>{user.full_name || user.email}</option>)}</select>}
              <input type="number" min="0" value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)} placeholder="תקרה לפעולה ₪" className="rounded-lg border p-2" />
              <input type="number" min="0" value={dailyLimit} onChange={(e) => setDailyLimit(e.target.value)} placeholder="תקרה יומית ₪" className="rounded-lg border p-2" />
              <input type="number" min="0" value={monthlyLimit} onChange={(e) => setMonthlyLimit(e.target.value)} placeholder="תקרה חודשית ₪" className="rounded-lg border p-2" />
              <input type="number" min="1" value={requiredApprovals} onChange={(e) => setRequiredApprovals(e.target.value)} placeholder="מספר מאשרים" className="rounded-lg border p-2" />
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              {['web', 'whatsapp', 'telegram'].map((item) => <label key={item} className="flex items-center gap-1"><input type="checkbox" checked={channels.includes(item)} onChange={() => setChannels((old) => old.includes(item) ? old.filter((value) => value !== item) : [...old, item])} />{item}</label>)}
              <label className="flex items-center gap-1"><input type="checkbox" checked={separation} onChange={(e) => setSeparation(e.target.checked)} />הפרדת תפקידים</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={requiresReason} onChange={(e) => setRequiresReason(e.target.checked)} />נימוק חובה</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={requiresStepUp} onChange={(e) => setRequiresStepUp(e.target.checked)} />אימות מוגבר (חוסם עד שיושלם flow)</label>
            </div>
            <button type="button" disabled={saving} onClick={() => void createPolicy()} className="mt-4 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50"><Plus size={16} /> שמירת מדיניות</button>
          </section>

          <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
            <h2 className="border-b p-4 text-lg font-semibold">מדיניות הארגון</h2>
            <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-slate-50"><tr><th className="p-3 text-right">פעולה</th><th className="p-3 text-right">הכרעה</th><th className="p-3 text-right">נושא</th><th className="p-3 text-right">תקרות</th><th className="p-3 text-right">ערוצים/אישורים</th><th className="p-3"></th></tr></thead><tbody>{policies.map((item) => <tr key={item.id} className={`border-t ${item.is_active ? '' : 'opacity-50'}`}><td className="p-3 font-medium">{item.action}</td><td className={`p-3 ${item.effect === 'deny' ? 'text-red-700' : 'text-emerald-700'}`}>{item.effect}</td><td className="p-3">{item.user_id ? userName.get(item.user_id) || `משתמש ${item.user_id}` : item.role}</td><td className="p-3">פעולה {item.max_amount ?? '—'} · יום {item.daily_limit_amount ?? '—'} · חודש {item.monthly_limit_amount ?? '—'}</td><td className="p-3">{item.allowed_channels?.join(', ') || 'הכול'} · {item.required_approvals} מאשרים{item.separation_of_duties ? ' · הפרדה' : ''}</td><td className="p-3">{item.is_active && <button type="button" aria-label="בטל מדיניות" onClick={() => void revokePolicy(item.id)} disabled={saving} className="rounded p-2 text-red-600 hover:bg-red-50"><Trash2 size={16} /></button>}</td></tr>)}</tbody></table></div>
          </section>

          <section className="rounded-xl border bg-white p-5 shadow-sm">
            <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold"><KeyRound size={19} /> מורשי חתימה</h2>
            <p className="mb-4 text-sm text-slate-500">תפקיד מערכת אינו סמכות חתימה. רק בעלים קיים יכול להעניק סמכות נוספת.</p>
            <div className="grid gap-3 md:grid-cols-3"><select value={authorityUserId} onChange={(e) => setAuthorityUserId(e.target.value)} className="rounded-lg border p-2"><option value="">בחר משתמש</option>{users.map((user) => <option key={user.id} value={user.id}>{user.full_name || user.email}</option>)}</select><select value={authorityType} onChange={(e) => setAuthorityType(e.target.value)} className="rounded-lg border p-2"><option value="authorized_signer">מורשה חתימה</option><option value="owner">בעלים</option></select><button type="button" onClick={() => void grantAuthority()} disabled={saving} className="rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">הענקת סמכות</button></div>
            <div className="mt-3 flex flex-wrap gap-3 text-sm">{IRREVERSIBLE_ACTIONS.map((item) => <label key={item} className="flex items-center gap-1"><input type="checkbox" checked={authorityActions.includes(item)} onChange={() => setAuthorityActions((old) => old.includes(item) ? old.filter((value) => value !== item) : [...old, item])} />{item}</label>)}</div>
            <div className="mt-5 space-y-2">{authorities.map((item) => <div key={item.id} className="flex flex-wrap justify-between gap-3 rounded-lg border p-3 text-sm"><span className="font-medium">{userName.get(item.user_id) || `משתמש ${item.user_id}`} · {item.authority_type}</span><span>{item.action_types.join(', ')}</span></div>)}</div>
          </section>
        </>}
      </div>
    </div>
  );
}
