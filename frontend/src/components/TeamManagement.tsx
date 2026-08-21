import React, { useCallback, useEffect, useState } from 'react';
import api from '../services/api';
import { CurrentUser } from './OrgSwitcher';
import {
  Loader2,
  RefreshCw,
  ShieldOff,
  Trash2,
  UserPlus,
  Users,
  Copy,
  Check,
} from 'lucide-react';

/**
 * מסך ניהול צוות — חברי הארגון הפעיל, תפקידים וסטטוס חברות.
 * ה-backend כבר קיים במלואו (memberships invite/suspend/revoke, PATCH users);
 * המסך הזה רק חושף אותו.
 */

interface TeamMember {
  id: number;
  email: string;
  full_name: string;
  phone?: string | null;
  role: string;
  is_active: boolean;
  last_login?: string | null;
  membership_status: string;
  membership_expires_at?: string | null;
}

interface Props {
  darkMode: boolean;
  currentUser: CurrentUser | null;
}

const ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'admin', label: 'מנהל ארגון' },
  { value: 'accountant', label: 'רואה חשבון' },
  { value: 'manager', label: 'מנהל' },
  { value: 'user', label: 'משתמש' },
  { value: 'viewer', label: 'צופה בלבד' },
];

const ROLE_LABELS: Record<string, string> = {
  super_admin: 'מנהל על',
  admin: 'מנהל ארגון',
  accountant: 'רואה חשבון',
  manager: 'מנהל',
  user: 'משתמש',
  viewer: 'צופה בלבד',
};

const STATUS_LABELS: Record<string, { label: string; tone: 'green' | 'yellow' | 'red' | 'gray' }> = {
  active: { label: 'פעיל', tone: 'green' },
  invited: { label: 'הוזמן — טרם אישר', tone: 'yellow' },
  suspended: { label: 'מושהה', tone: 'red' },
  revoked: { label: 'בוטל', tone: 'gray' },
};

function generateTempPassword(): string {
  // סיסמה זמנית אקראית (16 תווים) — המנהל מעתיק ומוסר, והמשתמש יחליף.
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%';
  const values = new Uint32Array(16);
  crypto.getRandomValues(values);
  return Array.from(values, (v) => chars[v % chars.length]).join('');
}

