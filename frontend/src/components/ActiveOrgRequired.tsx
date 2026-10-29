/**
 * מסך חוסם — "בחר ארגון פעיל".
 *
 * השרת מחזיר 409 `active_organization_required` כשאין `X-Active-Org-Id`
 * ויש יותר מארגון אחד לבחירה: סופר-אדמין מול קטלוג הלקוחות, או משתמש עם
 * כמה חברויות. עד 11/08/2026 סופר-אדמין בלי כותרת נפל בשקט לארגון 1.
 *
 * אם הבית או רשימת החברויות כבר מספיקים כדי לבחור, הרכיב כותב את המזהה
 * וטוען מחדש במקום להציג את החלון. הבורר נשאר כשאין בחירה בטוחה
 * (קטלוג סופר-אדמין בלי בית שמור).
 *
 * `api.ts` משדר `rezef:active-org-required` עם רשימת הארגונים שהשרת צירף
 * לשגיאה. הרשימה מגיעה מהשרת ולא נשמרת בלקוח: הלקוח אינו מקור אמת לשאלה
 * לאילו ארגונים מותר לגשת.
 */
import { useEffect, useState } from 'react';
import { Building2, AlertTriangle } from 'lucide-react';
import { readActiveOrgId, readOrgSession, resolveFromRequiredDetail, writeActiveOrgId } from '../activeOrg';
import type { CurrentUser } from './OrgSwitcher';

interface Org {
  id: number;
  name: string;
}

export const ACTIVE_ORG_REQUIRED_EVENT = 'rezef:active-org-required';

export default function ActiveOrgRequired({
  darkMode = false,
  currentUser = null,
  identityReady = false,
}: {
  darkMode?: boolean;
  currentUser?: CurrentUser | null;
  identityReady?: boolean;
}) {
  const [orgs, setOrgs] = useState<Org[] | null>(null);

  useEffect(() => {
    const onRequired = (e: Event) => {
      const detail = (e as CustomEvent<{ organizations?: Org[] }>).detail;
      setOrgs(detail?.organizations ?? []);
    };
    window.addEventListener(ACTIVE_ORG_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(ACTIVE_ORG_REQUIRED_EVENT, onRequired);
  }, []);

  const session = !identityReady
    ? null
    : currentUser
      ? {
          preferredId: currentUser.organization_id,
          scope: currentUser.role === 'super_admin' ? 'catalog' as const : 'membership' as const,
        }
      : readOrgSession();
  const resolved = orgs ? resolveFromRequiredDetail(readActiveOrgId(), orgs, session) : null;

  useEffect(() => {
    if (!resolved || readActiveOrgId() === resolved) return;
    writeActiveOrgId(resolved);
    window.location.reload();
  }, [resolved]);

  if (orgs === null || resolved || !identityReady) return null;

  const select = (id: number) => {
    writeActiveOrgId(id);
    window.location.reload();
  };

  return (
    <div
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="active-org-required-title"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4"
    >
      <div
        className={`w-full max-w-md rounded-2xl shadow-2xl border p-6 ${
          darkMode ? 'bg-gray-900 border-gray-700' : 'bg-white border-gray-200'
        }`}
      >
        <div className="flex items-center gap-3 mb-2">
          <AlertTriangle className="text-amber-500 shrink-0" size={22} />
          <h2
            id="active-org-required-title"
            className={`text-lg font-bold ${darkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            יש לבחור ארגון פעיל
          </h2>
        </div>
        <p className={`text-sm mb-5 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          לחשבון שלך אין ארגון משלו. בחר את התיק שבו תפעל — כל קריאה, כתיבה
          וסנכרון יתבצעו בתוכו.
        </p>

        {orgs.length === 0 ? (
          <p
            className={`text-sm text-center py-6 ${
              darkMode ? 'text-gray-500' : 'text-gray-400'
            }`}
          >
            אין ארגונים פעילים לבחירה.
          </p>
        ) : (
          <div className="max-h-72 overflow-y-auto -mx-1 px-1 space-y-1">
            {orgs.map((o) => (
              <button
                key={o.id}
                onClick={() => select(o.id)}
                className={`w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-lg text-right transition ${
                  darkMode
                    ? 'text-gray-200 hover:bg-gray-800'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <Building2 size={16} className="shrink-0" />
                  <span className="text-sm truncate">{o.name}</span>
                </span>
                <span className={`text-[11px] shrink-0 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                  #{o.id}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
