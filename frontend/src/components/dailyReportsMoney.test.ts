import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  formatReportMoney,
  moneySign,
  profitBarHeightPercent,
  profitBarScale,
} from './dailyReportsMoney.ts';

test('a missing amount is חסר and is not drawn as ₪0', () => {
  assert.equal(formatReportMoney(null), 'חסר');
  assert.equal(formatReportMoney(undefined), 'חסר');
  assert.equal(formatReportMoney(Number.NaN), 'חסר');
  assert.notEqual(formatReportMoney(null), '₪0');
  assert.equal(formatReportMoney(0), '₪0');
  assert.equal(formatReportMoney(2500), '₪2,500');
});

test('null is not a profit: the >= 0 comparison would paint it green', () => {
  assert.equal(moneySign(null), 'missing');
  assert.equal(moneySign(undefined), 'missing');
  assert.notEqual(moneySign(null), 'profit');
  assert.equal(moneySign(0), 'profit');
  assert.equal(moneySign(120), 'profit');
  assert.equal(moneySign(-40), 'loss');
});

test('a chart with no measured profit has no scale and no bar height', () => {
  assert.equal(profitBarScale([]), null);
  assert.equal(profitBarScale([null, undefined]), null);
  assert.equal(profitBarHeightPercent(null, null), null);
  assert.equal(profitBarHeightPercent(null, 100), null);
  assert.notEqual(profitBarHeightPercent(null, 100), 2);
});

test('known profits set the scale and a missing day stays off the chart', () => {
  // abs(-80) = 80, abs(40) = 40 → scale 80. 40/80 = 50%.
  assert.equal(profitBarScale([null, -80, 40]), 80);
  assert.equal(profitBarHeightPercent(-80, 80), 100);
  assert.equal(profitBarHeightPercent(40, 80), 50);
  assert.equal(profitBarHeightPercent(null, 80), null);
  assert.equal(profitBarHeightPercent(0, 80), 2);
});
