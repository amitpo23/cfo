import assert from 'node:assert/strict';
import { test } from 'node:test';
import { missingFigure, periodBankTotals } from './periodBankTotals.ts';
import type { Figure, PeriodCompare } from './PeriodCompare.tsx';

const figure = (amount: number | null, as_of: string | null = null): Figure => ({
  amount,
  as_of,
  missing_label: amount == null ? 'חסר' : null,
});

function side(inflow: number | null, outflow: number | null, net: number | null) {
  return { in: figure(inflow), out: figure(outflow), net: figure(net) };
}

function report(totals: PeriodCompare['totals']): PeriodCompare {
  return { grain: 'day', start: '2026-10-29', end: '2026-10-29', periods: [], totals };
}

const empty = { revenue: figure(null), costs: figure(null), net: figure(null) };

test('KPIs are the server totals for the selected range, not a client sum', () => {
  const totals = periodBankTotals(report({
    budget: empty, books: empty,
    bank: side(100, 55.5, 44.5),
    cash: side(100, 55.5, 44.5),
  }));
  assert.equal(totals?.inflows, 100);
  assert.equal(totals?.outflows, 55.5);
  assert.equal(totals?.net, 44.5);
});

test('withheld profit does not hide the cash that moved', () => {
  const totals = periodBankTotals(report({
    budget: empty, books: empty,
    bank: side(500, 200, null),
    cash: side(500, 200, 300),
  }));
  assert.equal(totals?.net, 300);
});

test('a real zero stays zero', () => {
  const totals = periodBankTotals(report({ budget: empty, books: empty, bank: side(0, 0, 0), cash: side(0, 0, 0) }));
  assert.equal(totals?.inflows, 0);
  assert.equal(totals?.net, 0);
  assert.equal(missingFigure(0, '2026-10-29'), null);
});

test('loading or a payload without totals is not a total', () => {
  assert.equal(periodBankTotals(null), null);
  assert.equal(periodBankTotals(undefined), null);
  assert.equal(periodBankTotals(report(undefined)), null);
});

test('a missing amount stays חסר and keeps its as-of', () => {
  assert.equal(missingFigure(null, null), 'חסר');
  assert.equal(missingFigure(undefined, '2026-10-26'), 'חסר · נכון ל-2026-10-26');
  const cash = { in: figure(null, '2026-10-26'), out: figure(0, '2026-10-26'), net: figure(null, '2026-10-26') };
  const totals = periodBankTotals(report({ budget: empty, books: empty, bank: cash, cash }));
  assert.equal(totals?.inflows, null);
  assert.equal(totals?.inflowsAsOf, '2026-10-26');
  assert.equal(totals?.outflows, 0);
});
