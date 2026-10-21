import React, { useCallback, useEffect, useState } from 'react';
import api from '../services/api';
import { Download, KeyRound, Loader2, RefreshCw, Shield, UserPlus, XCircle } from 'lucide-react';

/**
 * הרשאות גישה לפי מייל — פורט של app/admin/rbac (Medici) ושל admin-hotel-access
 * (price-monitor). מנהל-על: כל ארגון; מנהל ארגון: רק הארגונים שבהם הוא ADMIN.
 * כל בדיקת סמכות נעשית בשרת (/api/admin/access/*) — המסך רק מציג.
 */

interface Org { id: number; name: string }
interface Dashboard { id: number; slug: string; title: string; access_mode: string }
interface Grant {
  email: string;
  target: { type: 'organization' | 'dashboard'; id: number; slug?: string };
  role: string;
  status: string;
  source: string;
}
interface RoleConfig { description: string; scopes: string[]; capabilities: string[] }
interface RbacConfig { roles: Record<string, RoleConfig>; scopes: Record<string, string> }

const ORG_ROLES = [
  { value: 'viewer', label: 'צופה' },
  { value: 'user', label: 'משתמש' },
  { value: 'manager', label: 'מנהל/ת' },
  { value: 'accountant', label: 'רואה חשבון' },
  { value: 'admin', label: 'מנהל ארגון' },
];
const DASHBOARD_ROLES = [
  { value: 'client_viewer', label: 'צופה בדשבורד' },
  { value: 'client_editor', label: 'עורך תוכנית דשבורד' },
];
const STATUS_LABELS: Record<string, string> = {
  invited: 'ממתין לכניסה ראשונה',
  active: 'פעיל',
  revoked: 'בוטל',
  suspended: 'מושהה',
};

function errorText(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message_he) return detail.message_he;
  return fallback;
}

