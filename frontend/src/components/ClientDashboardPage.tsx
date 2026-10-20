import { useEffect, useState } from 'react';

type CashMonth = {
  month: string;
  inflows: number;
  outflows: number;
  net_flow: number;
};

type DashboardView = {
  source?: string;
  provider_calls?: number;
  cashflow?: {
    months?: CashMonth[];
    message?: string | null;
    coverage?: { message?: string | null } | null;
  };
  pnl?: {
    status?: string;
    total_revenue?: number | null;
    total_expenses?: number | null;
    net_income_before_tax?: number | null;
    message?: string | null;
  };
  error?: { message_he?: string };
};

function slugFromLocation(): string {
  const parts = window.location.pathname.replace(/\/+$/, '').split('/');
  return parts[2] || '';
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'לא ידוע';
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(value);
}

export default function ClientDashboardPage() {
  const [view, setView] = useState<DashboardView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const slug = slugFromLocation();
    const token = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('k');
    if (window.location.hash) {
      window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`);
    }
    let cancelled = false;

    async function load() {
      if (token) {
        await fetch(`/api/public/d/${slug}/session`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
      }
      const response = await fetch(`/api/public/d/${slug}`, { credentials: 'include' });
      const body = (await response.json().catch(() => ({}))) as DashboardView;
      if (cancelled) return;
      if (!response.ok) {
        setError(body.error?.message_he || 'הדשבורד לא נמצא');
        return;
      }
      setView(body);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const months = view?.cashflow?.months ?? [];
  const pnl = view?.pnl;

  return (
    <main dir="rtl" className="min-h-screen bg-stone-50 text-stone-900">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <p className="text-sm text-stone-500">רצף</p>
        <h1 className="mt-1 text-2xl font-semibold">דשבורד לקוח</h1>
        {error ? <p className="mt-8 text-stone-700">{error}</p> : null}
        {!error && !view ? <p className="mt-8 text-stone-500">טוען נתונים…</p> : null}
        {view ? (
          <div className="mt-8 grid gap-6">
            <section className="rounded-xl bg-white p-5 shadow-sm">
              <h2 className="text-lg font-medium">רווח והפסד</h2>
              {pnl?.status === 'unknown' ? (
                <p className="mt-3 text-stone-600">{pnl.message}</p>
              ) : (
                <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <dt className="text-sm text-stone-500">הכנסות</dt>
                    <dd className="text-xl">{money(pnl?.total_revenue)}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-stone-500">הוצאות</dt>
                    <dd className="text-xl">{money(pnl?.total_expenses)}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-stone-500">רווח לפני מס</dt>
                    <dd className="text-xl">{money(pnl?.net_income_before_tax)}</dd>
                  </div>
                </dl>
              )}
              {pnl?.status === 'ready' && pnl.message ? (
                <p className="mt-3 text-sm text-stone-500">{pnl.message}</p>
              ) : null}
            </section>
            <section className="rounded-xl bg-white p-5 shadow-sm">
              <h2 className="text-lg font-medium">תזרים</h2>
              {months.length === 0 ? (
                <p className="mt-3 text-stone-600">{view.cashflow?.message || 'אין תנועות בנק בתקופה.'}</p>
              ) : (
                <table className="mt-4 w-full text-sm">
                  <thead>
                    <tr className="border-b text-stone-500">
                      <th className="py-2 text-right font-medium">חודש</th>
                      <th className="py-2 text-right font-medium">כניסות</th>
                      <th className="py-2 text-right font-medium">יציאות</th>
                      <th className="py-2 text-right font-medium">נטו</th>
                    </tr>
                  </thead>
                  <tbody>
                    {months.map((month) => (
                      <tr key={month.month} className="border-b border-stone-100">
                        <td className="py-2">{month.month}</td>
                        <td className="py-2">{money(month.inflows)}</td>
                        <td className="py-2">{money(month.outflows)}</td>
                        <td className="py-2">{money(month.net_flow)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {view.cashflow?.coverage?.message ? (
                <p className="mt-3 text-sm text-stone-600">{view.cashflow.coverage.message}</p>
              ) : null}
            </section>
          </div>
        ) : null}
      </div>
    </main>
  );
}
