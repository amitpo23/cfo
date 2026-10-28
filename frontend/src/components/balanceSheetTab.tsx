import { money } from './dashboardTabs';

export type SheetLine = {
  code: string | null;
  name: string;
  amount: number | null;
  mapped?: boolean;
  mark?: string | null;
  reason?: string | null;
  source: string | null;
  source_label: string | null;
  synced_at: string | null;
};

export type SheetSection = {
  status: string;
  total: number | null;
  source: string | null;
  source_label: string | null;
  synced_at: string | null;
  lines: SheetLine[];
};

export type PortalProfit = {
  status: string;
  total_revenue: number | null;
  total_expenses: number | null;
  net: number | null;
  lines: SheetLine[];
  unmapped_count?: number;
  synced_at: string | null;
  as_of: string | null;
  source_label: string | null;
};

export type PortalCard = {
  code: string | null;
  name: string;
  amount: number | null;
  mapped?: boolean;
  reason?: string | null;
  movements?: number;
  source_label: string | null;
  synced_at: string | null;
};

export type PortalCards = {
  status: string;
  cards: PortalCard[];
  total: number | null;
  synced_at: string | null;
  as_of: string | null;
  source_label: string | null;
  unmapped_count?: number;
};

export type UnclassifiedBucket = {
  label?: string;
  amount: number | null;
  row_count: number | null;
  lines?: SheetLine[];
  source?: string | null;
  source_label?: string | null;
  synced_at?: string | null;
};

export type SectionGap = {
  portal: number | null;
  books: number | null;
  gap: number | null;
  flagged: boolean;
};

export type BalanceSheetView = {
  status: string;
  presentation?: 'single' | 'compared';
  basis: string | null;
  basis_label: string | null;
  as_of: string | null;
  synced_at: string | null;
  balanced: boolean | null;
  message?: string | null;
  disclaimer?: string | null;
  assets: SheetSection;
  liabilities: SheetSection;
  equity: SheetSection & {
    opening_equity: number | null;
    retained_earnings: number | null;
  };
  unclassified?: UnclassifiedBucket | SheetLine[];
  file_total?: number | null;
  presented_total?: number | null;
  portal?: BalanceSheetView | null;
  books?: BalanceSheetView | null;
  difference?: {
    assets: SectionGap;
    liabilities: SectionGap;
    equity: SectionGap;
    unclassified: SectionGap;
  } | null;
  imports?: {
    profit_loss?: PortalProfit | null;
    ledger_cards?: PortalCards | null;
  };
};

function whenSynced(value: string | null | undefined): string {
  if (!value) return 'תאריך סנכרון לא ידוע';
  return value.slice(0, 10);
}

function Figure({ label, amount, source, syncedAt, strong }: {
  label?: string;
  amount: number | null | undefined;
  source?: string | null;
  syncedAt?: string | null;
  strong?: boolean;
}) {
  return (
    <div>
      {label ? <div className="text-sm text-stone-500">{label}</div> : null}
      <div className={strong ? 'text-xl' : undefined}>{money(amount)}</div>
      <p className="text-xs text-stone-500">
        {source || 'מקור לא ידוע'} · {whenSynced(syncedAt)}
      </p>
    </div>
  );
}

