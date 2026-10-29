import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveActiveOrgId } from './activeOrg.ts';
import { canManageTeam } from './teamAccess.ts';

test('a stored org is restored when it is still a membership', () => {
  assert.equal(resolveActiveOrgId('6', [{ id: 2 }, { id: 6 }]), '6');
});

test('one membership is selected without a stored choice', () => {
  assert.equal(resolveActiveOrgId(null, [{ id: 6 }]), '6');
});

test('several memberships and no stored choice stay unselected', () => {
  assert.equal(resolveActiveOrgId(null, [{ id: 2 }, { id: 6 }]), null);
  assert.equal(resolveActiveOrgId('99', [{ id: 2 }, { id: 6 }]), null);
});

test('a viewer cannot manage the team; an admin and a super admin can', () => {
  assert.equal(canManageTeam('viewer', 'viewer'), false);
  assert.equal(canManageTeam('user', 'viewer'), false);
  assert.equal(canManageTeam('admin', 'viewer'), false);
  assert.equal(canManageTeam('viewer', 'admin'), true);
  assert.equal(canManageTeam('super_admin', 'viewer'), true);
});
