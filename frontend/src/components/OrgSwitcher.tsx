/** Organization selection is explicit and persists across all tenant requests. */
import { useEffect, useRef, useState } from 'react';
import { Building2, ChevronDown, Check } from 'lucide-react';
import api from '../services/api';
import {
  ACTIVE_ORG_KEY,
  commitActiveOrgId,
  readActiveOrgId,
  rememberOrgSession,
  writeActiveOrgId,
} from '../activeOrg';

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

export { ACTIVE_ORG_KEY };

export default function OrgSwitcher({
  currentUser,
  darkMode,
  onReady,
}: {
  currentUser: CurrentUser;
  darkMode: boolean;
  /** Fired after `active_org_id` is written, before tenant requests should start. */
  onReady?: () => void;
}) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [open, setOpen] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(() => {
    const raw = readActiveOrgId();
    return raw ? Number(raw) : null;
  });
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    let cancelled = false;
    let reloading = false;
    rememberOrgSession(currentUser);
    (async () => {
      try {
        const listed = await api.get<Org[]>('/admin/auth/organizations');
        if (cancelled) return;
        setOrgs(listed);
        const scope = currentUser.role === 'super_admin' ? 'catalog' : 'membership';
        const stored = readActiveOrgId();
        // Synchronous write: tenant routes stay unmounted until onReady, so this
        // key is in localStorage before the first X-Active-Org-Id request.
        const resolved = commitActiveOrgId(stored, listed, currentUser.organization_id, scope);
        setActiveId(resolved ? Number(resolved) : null);
        if (resolved && stored && resolved !== stored) {
          reloading = true;
          window.location.reload();
        }
      } catch {
        /* non-fatal: switcher just stays empty */
      } finally {
        if (!cancelled && !reloading) onReadyRef.current?.();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentUser]);

  if (orgs.length === 0) return null;

  const select = (id: number) => {
    writeActiveOrgId(id);
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
        title="Switch organization"
        aria-expanded={open}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition ${
          darkMode
            ? 'border-purple-700 bg-purple-900/30 text-purple-200 hover:bg-purple-900/50'
            : 'border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100'
        }`}
      >
        <Building2 size={16} />
        <span className="text-sm font-medium max-w-[100px] md:max-w-[160px] truncate">{activeName}</span>
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
