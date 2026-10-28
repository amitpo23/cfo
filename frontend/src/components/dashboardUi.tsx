// The /d/ chrome: navy frame with white content (the Koach reference in
// koach/VIDEO_BREAKDOWN.md), status tabs, the entity filter bar, KPI cards,
// the loading skeleton and the empty state. Sections use .d-card / .d-table (index.css).
import type { ReactNode } from 'react';

export function missingAsOf(asOf?: string | null): string {
  if (typeof asOf === 'string') {
    const day = asOf.match(/^(\d{4}-\d{2}-\d{2})/)?.[1]
      ?? (asOf.match(/^\d{4}-\d{2}$/) ? `${asOf}-01` : null);
    if (day) return `חסר נכון ל-${day}`;
  }
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  return `חסר נכון ל-${today}`;
}

export function DashboardFrame({ title, subtitle, children }: { title: string; subtitle?: string | null; children: ReactNode }) {
  return (
    <main dir="rtl" className="min-h-screen bg-navy-50 text-stone-900">
      <header className="bg-navy-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-4">
          <span className="text-sm font-semibold tracking-wide text-navy-200">רצף</span>
          <h1 className="text-xl font-semibold">{title}</h1>
          {subtitle ? <span className="text-sm text-navy-200">{subtitle}</span> : null}
        </div>
      </header>
      <div className="mx-auto max-w-7xl px-3 pb-10 sm:px-4">{children}</div>
    </main>
  );
}

export type TabItem<T extends string> = { id: T; label: string };

export function StatusTabs<T extends string>({ tabs, active, onSelect }: { tabs: readonly TabItem<T>[]; active: T; onSelect: (id: T) => void }) {
  return (
    <nav className="-mx-3 overflow-x-auto bg-navy-800 px-3 sm:mx-0 sm:rounded-b-lg" role="tablist" aria-label="לשוניות הדשבורד">
      <div className="flex min-w-max gap-1">
        {tabs.map((item) => (
          <button
            key={item.id}
            id={`tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={active === item.id}
            aria-controls="dashboard-panel"
            className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-sm ${
              active === item.id ? 'border-white font-semibold text-white' : 'border-transparent text-navy-200 hover:text-white'
            }`}
            onClick={() => onSelect(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </nav>
  );
}

export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-navy-100 bg-white px-3 py-2 text-sm">
      {children}
    </div>
  );
}

export function Segmented({ label, options, value, onChange }: {
  label: string;
  options: { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-stone-500">{label}</span>
      <div className="flex overflow-hidden rounded-md border border-navy-200" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.key}
            type="button"
            role="radio"
            aria-checked={value === option.key}
            className={`px-3 py-1 text-sm ${value === option.key ? 'bg-navy-800 text-white' : 'bg-white text-navy-700 hover:bg-navy-50'}`}
            onClick={() => onChange(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export type Kpi = { label: string; value: string; note?: string | null; tone?: 'warn' | null };

export function KpiCards({ items }: { items: Kpi[] }) {
  return (
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5" aria-label="מדדים">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border border-navy-100 bg-white p-3">
          <p className="text-xs text-stone-500">{item.label}</p>
          <p className={`mt-1 text-lg font-semibold tabular-nums ${item.value === 'לא ידוע' ? 'text-stone-400' : 'text-navy-900'}`}>{item.value}</p>
          {item.note ? <p className={`mt-0.5 text-xs ${item.tone === 'warn' ? 'text-amber-700' : 'text-stone-500'}`}>{item.note}</p> : null}
        </div>
      ))}
    </section>
  );
}

export function DashboardLoginPrompt({ message, loginPath }: { message: string; loginPath: string }) {
  return (
    <EmptyState title={message}>
      <a className="mt-3 inline-block font-medium text-navy-800 underline" href={loginPath}>התחברות</a>
      <p className="mt-1">אחרי ההתחברות חוזרים לדשבורד הזה.</p>
    </EmptyState>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-navy-200 bg-white px-4 py-8 text-center">
      <p className="font-medium text-navy-900">{title}</p>
      {children ? <div className="mt-1 text-sm text-stone-600">{children}</div> : null}
    </div>
  );
}

function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-navy-100 motion-reduce:animate-none ${className}`} />;
}

// The shape of the status tab while /view is on its way: KPI cards, then a table.
export function DashboardSkeleton() {
  return (
    <div className="mt-4 grid gap-4" role="status" aria-live="polite">
      <span className="sr-only">טוען את הדשבורד…</span>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((index) => (
          <div key={index} className="rounded-lg border border-navy-100 bg-white p-3">
            <Bar className="h-3 w-20" />
            <Bar className="mt-2 h-5 w-28" />
          </div>
        ))}
      </div>
      {[0, 1].map((card) => (
        <div key={card} className="d-card">
          <Bar className="h-4 w-40" />
          <div className="mt-4 grid gap-2">
            {[0, 1, 2, 3, 4].map((row) => <Bar key={row} className="h-3 w-full" />)}
          </div>
        </div>
      ))}
    </div>
  );
}
