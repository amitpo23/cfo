export type PeriodBankTotals = {
  inflows: number | null;
  outflows: number | null;
  net: number | null;
  inflowsAsOf: string | null;
  outflowsAsOf: string | null;
  netAsOf: string | null;
};

type BankFigure = { amount?: number | null; as_of?: string | null } | null | undefined;
type BankSide = { in?: BankFigure; out?: BankFigure; net?: BankFigure } | null | undefined;

/** Missing money or a ratio. A real zero stays a number for the caller to format. */
export function missingFigure(amount: number | null | undefined, asOf?: string | null): string | null {
  if (amount != null && !Number.isNaN(amount)) return null;
  return asOf ? `חסר · נכון ל-${asOf}` : 'חסר';
}

/** Booked bank movement for the period the user selected.

Read from the server totals that /pnl and /budget show for the same range. Days
that have not happened stay out, and a withheld profit claim does not hide the
cash that moved. A still-loading payload is not a total.
*/
export function periodBankTotals(
  report: { totals?: { bank?: BankSide; cash?: BankSide } | null } | null | undefined,
): PeriodBankTotals | null {
  const side = report?.totals?.cash ?? report?.totals?.bank;
  if (!side) return null;
  const read = (figure: BankFigure) => {
    const amount = figure?.amount;
    return amount == null || Number.isNaN(amount) ? null : amount;
  };
  return {
    inflows: read(side.in),
    outflows: read(side.out),
    net: read(side.net),
    inflowsAsOf: side.in?.as_of ?? null,
    outflowsAsOf: side.out?.as_of ?? null,
    netAsOf: side.net?.as_of ?? null,
  };
}