function SectionTable({ title, section }: { title: string; section: SheetSection }) {
  return (
    <section className="d-card">
      <h3>{title}</h3>
      <div className="mt-3">
        <Figure
          label="סה״כ"
          amount={section.total}
          source={section.source_label}
          syncedAt={section.synced_at}
          strong
        />
      </div>
      {section.lines.length > 0 ? (
        <table className="mt-4 d-table">
          <thead>
            <tr>
              <th>חשבון</th>
              <th>סכום</th>
            </tr>
          </thead>
          <tbody>
            {section.lines.map((line) => (
              <tr key={`${line.code || ''}-${line.name}`}>
                <td>
                  <div>{line.name}</div>
                  {line.code ? <div className="text-xs text-stone-500" dir="ltr">{line.code}</div> : null}
                  {line.mapped === false ? (
                    <div className="text-xs text-amber-800">{line.mark || 'לא ממופה'}</div>
                  ) : null}
                </td>
                <td>
                  <Figure amount={line.amount} source={line.source_label} syncedAt={line.synced_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-3 text-sm text-stone-600">אין שורות בסעיף. חסר אינו אפס.</p>
      )}
    </section>
  );
}

function unclassifiedOf(bucket: BalanceSheetView['unclassified']): UnclassifiedBucket | null {
  if (!bucket) return null;
  if (Array.isArray(bucket)) {
    if (bucket.length === 0) return null;
    const amount = bucket.some((line) => line.amount == null) ? null : bucket.reduce((sum, line) => sum + (line.amount || 0), 0);
    return { label: 'ללא סיווג', amount, row_count: bucket.length, lines: bucket };
  }
  return bucket;
}

function UnclassifiedBlock({ bucket }: { bucket: BalanceSheetView['unclassified'] }) {
  const row = unclassifiedOf(bucket);
  if (!row || (row.row_count == null && row.amount == null)) return null;
  const count = row.row_count == null ? 'מספר שורות לא ידוע' : `${row.row_count} שורות`;
  return (
    <section className="d-card">
      <h3>ללא סיווג</h3>
      <div className="mt-3">
        <Figure label={count} amount={row.amount} source={row.source_label} syncedAt={row.synced_at} strong />
      </div>
      {(row.lines || []).map((line) => (
        <p key={`${line.code || ''}-${line.name}`} className="mt-2 text-sm">
          {line.name}: {money(line.amount)}
        </p>
      ))}
    </section>
  );
}

const GAP_ROWS = [
  ['assets', 'נכסים'],
  ['liabilities', 'התחייבויות'],
  ['equity', 'הון'],
  ['unclassified', 'ללא סיווג'],
] as const;

function ComparedSheets({ sheet }: { sheet: BalanceSheetView }) {
  const portal = sheet.portal;
  const books = sheet.books;
  const difference = sheet.difference;
  if (!portal || !books || !difference) return null;
  return (
    <section className="d-card">
      <h2>מאזן — שני מקורות</h2>
      <p className="mt-2 text-sm text-stone-600">{sheet.message}</p>
      <div className="mt-4 overflow-x-auto">
        <table className="d-table">
          <thead>
            <tr>
              <th>סעיף</th>
              <th>
                {portal.basis_label || 'מקור לא ידוע'}
                <div className="text-xs font-normal text-stone-500">
                  {portal.as_of ? `נכון ל-${portal.as_of}` : 'תאריך הדוח לא ידוע'} · {whenSynced(portal.synced_at)}
                </div>
              </th>
              <th>
                {books.basis_label || 'מקור לא ידוע'}
                <div className="text-xs font-normal text-stone-500">
                  {books.as_of ? `נכון ל-${books.as_of}` : 'תאריך הדוח לא ידוע'} · {whenSynced(books.synced_at)}
                </div>
              </th>
              <th>הפרש</th>
            </tr>
          </thead>
          <tbody>
            {GAP_ROWS.map(([key, label]) => {
              const gap = difference[key];
              return (
                <tr key={key}>
                  <td>{label}</td>
                  <td>{money(gap.portal)}</td>
                  <td>{money(gap.books)}</td>
                  <td className={gap.flagged ? 'font-medium text-red-700' : undefined}>
                    {money(gap.gap)}
                    {gap.flagged ? ' · פער מעל ₪1' : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function BalanceSheetCard({ sheet }: { sheet: BalanceSheetView | null | undefined }) {
  if (!sheet) {
    return (
      <section className="d-card">
        <h2>מאזן</h2>
        <p className="mt-3 text-stone-600">המאזן לא ידוע.</p>
      </section>
    );
  }
  const profit = sheet.imports?.profit_loss;
  const cards = sheet.imports?.ledger_cards;
  if (sheet.presentation === 'compared') {
    return (
      <>
        <ComparedSheets sheet={sheet} />
        {sheet.portal ? <SingleSheet sheet={sheet.portal} profit={null} cards={null} /> : null}
        {sheet.books ? <SingleSheet sheet={sheet.books} profit={null} cards={null} /> : null}
        <ImportReports profit={profit} cards={cards} />
      </>
    );
  }
  return <SingleSheet sheet={sheet} profit={profit} cards={cards} />;
}

function SingleSheet({ sheet, profit, cards }: {
  sheet: BalanceSheetView;
  profit: PortalProfit | null | undefined;
  cards: PortalCards | null | undefined;
}) {
  const equitySide = sheet.liabilities.total != null && sheet.equity.total != null
    ? sheet.liabilities.total + sheet.equity.total
    : null;
  return (
    <>
      <section className="d-card">
        <h2>מאזן</h2>
        <p className="mt-2 text-sm text-stone-600">
          {sheet.basis_label || 'מקור לא ידוע'}
          {' · '}
          {sheet.as_of ? `נכון ל-${sheet.as_of}` : 'תאריך הדוח לא ידוע'}
          {' · '}
          {whenSynced(sheet.synced_at)}
        </p>
        {sheet.message ? <p className="mt-2 text-sm text-stone-600">{sheet.message}</p> : null}
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <dt className="text-sm text-stone-500">נכסים</dt>
            <dd><Figure amount={sheet.assets.total} source={sheet.assets.source_label} syncedAt={sheet.assets.synced_at} strong /></dd>
          </div>
          <div>
            <dt className="text-sm text-stone-500">התחייבויות והון</dt>
            <dd>
              <Figure
                amount={equitySide}
                source={sheet.equity.source_label || sheet.liabilities.source_label}
                syncedAt={sheet.equity.synced_at || sheet.liabilities.synced_at}
                strong
              />
            </dd>
          </div>
        </dl>
        <p className="mt-3 text-sm text-stone-600">
          {sheet.balanced == null ? 'האיזון לא ידוע.' : sheet.balanced ? 'המאזן מאוזן.' : 'המאזן אינו מאוזן.'}
        </p>
      </section>
      <div className="grid gap-4 lg:grid-cols-3">
        <SectionTable title="נכסים" section={sheet.assets} />
        <SectionTable title="התחייבויות" section={sheet.liabilities} />
        <section className="d-card">
          <h3>הון</h3>
          <div className="mt-3">
            <Figure label="סה״כ" amount={sheet.equity.total} source={sheet.equity.source_label} syncedAt={sheet.equity.synced_at} strong />
          </div>
          {sheet.basis === 'rezef_books' ? (
            <div className="mt-4 grid gap-3">
              <Figure label="הון פתיחה" amount={sheet.equity.opening_equity} source={sheet.equity.source_label} syncedAt={sheet.equity.synced_at} />
              <Figure label="עודפים" amount={sheet.equity.retained_earnings} source={sheet.equity.source_label} syncedAt={sheet.equity.synced_at} />
            </div>
          ) : null}
          {sheet.equity.lines.length > 0 ? (
            <table className="mt-4 d-table">
              <thead>
                <tr>
                  <th>חשבון</th>
                  <th>סכום</th>
                </tr>
              </thead>
              <tbody>
                {sheet.equity.lines.map((line) => (
                  <tr key={`${line.code || ''}-${line.name}`}>
                    <td>
                      {line.name}
                      {line.mapped === false ? <div className="text-xs text-amber-800">{line.mark || 'לא ממופה'}</div> : null}
                    </td>
                    <td><Figure amount={line.amount} source={line.source_label} syncedAt={line.synced_at} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      </div>
      <UnclassifiedBlock bucket={sheet.unclassified} />
      <ImportReports profit={profit} cards={cards} />
    </>
  );
}

function ImportReports({ profit, cards }: { profit: PortalProfit | null | undefined; cards: PortalCards | null | undefined }) {
  return (
    <>
      {profit && profit.status !== 'unknown' ? (
        <section className="d-card">
          <h3>רווח והפסד מיובא</h3>
          <p className="mt-2 text-sm text-stone-600">
            {profit.source_label || 'מקור לא ידוע'} · {profit.as_of || 'תאריך לא ידוע'} · {whenSynced(profit.synced_at)}
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Figure label="הכנסות" amount={profit.total_revenue} source={profit.source_label} syncedAt={profit.synced_at} />
            <Figure label="הוצאות" amount={profit.total_expenses} source={profit.source_label} syncedAt={profit.synced_at} />
            <Figure label="נטו" amount={profit.net} source={profit.source_label} syncedAt={profit.synced_at} />
          </div>
          {profit.unmapped_count ? (
            <p className="mt-3 text-sm text-amber-800">{profit.unmapped_count} שורות לא מופו לחשבון ברצף.</p>
          ) : null}
        </section>
      ) : null}
      {cards && cards.status !== 'unknown' ? (
        <section className="d-card">
          <h3>כרטיסי הנה״ח מיובאים</h3>
          <p className="mt-2 text-sm text-stone-600">
            {cards.source_label || 'מקור לא ידוע'} · {cards.as_of || 'תאריך לא ידוע'} · {whenSynced(cards.synced_at)}
          </p>
          <p className="mt-2 text-sm text-stone-600">אין סיכום לכרטיסים. חיבור כרטיסים מסוגים שונים אינו מאזן.</p>
          <table className="mt-4 d-table">
            <thead>
              <tr>
                <th>כרטיס</th>
                <th>יתרה</th>
              </tr>
            </thead>
            <tbody>
              {cards.cards.map((card) => (
                <tr key={`${card.code || ''}-${card.name}`}>
                  <td>
                    {card.name}
                    {card.code ? <div className="text-xs text-stone-500" dir="ltr">{card.code}</div> : null}
                    {card.mapped === false ? <div className="text-xs text-amber-800">לא ממופה</div> : null}
                  </td>
                  <td><Figure amount={card.amount} source={card.source_label} syncedAt={card.synced_at} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </>
  );
}
