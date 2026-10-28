export interface ProviderStatus {
  sumit: { connected: boolean; status: string; last_synced_at: string | null };
  open_finance: {
    connected: boolean;
    status: string;
    last_synced_at: string | null;
    bank_connections: number;
    last_refresh_at: string | null;
  };
  sumit_quota: {
    limit: number;
    used: number;
    remaining: number;
    live_shared_cap: number;
    shared: boolean;
  };
  confirmations: { sumit: string; open_finance: string };
  provider_calls: number;
}

interface Props {
  status: ProviderStatus;
  sumitArmed: boolean;
  financeArmed: boolean;
  pending: 'sumit' | 'finance' | null;
  notice: string | null;
  onSumitArmed: (armed: boolean) => void;
  onFinanceArmed: (armed: boolean) => void;
  onSumit: () => void;
  onFinance: () => void;
}

function connectionLabel(connected: boolean): string {
  return connected ? 'מחובר' : 'לא מחובר';
}

export function ProviderAccessCard({
  status, sumitArmed, financeArmed, pending, notice,
  onSumitArmed, onFinanceArmed, onSumit, onFinance,
}: Props) {
  const quota = status.sumit_quota;
  return (
    <section className="grid gap-3 text-sm" aria-label="חיבורי ספק">
      <p className="text-xs text-gray-500">
        נותרו {quota.remaining} מתוך {quota.limit} קריאות SUMIT החודש
        {' '}(תקרה משותפת לכל הארגונים, עד {quota.live_shared_cap} בחשבון החי).
        פתיחת המסך לא מושכת נתונים.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-gray-200 p-3">
          <p className="font-medium">SUMIT</p>
          <p>{connectionLabel(status.sumit.connected)} · {status.sumit.status}</p>
          <label className="mt-2 flex items-center gap-2">
            <input
              type="checkbox"
              checked={sumitArmed}
              onChange={(event) => onSumitArmed(event.target.checked)}
            />
            אני מאשר קריאה ל-SUMIT
          </label>
          <button
            type="button"
            disabled={!sumitArmed || pending !== null}
            onClick={onSumit}
            className="mt-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-white disabled:opacity-50"
          >
            {pending === 'sumit' ? 'שולח אישור…' : 'אשר קריאה ל-SUMIT'}
          </button>
        </div>
        <div className="rounded-lg border border-gray-200 p-3">
          <p className="font-medium">Open Finance</p>
          <p>
            {connectionLabel(status.open_finance.connected)} · {status.open_finance.status}
            {' '}· {status.open_finance.bank_connections} חיבורי בנק
          </p>
          <label className="mt-2 flex items-center gap-2">
            <input
              type="checkbox"
              checked={financeArmed}
              onChange={(event) => onFinanceArmed(event.target.checked)}
            />
            אני מאשר רענון Open Finance
          </label>
          <button
            type="button"
            disabled={!financeArmed || pending !== null}
            onClick={onFinance}
            className="mt-2 rounded-lg border px-3 py-1.5 disabled:opacity-50"
          >
            {pending === 'finance' ? 'שולח אישור…' : 'אשר רענון Open Finance'}
          </button>
        </div>
      </div>
      {notice ? <p role="status">{notice}</p> : null}
    </section>
  );
}
