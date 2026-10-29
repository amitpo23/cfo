export type PeriodBankTotals = {
  inflows: number | null;
  outflows: number | null;
  net: number | null;
  inflowsAsOf: string | null;
  outflowsAsOf: string | null;
  netAsOf: string | null;
};

type BankFigure = { amount?: number | null; as_of?: string | null } | null | undefined;

/** Missing money or a ratio. A real zero stays a number for the caller to format. */
export function missingFigure(amount: number | null | undefined, asOf?: string | null): string | null {
  if (amount != null && !Number.isNaN(amount)) return null;
  return asOf ? `חסר · נכון ל-${asOf}` : 'חסר';
}

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
  const inflows = sumSide(periods, (period) => period.bank?.in);
  const outflows = sumSide(periods, (period) => period.bank?.out);
  const net = sumSide(periods, (period) => period.bank?.net);
  return {
    inflows: inflows.amount,
    outflows: outflows.amount,
    net: net.amount,
    inflowsAsOf: inflows.asOf,
    outflowsAsOf: outflows.asOf,
    netAsOf: net.asOf,
  };
}

function sumSide(
  periods: BankPeriod[],
  read: (period: BankPeriod) => BankFigure,
): { amount: number | null; asOf: string | null } {
  let total = 0;
  let asOf: string | null = null;
  let missing = false;
  for (const period of periods) {
    const figure = read(period);
    if (figure?.as_of && (!asOf || figure.as_of > asOf)) asOf = figure.as_of;
    const amount = figure?.amount;
    if (amount == null || Number.isNaN(amount)) missing = true;
    else total += amount;
  }
  return { amount: missing ? null : Math.round(total * 100) / 100, asOf };
}
