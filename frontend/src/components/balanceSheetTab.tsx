import { money } from './dashboardTabs';

export type SheetLine = {
  code: string | null;
  name: string;
  amount: number | null;
  mapped?: boolean;
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

export type BalanceSheetView = {
  status: string;
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
  unclassified?: SheetLine[];
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
                    <div className="text-xs text-amber-800">{line.reason || 'לא מופה לחשבון ברצף'}</div>
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
                      {line.mapped === false ? <div className="text-xs text-amber-800">{line.reason || 'לא מופה לחשבון ברצף'}</div> : null}
                    </td>
                    <td><Figure amount={line.amount} source={line.source_label} syncedAt={line.synced_at} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      </div>
      {(sheet.unclassified || []).length > 0 ? (
        <section className="d-card">
          <h3>לא סווג למאזן</h3>
          <ul className="mt-3 text-sm">
            {sheet.unclassified?.map((line) => (
              <li key={`${line.code || ''}-${line.name}`} className="mt-2">
                {line.name}: <Figure amount={line.amount} source={line.source_label} syncedAt={line.synced_at} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
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
                    {card.mapped === false ? <div className="text-xs text-amber-800">{card.reason || 'לא מופה לחשבון ברצף'}</div> : null}
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
