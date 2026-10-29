/** Missing money is חסר. A measured zero stays ₪0. */
export const MISSING_MONEY = 'חסר';

export function formatReportMoney(amount: number | null | undefined): string {
  if (amount == null || Number.isNaN(amount)) return MISSING_MONEY;
  return `₪${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export type MoneySign = 'profit' | 'loss' | 'missing';

/** Null is missing. Do not use `amount >= 0` — in JS that is true for null. */
export function moneySign(amount: number | null | undefined): MoneySign {
  if (amount == null || Number.isNaN(amount)) return 'missing';
  return amount >= 0 ? 'profit' : 'loss';
}

/** Largest absolute measured profit. Null when nothing was measured — not 1, not 0. */
export function profitBarScale(amounts: ReadonlyArray<number | null | undefined>): number | null {
  let scale: number | null = null;
  for (const amount of amounts) {
    if (amount == null || Number.isNaN(amount)) continue;
    const abs = Math.abs(amount);
    scale = scale == null ? abs : Math.max(scale, abs);
  }
  if (scale == null) return null;
  return Math.max(scale, 1);
}

/** Percent height of a measured bar. Null means do not draw one. */
export function profitBarHeightPercent(
  amount: number | null | undefined,
  scale: number | null,
): number | null {
  if (amount == null || scale == null || Number.isNaN(amount) || scale <= 0) return null;
  return Math.max(2, (Math.abs(amount) / scale) * 100);
}
