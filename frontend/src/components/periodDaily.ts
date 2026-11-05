import type { Figure, Grain, PeriodCompare } from './PeriodCompare.tsx';

/** One request feeds the chart, the cumulative table and the period table. */
export function periodQuery(grain: Grain, start: string, end: string) {
  return {
    queryKey: ['cashflow-period', grain, start, end] as const,
    url: `/cashflow/period?grain=${grain}&start=${start}&end=${end}`,
  };
}

function iso(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

/** /pnl ranges. Day grain opens month-to-date so the chart has days to show. */
export function pnlRange(grain: Grain, today = new Date()): { start: string; end: string } {
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
  if (grain === 'day') return { start: iso(monthStart), end: iso(today) };
  if (grain === 'week') {
    const start = new Date(today);
    start.setDate(today.getDate() - today.getDay());
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    return { start: iso(start), end: iso(end) };
  }
  if (grain === 'quarter') {
    const quarterStart = Math.floor(today.getMonth() / 3) * 3;
    return {
      start: iso(new Date(today.getFullYear(), quarterStart, 1)),
      end: iso(new Date(today.getFullYear(), quarterStart + 3, 0)),
    };
  }
  if (grain === 'year') return { start: `${today.getFullYear()}-01-01`, end: `${today.getFullYear()}-12-31` };
  return { start: iso(monthStart), end: iso(new Date(today.getFullYear(), today.getMonth() + 1, 0)) };
}

export type DailyChartRow = {
  date: string;
  label: string;
  elapsed: boolean;
  bankIn: number | null;
  bankOut: number | null;
  booksRevenue: number | null;
  booksCosts: number | null;
  budgetNet: number | null;
};

const amount = (figure?: Figure): number | null => figure?.amount ?? null;

/** Income and expense per bucket. A missing figure stays null so the chart leaves a gap. */
export function dailyChartRows(report: PeriodCompare | null): DailyChartRow[] {
  if (!report) return [];
  return report.periods.map((period) => ({
    date: period.start,
    label: period.label,
    elapsed: period.elapsed !== false,
    bankIn: amount(period.bank.in),
    bankOut: amount(period.bank.out),
    booksRevenue: amount(period.books.revenue),
    booksCosts: amount(period.books.costs),
    budgetNet: amount(period.budget.net),
  }));
}

/** The server returns a day budget only when the driver itself splits by day. */
export function hasDailyBudget(report: PeriodCompare | null): boolean {
  return Boolean(report?.periods.some((period) => period.budget.net.amount != null));
}

export type RunningFigure = {
  amount: number | null;
  /** First elapsed day with no figure. From here on the running total is unknown. */
  missingSince?: string;
  notStarted?: boolean;
};

export type CumulativeRow = {
  date: string;
  label: string;
  bankIn: RunningFigure;
  bankOut: RunningFigure;
  bankNet: RunningFigure;
  booksRevenue: RunningFigure;
  booksCosts: RunningFigure;
  booksNet: RunningFigure;
  budgetNet: RunningFigure;
};

type SeriesKey = Exclude<keyof CumulativeRow, 'date' | 'label'>;

const SERIES: { key: SeriesKey; pick: (period: PeriodCompare['periods'][number]) => Figure; gapIsMissing: boolean }[] = [
  { key: 'bankIn', pick: (p) => p.bank.in, gapIsMissing: true },
  { key: 'bankOut', pick: (p) => p.bank.out, gapIsMissing: true },
  { key: 'bankNet', pick: (p) => p.bank.net, gapIsMissing: true },
  { key: 'booksRevenue', pick: (p) => p.books.revenue, gapIsMissing: true },
  { key: 'booksCosts', pick: (p) => p.books.costs, gapIsMissing: true },
  { key: 'booksNet', pick: (p) => p.books.net, gapIsMissing: true },
  { key: 'budgetNet', pick: (p) => p.budget.net, gapIsMissing: false },
];

const cents = (value: number) => Math.round(value * 100) / 100;

/**
 * Running totals with the same rules as the server's ``_totals``: only days
 * that have started count; bank and books become unknown at the first missing
 * day; budget skips days without a budget. Withheld net stays withheld.
 */
export function cumulativeRows(report: PeriodCompare | null): CumulativeRow[] {
  if (!report) return [];
  const state = Object.fromEntries(SERIES.map(({ key }) => [key, { total: 0, known: false, missingSince: undefined as string | undefined }]));
  return report.periods.map((period) => {
    const row = { date: period.start, label: period.label } as CumulativeRow;
    for (const { key, pick, gapIsMissing } of SERIES) {
      const running = state[key];
      if (period.elapsed === false) {
        row[key] = { amount: null, notStarted: true };
        continue;
      }
      const value = pick(period).amount;
      if (value == null) {
        if (gapIsMissing && running.missingSince === undefined) running.missingSince = period.start;
      } else {
        running.total = cents(running.total + value);
        running.known = true;
      }
      row[key] = running.missingSince !== undefined
        ? { amount: null, missingSince: running.missingSince }
        : { amount: running.known ? running.total : null };
    }
    return row;
  });
}
