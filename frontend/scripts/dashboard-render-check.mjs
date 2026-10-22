// Renders the /d/ dashboard tabs on the server with the payload shapes the API
// sends, and fails on a render error or a missing value. Run from the repo:
//   node frontend/scripts/dashboard-render-check.mjs
// tests/test_dashboard_ui_render.py runs it when frontend/node_modules exists.
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const here = dirname(fileURLToPath(import.meta.url));
const components = process.argv[2] || join(here, '..', 'src', 'components');

const entry = `
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { BudgetVsActual } from ${JSON.stringify(join(components, 'ClientDashboardPage.tsx'))};
import { LiquidityPanel, upcomingAmount } from ${JSON.stringify(join(components, 'dashboardTabs.tsx'))};
import { BudgetEditor, firstPlanMonth, lineDefaultsFromPayload, linesFromPayload } from ${JSON.stringify(join(components, 'dashboardFiling.tsx'))};
export { renderToStaticMarkup, createElement, BudgetVsActual, LiquidityPanel, upcomingAmount,
  BudgetEditor, firstPlanMonth, lineDefaultsFromPayload, linesFromPayload };
`;

const dir = mkdtempSync(join(tmpdir(), 'dashboard-render-'));
const failures = [];
function check(name, fn) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (error) {
    failures.push(name);
    console.log(`FAIL ${name}: ${error instanceof Error ? error.message : String(error)}`);
  }
}
function expect(condition, message) {
  if (!condition) throw new Error(message);
}

try {
  const entryFile = join(dir, 'entry.tsx');
  writeFileSync(entryFile, entry);
  const out = join(dir, 'bundle.cjs');
  await build({
    entryPoints: [entryFile], bundle: true, platform: 'node', format: 'cjs', outfile: out,
    jsx: 'automatic', logLevel: 'silent', nodePaths: [join(here, '..', 'node_modules')],
  });
  const ui = createRequire(import.meta.url)(out);
  const html = (component, props) => ui.renderToStaticMarkup(ui.createElement(component, props));

  check('consolidated budget vs actual without totals renders', () => {
    // The shape /view sent for the combined scope before the fix: no totals.
    const section = {
      status: 'ready', has_budget: true, message: 'סכום',
      months: [{ month: '2026-08', categories: [
        { kind: 'cost', category: 'payroll', category_he: 'שכר', budget: 49700, actual: 30000, variance: -19700, variance_pct: -39.6 },
      ] }],
    };
    const markup = html(ui.BudgetVsActual, { section });
    expect(markup.includes('שכר') && markup.includes('2026-08'), 'the payroll line is missing');
  });

  check('a month without categories renders', () => {
    const markup = html(ui.BudgetVsActual, { section: { status: 'ready', has_budget: false, months: [{ month: '2026-09' }] } });
    expect(markup.includes('לא הוזן תקציב'), 'no empty-budget message');
  });

  check('consolidated budget vs actual with totals renders the totals', () => {
    const compare = { budget: 49700, actual: 30000, variance: -19700, variance_pct: -39.6 };
    const section = {
      status: 'ready', has_budget: true,
      months: [{ month: '2026-08', source: 'cash_basis', source_label: 'בסיס מזומן', blocked: false,
        categories: [{ kind: 'cost', category: 'payroll', category_he: 'שכר', ...compare }],
        totals: { revenue: { budget: null, actual: null, variance: null, variance_pct: null }, costs: compare } }],
    };
    const markup = html(ui.BudgetVsActual, { section });
    expect(markup.includes('סה&quot;כ הוצאות') || markup.includes('סה"כ הוצאות'), 'no cost total row');
    expect(markup.includes('בסיס מזומן'), 'no source label');
  });

  check('combined liquidity shows the known part and the credit line', () => {
    const section = {
      status: 'ready', balance: null, balance_known: -100, limit: null, limit_known: 80000,
      balance_note: 'יתרת העו״ש של פוד גרופ אינה ידועה',
      entities: [
        { entity: 'השף', balance: -100, as_of: '2026-10-19', balance_source: 'accounts', limit: null, available_to_limit: null },
        { entity: 'פוד גרופ', balance: null, as_of: null, balance_source: null, limit: 80000, available_to_limit: null },
      ],
      upcoming: [{ date: '2026-12-31', label: 'מסגרת', kind: 'facility_expiry', amount: null, reference_amount: 80000, entity: 'פוד גרופ' }],
      debts: [], debt_service: [],
    };
    const markup = html(ui.LiquidityPanel, { section });
    expect(markup.includes('(חלקי)'), 'the known part is not shown');
    expect(markup.includes('פוד גרופ'), 'no per-entity row');
    expect(markup.includes('80,000'), 'the Food Group credit line is not shown');
    expect(markup.includes('יתרת העו״ש של פוד גרופ אינה ידועה'), 'no per-entity note');
  });

  check('upcoming amount: documented, facility limit, unknown', () => {
    expect(ui.upcomingAmount({ amount: -62708.33 }).includes('62,708'), 'documented amount');
    expect(ui.upcomingAmount({ amount: null, reference_amount: 80000 }).includes('80,000'), 'facility limit');
    expect(ui.upcomingAmount({ amount: null }) === 'לא ידוע', 'unknown amount');
  });

  check('budget editor shows quantity × rate of canonical lines and seed defaults', () => {
    const payload = {
      budgetLines: [
        { id: 'wage_11', label: 'עובד 11', category: 'salaries', kind: 'cost', group: 'כוח אדם',
          months: { '2026-10': { quantity: 1, rate: 30000 }, '2026-11': { quantity: 1, rate: 30000 } } },
        { id: 'wage_01', label: 'עובד 1', category: 'salaries', kind: 'cost', group: 'כוח אדם', months: {} },
      ],
      eliavImport: { lines: { wage_01: { defaults: { quantity: null, rate: 57 } } } },
    };
    const lines = ui.linesFromPayload(payload);
    const markup = html(ui.BudgetEditor, {
      canEdit: true, lines, lineDefaults: ui.lineDefaultsFromPayload(payload), month: '2026-10',
      categories: [{ key: 'salaries', label_he: 'משכורות', kind: 'cost' }],
      onMonth: () => {}, onLines: () => {}, onSave: () => {}, saving: false,
    });
    expect(markup.includes('30,000'), 'the month amount is missing');
    expect(markup.includes('60,000'), 'the year total is missing');
    expect(markup.includes('חסרה כמות'), 'a rate-only seed line is not explained');
    expect(markup.includes('placeholder="57"'), 'the seed rate is not offered');
  });

  check('editor opens on a month the plan covers', () => {
    const payload = { budgetLines: [{ id: 'a', label: 'a', category: 'salaries', months: { '2026-01': { quantity: 1, rate: 1 }, '2026-06': { quantity: 1, rate: 1 } } }] };
    expect(ui.firstPlanMonth(payload, '2026-06') === null, 'keeps a covered month');
    expect(ui.firstPlanMonth(payload, '2026-10') === '2026-06', 'nearest earlier month');
    expect(ui.firstPlanMonth(payload, '2025-10') === '2026-01', 'first month');
  });
} finally {
  rmSync(dir, { recursive: true, force: true });
}

if (failures.length > 0) {
  console.log(`${failures.length} failed`);
  process.exit(1);
}
console.log('all passed');
