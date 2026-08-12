/**
 * מסך חוסם — "בחר ארגון פעיל".
 *
 * השרת מחזיר 409 `active_organization_required` לכל סופר-אדמין שאין לו
 * ארגון משלו ולא שלח `X-Active-Org-Id`. עד 11/08/2026 השרת החזיר במקום
 * זאת את ארגון 1 בשקט, ולכן דפדפן חדש, מצב פרטי או ניקוי אחסון היו
 * מפנים את כל האפליקציה לתיק של לקוח אמיתי בלי שאיש בחר בו.
 *
 * `api.ts` משדר `rezef:active-org-required` עם רשימת הארגונים שהשרת צירף
 * לשגיאה. הרשימה מגיעה מהשרת ולא נשמרת בלקוח: הלקוח אינו מקור אמת לשאלה
 * לאילו ארגונים מותר לגשת.
 */
import { useEffect, useState } from 'react';
import { Building2, AlertTriangle } from 'lucide-react';
import { ACTIVE_ORG_KEY } from './OrgSwitcher';

interface Org {
  id: number;
  name: string;
}

export const ACTIVE_ORG_REQUIRED_EVENT = 'rezef:active-org-required';

export default function ActiveOrgRequired({ darkMode = false }: { darkMode?: boolean }) {
  const [orgs, setOrgs] = useState<Org[] | null>(null);

  useEffect(() => {
    const onRequired = (e: Event) => {
      const detail = (e as CustomEvent<{ organizations?: Org[] }>).detail;
      setOrgs(detail?.organizations ?? []);
    };
    window.addEventListener(ACTIVE_ORG_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(ACTIVE_ORG_REQUIRED_EVENT, onRequired);
  }, []);

  if (orgs === null) return null;

  const select = (id: number) => {
    localStorage.setItem(ACTIVE_ORG_KEY, String(id));
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
