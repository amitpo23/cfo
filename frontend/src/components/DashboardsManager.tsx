import React, { useCallback, useEffect, useState } from 'react';
import { ExternalLink, LayoutGrid, Loader2, Plus, RefreshCw } from 'lucide-react';
import api from '../services/api';
import { ProviderAccessCard, ProviderStatus } from './dashboardProviders';
import { ShareLinksCard } from './dashboardTabs';

/**
 * מסך ניהול דשבורדים (/d/) — יצירה, הפעלה, ישויות קשורות, שיוך חשבונות
 * בנק ואשראי, וקישורי שיתוף. ה-API כבר קיים (client_dashboards); המסך רק
 * חושף אותו. אין כאן קריאה לספק: כל הפעולות מקומיות.
 */

interface Dashboard {
  id: number;
  slug: string;
  title: string;
  status: string;
  access_mode: string;
  template: string;
  primary_organization_id: number;
}

interface Org { id: number; name: string }

interface Entity {
  id: number;
  organization_id: number;
  label: string;
  role: string;
  accounts: { account_id: number; display_label: string | null }[];
}

interface CandidateAccount { id: number; name: string; kind: string; source: string; bound: boolean }

const STATUS_LABELS: Record<string, string> = {
  draft: 'טיוטה', active: 'פעיל', paused: 'מושהה', archived: 'בארכיון',
};
const ACCESS_LABELS: Record<string, string> = {
  members: 'חברי הארגון בלבד', link: 'גם בקישור שיתוף', public: 'ציבורי לכל מי שיש לו כתובת',
};
const TEMPLATE_LABELS: Record<string, string> = { generic: 'כללי', restaurant: 'מסעדה', services: 'שירותים' };
const KIND_LABELS: Record<string, string> = {
  checking: 'עו״ש', card: 'כרטיס אשראי', loan: 'הלוואה', credit_line_mirror: 'מסגרת', other: 'אחר',
};