const AccessManagement: React.FC<{ darkMode: boolean }> = ({ darkMode }) => {
  const [tab, setTab] = useState<'grants' | 'rbac'>('grants');
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [isSuper, setIsSuper] = useState(false);
  const [orgId, setOrgId] = useState<number | null>(null);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [rbac, setRbac] = useState<RbacConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [targetType, setTargetType] = useState<'organization' | 'dashboard'>('organization');
  const [dashboardId, setDashboardId] = useState<number | null>(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('viewer');
  const [activateNow, setActivateNow] = useState(false);

  useEffect(() => {
    api.get<{ organizations: Org[]; is_super_admin: boolean }>('/admin/access/organizations')
      .then((data) => {
        setOrgs(data.organizations);
        setIsSuper(data.is_super_admin);
        if (data.organizations.length) setOrgId(data.organizations[0].id);
      })
      .catch((err) => setError(errorText(err, 'טעינת הארגונים נכשלה')));
    api.get<RbacConfig>('/admin/access/rbac').then(setRbac).catch(() => setRbac(null));
  }, []);

  const load = useCallback(async () => {
    if (orgId === null) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<{ grants: Grant[]; dashboards: Dashboard[] }>(
        '/admin/access/grants', { params: { organization_id: orgId } },
      );
      setGrants(data.grants);
      setDashboards(data.dashboards);
      setDashboardId(data.dashboards[0]?.id ?? null);
    } catch (err) {
      setError(errorText(err, 'טעינת ההרשאות נכשלה'));
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => { void load(); }, [load]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (orgId === null) return;
    setError(null);
    setInfo(null);
    try {
      await api.post('/admin/access/grants', {
        target_type: targetType,
        organization_id: targetType === 'organization' ? orgId : undefined,
        dashboard_id: targetType === 'dashboard' ? dashboardId : undefined,
        email,
        role,
        activate_now: targetType === 'organization' && isSuper && activateNow ? true : undefined,
      });
      setInfo(`ההרשאה נשמרה. ${email} ייכנס/תיכנס עם Google באותה כתובת.`);
      setEmail('');
      await load();
    } catch (err) {
      setError(errorText(err, 'שמירת ההרשאה נכשלה'));
    }
  };

  const revoke = async (grant: Grant) => {
    if (!window.confirm(`לבטל את הגישה של ${grant.email}?`)) return;
    setError(null);
    try {
      await api.post('/admin/access/grants/revoke', {
        target_type: grant.target.type,
        organization_id: grant.target.type === 'organization' ? grant.target.id : undefined,
        dashboard_id: grant.target.type === 'dashboard' ? grant.target.id : undefined,
        email: grant.email,
      });
      await load();
    } catch (err) {
      setError(errorText(err, 'ביטול ההרשאה נכשל'));
    }
  };

  const exportJson = async () => {
    try {
      const data = await api.get<unknown>('/admin/access/export', { params: { organization_id: orgId } });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `rezef-access-org-${orgId}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorText(err, 'הייצוא נכשל'));
    }
  };

  const card = darkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-900';
  const input = `rounded-lg border px-3 py-2 text-sm ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300'}`;

  return (
    <div dir="rtl" className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <KeyRound className="h-7 w-7 text-blue-600" />
        <div>
          <h1 className={`text-2xl font-bold ${darkMode ? 'text-white' : 'text-gray-900'}`}>הרשאות גישה</h1>
          <p className="text-sm text-gray-500">כל אדם נכנס עם המייל שלו ורואה רק את הארגון/הדשבורד שהוענקו לו.</p>
        </div>
      </div>

      <div className="flex gap-2">
        <button type="button" onClick={() => setTab('grants')}
          className={`rounded-lg px-4 py-2 text-sm ${tab === 'grants' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'}`}>
          הרשאות לפי מייל
        </button>
        <button type="button" onClick={() => setTab('rbac')}
          className={`rounded-lg px-4 py-2 text-sm ${tab === 'rbac' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'}`}>
          תפקידים והרשאות (RBAC)
        </button>
      </div>

      {error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}
      {info && <div className="rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">{info}</div>}

      {tab === 'grants' && (
        <>
          <div className={`flex flex-wrap items-center gap-3 rounded-xl p-4 shadow-sm ${card}`}>
            <label className="text-sm">ארגון</label>
            <select className={input} value={orgId ?? ''} onChange={(e) => setOrgId(Number(e.target.value))}>
              {orgs.map((org) => <option key={org.id} value={org.id}>{org.name} (#{org.id})</option>)}
            </select>
            <button type="button" onClick={() => void load()} className="flex items-center gap-1 text-sm text-blue-600">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} רענון
            </button>
            <button type="button" onClick={() => void exportJson()} className="flex items-center gap-1 text-sm text-blue-600">
              <Download className="h-4 w-4" /> ייצוא JSON (ל-Medici)
            </button>
            {orgs.length === 0 && <span className="text-sm text-gray-500">אין ארגונים שבהם יש לך הרשאת ניהול.</span>}
          </div>

          <form onSubmit={submit} className={`grid gap-3 rounded-xl p-4 shadow-sm md:grid-cols-5 ${card}`}>
            <select className={input} value={targetType} onChange={(e) => {
              const next = e.target.value as 'organization' | 'dashboard';
              setTargetType(next);
              setRole(next === 'organization' ? 'viewer' : 'client_viewer');
            }}>
              <option value="organization">כל הארגון</option>
              <option value="dashboard" disabled={!dashboards.length}>דשבורד לקוח</option>
            </select>
            {targetType === 'dashboard' ? (
              <select className={input} value={dashboardId ?? ''} onChange={(e) => setDashboardId(Number(e.target.value))}>
                {dashboards.map((d) => <option key={d.id} value={d.id}>{d.title} (/d/{d.slug})</option>)}
              </select>
            ) : <div />}
            <input className={input} type="email" required placeholder="אימייל" value={email}
              onChange={(e) => setEmail(e.target.value)} />
            <select className={input} value={role} onChange={(e) => setRole(e.target.value)}>
              {(targetType === 'organization' ? ORG_ROLES : DASHBOARD_ROLES).map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
            <button type="submit" className="flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white">
              <UserPlus className="h-4 w-4" /> הענקת גישה
            </button>
            {isSuper && targetType === 'organization' && (
              <label className="flex items-center gap-2 text-xs text-gray-500 md:col-span-5">
                <input type="checkbox" checked={activateNow} onChange={(e) => setActivateNow(e.target.checked)} />
                הפעלה מיידית למשתמש קיים (מנהל-על בלבד; אחרת ההרשאה נפתחת בכניסת Google הראשונה)
              </label>
            )}
          </form>

          <div className={`overflow-x-auto rounded-xl shadow-sm ${card}`}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-right text-gray-500">
                  <th className="p-3">אימייל</th><th className="p-3">יעד</th><th className="p-3">תפקיד</th>
                  <th className="p-3">סטטוס</th><th className="p-3">מקור</th><th className="p-3" />
                </tr>
              </thead>
              <tbody>
                {grants.map((grant) => (
                  <tr key={`${grant.target.type}-${grant.target.id}-${grant.email}`} className="border-b last:border-0">
                    <td className="p-3" dir="ltr">{grant.email}</td>
                    <td className="p-3">{grant.target.type === 'organization' ? 'ארגון' : `דשבורד /d/${grant.target.slug}`}</td>
                    <td className="p-3">{grant.role}</td>
                    <td className="p-3">{STATUS_LABELS[grant.status] || grant.status}</td>
                    <td className="p-3">{grant.source}</td>
                    <td className="p-3">
                      {grant.status !== 'revoked' && (
                        <button type="button" onClick={() => void revoke(grant)} className="flex items-center gap-1 text-red-600">
                          <XCircle className="h-4 w-4" /> ביטול
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!grants.length && !loading && (
                  <tr><td colSpan={6} className="p-6 text-center text-gray-500">אין הרשאות בארגון הזה.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'rbac' && rbac && (
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(rbac.roles).map(([name, config]) => (
            <div key={name} className={`rounded-xl p-4 shadow-sm ${card}`}>
              <div className="flex items-center gap-2 font-semibold"><Shield className="h-4 w-4 text-blue-600" />{name}</div>
              <p className="mt-1 text-sm text-gray-500">{config.description}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                {config.scopes.map((scope) => (
                  <span key={scope} title={rbac.scopes[scope]} className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700" dir="ltr">{scope}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default AccessManagement;
