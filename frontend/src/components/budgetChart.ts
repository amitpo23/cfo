// Slices of the /budget pie: positive budgets only, largest first, the small
// ones folded into one "אחר" slice so labels do not pile up.
export const PIE_MAX_SLICES = 6;
// A slice smaller than this share gets no label on the pie; the legend names it.
export const PIE_LABEL_MIN_SHARE = 0.08;

export type PieSlice = { name: string; value: number };

export function pieSlices(rows: { category: string; planned: number }[], max = PIE_MAX_SLICES): PieSlice[] {
  const positive = rows
    .filter((row) => Number.isFinite(row.planned) && row.planned > 0)
    .map((row) => ({ name: row.category, value: row.planned }))
    .sort((a, b) => b.value - a.value);
  if (positive.length <= max) return positive;
  const head = positive.slice(0, max - 1);
  const rest = positive.slice(max - 1).reduce((sum, slice) => sum + slice.value, 0);
  return [...head, { name: 'אחר', value: Math.round(rest * 100) / 100 }];
}
