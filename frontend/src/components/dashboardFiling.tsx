import { Fragment, useEffect, useState, type ReactNode } from 'react';
import { missingAsOf } from './dashboardUi';

export type FilingRule = {
  id: string;
  source: 'builtin' | 'custom';
  contains: string;
  field: 'description' | 'counterparty' | 'any';
  direction: 'in' | 'out' | 'both';
  category: string;
  category_he: string;
  organization_id?: number | null;
  match_count: number;
  overridden: number;
  total: number;
  fallback?: boolean;
};

export type ReviewItem = {
  id: string;
  organization_id: number;
  date: string;
  description: string;
  counterparty: string;
  amount: number;
  entity?: string | null;
  filed_by: { reason_he: string; note?: string | null };
};

export type FilingCategory = { key: string; label_he: string };
export type BudgetCategory = { key: string; label_he: string; kind: 'revenue' | 'cost' | 'financing' };

export type FilingReport = {
  rules: FilingRule[];
  review: { total: number; page: number; page_size: number; items: ReviewItem[] };
  categories: FilingCategory[];
  budget_categories: BudgetCategory[];
  unmatched_decisions?: { transaction_id: string; reason: string }[];
  builtin_manifest?: { count: number; sha256: string; pinned_sha256: string | null; in_sync: boolean | null };
  entities?: { organization_id: number; label: string | null }[];
  can_edit: boolean;
};

export type LineDraft = {
  id: string;
  label: string;
  category: string;
  group?: string;
  unit?: string;
  months: Record<string, { quantity: string; rate: string }>;
  // Fields of the stored line the editor does not edit; saved back as they were.
  extra?: Record<string, unknown>;
};

const EDITED_LINE_KEYS = new Set(['id', 'label', 'category', 'kind', 'group', 'unit', 'months']);

export type PlanPayload = Record<string, unknown>;

const PAGE_SIZE = 50;

function money(value: number): string {
  return new Intl.NumberFormat('he-IL', {
    style: 'currency', currency: 'ILS', maximumFractionDigits: 0,
  }).format(value);
}

function fieldLabel(field: FilingRule['field']): string {
  if (field === 'counterparty') return 'מוטב';
  if (field === 'any') return 'תיאור או מוטב';
  return 'תיאור';
}

function directionLabel(direction: FilingRule['direction']): string {
  if (direction === 'in') return 'נכנס';
  if (direction === 'out') return 'יוצא';
  return 'כל כיוון';
}

export function linesFromPayload(payload: PlanPayload): LineDraft[] {
  const raw = payload.budgetLines;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const row = item as Record<string, unknown>;
    if (typeof row.id !== 'string' || typeof row.label !== 'string' || typeof row.category !== 'string') {
      return [];
    }
    const months: LineDraft['months'] = {};
    if (row.months && typeof row.months === 'object') {
      for (const [key, cell] of Object.entries(row.months as Record<string, unknown>)) {
        if (!cell || typeof cell !== 'object') continue;
        const typed = cell as Record<string, unknown>;
        months[key] = {
          quantity: typed.quantity === undefined || typed.quantity === null ? '' : String(typed.quantity),
          rate: typed.rate === undefined || typed.rate === null ? '' : String(typed.rate),
        };
      }
    }
    const extra = Object.fromEntries(Object.entries(row).filter(([key]) => !EDITED_LINE_KEYS.has(key)));
    return [{
      id: row.id,
      label: row.label,
      category: row.category,
      ...(typeof row.group === 'string' ? { group: row.group } : {}),
      ...(typeof row.unit === 'string' ? { unit: row.unit } : {}),
      months,
      ...(Object.keys(extra).length > 0 ? { extra } : {}),
    }];
  });
}

export type CellDraft = { quantity: string; rate: string };

