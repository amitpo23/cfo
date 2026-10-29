/** Active organization selection, shared by the API client and the switcher. */

export const ACTIVE_ORG_KEY = 'active_org_id';

export type OrgChoice = { id: number };

export function readActiveOrgId(storage: Pick<Storage, 'getItem'> | null = safeStorage()): string | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(ACTIVE_ORG_KEY);
    return raw && /^\d+$/.test(raw) ? raw : null;
  } catch {
    return null;
  }
}

export function writeActiveOrgId(id: number | string, storage: Pick<Storage, 'setItem'> | null = safeStorage()): void {
  if (!storage) return;
  storage.setItem(ACTIVE_ORG_KEY, String(id));
}

export function clearActiveOrgId(storage: Pick<Storage, 'removeItem'> | null = safeStorage()): void {
  if (!storage) return;
  storage.removeItem(ACTIVE_ORG_KEY);
}

/**
 * Restore a stored choice when it is still usable.
 * One membership is selected automatically.
 * Several memberships and no stored choice stay unselected (the chooser).
 */
export function resolveActiveOrgId(stored: string | null, orgs: OrgChoice[]): string | null {
  const ids = new Set(orgs.map((org) => String(org.id)));
  if (stored && ids.has(stored)) return stored;
  if (orgs.length === 1) return String(orgs[0].id);
  return null;
}

function safeStorage(): Storage | null {
  try {
    return localStorage;
  } catch {
    return null;
  }
}