function errorText(error: any, fallback: string): string {
  return error?.response?.data?.error?.message_he || fallback;
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface Props { darkMode: boolean }

export default function DashboardsManager({ darkMode }: Props) {
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [form, setForm] = useState({ organization: '', slug: '', title: '', template: 'generic', access: 'members' });
  const [workspace, setWorkspace] = useState({ name: '', slug: '', title: '', access: 'members' });
  const [related, setRelated] = useState<{ organization_id: number; label: string }[]>([]);
  const [relatedPick, setRelatedPick] = useState('');
  const [creating, setCreating] = useState(false);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);

  const card = `rounded-xl border shadow-sm ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`;
  const textMain = darkMode ? 'text-white' : 'text-gray-900';
  const textSub = darkMode ? 'text-gray-400' : 'text-gray-500';
  const input = `rounded-lg border px-3 py-2 text-sm ${darkMode ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300'}`;
  const button = 'rounded-lg border px-3 py-1.5 text-sm transition hover:bg-gray-50 disabled:opacity-50 dark:hover:bg-gray-700';

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, manageable] = await Promise.all([
        api.get<{ dashboards: Dashboard[] }>('/dashboards'),
        api.get<{ organizations: Org[] }>('/dashboards/manageable-organizations'),
      ]);
      setDashboards(list.dashboards);
      setOrgs(manageable.organizations);
      setForm((current) => (current.organization || !manageable.organizations.length
        ? current : { ...current, organization: String(manageable.organizations[0].id) }));
    } catch (err) {
      setError(errorText(err, 'טעינת הדשבורדים נכשלה'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function createWorkspace(event: React.FormEvent) {
    event.preventDefault();
    setCreatingWorkspace(true);
    setError(null);
    try {
      const created = await api.post<{ dashboard: { id: number } }>('/dashboards/workspaces', {
        name: workspace.name.trim(),
        slug: workspace.slug.trim(),
        title: workspace.title.trim() || workspace.name.trim(),
        access_mode: workspace.access,
        entities: related,
      });
      setWorkspace({ name: '', slug: '', title: '', access: 'members' });
      setRelated([]);
      await load();
      setOpenId(created.dashboard.id);
    } catch (err) {
      setError(errorText(err, 'יצירת העסק והדשבורד נכשלה'));
    } finally {
      setCreatingWorkspace(false);
    }
  }

  function addRelated() {
    const organizationId = Number(relatedPick);
    if (!organizationId || related.some((item) => item.organization_id === organizationId)) return;
    const org = orgs.find((item) => item.id === organizationId);
    setRelated((current) => [...current, { organization_id: organizationId, label: org?.name ?? '' }]);
    setRelatedPick('');
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const created = await api.post<{ id: number }>('/dashboards', {
        primary_organization_id: Number(form.organization), slug: form.slug.trim(), title: form.title.trim(),
        template: form.template, access_mode: form.access,
      });
      setForm((current) => ({ ...current, slug: '', title: '' }));
      await load();
      setOpenId(created.id);
    } catch (err) {
      setError(errorText(err, 'יצירת הדשבורד נכשלה'));
    } finally {
      setCreating(false);
    }
  }

  async function patch(dashboard: Dashboard, changes: Partial<Pick<Dashboard, 'status' | 'access_mode'>>) {
    if (changes.access_mode === 'public'
      && !window.confirm('דשבורד ציבורי פתוח לכל מי שיודע את הכתובת, בלי קישור ובלי התחברות. להמשיך?')) {
      return;
    }
    setError(null);
    try {
      await api.patch(`/dashboards/${dashboard.id}`, changes);
      await load();
    } catch (err) {
      setError(errorText(err, 'העדכון נכשל'));
    }
  }

  const orgName = (id: number) => orgs.find((org) => org.id === id)?.name ?? `ארגון ${id}`;

  return (
    <div className="p-6 space-y-6" dir="rtl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-emerald-500 to-sky-600 rounded-xl flex items-center justify-center">
            <LayoutGrid size={20} className="text-white" />
          </div>
          <div>
            <h1 className={`text-2xl font-bold ${textMain}`}>דשבורדים</h1>
            <p className={`text-sm ${textSub}`}>דשבורדי /d/ לעסקים: יצירה, ישויות, חשבונות ושיתוף</p>
          </div>
        </div>
        <button type="button" onClick={() => { void load(); }} disabled={loading}
          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${darkMode ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-600 hover:bg-gray-100'}`}>
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          רענון
        </button>
      </div>

      {error ? <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

      <div className={`${card} p-5`}>
        <h2 className={`text-lg font-semibold mb-1 ${textMain}`}>עסק ודשבורד חדשים</h2>
        <p className={`mb-3 text-sm ${textSub}`}>
          ברירת המחדל סגורה לחברי הארגון. דשבורד חדש לא נוצר כציבורי, והשמירה לא פונה לספק.
        </p>
        <form onSubmit={(event) => { void createWorkspace(event); }} className="flex flex-wrap items-end gap-3">
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            שם העסק
            <input className={input} required maxLength={255} value={workspace.name}
              onChange={(event) => setWorkspace({ ...workspace, name: event.target.value })} />
          </label>
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            כתובת (אנגלית)
            <input className={input} dir="ltr" required minLength={3} maxLength={48} pattern={'[a-z0-9][a-z0-9\\-]{2,47}'}
              placeholder="my-business" value={workspace.slug}
              onChange={(event) => setWorkspace({ ...workspace, slug: event.target.value.toLowerCase() })} />
          </label>
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            כותרת הדשבורד
            <input className={input} maxLength={255} value={workspace.title}
              onChange={(event) => setWorkspace({ ...workspace, title: event.target.value })} />
          </label>
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            גישה
            <select className={input} value={workspace.access}
              onChange={(event) => setWorkspace({ ...workspace, access: event.target.value })}>
              <option value="members">{ACCESS_LABELS.members}</option>
              <option value="link">{ACCESS_LABELS.link}</option>
            </select>
          </label>
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            ישות קשורה
            <select className={input} value={relatedPick} onChange={(event) => setRelatedPick(event.target.value)}>
              <option value="">בלי ישות נוספת</option>
              {orgs.filter((org) => !related.some((item) => item.organization_id === org.id)).map((org) => (
                <option key={org.id} value={org.id}>{org.name}</option>
              ))}
            </select>
          </label>
          <button type="button" className={button} disabled={!relatedPick} onClick={addRelated}>הוסף ישות</button>
          <button type="submit" disabled={creatingWorkspace}
            className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50">
            {creatingWorkspace ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            צור עסק ודשבורד
          </button>
        </form>
        {related.length ? (
          <ul className={`mt-3 text-sm ${textSub}`}>
            {related.map((item) => (
              <li key={item.organization_id}>
                {item.label || `ארגון ${item.organization_id}`}
                <button type="button" className="ms-2 underline"
                  onClick={() => setRelated((current) => current.filter((row) => row.organization_id !== item.organization_id))}>
                  הסר
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className={`${card} p-5`}>
        <h2 className={`text-lg font-semibold mb-3 ${textMain}`}>דשבורד לעסק קיים</h2>
        {orgs.length === 0 && !loading ? (
          <p className={`text-sm ${textSub}`}>אין ארגון שאתה מנהל בו. יצירת דשבורד דורשת הרשאת מנהל בארגון.</p>
        ) : (
          <form onSubmit={(event) => { void create(event); }} className="flex flex-wrap items-end gap-3">
            <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
              עסק
              <select className={input} value={form.organization}
                onChange={(event) => setForm({ ...form, organization: event.target.value })}>
                {orgs.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
              </select>
            </label>
            <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
              כתובת (אנגלית)
              <input className={input} dir="ltr" required minLength={3} maxLength={48} pattern={'[a-z0-9][a-z0-9\\-]{2,47}'}
                placeholder="my-business" value={form.slug}
                onChange={(event) => setForm({ ...form, slug: event.target.value.toLowerCase() })} />
            </label>
            <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
              כותרת
              <input className={input} required maxLength={255} value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })} />
            </label>
            <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
              תבנית
              <select className={input} value={form.template} onChange={(event) => setForm({ ...form, template: event.target.value })}>
                {Object.entries(TEMPLATE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
              גישה
              <select className={input} value={form.access} onChange={(event) => setForm({ ...form, access: event.target.value })}>
                <option value="members">{ACCESS_LABELS.members}</option>
                <option value="link">{ACCESS_LABELS.link}</option>
              </select>
            </label>
            <button type="submit" disabled={creating || !form.organization}
              className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50">
              {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
              צור כטיוטה
            </button>
          </form>
        )}
      </div>

      <div className="space-y-3">
        {dashboards.length === 0 && !loading ? (
          <p className={`text-sm ${textSub}`}>עדיין אין דשבורדים.</p>
        ) : null}
        {dashboards.map((dashboard) => (
          <div key={dashboard.id} className={`${card} p-4`}>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className={`font-semibold ${textMain}`}>{dashboard.title}</p>
                <p className={`text-xs ${textSub}`}>
                  <span dir="ltr">/d/{dashboard.slug}</span>
                  {' · '}{orgName(dashboard.primary_organization_id)}
                  {' · '}{TEMPLATE_LABELS[dashboard.template] ?? dashboard.template}
                </p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs ${dashboard.status === 'active' ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-700'}`}>
                {STATUS_LABELS[dashboard.status] ?? dashboard.status}
              </span>
              <select className={input} value={dashboard.access_mode} aria-label="מצב גישה"
                onChange={(event) => { void patch(dashboard, { access_mode: event.target.value }); }}>
                {Object.entries(ACCESS_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              {dashboard.status === 'active' ? (
                <button type="button" className={button} onClick={() => { void patch(dashboard, { status: 'paused' }); }}>השהה</button>
              ) : (
                <button type="button" className={button} onClick={() => { void patch(dashboard, { status: 'active' }); }}>הפעל</button>
              )}
              <a href={`/d/${dashboard.slug}`} target="_blank" rel="noreferrer" className={`${button} flex items-center gap-1`}>
                <ExternalLink size={14} /> פתח
              </a>
              <button type="button" className={button} onClick={() => setOpenId(openId === dashboard.id ? null : dashboard.id)}>
                {openId === dashboard.id ? 'סגור' : 'ישויות וחשבונות'}
              </button>
            </div>
            {openId === dashboard.id ? (
              <DashboardWiring dashboard={dashboard} orgs={orgs} darkMode={darkMode} onError={setError} />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function DashboardWiring({ dashboard, orgs, darkMode, onError }: {
  dashboard: Dashboard; orgs: Org[]; darkMode: boolean; onError: (message: string | null) => void;
}) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [providers, setProviders] = useState<ProviderStatus | null>(null);
  const [sumitArmed, setSumitArmed] = useState(false);
  const [financeArmed, setFinanceArmed] = useState(false);
  const [pending, setPending] = useState<'sumit' | 'finance' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newOrg, setNewOrg] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const textSub = darkMode ? 'text-gray-400' : 'text-gray-500';
  const input = `rounded-lg border px-3 py-2 text-sm ${darkMode ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300'}`;

  const load = useCallback(async () => {
    try {
      const [body, providerBody] = await Promise.all([
        api.get<{ entities: Entity[] }>(`/dashboards/${dashboard.id}/entities`),
        api.get<ProviderStatus>(`/dashboards/${dashboard.id}/providers`),
      ]);
      setEntities(body.entities);
      setProviders(providerBody);
    } catch (err) {
      onError(errorText(err, 'טעינת הישויות נכשלה'));
    }
  }, [dashboard.id, onError]);

  useEffect(() => { void load(); }, [load]);

  const addable = orgs.filter((org) => !entities.some((entity) => entity.organization_id === org.id));

  async function addEntity() {
    onError(null);
    try {
      await api.post(`/dashboards/${dashboard.id}/entities`, { organization_id: Number(newOrg), label: newLabel.trim() });
      setNewOrg('');
      setNewLabel('');
      await load();
    } catch (err) {
      onError(errorText(err, 'הוספת הישות נכשלה'));
    }
  }

  async function confirmProvider(kind: 'sumit' | 'finance') {
    if (!providers) return;
    setPending(kind);
    setNotice(null);
    onError(null);
    try {
      const path = kind === 'sumit'
        ? `/dashboards/${dashboard.id}/providers/sumit`
        : `/dashboards/${dashboard.id}/providers/open-finance/refresh`;
      const confirmation = kind === 'sumit' ? providers.confirmations.sumit : providers.confirmations.open_finance;
      const body = await api.post<{ message_he?: string; provider_calls?: number }>(path, { confirmation });
      setNotice(body.message_he || 'האישור נקלט');
      if (kind === 'sumit') setSumitArmed(false);
      else setFinanceArmed(false);
      await load();
    } catch (err) {
      onError(errorText(err, 'האישור נדחה'));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className={`mt-4 space-y-4 border-t pt-4 ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
      {providers ? (
        <ProviderAccessCard
          status={providers}
          sumitArmed={sumitArmed}
          financeArmed={financeArmed}
          pending={pending}
          notice={notice}
          onSumitArmed={setSumitArmed}
          onFinanceArmed={setFinanceArmed}
          onSumit={() => { void confirmProvider('sumit'); }}
          onFinance={() => { void confirmProvider('finance'); }}
        />
      ) : null}
      {entities.map((entity) => (
        <EntityAccounts key={entity.id} dashboardId={dashboard.id} entity={entity} darkMode={darkMode}
          onSaved={load} onError={onError} />
      ))}
      {addable.length ? (
        <div className="flex flex-wrap items-end gap-3">
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            ישות קשורה (אותו משרד)
            <select className={input} value={newOrg} onChange={(event) => setNewOrg(event.target.value)}>
              <option value="">בחר עסק…</option>
              {addable.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
            </select>
          </label>
          <label className={`flex flex-col gap-1 text-xs ${textSub}`}>
            שם בדשבורד
            <input className={input} maxLength={255} value={newLabel} onChange={(event) => setNewLabel(event.target.value)} />
          </label>
          <button type="button" disabled={!newOrg} onClick={() => { void addEntity(); }}
            className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50">הוסף ישות</button>
        </div>
      ) : null}
      <ShareLinksCard dashboardId={dashboard.id} slug={dashboard.slug} headers={authHeaders} />
    </div>
  );
}

function EntityAccounts({ dashboardId, entity, darkMode, onSaved, onError }: {
  dashboardId: number; entity: Entity; darkMode: boolean; onSaved: () => Promise<void>; onError: (message: string | null) => void;
}) {
  const [accounts, setAccounts] = useState<CandidateAccount[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const textMain = darkMode ? 'text-white' : 'text-gray-900';
  const textSub = darkMode ? 'text-gray-400' : 'text-gray-500';

  useEffect(() => {
    let cancelled = false;
    api.get<{ accounts: CandidateAccount[] }>(`/dashboards/${dashboardId}/entities/${entity.id}/available-accounts`)
      .then((body) => {
        if (cancelled) return;
        setAccounts(body.accounts);
        setChosen(new Set(body.accounts.filter((account) => account.bound).map((account) => account.id)));
      })
      .catch((err) => onError(errorText(err, 'טעינת החשבונות נכשלה')));
    return () => { cancelled = true; };
  }, [dashboardId, entity.id, onError]);

  const savedIds = new Set(entity.accounts.map((account) => account.account_id));
  const dirty = chosen.size !== savedIds.size || [...chosen].some((id) => !savedIds.has(id));

  async function save() {
    setSaving(true);
    onError(null);
    try {
      await api.put(`/dashboards/${dashboardId}/entities/${entity.id}/accounts`, {
        accounts: [...chosen].map((account_id) => ({ account_id })),
      });
      await onSaved();
    } catch (err) {
      onError(errorText(err, 'שמירת החשבונות נכשלה'));
    } finally {
      setSaving(false);
    }
  }

  function toggle(id: number) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChosen(next);
  }

  return (
    <div>
      <p className={`font-medium ${textMain}`}>
        {entity.label} <span className={`text-xs ${textSub}`}>{entity.role === 'primary' ? 'ישות ראשית' : 'ישות קשורה'}</span>
      </p>
      <p className={`mt-1 text-xs ${textSub}`}>
        {savedIds.size
          ? 'הנזילות של הישות נקראת רק מהחשבונות המסומנים.'
          : 'לא סומן חשבון: הנזילות נקראת מכל חשבונות הבנקאות הפתוחה של העסק.'}
      </p>
      {accounts.length === 0 ? (
        <p className={`mt-2 text-sm ${textSub}`}>אין לעסק חשבונות בנק או אשראי במערכת.</p>
      ) : (
        <ul className="mt-2 grid gap-1 sm:grid-cols-2">
          {accounts.map((account) => (
            <li key={account.id}>
              <label className={`flex items-center gap-2 text-sm ${textMain}`}>
                <input type="checkbox" aria-label={account.name} checked={chosen.has(account.id)} onChange={() => toggle(account.id)} />
                {account.name}
                <span className={`text-xs ${textSub}`}>{KIND_LABELS[account.kind] ?? account.kind}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {dirty ? (
        <button type="button" disabled={saving} onClick={() => { void save(); }}
          className="mt-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {saving ? 'שומר…' : 'שמור חשבונות'}
        </button>
      ) : null}
    </div>
  );
}