// The months a plan's lines have cells for. The editor opens on the current
// month when the plan covers it, otherwise on the plan's nearest month.
export function firstPlanMonth(payload: PlanPayload, current: string): string | null {
  const months = new Set<string>();
  for (const line of linesFromPayload(payload)) {
    for (const key of Object.keys(line.months)) months.add(key);
  }
  if (months.size === 0 || months.has(current)) return null;
  const sorted = [...months].sort();
  const before = sorted.filter((key) => key <= current);
  return before.length > 0 ? before[before.length - 1] : sorted[0];
}

// The tool's per-line defaults (eliavImport.lines[id].defaults): a rate or a
// quantity without the other. They prefill a month the line has no cell for.
export function lineDefaultsFromPayload(payload: PlanPayload | null | undefined): Record<string, CellDraft> {
  const imported = payload?.eliavImport;
  const lines = imported && typeof imported === 'object' ? (imported as Record<string, unknown>).lines : null;
  if (!lines || typeof lines !== 'object') return {};
  const out: Record<string, CellDraft> = {};
  for (const [id, detail] of Object.entries(lines as Record<string, unknown>)) {
    const defaults = detail && typeof detail === 'object' ? (detail as Record<string, unknown>).defaults : null;
    if (!defaults || typeof defaults !== 'object') continue;
    const typed = defaults as Record<string, unknown>;
    const text = (value: unknown) => (typeof value === 'number' || typeof value === 'string' ? String(value) : '');
    out[id] = { quantity: text(typed.quantity), rate: text(typed.rate) };
  }
  return out;
}

export function cellValue(cell: CellDraft | undefined): number | null {
  if (!cell) return null;
  const quantity = parseAmount(cell.quantity);
  const rate = parseAmount(cell.rate);
  if (quantity === null || rate === null) return null;
  return quantity * rate;
}

