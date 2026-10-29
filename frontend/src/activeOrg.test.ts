import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  commitActiveOrgId,
  readActiveOrgId,
  resolveActiveOrgId,
  resolveFromRequiredDetail,
  writeActiveOrgId,
  ACTIVE_ORG_HEADER,
} from './activeOrg.ts';
import { canManageTeam } from './teamAccess.ts';

test('a stored org is restored when it is still a membership', () => {
  assert.equal(resolveActiveOrgId('6', [{ id: 2 }, { id: 6 }]), '6');
});

test('one membership is selected without a stored choice', () => {
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }]), '6');
});

test('two memberships and an empty store restore the home org, not the other one', () => {
  // Chef 6 is home. Food Group 2 is the other membership.
  assert.equal(resolveActiveOrgId(null, [{ id: 2 }, { id: 6 }], 6), '6');
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }, { id: 2 }], '6'), '6');
});

test('two memberships and no stored or home org pick the lowest id', () => {
  // List is high-to-low so a "first row" pick would return 6.
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }, { id: 2 }]), '2');
  assert.equal(resolveActiveOrgId('99', [{ id: 6 }, { id: 2 }], null), '2');
  // A home id that is not a membership is not sent; the lowest membership is.
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }, { id: 2 }], 99), '2');
});

test('a stored choice wins over a different home org', () => {
  assert.equal(resolveActiveOrgId('2', [{ id: 2 }, { id: 6 }], 6), '2');
});

test('a super-admin catalog with no stored or home org stays unselected', () => {
  const catalog = [{ id: 1 }, { id: 2 }, { id: 6 }, { id: 9 }];
  assert.equal(resolveActiveOrgId(null, catalog, null, 'catalog'), null);
  assert.equal(resolveActiveOrgId('99', catalog, null, 'catalog'), null);
  // Two clients is still a choice. Lowest-id is only for a membership list.
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }, { id: 2 }], null, 'catalog'), null);
});

test('a super-admin home org that is in the catalog is restored', () => {
  assert.equal(resolveActiveOrgId(null, [{ id: 2 }, { id: 6 }, { id: 9 }], 6, 'catalog'), '6');
  assert.equal(resolveActiveOrgId(null, [{ id: 2 }, { id: 6 }], 99, 'catalog'), null);
});

test('one catalog org is selected without a stored choice', () => {
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }], null, 'catalog'), '6');
});

test('a resolved org that is not stored is written for the next request', () => {
  const mem = memoryStorage();
  const resolved = commitActiveOrgId(null, [{ id: 6 }, { id: 2 }], 6, 'membership', mem);
  assert.equal(resolved, '6');
  assert.equal(readActiveOrgId(mem), '6');
  assert.equal(mem.getItem('active_org_id'), '6');
});

test('a choice that is already stored is left as the header value', () => {
  const mem = memoryStorage({ active_org_id: '6' });
  writeActiveOrgId(6, mem);
  assert.equal(readActiveOrgId(mem), '6');
  const resolved = commitActiveOrgId('6', [{ id: 2 }, { id: 6 }], 2, 'membership', mem);
  assert.equal(resolved, '6');
  assert.equal(readActiveOrgId(mem), '6');
});

test('409 recovery uses the home org for a membership and refuses a catalog guess', () => {
  const two = [{ id: 6 }, { id: 2 }];
  assert.equal(
    resolveFromRequiredDetail(null, two, { preferredId: 6, scope: 'membership' }),
    '6',
  );
  assert.equal(
    resolveFromRequiredDetail(null, two, { preferredId: null, scope: 'membership' }),
    '2',
  );
  assert.equal(
    resolveFromRequiredDetail(null, [{ id: 1 }, { id: 2 }, { id: 6 }], null),
    null,
  );
  assert.equal(
    resolveFromRequiredDetail(null, [{ id: 1 }, { id: 2 }, { id: 6 }], { preferredId: null, scope: 'catalog' }),
    null,
  );
  assert.equal(ACTIVE_ORG_HEADER, 'X-Active-Org-Id');
});

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key: string) {
      return data.has(key) ? data.get(key)! : null;
    },
    setItem(key: string, value: string) {
      data.set(key, value);
    },
    removeItem(key: string) {
      data.delete(key);
    },
  };
}

test('a viewer cannot manage the team; an admin and a super admin can', () => {
  assert.equal(canManageTeam('viewer', 'viewer'), false);
  assert.equal(canManageTeam('user', 'viewer'), false);
  assert.equal(canManageTeam('admin', 'viewer'), false);
  assert.equal(canManageTeam('viewer', 'admin'), true);
  assert.equal(canManageTeam('super_admin', 'viewer'), true);
});
