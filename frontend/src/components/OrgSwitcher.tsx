/**
 * Super-admin organization switcher ("act as client").
 *
 * Renders ONLY for SUPER_ADMIN. Lists every organization (/admin/organizations)
 * and lets the operator pick the active one. The choice is persisted in
 * localStorage('active_org_id') and sent on every request as X-Active-Org-Id
 * (see services/api.ts), so the entire app — dashboards, AR/AP, cash flow, sync
 * — re-scopes to the chosen client. Switching clears the react-query cache and
 * reloads so no stale org data lingers.
 */
import { useEffect, useState } from 'react';
import { Building2, ChevronDown, Check } from 'lucide-react';
import api from '../services/api';

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  organization_id: number | null;
}

interface Org {
  id: number;
  name: string;
}

export const ACTIVE_ORG_KEY = 'active_org_id';

export default function OrgSwitcher({
  currentUser,
  darkMode,
}: {
  currentUser: CurrentUser;
  darkMode: boolean;
}) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [open, setOpen] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(() => {
    const raw = localStorage.getItem(ACTIVE_ORG_KEY);
    return raw ? Number(raw) : currentUser.organization_id;
  });

  const isSuper = currentUser.role === 'super_admin';

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        setOrgs(await api.get<Org[]>('/admin/organizations'));
      } catch {
        /* non-fatal: switcher just stays empty */
      }
    })();
  }, [isSuper]);

  if (!isSuper) return null;

  const select = (id: number) => {
    if (id === currentUser.organization_id) {
      // Back to the operator's home org → drop the override entirely.
      localStorage.removeItem(ACTIVE_ORG_KEY);
    } else {
      localStorage.setItem(ACTIVE_ORG_KEY, String(id));
    }
    setActiveId(id);
    setOpen(false);
    // Hard reload so every dashboard refetches under the new org scope.
    window.location.reload();
  };

  const activeName =
    orgs.find((o) => o.id === activeId)?.name || `ארגון ${activeId ?? '—'}`;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title="החלפת לקוח (super admin)"
        className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition ${
          darkMode
            ? 'border-purple-700 bg-purple-900/30 text-purple-200 hover:bg-purple-900/50'
            : 'border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100'
        }`}
      >
        <Building2 size={16} />
        <span className="text-sm font-medium max-w-[160px] truncate">{activeName}</span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div
          className={`absolute right-0 mt-2 w-64 rounded-xl shadow-xl border z-50 ${
            darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
          }`}
        >
          <div
            className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider border-b ${
              darkMode ? 'text-gray-500 border-gray-700' : 'text-gray-400 border-gray-200'
            }`}
          >
            כל הלקוחות ({orgs.length})
          </div>
          <div className="max-h-80 overflow-y-auto p-2">
            {orgs.map((o) => {
              const active = o.id === activeId;
              const home = o.id === currentUser.organization_id;
              return (
                <button
                  key={o.id}
                  onClick={() => select(o.id)}
                  className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-right transition ${
                    active
                      ? darkMode
                        ? 'bg-purple-900/40 text-purple-200'
                        : 'bg-purple-50 text-purple-700'
                      : darkMode
                      ? 'text-gray-300 hover:bg-gray-700'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    {active ? <Check size={15} /> : <span className="w-[15px]" />}
                    <span className="text-sm truncate">{o.name}</span>
                  </span>
                  <span className="flex items-center gap-1 shrink-0">
                    {home && (
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded ${
                          darkMode ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        הבית שלי
                      </span>
                    )}
                    <span className={`text-[11px] ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                      #{o.id}
                    </span>
                  </span>
                </button>
              );
            })}
            {orgs.length === 0 && (
              <p className={`px-3 py-4 text-sm text-center ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                טוען ארגונים…
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