export function yearMonths(month: string): string[] {
  const year = month.slice(0, 4);
  return Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, '0')}`);
}

export function lineYearTotal(line: LineDraft, month: string): number | null {
  const values = yearMonths(month).map((key) => cellValue(line.months[key])).filter((value): value is number => value !== null);
  return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) : null;
}

export function customRulesPayload(rules: FilingRule[]): Record<string, unknown>[] {
  return rules.filter((rule) => rule.source === 'custom').map((rule) => ({
    id: rule.id,
    contains: rule.contains,
    field: rule.field,
    direction: rule.direction,
    category: rule.category,
    ...(rule.organization_id ? { organizationId: rule.organization_id } : {}),
  }));
}

function parseAmount(value: string): number | null {
  const text = value.trim();
  if (!text) return null;
  const parsed = Number(text);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return parsed;
}

// The amount column. A line the tool seeded with only a quantity or only a
// rate says which half is missing and shows the half it has, so the row does
// not read as empty.
export function cellAmount(cell: CellDraft | undefined, defaults: CellDraft | undefined): string {
  const value = cellValue(cell);
  if (value !== null) return money(value);
  const quantity = cell?.quantity.trim() || defaults?.quantity || '';
  const rate = cell?.rate.trim() || defaults?.rate || '';
  const fromSeed = !cell?.quantity.trim() && !cell?.rate.trim();
  if (!quantity && rate) return fromSeed ? `חסרה כמות · תעריף ${rate} מהכלי` : 'חסרה כמות';
  if (quantity && !rate) return fromSeed ? `חסר תעריף · כמות ${quantity} מהכלי` : 'חסר תעריף';
  return missingAsOf();
}

// How many lines have an amount in the month: the editor says it above the table.
export function budgetedCount(lines: LineDraft[], month: string): number {
  return lines.filter((line) => cellValue(line.months[month]) !== null).length;
}

export function budgetLinesPayload(lines: LineDraft[], categories: BudgetCategory[]): { lines: Record<string, unknown>[] } | { error: string } {
  const kindByKey = new Map(categories.map((category) => [category.key, category.kind]));
  const payload: Record<string, unknown>[] = [];
  for (const line of lines) {
    const label = line.label.trim();
    if (!label) return { error: 'לכל שורת תקציב צריכה להיות כותרת' };
    if (!line.category) return { error: 'לכל שורת תקציב צריכה להיות קטגוריה' };
    const months: Record<string, { quantity: number; rate: number }> = {};
    for (const [month, cell] of Object.entries(line.months)) {
      const quantityText = cell.quantity.trim();
      const rateText = cell.rate.trim();
      if (!quantityText && !rateText) continue;
      const quantity = parseAmount(quantityText);
      const rate = parseAmount(rateText);
      if (quantity === null || rate === null) {
        return { error: `בשורה "${label}" בחודש ${month} חסרים כמות או תעריף (או שאינם מספר). מלאו את שניהם או מחקו את שניהם.` };
      }
      months[month] = { quantity, rate };
    }
    payload.push({
      ...(line.extra ?? {}),
      id: line.id,
      label,
      category: line.category,
      kind: kindByKey.get(line.category),
      months,
      ...(line.group ? { group: line.group } : {}),
      ...(line.unit ? { unit: line.unit } : {}),
    });
  }
  return { lines: payload };
}

const NO_GROUP = 'שורות נוספות';

// Lines of one group together, in the order each group first appears.
export function groupedLines(lines: LineDraft[]): { line: LineDraft; header: string | null }[] {
  const order: string[] = [];
  const byGroup = new Map<string, LineDraft[]>();
  for (const line of lines) {
    const group = line.group || NO_GROUP;
    if (!byGroup.has(group)) {
      byGroup.set(group, []);
      order.push(group);
    }
    byGroup.get(group)?.push(line);
  }
  const showHeaders = order.length > 1 || order[0] !== NO_GROUP;
  return order.flatMap((group) => (byGroup.get(group) ?? []).map((line, index) => ({
    line,
    header: showHeaders && index === 0 ? group : null,
  })));
}

function groupTotal(lines: LineDraft[], group: string, month: string): number | null {
  const values = lines
    .filter((line) => (line.group || NO_GROUP) === group)
    .map((line) => cellValue(line.months[month]))
    .filter((value): value is number => value !== null);
  return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) : null;
}

export function monthTotal(lines: LineDraft[], month: string, categories: BudgetCategory[], kind: BudgetCategory['kind']): number | null {
  const kindByKey = new Map(categories.map((category) => [category.key, category.kind]));
  let total = 0;
  let saw = false;
  for (const line of lines) {
    if (kindByKey.get(line.category) !== kind) continue;
    const value = cellValue(line.months[month]);
    if (value == null) continue;
    total += value;
    saw = true;
  }
  return saw ? total : null;
}

function showTotal(value: number | null, asOf: string): string {
  return value == null ? missingAsOf(asOf) : money(value);
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="d-card">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function BudgetEditor({
  canEdit,
  categories,
  lines,
  lineDefaults = {},
  month,
  onMonth,
  onLines,
  onSave,
  saving,
}: {
  canEdit: boolean;
  categories: BudgetCategory[];
  lines: LineDraft[];
  lineDefaults?: Record<string, CellDraft>;
  month: string;
  onMonth: (month: string) => void;
  onLines: (lines: LineDraft[]) => void;
  onSave: () => void;
  saving: boolean;
}) {
  const [onlyBudgeted, setOnlyBudgeted] = useState(false);
  const budgeted = budgetedCount(lines, month);
  const shown = onlyBudgeted ? lines.filter((line) => cellValue(line.months[month]) !== null) : lines;

  function update(id: string, patch: Partial<LineDraft>) {
    onLines(lines.map((line) => (line.id === id ? { ...line, ...patch } : line)));
  }

  function updateCell(id: string, field: 'quantity' | 'rate', value: string) {
    onLines(lines.map((line) => {
      if (line.id !== id) return line;
      // A month without a cell starts from the line's defaults (the tool's seed).
      const current = line.months[month] ?? {
        quantity: lineDefaults[line.id]?.quantity ?? '',
        rate: lineDefaults[line.id]?.rate ?? '',
      };
      return { ...line, months: { ...line.months, [month]: { ...current, [field]: value } } };
    }));
  }

  function addLine() {
    const category = categories[0]?.key ?? '';
    onLines([...lines, {
      id: `line-${crypto.randomUUID()}`,
      label: '',
      category,
      months: { [month]: { quantity: '1', rate: '' } },
    }]);
  }

  return (
    <Card title="הזנת תקציב">
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <label className="text-stone-600">
          חודש
          <input
            type="month"
            dir="ltr"
            className="mr-2 rounded border border-stone-300 px-2 py-1"
            value={month}
            onChange={(event) => onMonth(event.target.value)}
          />
        </label>
        {canEdit ? (
          <button type="button" className="rounded border border-stone-300 px-3 py-1" onClick={addLine}>
            הוסף שורה
          </button>
        ) : (
          <span className="text-stone-500">צפייה בלבד</span>
        )}
        {lines.length > 0 ? (
          <label className="text-stone-600">
            <input
              type="checkbox"
              className="ml-1"
              checked={onlyBudgeted}
              onChange={(event) => setOnlyBudgeted(event.target.checked)}
            />
            רק שורות עם תקציב
          </label>
        ) : null}
      </div>
      {lines.length > 0 ? (
        <p className="mt-2 text-sm text-stone-600" data-budgeted={budgeted}>
          בחודש {month} יש סכום ל-{budgeted} מתוך {lines.length} שורות.
          {budgeted < lines.length
            ? ' בשאר השורות אין עדיין כמות × תעריף. בשורות מהכלי שיש להן רק חצי, החצי הקיים מוצג בעמודת הסכום. מלאו את החסר כדי לתקצב.'
            : null}
        </p>
      ) : null}
      {lines.length === 0 ? <p className="mt-3 text-stone-600">אין שורות תקציב.</p> : (
        <table className="mt-4 d-table">
          <thead>
            <tr>
              <th>שורה</th>
              <th>קטגוריה</th>
              <th>כמות</th>
              <th>תעריף</th>
              <th>סכום</th>
              <th>סה״כ {month.slice(0, 4)}</th>
              {canEdit ? <th> </th> : null}
            </tr>
          </thead>
          <tbody>
            {groupedLines(shown).map(({ line, header }) => {
              const stored = line.months[month];
              const cell = stored ?? { quantity: '', rate: '' };
              const defaults = lineDefaults[line.id];
              const yearTotal = lineYearTotal(line, month);
              return (
                <Fragment key={line.id}>
                {header ? (
                  <tr className="border-b bg-stone-50">
                    <td className="py-2 font-medium" colSpan={4}>{header}</td>
                    <td className="py-2 font-medium" colSpan={canEdit ? 3 : 2}>
                      {(() => {
                        const total = groupTotal(lines, header, month);
                        return total === null ? missingAsOf(month) : money(total);
                      })()}
                    </td>
                  </tr>
                ) : null}
                <tr>
                  <td>
                    <input
                      className="w-full rounded border border-stone-200 px-2 py-1"
                      value={line.label}
                      readOnly={!canEdit}
                      aria-label="כותרת שורה"
                      onChange={(event) => update(line.id, { label: event.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      className="w-full rounded border border-stone-200 px-2 py-1"
                      value={line.category}
                      disabled={!canEdit}
                      aria-label="קטגוריה"
                      onChange={(event) => update(line.id, { category: event.target.value })}
                    >
                      {categories.some((category) => category.key === line.category) ? null : (
                        <option value={line.category}>{line.category}</option>
                      )}
                      {categories.map((category) => (
                        <option key={category.key} value={category.key}>{category.label_he}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      dir="ltr"
                      inputMode="decimal"
                      className="w-24 rounded border border-stone-200 px-2 py-1 text-left"
                      value={cell.quantity}
                      placeholder={stored ? undefined : defaults?.quantity || undefined}
                      readOnly={!canEdit}
                      aria-label="כמות"
                      onChange={(event) => updateCell(line.id, 'quantity', event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      dir="ltr"
                      inputMode="decimal"
                      className="w-28 rounded border border-stone-200 px-2 py-1 text-left"
                      value={cell.rate}
                      placeholder={stored ? undefined : defaults?.rate || undefined}
                      readOnly={!canEdit}
                      aria-label="תעריף"
                      onChange={(event) => updateCell(line.id, 'rate', event.target.value)}
                    />
                  </td>
                  <td className={`py-2 ${cellValue(stored) === null ? 'text-stone-400' : ''}`}>{cellAmount(stored, defaults)}</td>
                  <td className="py-2 text-stone-600">{yearTotal === null ? missingAsOf(month) : money(yearTotal)}</td>
                  {canEdit ? (
                    <td>
                      <button
                        type="button"
                        className="text-stone-600 underline"
                        onClick={() => onLines(lines.filter((candidate) => candidate.id !== line.id))}
                      >
                        מחק
                      </button>
                    </td>
                  ) : null}
                </tr>
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {lines.length > 0 ? (
        <p className="mt-3 text-sm text-stone-600">
          סה״כ {month}: הכנסות {showTotal(monthTotal(lines, month, categories, 'revenue'), month)} · הוצאות {showTotal(monthTotal(lines, month, categories, 'cost'), month)} · מימון {showTotal(monthTotal(lines, month, categories, 'financing'), month)}
        </p>
      ) : null}
      {lines.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="d-table">
            <thead>
              <tr>
                <th className="py-1 text-right font-medium">{month.slice(0, 4)}</th>
                {yearMonths(month).map((key) => (
                  <th key={key} className="py-1 text-right font-medium">
                    <button type="button" className={key === month ? 'font-semibold underline' : ''} onClick={() => onMonth(key)}>
                      {key.slice(5)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {([['revenue', 'הכנסות'], ['cost', 'הוצאות'], ['financing', 'מימון']] as const).map(([kind, label]) => (
                <tr key={kind}>
                  <td>{label}</td>
                  {yearMonths(month).map((key) => (
                    <td key={key}>{showTotal(monthTotal(lines, key, categories, kind), key)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {canEdit ? (
        <button
          type="button"
          className="mt-4 rounded bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          disabled={saving}
          onClick={onSave}
        >
          שמור תקציב
        </button>
      ) : null}
    </Card>
  );
}

export function FilingRulesCard({
  canEdit,
  rules,
  categories,
  seed,
  saving,
  onSave,
  manifest,
}: {
  manifest?: FilingReport['builtin_manifest'];
  canEdit: boolean;
  rules: FilingRule[];
  categories: FilingCategory[];
  seed: { text: string; nonce: number };
  saving: boolean;
  onSave: (rules: FilingRule[]) => void;
}) {
  const [contains, setContains] = useState('');
  const [field, setField] = useState<FilingRule['field']>('description');
  const [direction, setDirection] = useState<FilingRule['direction']>('both');
  const [category, setCategory] = useState(categories[0]?.key ?? '');

  useEffect(() => {
    if (seed.text) setContains(seed.text);
  }, [seed.nonce, seed.text]);

  function addRule() {
    const keyword = contains.trim();
    if (!keyword || !category) return;
    onSave([...rules, {
      id: `custom-${crypto.randomUUID()}`,
      source: 'custom',
      contains: keyword,
      field,
      direction,
      category,
      category_he: categories.find((item) => item.key === category)?.label_he ?? category,
      match_count: 0,
      overridden: 0,
      total: 0,
    }]);
    setContains('');
  }

  return (
    <Card title="כללי תיוק">
      <p className="mt-3 text-sm text-stone-600">
        סדר העדיפות: החלטת מנהל ← כלל מותאם ← כלל מובנה. {rules.filter((rule) => rule.source === 'builtin').length} כללים מובנים, {rules.filter((rule) => rule.source === 'custom').length} מותאמים.
        {manifest?.in_sync === false ? ' הכללים המובנים השתנו מאז שקובעו בתוכנית — יש לבדוק את הסיווג מחדש.' : ''}
        {manifest?.in_sync === true ? ' הכללים המובנים תואמים לקיבוע בתוכנית.' : ''}
      </p>
      <table className="mt-4 d-table">
        <thead>
          <tr>
            <th>כלל</th>
            <th>מילות מפתח</th>
            <th>התאמות</th>
            <th>סכום</th>
            {canEdit ? <th> </th> : null}
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>
                {rule.category_he}
                <span className="mr-2 text-stone-500">{rule.source === 'custom' ? 'מותאם' : 'מובנה'}</span>
              </td>
              <td>
                {rule.fallback ? 'כל תנועה שלא נתפסה בכלל קודם' : `«${rule.contains}»`} · {fieldLabel(rule.field)} · {directionLabel(rule.direction)}
                {rule.overridden > 0 ? <span className="mr-2 text-stone-500">נדרס {rule.overridden}</span> : null}
              </td>
              <td>{rule.match_count}</td>
              <td>{money(rule.total)}</td>
              {canEdit ? (
                <td>
                  {rule.source === 'custom' ? (
                    <button
                      type="button"
                      className="text-stone-600 underline"
                      disabled={saving}
                      onClick={() => onSave(rules.filter((candidate) => candidate.id !== rule.id))}
                    >
                      מחק
                    </button>
                  ) : null}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {canEdit ? (
        <div className="mt-4 flex flex-wrap items-end gap-2 text-sm">
          <label className="text-stone-600">
            מילת מפתח
            <input
              className="mt-1 block rounded border border-stone-300 px-2 py-1"
              value={contains}
              onChange={(event) => setContains(event.target.value)}
            />
          </label>
          <label className="text-stone-600">
            שדה
            <select className="mt-1 block rounded border border-stone-300 px-2 py-1" value={field} onChange={(event) => setField(event.target.value as FilingRule['field'])}>
              <option value="description">תיאור</option>
              <option value="counterparty">מוטב</option>
              <option value="any">תיאור או מוטב</option>
            </select>
          </label>
          <label className="text-stone-600">
            כיוון
            <select className="mt-1 block rounded border border-stone-300 px-2 py-1" value={direction} onChange={(event) => setDirection(event.target.value as FilingRule['direction'])}>
              <option value="both">כל כיוון</option>
              <option value="in">נכנס</option>
              <option value="out">יוצא</option>
            </select>
          </label>
          <label className="text-stone-600">
            קטגוריה
            <select className="mt-1 block rounded border border-stone-300 px-2 py-1" value={category} onChange={(event) => setCategory(event.target.value)}>
              {categories.map((item) => <option key={item.key} value={item.key}>{item.label_he}</option>)}
            </select>
          </label>
          <button type="button" className="rounded bg-stone-900 px-3 py-1 text-white disabled:opacity-50" disabled={saving || !contains.trim()} onClick={addRule}>
            הוסף כלל
          </button>
        </div>
      ) : null}
    </Card>
  );
}

function ReviewRow({
  item,
  canEdit,
  categories,
  saving,
  onApprove,
  onCreateRule,
}: {
  item: ReviewItem;
  canEdit: boolean;
  categories: FilingCategory[];
  saving: boolean;
  onApprove: (item: ReviewItem, category: string, note: string) => void;
  onCreateRule: (description: string) => void;
}) {
  const [category, setCategory] = useState(categories[0]?.key ?? '');
  const [note, setNote] = useState('');
  const description = item.description || item.counterparty || 'ללא תיאור';
  return (
    <tr className="border-b border-stone-100 align-top">
      <td>{item.date}</td>
      <td>
        {item.entity ? <div className="text-xs text-stone-500">{item.entity}</div> : null}
        <div>{description}</div>
        {item.counterparty && item.counterparty !== item.description ? <div className="text-stone-500">{item.counterparty}</div> : null}
      </td>
      <td>{money(item.amount)}</td>
      <td className="py-2 text-stone-600">{item.filed_by.reason_he}</td>
      {canEdit ? (
        <td>
          <div className="flex flex-wrap gap-2">
            <select className="rounded border border-stone-300 px-2 py-1" value={category} aria-label="קטגוריה לאישור" onChange={(event) => setCategory(event.target.value)}>
              {categories.map((option) => <option key={option.key} value={option.key}>{option.label_he}</option>)}
            </select>
            <input
              className="w-32 rounded border border-stone-300 px-2 py-1"
              value={note}
              placeholder="הערה"
              aria-label="הערה"
              onChange={(event) => setNote(event.target.value)}
            />
            <button type="button" className="rounded bg-stone-900 px-2 py-1 text-white disabled:opacity-50" disabled={saving} onClick={() => onApprove(item, category, note.trim())}>
              אשר כקטגוריה
            </button>
            <button type="button" className="text-stone-700 underline" onClick={() => onCreateRule(description)}>
              צור כלל מתיאור זה
            </button>
          </div>
        </td>
      ) : null}
    </tr>
  );
}

export function ReviewList({
  canEdit,
  report,
  saving,
  onPage,
  onApprove,
  onCreateRule,
}: {
  canEdit: boolean;
  report: FilingReport;
  saving: boolean;
  onPage: (page: number) => void;
  onApprove: (item: ReviewItem, category: string, note: string) => void;
  onCreateRule: (description: string) => void;
}) {
  const { review, categories, unmatched_decisions: unmatched = [] } = report;
  const from = review.total === 0 ? 0 : (review.page - 1) * review.page_size + 1;
  const to = Math.min(review.page * review.page_size, review.total);
  return (
    <Card title="תנועות לבירור">
      <p className="mt-3 text-sm text-stone-600">
        {review.total === 0 ? 'אין תנועות לבירור.' : `מציג ${from}–${to} מתוך ${review.total}`}
      </p>
      {unmatched.length > 0 ? (
        <p className="mt-2 text-sm text-stone-600">החלטות שלא הותאמו לתנועה: {unmatched.length}</p>
      ) : null}
      {review.items.length === 0 ? null : (
        <table className="mt-4 d-table">
          <thead>
            <tr>
              <th>תאריך</th>
              <th>תיאור</th>
              <th>סכום</th>
              <th>למה לא תויק</th>
              {canEdit ? <th>סיווג</th> : null}
            </tr>
          </thead>
          <tbody>
            {review.items.map((item) => (
              <ReviewRow
                key={item.id}
                item={item}
                canEdit={canEdit}
                categories={categories}
                saving={saving}
                onApprove={onApprove}
                onCreateRule={onCreateRule}
              />
            ))}
          </tbody>
        </table>
      )}
      {review.total > PAGE_SIZE ? (
        <div className="mt-4 flex gap-2 text-sm">
          <button type="button" className="rounded border border-stone-300 px-3 py-1 disabled:opacity-40" disabled={review.page <= 1} onClick={() => onPage(review.page - 1)}>
            הקודם
          </button>
          <button
            type="button"
            className="rounded border border-stone-300 px-3 py-1 disabled:opacity-40"
            disabled={review.page * review.page_size >= review.total}
            onClick={() => onPage(review.page + 1)}
          >
            הבא
          </button>
        </div>
      ) : null}
    </Card>
  );
}

export const FILING_PAGE_SIZE = PAGE_SIZE;
