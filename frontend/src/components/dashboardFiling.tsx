import { useEffect, useState, type ReactNode } from 'react';

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
};

export type ReviewItem = {
  id: string;
  organization_id: number;
  date: string;
  description: string;
  counterparty: string;
  amount: number;
  filed_by: { reason_he: string; note?: string | null };
};

export type FilingCategory = { key: string; label_he: string };
export type BudgetCategory = { key: string; label_he: string; kind: 'revenue' | 'cost' };

export type FilingReport = {
  rules: FilingRule[];
  review: { total: number; page: number; page_size: number; items: ReviewItem[] };
  categories: FilingCategory[];
  budget_categories: BudgetCategory[];
  unmatched_decisions?: { transaction_id: string; reason: string }[];
  can_edit: boolean;
};

export type LineDraft = {
  id: string;
  label: string;
  category: string;
  months: Record<string, { quantity: string; rate: string }>;
};

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
    return [{ id: row.id, label: row.label, category: row.category, months }];
  });
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

function cellAmount(cell: { quantity: string; rate: string } | undefined): string {
  if (!cell) return '—';
  const quantity = parseAmount(cell.quantity);
  const rate = parseAmount(cell.rate);
  if (quantity === null || rate === null) return '—';
  return money(quantity * rate);
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
      if (quantity === null || rate === null) return { error: `כמות או תעריף לא תקינים בחודש ${month}` };
      months[month] = { quantity, rate };
    }
    payload.push({
      id: line.id,
      label,
      category: line.category,
      kind: kindByKey.get(line.category),
      months,
    });
  }
  return { lines: payload };
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium">{title}</h2>
      {children}
    </section>
  );
}

export function BudgetEditor({
  canEdit,
  categories,
  lines,
  month,
  onMonth,
  onLines,
  onSave,
  saving,
}: {
  canEdit: boolean;
  categories: BudgetCategory[];
  lines: LineDraft[];
  month: string;
  onMonth: (month: string) => void;
  onLines: (lines: LineDraft[]) => void;
  onSave: () => void;
  saving: boolean;
}) {
  function update(id: string, patch: Partial<LineDraft>) {
    onLines(lines.map((line) => (line.id === id ? { ...line, ...patch } : line)));
  }

  function updateCell(id: string, field: 'quantity' | 'rate', value: string) {
    onLines(lines.map((line) => {
      if (line.id !== id) return line;
      const current = line.months[month] ?? { quantity: '', rate: '' };
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
      </div>
      {lines.length === 0 ? <p className="mt-3 text-stone-600">אין שורות תקציב.</p> : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500">
              <th className="py-2 text-right font-medium">שורה</th>
              <th className="py-2 text-right font-medium">קטגוריה</th>
              <th className="py-2 text-right font-medium">כמות</th>
              <th className="py-2 text-right font-medium">תעריף</th>
              <th className="py-2 text-right font-medium">סכום</th>
              {canEdit ? <th className="py-2 text-right font-medium"> </th> : null}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const cell = line.months[month] ?? { quantity: '', rate: '' };
              return (
                <tr key={line.id} className="border-b border-stone-100">
                  <td className="py-2">
                    <input
                      className="w-full rounded border border-stone-200 px-2 py-1"
                      value={line.label}
                      readOnly={!canEdit}
                      aria-label="כותרת שורה"
                      onChange={(event) => update(line.id, { label: event.target.value })}
                    />
                  </td>
                  <td className="py-2">
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
                  <td className="py-2">
                    <input
                      dir="ltr"
                      inputMode="decimal"
                      className="w-24 rounded border border-stone-200 px-2 py-1 text-left"
                      value={cell.quantity}
                      readOnly={!canEdit}
                      aria-label="כמות"
                      onChange={(event) => updateCell(line.id, 'quantity', event.target.value)}
                    />
                  </td>
                  <td className="py-2">
                    <input
                      dir="ltr"
                      inputMode="decimal"
                      className="w-28 rounded border border-stone-200 px-2 py-1 text-left"
                      value={cell.rate}
                      readOnly={!canEdit}
                      aria-label="תעריף"
                      onChange={(event) => updateCell(line.id, 'rate', event.target.value)}
                    />
                  </td>
                  <td className="py-2">{cellAmount(cell)}</td>
                  {canEdit ? (
                    <td className="py-2">
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
              );
            })}
          </tbody>
        </table>
      )}
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
}: {
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
      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="border-b text-stone-500">
            <th className="py-2 text-right font-medium">כלל</th>
            <th className="py-2 text-right font-medium">מילות מפתח</th>
            <th className="py-2 text-right font-medium">התאמות</th>
            <th className="py-2 text-right font-medium">סכום</th>
            {canEdit ? <th className="py-2 text-right font-medium"> </th> : null}
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id} className="border-b border-stone-100">
              <td className="py-2">
                {rule.category_he}
                <span className="mr-2 text-stone-500">{rule.source === 'custom' ? 'מותאם' : 'מובנה'}</span>
              </td>
              <td className="py-2">
                «{rule.contains}» · {fieldLabel(rule.field)} · {directionLabel(rule.direction)}
                {rule.overridden > 0 ? <span className="mr-2 text-stone-500">נדרס {rule.overridden}</span> : null}
              </td>
              <td className="py-2">{rule.match_count}</td>
              <td className="py-2">{money(rule.total)}</td>
              {canEdit ? (
                <td className="py-2">
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
      <td className="py-2">{item.date}</td>
      <td className="py-2">
        <div>{description}</div>
        {item.counterparty && item.counterparty !== item.description ? <div className="text-stone-500">{item.counterparty}</div> : null}
      </td>
      <td className="py-2">{money(item.amount)}</td>
      <td className="py-2 text-stone-600">{item.filed_by.reason_he}</td>
      {canEdit ? (
        <td className="py-2">
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
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b text-stone-500">
              <th className="py-2 text-right font-medium">תאריך</th>
              <th className="py-2 text-right font-medium">תיאור</th>
              <th className="py-2 text-right font-medium">סכום</th>
              <th className="py-2 text-right font-medium">למה לא תויק</th>
              {canEdit ? <th className="py-2 text-right font-medium">סיווג</th> : null}
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
