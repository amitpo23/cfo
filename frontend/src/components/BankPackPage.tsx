import { useEffect, useState } from 'react';

type Figure = { amount: number | null; missing_label: string | null; source: string; as_of: string };
type Week = {
  start?: string; end?: string; in?: number | null; out?: number | null; net?: number | null;
  closing?: number | null; in_missing?: string; out_missing?: string; net_missing?: string; closing_missing?: string;
};
type Today = {
  checking?: { balance?: number | null; label_he?: string; last_booked?: number | null; last_booked_as_of?: string | null; status?: string };
  facility?: { limit?: number | null; used?: number | null; headroom?: number | null; breach?: boolean | null; available_limit?: number | null };
};
type Pack = {
  title?: string;
  title_he: string;
  as_of: string;
  liquidity_today?: Today | null;
  pnl: { revenue: Figure; expenses: Figure };
  forecast: { opening: Figure; weeks: Week[]; supplier_terms?: string };
  assumptions: { label_he: string; month: string | null; amount: number | null; source: string | null; missing_label: string | null; as_of?: string }[];
  budget_vs_actual?: { status?: string; months?: { month: string; budget?: number | null; actual?: number | null; revenue_budget?: number | null; cost_budget?: number | null; source_label?: string }[] };
};

function figure(value: Figure): string {
  return value.amount == null ? (value.missing_label || 'חסר') : new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(value.amount);
}

function cell(amount: number | null | undefined, missing?: string): string {
  return amount == null ? (missing || 'חסר') : new Intl.NumberFormat('he-IL', { maximumFractionDigits: 0 }).format(amount);
}

export default function BankPackPage() {
  const slug = window.location.pathname.replace(/\/+$/, '').split('/')[2] || '';
  const [pack, setPack] = useState<Pack | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
    async function load() {
      if (token) {
        const found = await fetch(`/api/dashboards/by-slug/${slug}`, { headers });
        if (found.ok) {
          const dashboard = await found.json();
          const packResponse = await fetch(`/api/dashboards/${dashboard.id}/bank-pack`, { headers });
          const body = await packResponse.json();
          if (packResponse.ok) {
            setPack(body);
            return;
          }
        }
      }
      const response = await fetch(`/api/public/d/${slug}/bank-pack`, { credentials: 'include', headers });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(body.error?.message_he || 'החבילה לא נמצאה');
        return;
      }
      setPack(body);
    }
    void load();
  }, [slug]);

  return (
    <main dir="rtl" className="bank-pack mx-auto max-w-4xl bg-white p-6 text-stone-900">
      <style>{`
        @media print {
          .no-print { display: none; }
          .bank-pack { max-width: none; padding: 0; }
          @page { size: A4; margin: 14mm; }
        }
      `}</style>
      <p className="no-print mb-4 text-sm"><button type="button" className="underline" onClick={() => window.print()}>הדפסה / PDF</button></p>
      {error ? <p>{error}</p> : null}
      {!pack && !error ? <p>טוען חבילה לבנק…</p> : null}
      {pack ? (
        <>
          <h1 className="text-2xl font-semibold">{pack.title_he}{pack.title ? ` — ${pack.title}` : ''}</h1>
          <p className="mt-1 text-sm text-stone-600">נכון ל-{pack.as_of}. ספקים: {pack.forecast.supplier_terms === 'end_of_next_month' ? 'סוף החודש העוקב' : pack.forecast.supplier_terms}. חסר נשאר חסר.</p>
          {pack.liquidity_today ? (
            <section className="mt-4">
              <h2 className="text-lg font-medium">מצב בנק היום</h2>
              <p>{pack.liquidity_today.checking?.label_he || 'לא ידוע'}</p>
              <p>יתרת עו״ש לשימוש: {pack.liquidity_today.checking?.balance == null ? 'לא ידוע' : cell(pack.liquidity_today.checking.balance)}</p>
              {pack.liquidity_today.checking?.status !== 'ready' && pack.liquidity_today.checking?.last_booked != null ? (
                <p>יתרה שמורה אחרונה: {cell(pack.liquidity_today.checking.last_booked)} · {pack.liquidity_today.checking.last_booked_as_of || ''}</p>
              ) : null}
              <p>
                מסגרת {cell(pack.liquidity_today.facility?.limit)} · ניצול {cell(pack.liquidity_today.facility?.used)} · פנוי {cell(pack.liquidity_today.facility?.headroom)}
                {pack.liquidity_today.facility?.breach == null ? '' : pack.liquidity_today.facility.breach ? ' · חריגה' : ' · בתוך המסגרת'}
              </p>
              {pack.liquidity_today.facility?.available_limit != null ? (
                <p>יתרה זמינה מהבנק, בנפרד מיתרת העו״ש: {cell(pack.liquidity_today.facility.available_limit)}</p>
              ) : null}
            </section>
          ) : null}
          <h2 className="mt-6 text-lg font-medium">רווח והפסד</h2>
          <p>הכנסות: {figure(pack.pnl.revenue)} · מקור {pack.pnl.revenue.source} · {pack.pnl.revenue.as_of}</p>
          <p>הוצאות: {figure(pack.pnl.expenses)} · מקור {pack.pnl.expenses.source} · {pack.pnl.expenses.as_of}</p>
          <h2 className="mt-6 text-lg font-medium">תזרים 13 שבועות</h2>
          <p>יתרת פתיחה: {figure(pack.forecast.opening)} · מקור {pack.forecast.opening.source} · {pack.forecast.opening.as_of}</p>
          <table className="mt-2 w-full text-sm">
            <thead><tr className="text-right"><th>שבוע</th><th>נכנס</th><th>יוצא</th><th>נטו</th><th>סגירה</th></tr></thead>
            <tbody>
              {pack.forecast.weeks.map((week) => (
                <tr key={week.start}>
                  <td>{week.start}–{week.end}</td>
                  <td>{cell(week.in, week.in_missing)}</td>
                  <td>{cell(week.out, week.out_missing)}</td>
                  <td>{cell(week.net, week.net_missing)}</td>
                  <td>{cell(week.closing, week.closing_missing)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2 className="mt-6 text-lg font-medium">תקציב מול ביצוע</h2>
          {(pack.budget_vs_actual?.months || []).length ? (
            <ul>
              {(pack.budget_vs_actual?.months || []).map((month) => {
                const income = month.revenue_budget ?? null;
                const costs = month.cost_budget ?? null;
                const budgetText = income == null && costs == null
                  ? (month.budget == null ? 'חסר' : String(month.budget))
                  : `הכנסות ${income == null ? 'חסר' : income.toLocaleString('he-IL')} · הוצאות ${costs == null ? 'חסר' : costs.toLocaleString('he-IL')}`;
                return (
                  <li key={month.month}>{month.month}: תקציב {budgetText} · ביצוע {month.actual == null ? 'חסר' : month.actual}{month.source_label ? ` · ${month.source_label}` : ''}</li>
                );
              })}
            </ul>
          ) : <p>אין שורות תקציב מול ביצוע בחלון. חסר, לא 0.</p>}
          <h2 className="mt-6 text-lg font-medium">הנחות</h2>
          <ul>
            {pack.assumptions.map((row) => (
              <li key={`${row.label_he}-${row.month}`}>
                {row.label_he} {row.month || ''}: {row.amount == null ? (row.missing_label || 'חסר') : row.amount}
                {row.source ? ` · ${row.source}` : ''}{row.as_of ? ` · ${row.as_of}` : ''}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </main>
  );
}
