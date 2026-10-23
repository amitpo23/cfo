// Renders the /d/ dashboard tabs on the server with the payload shapes the API
// sends, and fails on a render error or a missing value. Run from the repo:
//   node frontend/scripts/dashboard-render-check.mjs
// tests/test_dashboard_ui_render.py runs it when frontend/node_modules exists.
// With REZEF_IMPORTED_PLAN=<plan.json> (the payload the Eliav import writes,
// tests/fixtures/eliav_imported_plan.json) it also checks the budget editor on it.
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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
import { BudgetVsActual, CashStatementCard, IntercompanyCard, JournalCard, SourcesCard } from ${JSON.stringify(join(components, 'ClientDashboardPage.tsx'))};
import { LiquidityEvidenceCard, LiquidityPanel, OpeningBalanceCard, draftFromItem, evidenceItems, itemFromDraft, upcomingAmount, withEvidenceItem, withOpeningBalance, ZReportsCard, withZReport, zReportsFromPayload } from ${JSON.stringify(join(components, 'dashboardTabs.tsx'))};
import { BudgetEditor, budgetLinesPayload, firstPlanMonth, lineDefaultsFromPayload, linesFromPayload, monthTotal } from ${JSON.stringify(join(components, 'dashboardFiling.tsx'))};
import { DashboardFrame, DashboardSkeleton, EmptyState, KpiCards, StatusTabs } from ${JSON.stringify(join(components, 'dashboardUi.tsx'))};
import { categoryLabel } from ${JSON.stringify(join(components, '..', 'services', 'categoryLabels.ts'))};
import { pieSlices } from ${JSON.stringify(join(components, 'budgetChart.ts'))};
export { renderToStaticMarkup, createElement, BudgetVsActual, CashStatementCard, IntercompanyCard, JournalCard, SourcesCard, LiquidityPanel, upcomingAmount, OpeningBalanceCard, withOpeningBalance,
  LiquidityEvidenceCard, draftFromItem, evidenceItems, itemFromDraft, withEvidenceItem, ZReportsCard, withZReport, zReportsFromPayload,
  BudgetEditor, budgetLinesPayload, firstPlanMonth, lineDefaultsFromPayload, linesFromPayload, monthTotal,
  categoryLabel, pieSlices, DashboardFrame, DashboardSkeleton, EmptyState, KpiCards, StatusTabs };
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
  check('category keys have Hebrew labels', () => {
    expect(ui.categoryLabel('salaries') === 'משכורות', 'salaries');
    expect(ui.categoryLabel('payroll') === 'כוח אדם', 'payroll');
    expect(ui.categoryLabel('salaries', 'שכר') === 'שכר', 'the server label wins');
    expect(ui.categoryLabel('salaries', 'salaries') === 'משכורות', 'a raw key from the server is not a label');
    expect(ui.categoryLabel('no_such_key') === 'no_such_key', 'unknown keys stay as sent');
  });

  check('pie: positive slices, small ones folded, labels only on large slices', () => {
    const rows = [
      { category: 'משכורות', planned: 49700 }, { category: 'שכירות', planned: 12000 },
      { category: 'a', planned: 500 }, { category: 'b', planned: 400 }, { category: 'c', planned: 0 },
      { category: 'd', planned: -10 }, { category: 'e', planned: 300 }, { category: 'f', planned: 200 },
      { category: 'g', planned: 100 }, { category: 'h', planned: 50 },
    ];
    const slices = ui.pieSlices(rows);
    expect(slices.length <= 6, `too many slices: ${slices.length}`);
    expect(slices[0].name === 'משכורות', 'largest first');
    expect(slices.every((slice) => slice.value > 0), 'no zero or negative slice');
    const other = slices.find((slice) => slice.name === 'אחר');
    expect(other && Math.abs(other.value - 350) < 0.01, 'the small slices fold into אחר');
    expect(Math.abs(slices.reduce((sum, slice) => sum + slice.value, 0) - 63250) < 0.01, 'the total is kept');
  });

  check('opening balance: one per entity, the rest of the evidence kept, card renders', () => {
    const payload = { budgetLines: [], liquidityEvidence: { facilities: [{ label: 'מסגרת', limit: 80000 }],
      openingBalances: [{ organizationId: 6, date: '2026-07-01', amount: 1, source: 'ישן' },
        { organizationId: 2, date: '2026-07-01', amount: 5, source: 'שף' }] } };
    const item = { organizationId: 6, date: '2026-07-31', amount: -30000, source: 'דף בנק' };
    const next = ui.withOpeningBalance(payload, 6, item);
    const items = next.liquidityEvidence.openingBalances;
    expect(items.length === 2 && items.some((row) => row.source === 'שף') && items.some((row) => row.amount === -30000), 'replace one entity');
    expect(next.liquidityEvidence.facilities.length === 1 && next.budgetLines, 'the rest of the plan is kept');
    expect(ui.withOpeningBalance(next, 6, null).liquidityEvidence.openingBalances.length === 1, 'remove');
    const markup = html(ui.OpeningBalanceCard, {
      entities: [{ organization_id: 2, label: 'השף' }, { organization_id: 6, label: 'פוד גרופ' }],
      items, saving: false, onSave: () => {},
    });
    expect(markup.includes('יתרת פתיחה ידנית') && markup.includes('value="-30000"'), 'the card does not show the saved balance');
    const panel = html(ui.LiquidityPanel, { section: { status: 'ready', position: { balance: -32099.5, as_of: '2026-10-13',
      balance_source: 'opening_balance', limit: 80000, limit_source: 'plan.liquidityEvidence', available_to_limit: 47900.5 } } });
    expect(panel.includes('יתרת פתיחה ידנית'), 'the balance source is not named');
  });

  check('journal card: source accounts by month and the bank amount not counted', () => {
    const months = [
      { month: '2026-07', source: null, revenue: null, costs: null, net: null,
        journal: { source_label: 'יומן', lines: [{ code: '99002', label: 'ריבית', row: 'interest', amount: 300 }], entries: 1, unbalanced: 1, balance_only: 0 } },
      { month: '2026-08', source: 'cash_basis', revenue: 10000, costs: 4872.46, net: 5127.54,
        journal: { source_label: 'יומן', lines: [{ code: '90003', label: 'מזון וחומרי גלם', row: 'suppliers', amount: 3000 }], entries: 2, unbalanced: 0, balance_only: 1 },
        journal_dedupe: { rows_replaced: [{ id: 'suppliers', label: 'ספקים', bank_amount: 5000, journal_amount: 3000 }], bank_dropped: 5000, journal_used: 3000 } },
      { month: '2026-09', source: 'cash_basis', revenue: 1, costs: 1, net: 0 },
    ];
    const markup = html(ui.JournalCard, { months });
    expect(markup.includes('מזון וחומרי גלם') && markup.includes('(90003)'), 'no source account row');
    expect(markup.includes('5,000') && markup.includes('לא נכלל'), 'no dropped bank amount / excluded month');
    expect(!markup.includes('2026-09'), 'a month without journal is shown');
    expect(html(ui.JournalCard, { months: [months[2]] }) === '', 'card rendered without a journal');
  });

  check('intercompany card: netted amount, rule and pairs', () => {
    const removed = { pairs: 1, inflows: 5000, outflows: 5000, amount: 5000, window_days: 4, rule: 'קיזוז בין-חברתי: עד 4 ימים',
      items: [{ from: 'פוד גרופ', to: 'השף', out_date: '2026-08-30', in_date: '2026-09-02', amount: 5000, days_apart: 3 }] };
    const markup = html(ui.IntercompanyCard, { removed });
    expect(markup.includes('5,000') && markup.includes('עד 4 ימים') && markup.includes('2026-09-02 (3 ימים)'), 'pairs or rule missing');
    const old = html(ui.IntercompanyCard, { removed: { pairs: 0, inflows: 0, outflows: 0 } });
    expect(old.includes('קוזזו 0'), 'the older shape does not render');
  });

  check('intercompany: netted amounts per month on both sides, never a bare 0 line', () => {
    const removed = { pairs: 2, inflows: 35000, outflows: 35000, amount: 35000,
      by_month: { '2026-09': { inflows: 30000, outflows: 30000 }, '2026-08': { inflows: 5000, outflows: 5000 } } };
    const card = html(ui.IntercompanyCard, { removed });
    expect(card.includes('כניסות שקוזזו') && card.includes('30,000') && card.indexOf('2026-08') < card.indexOf('2026-09'), 'per month table');
    const statement = {
      status: 'ready', months: ['2026-09'], groups: [{ id: 'internal', label: 'פנימי ומסים' }],
      lines: [
        { id: 'intercompany_netting_in', label: 'קיזוז בין-חברתי — כניסות שקוזזו (מאוחד)', group: 'internal', values: { '2026-09': -30000 }, total: -30000 },
        { id: 'intercompany_netting_out', label: 'קיזוז בין-חברתי — יציאות שקוזזו (מאוחד)', group: 'internal', values: { '2026-09': 30000 }, total: 30000 },
      ],
      totals: { internal: { '2026-09': 0 }, net: { '2026-09': 0 } }, netting_note: 'כבר הוסרו מהכניסות',
    };
    const markup = html(ui.CashStatementCard, { statement });
    expect(markup.includes('-30,000') || markup.includes('‎-30,000') || markup.includes('−30,000'), 'netted inflows line');
    expect(markup.includes('כבר הוסרו מהכניסות'), 'netting note');
  });

  check('sources card: per account, stale flag, entity column in the combined view', () => {
    const sources = { stale_count: 1, rule: 'כלל רעננות', items: [
      { kind: 'bank', kind_label: 'תנועות בנק', label: 'עו״ש 8954', source: 'open_finance', source_label: 'Open Finance', last_date: '2026-10-20',
        last_sync: '2026-10-21T02:00:35', rows: 1234, age_days: 1, status: 'fresh', status_label: 'עדכני', entity: 'השף' },
      { kind: 'journal', kind_label: 'יומן', label: 'יומן', source: 'reviewed_local_import', source_label: 'יבוא מקומי שנבדק', last_date: null,
        last_sync: null, rows: 0, age_days: null, status: 'unknown', status_label: 'לא ידוע', entity: 'פוד גרופ' },
    ] };
    const markup = html(ui.SourcesCard, { sources });
    expect(markup.includes('עו״ש 8954') && markup.includes('2026-10-21 02:00') && markup.includes('עדכני (1 ימים)'), 'bank row');
    expect(markup.includes('פוד גרופ') && markup.includes('לא ידוע') && markup.includes('1 מקורות לא עדכניים'), 'entity / unknown / stale count');
    expect(html(ui.SourcesCard, { sources: { items: [] } }) === '', 'empty card rendered');
  });

  check('cash statement: lines by month, group totals, unknown month, forecast columns', () => {
    const statement = {
      status: 'ready', months: ['2026-07', '2026-08'],
      groups: [{ id: 'operating_in', label: 'תפעולי — כניסות' }, { id: 'financing', label: 'מימון' }],
      lines: [
        { id: 'sales_cash', label: 'הפקדות מזומן (מכירות)', group: 'operating_in', values: { '2026-07': null, '2026-08': 11800 }, total: 11800 },
        { id: 'loans_out', label: 'החזרי הלוואות ומימון', group: 'financing', values: { '2026-07': null, '2026-08': -2000 }, total: -2000 },
      ],
      totals: { operating_in: { '2026-07': null, '2026-08': 11800 }, financing: { '2026-07': null, '2026-08': -2000 }, net: { '2026-07': null, '2026-08': 9800 } },
      forecast: { months: ['2026-11'], rows: { operating_in: { '2026-11': 10000 }, operating_out: { '2026-11': -8000 }, financing: { '2026-11': -1000 }, net: { '2026-11': 1000 } }, note: 'ללא מע״מ' },
    };
    const markup = html(ui.CashStatementCard, { statement });
    expect(markup.includes('11,800') && markup.includes('9,800') && markup.includes('לא ידוע'), 'actual cells');
    expect(markup.includes('2026-11 (תחזית)') && markup.includes('10,000') && markup.includes('ללא מע״מ'), 'forecast columns');
    // Line cells under the forecast are marked, not blank, and the note says why.
    expect(markup.includes('title="תחזית לפי קבוצה בלבד">—</td>') && markup.includes('לפי קבוצה בלבד'), 'forecast line cells unlabelled');
    expect(html(ui.CashStatementCard, { statement: { status: 'unknown', months: [] } }) === '', 'unknown statement rendered');
  });

  check('cash statement: a month one entity knows is labelled, a month none knows stays unknown', () => {
    const statement = {
      status: 'ready', months: ['2026-05', '2026-06'], groups: [{ id: 'operating_in', label: 'תפעולי — כניסות' }],
      lines: [{ id: 'sales_cash', label: 'הפקדות מזומן', group: 'operating_in', values: { '2026-05': null, '2026-06': 11800 }, total: 11800 }],
      totals: { operating_in: { '2026-05': null, '2026-06': 11800 }, net: { '2026-05': null, '2026-06': 11800 } },
      scope: { '2026-06': { label: 'שף בלבד', entities: ['שף'], missing: ['פוד גרופ'] } },
      scope_note: 'חודש שמסומן "בלבד"; 2026-06: שף בלבד (פוד גרופ — אין תנועות בנק).',
    };
    const markup = html(ui.CashStatementCard, { statement });
    expect(markup.includes('שף בלבד') && markup.includes('11,800') && markup.includes('לא ידוע'), 'partial month label or unknown month');
    expect(markup.includes('פוד גרופ — אין תנועות בנק'), 'scope note');
  });

  check('frame, status tabs, KPI cards, skeleton and empty state', () => {
    const frame = html(ui.DashboardFrame, { title: 'שף אליהב', subtitle: 'בעלים', children: 'x' });
    expect(frame.includes('dir="rtl"') && frame.includes('bg-navy-900') && frame.includes('שף אליהב'), 'navy frame');
    const tabs = html(ui.StatusTabs, { tabs: [{ id: 'status', label: 'תמונת מצב' }, { id: 'bva', label: 'תקציב' }], active: 'bva', onSelect: () => {} });
    expect(tabs.includes('role="tablist"') && tabs.includes('aria-selected="true"') && tabs.includes('aria-controls="dashboard-panel"'), 'tabs aria');
    const kpis = html(ui.KpiCards, { items: [{ label: 'הכנסות', value: 'לא ידוע' }, { label: 'לבירור', value: '12', tone: 'warn', note: 'דורש החלטה' }] });
    expect(kpis.includes('text-stone-400') && kpis.includes('text-amber-700'), 'unknown KPI muted, warn note');
    const skeleton = html(ui.DashboardSkeleton, {});
    expect(skeleton.includes('role="status"') && skeleton.includes('טוען') && skeleton.includes('motion-reduce:animate-none'), 'skeleton');
    expect(html(ui.EmptyState, { title: 'אין נתונים', children: 'הסבר' }).includes('הסבר'), 'empty state');
  });

  check('liquidity evidence form: add, edit, delete keep openingBalances and unknown keys', () => {
    const opening = [{ organizationId: 6, date: '2026-07-31', amount: -30000, source: 'דף בנק' }];
    const payload = { budgetLines: [{ id: 'x' }], somethingNew: { a: 1 },
      liquidityEvidence: { observedAt: '2026-10-15', openingBalances: opening,
        loans: [{ organizationId: 6, label: 'הלוואה 1', balance: 100000, account: '1662', product: '7', referenceBalance: 99000 }] } };
    const draft = { ...ui.draftFromItem('checks', null), organizationId: '6', check: '10005', date: '2026-11-05', amount: '2,500' };
    const built = ui.itemFromDraft('checks', draft, null);
    expect('item' in built && built.item.amount === 2500 && built.item.payee === null, 'check not built');
    const added = ui.withEvidenceItem(payload, 'checks', null, built.item);
    expect(added.liquidityEvidence.openingBalances === opening && added.somethingNew.a === 1 && added.budgetLines.length === 1, 'keys lost on add');
    expect(added.liquidityEvidence.observedAt === '2026-10-15' && ui.evidenceItems(added, 'checks').length === 1, 'check not added');
    const loan = ui.evidenceItems(added, 'loans')[0];
    const edited = ui.itemFromDraft('loans', { ...ui.draftFromItem('loans', loan), balance: '' }, loan);
    expect('item' in edited && edited.item.balance === null && edited.item.referenceBalance === 99000 && edited.item.product === '7', 'edit lost a field or made 0');
    const replaced = ui.withEvidenceItem(added, 'loans', 0, edited.item);
    expect(ui.evidenceItems(replaced, 'loans')[0].balance === null && replaced.liquidityEvidence.openingBalances === opening, 'edit');
    const removed = ui.withEvidenceItem(replaced, 'checks', 0, null);
    expect(ui.evidenceItems(removed, 'checks').length === 0 && removed.liquidityEvidence.openingBalances === opening, 'delete');
    expect('error' in ui.itemFromDraft('checks', { ...draft, amount: '0' }, null), 'a zero check is accepted');
    expect('error' in ui.itemFromDraft('events', { ...ui.draftFromItem('events', null), label: 'x', date: '31/10/2026' }, null), 'a bad date is accepted');
    const markup = html(ui.LiquidityEvidenceCard, { entities: [{ organization_id: 6, label: 'פוד גרופ' }], payload: added, saving: false, onSave: () => {} });
    expect(markup.includes('ראיות נזילות') && markup.includes('מסגרות (0)') && markup.includes('צ׳קים דחויים (1)'), 'card');
  });

  check('Z reports: one per entity and month, other keys kept, card renders', () => {
    const payload = { liquidityEvidence: { openingBalances: [{ organizationId: 6 }] },
      zReports: [{ organizationId: 6, month: '2026-08', revenueExVat: 52126.2, source: 'Z' }] };
    const next = ui.withZReport(payload, 6, '2026-07', { organizationId: 6, month: '2026-07', revenueExVat: 76510.82, source: 'Z' });
    expect(ui.zReportsFromPayload(next).map((item) => item.month).join() === '2026-07,2026-08', 'not added in order');
    expect(next.liquidityEvidence === payload.liquidityEvidence, 'evidence lost');
    const replaced = ui.withZReport(next, 6, '2026-08', { organizationId: 6, month: '2026-08', revenueExVat: 1, source: 'Z2' });
    expect(ui.zReportsFromPayload(replaced).length === 2 && ui.zReportsFromPayload(replaced)[1].revenueExVat === 1, 'not replaced');
    expect(ui.zReportsFromPayload(ui.withZReport(replaced, 6, '2026-07', null)).length === 1, 'not removed');
    const markup = html(ui.ZReportsCard, { entities: [{ organization_id: 6, label: 'פוד גרופ' }], items: ui.zReportsFromPayload(next), saving: false, onSave: () => {} });
    expect(markup.includes('הכנסות פיצה מדוחות Z') && markup.includes('76,511') && markup.includes('פוד גרופ'), 'card');
  });

  const importedPlan = process.env.REZEF_IMPORTED_PLAN;
  if (importedPlan) {
    check('imported plan: payroll 49,700 a month, defaults shown, save without loss', () => {
      const payload = JSON.parse(readFileSync(importedPlan, 'utf8'));
      const stored = payload.budgetLines;
      const kinds = new Map(stored.map((line) => [line.category, line.kind]));
      const categories = [...kinds].map(([key, kind]) => ({ key, label_he: key, kind }));
      const lines = ui.linesFromPayload(payload);
      expect(lines.length === stored.length, `${lines.length} of ${stored.length} lines read`);
      for (let index = 0; index < 18; index += 1) {
        const month = `${2026 + Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`;
        const cost = ui.monthTotal(lines, month, categories, 'cost');
        expect(Math.abs(cost - 49700) < 0.005, `${month}: cost ${cost}, not 49,700`);
      }
      const markup = html(ui.BudgetEditor, {
        canEdit: true, lines, lineDefaults: ui.lineDefaultsFromPayload(payload), month: '2026-10', categories,
        onMonth: () => {}, onLines: () => {}, onSave: () => {}, saving: false,
      });
      expect(markup.includes('49,700'), 'no 49,700 total');
      expect(markup.includes('30,000') && markup.includes('9,000'), 'a payroll line amount is missing');
      expect(markup.includes('value="30000"') && markup.includes('value="1"'), 'quantity/rate inputs are empty');
      expect(/יש סכום ל-4 מתוך 127/.test(markup), 'the budgeted-lines count is missing');
      expect(markup.includes('חסר תעריף · כמות 1 מהכלי'), 'a quantity-only seed line reads as empty');
      expect(markup.includes('חסרה כמות · תעריף'), 'a rate-only seed line reads as empty');
      const built = ui.budgetLinesPayload(lines, categories);
      expect(!built.error, built.error);
      const canonical = (rows) => JSON.stringify([...rows].sort((a, b) => (a.id < b.id ? -1 : 1)),
        (_key, value) => (value && typeof value === 'object' && !Array.isArray(value)
          ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => (a < b ? -1 : 1))) : value));
      expect(canonical(built.lines) === canonical(stored), 'the save payload differs from the stored lines');
      // A field the editor does not know survives the save.
      const extended = ui.linesFromPayload({ budgetLines: [{ ...stored[0], note: 'נשמר' }] });
      expect(ui.budgetLinesPayload(extended, categories).lines[0].note === 'נשמר', 'an unknown line field was dropped');
    });
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

if (failures.length > 0) {
  console.log(`${failures.length} failed`);
  process.exit(1);
}
console.log('all passed');
