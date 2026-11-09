import assert from 'node:assert/strict';
import { test } from 'node:test';
import { allocationWarning, normalizeTaxId } from './documentForm.ts';

test('tax id: 9 digits, spaces and dashes stripped, leading zeros kept', () => {
  assert.deepEqual(normalizeTaxId('12-345678-2'), { value: '123456782', error: null });
  assert.deepEqual(normalizeTaxId('012345678'), { value: '012345678', error: null });
  assert.deepEqual(normalizeTaxId('  '), { value: null, error: null });
});

test('tax id: malformed values get a Hebrew error', () => {
  for (const bad of ['12345', '12345678a', '1234567890']) {
    const result = normalizeTaxId(bad);
    assert.equal(result.value, null);
    assert.match(result.error ?? '', /9 ספרות/);
  }
});

test('allocation warning only for a tax invoice over the dated threshold without tax id', () => {
  const nov = '2026-11-09';
  assert.match(allocationWarning('invoice', 60000, null, nov) ?? '', /הקצאה/);
  assert.equal(allocationWarning('invoice', 60000, '123456782', nov), null);
  assert.equal(allocationWarning('invoice', 5000, null, nov), null);
  assert.equal(allocationWarning('quote', 60000, null, nov), null);
  // 01/01/2026–31/05/2026 the threshold was ₪10,000
  assert.equal(allocationWarning('invoice', 8000, null, '2026-03-01'), null);
  assert.match(allocationWarning('invoice_receipt', 8000, null, '2026-07-01') ?? '', /5,000/);
});
