/** Active organization selection, shared by the API client and the switcher. */

export const ACTIVE_ORG_KEY = 'active_org_id';
export const ACTIVE_ORG_HEADER = 'X-Active-Org-Id';

export type OrgChoice = { id: number };

/** `membership` is the caller's own orgs. `catalog` is every client a super-admin can open. */
export type OrgListScope = 'membership' | 'catalog';

export type OrgSessionHint = {
  preferredId: number | string | null;
  scope: OrgListScope;
};

export function readActiveOrgId(storage: Pick<Storage, 'getItem'> | null = safeStorage()): string | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(ACTIVE_ORG_KEY);
    return raw && /^\d+$/.test(raw) ? raw : null;
  } catch {
    return null;
  }
}

export function writeActiveOrgId(
  id: number | string,
  storage: Pick<Storage, 'setItem'> | null = safeStorage(),
): void {
  if (!storage) return;
  storage.setItem(ACTIVE_ORG_KEY, String(id));
}

export function clearActiveOrgId(storage: Pick<Storage, 'removeItem'> | null = safeStorage()): void {
  if (!storage) return;
  storage.removeItem(ACTIVE_ORG_KEY);
}

/**
 * Which org id rides on the next request.
 * A valid stored id wins. One org is selected on its own.
 * Otherwise a home org (`users.organization_id`) that is still in the list.
 * A membership list with nothing stored and no home org uses the lowest id,
 * so a reload is not blocked on the chooser.
 * A super-admin catalog with nothing stored and no home org stays unset:
 * the chooser opens instead of a silent client file.
 */
export function resolveActiveOrgId(
  stored: string | null,
  orgs: OrgChoice[],
  preferredId?: number | string | null,
  scope: OrgListScope = 'membership',
): string | null {
  const ids = new Set(orgs.map((org) => String(org.id)));
  if (stored && ids.has(stored)) return stored;
  if (orgs.length === 1) return String(orgs[0].id);
  const preferred = preferredOrgId(preferredId);
  if (preferred && ids.has(preferred)) return preferred;
  if (scope === 'membership' && orgs.length > 1) return lowestOrgId(orgs);
  return null;
}

/**
 * Write `active_org_id` when resolution picked something that is not already stored.
 * The request interceptor reads that key, so the write has to happen before the next call.
 */
export function commitActiveOrgId(
  stored: string | null,
  orgs: OrgChoice[],
  preferredId?: number | string | null,
  scope: OrgListScope = 'membership',
  storage: Pick<Storage, 'getItem' | 'setItem'> | null = safeStorage(),
): string | null {
  const resolved = resolveActiveOrgId(stored, orgs, preferredId, scope);
  if (resolved && resolved !== stored) writeActiveOrgId(resolved, storage);
  return resolved;
}

/**
 * 409 recovery. Without a signed-in session the list is treated as a catalog,
 * so an early failure cannot pin a client before we know whose memberships these are.
 */
export function resolveFromRequiredDetail(
  stored: string | null,
  organizations: OrgChoice[] | null | undefined,
  session: OrgSessionHint | null,
): string | null {
  const listed = organizations ?? [];
  if (!session) return resolveActiveOrgId(stored, listed, null, 'catalog');
  return resolveActiveOrgId(stored, listed, session.preferredId, session.scope);
}

let orgSession: OrgSessionHint | null = null;

export function rememberOrgSession(user: { organization_id?: number | null; role?: string | null }): void {
  orgSession = {
    preferredId: user.organization_id ?? null,
    scope: user.role === 'super_admin' ? 'catalog' : 'membership',
  };
}

export function readOrgSession(): OrgSessionHint | null {
  return orgSession;
}

function preferredOrgId(value: number | string | null | undefined): string | null {
  if (value == null || value === '') return null;
  const raw = String(value);
  return /^\d+$/.test(raw) ? raw : null;
}

function lowestOrgId(orgs: OrgChoice[]): string {
  let lowest = orgs[0].id;
  for (let i = 1; i < orgs.length; i += 1) {
    if (orgs[i].id < lowest) lowest = orgs[i].id;
  }
  return String(lowest);
}

function safeStorage(): Storage | null {
  try {
    return localStorage;
  } catch {
    return null;
  }
}
