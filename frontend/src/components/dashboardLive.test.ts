import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DASHBOARD_POLL_MS, revisionToken, shouldReloadView } from './dashboardLive.ts';

test('a budget save changes the revision token and the open dashboard reloads', () => {
  const before = revisionToken({ plan_version: 'aaa', budget_updated_at: '2026-10-28T10:00:00' });
  const after = revisionToken({ plan_version: 'bbb', budget_updated_at: '2026-10-28T10:00:03' });
  let seen: string | null = null;
  let reloaded = false;
  for (const token of [before, before, after]) {
    if (shouldReloadView(seen, token)) reloaded = true;
    seen = token;
  }
  assert.equal(reloaded, true);
  assert.equal(seen, after);
  assert.ok(DASHBOARD_POLL_MS <= 5000);
});

test('the first poll does not reload, and an unchanged token does not either', () => {
  const token = revisionToken({ plan_version: 'aaa', budget_updated_at: null });
  assert.equal(shouldReloadView(null, token), false);
  assert.equal(shouldReloadView(token, token), false);
});