const TeamManagement: React.FC<Props> = ({ darkMode, currentUser }) => {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);

  // טופס הזמנה
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('user');
  const [inviteBusy, setInviteBusy] = useState(false);
  // כשההזמנה נכשלת כי המשתמש לא קיים — מציעים יצירה עם סיסמה זמנית
  const [offerCreate, setOfferCreate] = useState(false);
  const [createFullName, setCreateFullName] = useState('');
  const [tempPassword, setTempPassword] = useState<string | null>(null);
  const [tempCopied, setTempCopied] = useState(false);

  const detailOf = (err: any, fallback: string): string => {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && typeof detail.message_he === 'string') {
      return detail.message_he;
    }
    return fallback;
  };

  const loadMembers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<TeamMember[]>('/admin/users');
      setMembers(data);
    } catch (err: any) {
      setError(detailOf(err, 'טעינת חברי הצוות נכשלה.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setOfferCreate(false);
    setTempPassword(null);
    setInviteBusy(true);
    try {
      await api.post('/admin/memberships/invite', {
        email: inviteEmail,
        role: inviteRole,
      });
      setNotice(`נשלחה הזמנה ל-${inviteEmail}. החברות תופעל כשהמשתמש יאשר אותה.`);
      setInviteEmail('');
      await loadMembers();
    } catch (err: any) {
      if (err?.response?.status === 404) {
        // מגבלת ה-API בכנות: הזמנה עובדת רק לחשבון קיים במערכת.
        setError(
          `אין חשבון קיים לכתובת ${inviteEmail} — ההזמנה דרך ה-API עובדת רק ` +
          'למשתמש שכבר נרשם. אפשר ליצור עבורו חשבון עם סיסמה זמנית שתמסרו לו.',
        );
        setOfferCreate(true);
      } else {
        setError(detailOf(err, 'שליחת ההזמנה נכשלה.'));
      }
    } finally {
      setInviteBusy(false);
    }
  };

  const handleCreateUser = async () => {
    setError(null);
    setNotice(null);
    setInviteBusy(true);
    const password = generateTempPassword();
    try {
      const activeOrg = localStorage.getItem('active_org_id');
      const orgId = activeOrg ? Number(activeOrg) : currentUser?.organization_id;
      await api.post('/admin/users', {
        email: inviteEmail,
        password,
        full_name: createFullName || inviteEmail.split('@')[0],
        role: inviteRole,
        organization_id: orgId,
      });
      setTempPassword(password);
      setTempCopied(false);
      setNotice(
        `נוצר חשבון עבור ${inviteEmail} עם הזמנה לארגון. העתיקו את הסיסמה הזמנית ` +
        'ומסרו לו אותה — היא לא תוצג שוב. המשתמש יאשר את ההזמנה בכניסה הראשונה.',
      );
      setOfferCreate(false);
      setInviteEmail('');
      setCreateFullName('');
      await loadMembers();
    } catch (err: any) {
      setError(detailOf(err, 'יצירת המשתמש נכשלה.'));
    } finally {
      setInviteBusy(false);
    }
  };

  const runAction = async (userId: number, action: () => Promise<unknown>, failMessage: string) => {
    setError(null);
    setNotice(null);
    setBusyUserId(userId);
    try {
      await action();
      await loadMembers();
    } catch (err: any) {
      setError(detailOf(err, failMessage));
    } finally {
      setBusyUserId(null);
    }
  };

  const changeRole = (member: TeamMember, role: string) =>
    runAction(member.id, () => api.patch(`/admin/users/${member.id}`, { role }), 'שינוי התפקיד נכשל.');

  const suspendMembership = (member: TeamMember) =>
    runAction(member.id, () => api.post(`/admin/memberships/${member.id}/suspend`), 'השעיית החברות נכשלה.');

  const reactivateMembership = (member: TeamMember) =>
    runAction(member.id, () => api.patch(`/admin/users/${member.id}`, { is_active: true }), 'הפעלת החברות מחדש נכשלה.');

  const revokeMembership = (member: TeamMember) => {
    if (!window.confirm(`לבטל את החברות של ${member.full_name} בארגון? הפעולה מסירה את הגישה שלו לתיק.`)) return;
    return runAction(member.id, () => api.post(`/admin/memberships/${member.id}/revoke`), 'ביטול החברות נכשל.');
  };

  const deactivateUser = (member: TeamMember) => {
    if (!window.confirm(`להשבית את המשתמש ${member.full_name}? ההשבתה משעה את החברות שלו בארגון.`)) return;
    return runAction(member.id, () => api.patch(`/admin/users/${member.id}`, { is_active: false }), 'השבתת המשתמש נכשלה.');
  };

  const copyTempPassword = async () => {
    if (!tempPassword) return;
    try {
      await navigator.clipboard.writeText(tempPassword);
      setTempCopied(true);
    } catch {
      setTempCopied(false);
    }
  };

  const card = `rounded-xl border shadow-sm ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`;
  const inputClass = `px-3 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
    darkMode
      ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
      : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
  }`;
  const textMain = darkMode ? 'text-white' : 'text-gray-900';
  const textSub = darkMode ? 'text-gray-400' : 'text-gray-500';

  const toneClass = (tone: 'green' | 'yellow' | 'red' | 'gray') => {
    switch (tone) {
      case 'green':
        return darkMode ? 'bg-green-900/40 text-green-300' : 'bg-green-100 text-green-700';
      case 'yellow':
        return darkMode ? 'bg-yellow-900/40 text-yellow-300' : 'bg-yellow-100 text-yellow-700';
      case 'red':
        return darkMode ? 'bg-red-900/40 text-red-300' : 'bg-red-100 text-red-700';
      default:
        return darkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600';
    }
  };

  return (
    <div className="p-6 space-y-6" dir="rtl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
            <Users size={20} className="text-white" />
          </div>
          <div>
            <h1 className={`text-2xl font-bold ${textMain}`}>ניהול צוות</h1>
            <p className={`text-sm ${textSub}`}>חברי הארגון הפעיל, תפקידים והרשאות</p>
          </div>
        </div>
        <button
          onClick={loadMembers}
          disabled={loading}
          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition ${
            darkMode ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-600 hover:bg-gray-100'
          }`}
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          רענון
        </button>
      </div>

      {/* טופס הזמנה */}
      <div className={`${card} p-5`}>
        <h2 className={`text-lg font-semibold mb-3 ${textMain}`}>הזמנת חבר צוות</h2>
        <form onSubmit={handleInvite} className="flex flex-wrap items-center gap-3">
          <input
            type="email"
            required
            value={inviteEmail}
            onChange={(e) => {
              setInviteEmail(e.target.value);
              setOfferCreate(false);
            }}
            placeholder="אימייל של המוזמן"
            className={`${inputClass} flex-1 min-w-[220px]`}
          />
          <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)} className={inputClass}>
            {ROLE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <button
            type="submit"
            disabled={inviteBusy}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-lg transition"
          >
            {inviteBusy ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={16} />}
            שליחת הזמנה
          </button>
        </form>

        {offerCreate && (
          <div className={`mt-4 p-4 rounded-lg border ${darkMode ? 'border-yellow-700 bg-yellow-900/20' : 'border-yellow-300 bg-yellow-50'}`}>
            <div className={`text-sm mb-3 ${darkMode ? 'text-yellow-200' : 'text-yellow-800'}`}>
              יצירת חשבון חדש עבור {inviteEmail} בתפקיד {ROLE_LABELS[inviteRole] || inviteRole}, עם סיסמה זמנית להעתקה.
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="text"
                value={createFullName}
                onChange={(e) => setCreateFullName(e.target.value)}
                placeholder="שם מלא (רשות)"
                className={`${inputClass} flex-1 min-w-[180px]`}
              />
              <button
                type="button"
                onClick={handleCreateUser}
                disabled={inviteBusy}
                className="flex items-center gap-2 bg-yellow-600 hover:bg-yellow-700 disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-lg transition"
              >
                {inviteBusy ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={16} />}
                יצירת חשבון עם סיסמה זמנית
              </button>
            </div>
          </div>
        )}

        {tempPassword && (
          <div className={`mt-4 p-4 rounded-lg border ${darkMode ? 'border-green-700 bg-green-900/20' : 'border-green-300 bg-green-50'}`}>
            <div className={`text-sm mb-2 ${darkMode ? 'text-green-200' : 'text-green-800'}`}>
              סיסמה זמנית (לא תוצג שוב אחרי יציאה מהמסך):
            </div>
            <div className="flex items-center gap-2">
              <code className={`px-3 py-1.5 rounded-lg text-sm font-mono ${darkMode ? 'bg-gray-900 text-green-300' : 'bg-white text-green-800 border border-green-200'}`} dir="ltr">
                {tempPassword}
              </code>
              <button
                type="button"
                onClick={copyTempPassword}
                className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm transition ${
                  darkMode ? 'text-green-300 hover:bg-green-900/40' : 'text-green-700 hover:bg-green-100'
                }`}
              >
                {tempCopied ? <Check size={14} /> : <Copy size={14} />}
                {tempCopied ? 'הועתק' : 'העתקה'}
              </button>
            </div>
          </div>
        )}
      </div>

      {notice && (
        <div className={`text-sm rounded-lg px-4 py-3 ${darkMode ? 'bg-green-900/20 text-green-300' : 'bg-green-50 text-green-700'}`}>
          {notice}
        </div>
      )}
      {error && (
        <div className={`text-sm rounded-lg px-4 py-3 ${darkMode ? 'bg-red-900/20 text-red-300' : 'bg-red-50 text-red-600'}`}>
          {error}
        </div>
      )}

      {/* טבלת חברי הארגון */}
      <div className={`${card} overflow-x-auto`}>
        {loading ? (
          <div className="flex items-center justify-center gap-2 p-10">
            <Loader2 size={20} className="animate-spin text-blue-500" />
            <span className={textSub}>טוען חברי צוות…</span>
          </div>
        ) : members.length === 0 ? (
          <div className={`p-10 text-center text-sm ${textSub}`}>
            אין חברי צוות בארגון הפעיל.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className={`text-right ${darkMode ? 'bg-gray-900/40 text-gray-400' : 'bg-gray-50 text-gray-500'}`}>
                <th className="px-4 py-3 font-medium">שם</th>
                <th className="px-4 py-3 font-medium">אימייל</th>
                <th className="px-4 py-3 font-medium">תפקיד בארגון</th>
                <th className="px-4 py-3 font-medium">סטטוס חברות</th>
                <th className="px-4 py-3 font-medium">כניסה אחרונה</th>
                <th className="px-4 py-3 font-medium">פעולות</th>
              </tr>
            </thead>
            <tbody>
              {members.map((member) => {
                const statusInfo = STATUS_LABELS[member.membership_status] || { label: member.membership_status, tone: 'gray' as const };
                const isSelf = currentUser?.id === member.id;
                const busy = busyUserId === member.id;
                return (
                  <tr key={member.id} className={`border-t ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                    <td className={`px-4 py-3 font-medium ${textMain}`}>
                      {member.full_name}
                      {isSelf && <span className={`mr-2 text-xs ${textSub}`}>(אני)</span>}
                      {!member.is_active && (
                        <span className={`mr-2 text-[11px] px-2 py-0.5 rounded-full ${toneClass('red')}`}>מושבת</span>
                      )}
                    </td>
                    <td className={`px-4 py-3 ${textSub}`} dir="ltr">{member.email}</td>
                    <td className="px-4 py-3">
                      {isSelf || member.role === 'super_admin' ? (
                        <span className={textMain}>{ROLE_LABELS[member.role] || member.role}</span>
                      ) : (
                        <select
                          value={member.role}
                          disabled={busy}
                          onChange={(e) => changeRole(member, e.target.value)}
                          className={inputClass}
                        >
                          {ROLE_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-1 rounded-full ${toneClass(statusInfo.tone)}`}>
                        {statusInfo.label}
                      </span>
                    </td>
                    <td className={`px-4 py-3 ${textSub}`}>
                      {member.last_login ? new Date(member.last_login).toLocaleString('he-IL') : 'טרם התחבר'}
                    </td>
                    <td className="px-4 py-3">
                      {isSelf ? (
                        <span className={`text-xs ${textSub}`}>אין פעולות עצמיות</span>
                      ) : busy ? (
                        <Loader2 size={16} className="animate-spin text-blue-500" />
                      ) : (
                        <div className="flex items-center gap-2">
                          {member.membership_status === 'active' ? (
                            <button
                              onClick={() => suspendMembership(member)}
                              title="השעיית חברות"
                              className={`p-1.5 rounded-lg transition ${darkMode ? 'text-yellow-300 hover:bg-yellow-900/30' : 'text-yellow-600 hover:bg-yellow-50'}`}
                            >
                              <ShieldOff size={16} />
                            </button>
                          ) : member.membership_status === 'suspended' ? (
                            <button
                              onClick={() => reactivateMembership(member)}
                              title="הפעלה מחדש"
                              className={`p-1.5 rounded-lg transition ${darkMode ? 'text-green-300 hover:bg-green-900/30' : 'text-green-600 hover:bg-green-50'}`}
                            >
                              <RefreshCw size={16} />
                            </button>
                          ) : null}
                          {member.membership_status !== 'revoked' && (
                            <button
                              onClick={() => revokeMembership(member)}
                              title="ביטול חברות בארגון"
                              className={`p-1.5 rounded-lg transition ${darkMode ? 'text-red-300 hover:bg-red-900/30' : 'text-red-500 hover:bg-red-50'}`}
                            >
                              <Trash2 size={16} />
                            </button>
                          )}
                          {member.is_active && member.membership_status === 'active' && (
                            <button
                              onClick={() => deactivateUser(member)}
                              title="השבתת משתמש"
                              className={`text-xs px-2 py-1 rounded-lg transition ${darkMode ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-600 hover:bg-gray-100'}`}
                            >
                              השבתה
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <p className={`text-xs ${textSub}`}>
        הערה: הזמנה מקנה סטטוס "הוזמן" בלבד — הגישה נפתחת רק אחרי שהמוזמן מאשר את
        ההזמנה מתוך החשבון שלו. השעיה וביטול נכנסים לתוקף בבקשה הבאה של המשתמש.
      </p>
    </div>
  );
};

export default TeamManagement;
