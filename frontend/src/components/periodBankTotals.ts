export type PeriodBankTotals = {
  inflows: number | null;
  outflows: number | null;
  net: number | null;
};

type BankFigure = { amount?: number | null } | null | undefined;

type BankPeriod = {
  bank?: {
    in?: BankFigure;
    out?: BankFigure;
    net?: BankFigure;
  } | null;
};

/** Sum booked bank movement for the period the user selected.

A missing amount stays missing. An empty or still-loading payload is not a total,
so the screen cannot fall back to the rolling monthly sum.
*/
export function sumPeriodBankTotals(
  report: { periods?: BankPeriod[] | null } | null | undefined,
): PeriodBankTotals | null {
  const periods = report?.periods;
  if (!periods || periods.length === 0) return null;
  return {
    inflows: sumSide(periods, (period) => period.bank?.in?.amount),
    outflows: sumSide(periods, (period) => period.bank?.out?.amount),
    net: sumSide(periods, (period) => period.bank?.net?.amount),
  };
}

function sumSide(
  periods: BankPeriod[],
  read: (period: BankPeriod) => number | null | undefined,
): number | null {
  let total = 0;
  for (const period of periods) {
    const amount = read(period);
    if (amount == null || Number.isNaN(amount)) return null;
    total += amount;
  }
  return Math.round(total * 100) / 100;
}
