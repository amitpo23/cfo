import React from 'react';
import type { LucideIcon } from 'lucide-react';

export const cls = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(' ');

export const formatILS = (value: number) =>
  new Intl.NumberFormat('he-IL', {
    style: 'currency',
    currency: 'ILS',
    maximumFractionDigits: 0,
  }).format(value || 0);

interface PageShellProps {
  darkMode?: boolean;
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  actions?: React.ReactNode;
  metrics?: Array<{ label: string; value: string; tone?: 'blue' | 'emerald' | 'amber' | 'rose' | 'slate' }>;
  children: React.ReactNode;
}

export function FinancePageShell({
  darkMode,
  eyebrow,
  title,
  description,
  icon: Icon,
  actions,
  metrics = [],
  children,
}: PageShellProps) {
  return (
    <div dir="rtl" className={cls('min-h-full p-5 lg:p-6', darkMode ? 'text-slate-100' : 'text-slate-950')}>
      <section
        className={cls(
          'overflow-hidden rounded-2xl border shadow-sm',
          darkMode ? 'border-slate-700 bg-slate-900' : 'border-slate-200 bg-white',
        )}
      >
        <div
          className={cls(
            'grid gap-6 border-b p-5 lg:grid-cols-[1fr_auto] lg:items-center lg:p-6',
            darkMode
              ? 'border-slate-700 bg-slate-900'
              : 'border-slate-200 bg-[linear-gradient(135deg,#f8fafc_0%,#ffffff_46%,#eef6ff_100%)]',
          )}
        >
          <div className="flex items-start gap-4">
            <div
              className={cls(
                'flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border',
                darkMode ? 'border-blue-400/30 bg-blue-500/10 text-blue-200' : 'border-blue-100 bg-blue-50 text-blue-700',
              )}
            >
              <Icon className="h-6 w-6" />
            </div>
            <div>
              <div className={cls('text-sm font-semibold', darkMode ? 'text-blue-200' : 'text-blue-700')}>{eyebrow}</div>
              <h1 className="mt-1 text-2xl font-bold tracking-normal lg:text-3xl">{title}</h1>
              <p className={cls('mt-2 max-w-3xl text-sm leading-6', darkMode ? 'text-slate-300' : 'text-slate-600')}>
                {description}
              </p>
            </div>
          </div>
          {actions && <div className="flex flex-wrap gap-2 lg:justify-end">{actions}</div>}
        </div>

        {metrics.length > 0 && (
          <div className={cls('grid gap-0 border-b md:grid-cols-2 xl:grid-cols-4', darkMode ? 'border-slate-700' : 'border-slate-200')}>
            {metrics.map((metric) => (
              <div key={metric.label} className={cls('p-5 md:border-l', darkMode ? 'border-slate-700' : 'border-slate-200')}>
                <div className={cls('text-xs font-medium', darkMode ? 'text-slate-400' : 'text-slate-500')}>{metric.label}</div>
                <div className={cls('mt-2 text-2xl font-bold', metricTone(metric.tone, darkMode))}>{metric.value}</div>
              </div>
            ))}
          </div>
        )}
      </section>
      <div className="mt-5 space-y-5">{children}</div>
    </div>
  );
}

export function FinanceCard({
  darkMode,
  title,
  subtitle,
  icon: Icon,
  action,
  children,
  className,
}: {
  darkMode?: boolean;
  title?: string;
  subtitle?: string;
  icon?: LucideIcon;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cls(
        'rounded-2xl border p-5 shadow-sm',
        darkMode ? 'border-slate-700 bg-slate-800 text-slate-100' : 'border-slate-200 bg-white text-slate-950',
        className,
      )}
    >
      {(title || action) && (
        <div className="mb-5 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            {Icon && (
              <div className={cls('rounded-lg p-2', darkMode ? 'bg-slate-700 text-blue-200' : 'bg-slate-100 text-blue-700')}>
                <Icon className="h-5 w-5" />
              </div>
            )}
            <div>
              {title && <h2 className="text-lg font-bold tracking-normal">{title}</h2>}
              {subtitle && <p className={cls('mt-1 text-sm leading-5', darkMode ? 'text-slate-400' : 'text-slate-500')}>{subtitle}</p>}
            </div>
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function MetricCard({
  darkMode,
  icon: Icon,
  label,
  value,
  detail,
  tone = 'blue',
  footnote,
  onClick,
}: {
  darkMode?: boolean;
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  detail: React.ReactNode;
  tone?: 'blue' | 'emerald' | 'amber' | 'rose' | 'slate';
  /** Small "source + freshness" line rendered under the detail line, e.g. "מקור: בנק · נכון ל-12/07". */
  footnote?: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') onClick(); } : undefined}
      className={cls(
        'rounded-2xl border p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md w-full',
        onClick ? 'text-right cursor-pointer' : '',
        darkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-white',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className={cls('rounded-xl p-3', iconTone(tone, darkMode))}>
          <Icon className="h-5 w-5" />
        </div>
        <span className={cls('rounded-full px-2 py-1 text-xs font-medium', badgeTone(tone, darkMode))}>{label}</span>
      </div>
      <div className="mt-4 text-2xl font-bold tracking-normal">{value}</div>
      <div className={cls('mt-1 text-sm leading-5', darkMode ? 'text-slate-400' : 'text-slate-500')}>{detail}</div>
      {footnote && (
        <div className={cls('mt-2 text-xs leading-4', darkMode ? 'text-slate-500' : 'text-slate-400')}>{footnote}</div>
      )}
    </div>
  );
}

/** Muted placeholder for a metric that has no data yet — honesty contract: null ≠ 0. */
export function NoDataYet({ darkMode }: { darkMode?: boolean }) {
  return <span className={darkMode ? 'text-slate-500' : 'text-slate-400'}>אין נתונים עדיין</span>;
}

export function AgentPanel({
  darkMode,
  insights,
}: {
  darkMode?: boolean;
  insights: Array<{ title: string; text: string; tone?: 'blue' | 'emerald' | 'amber' | 'rose' }>;
}) {
  return (
    <FinanceCard
      darkMode={darkMode}
      title="סוכן הכספים"
      subtitle="תובנות ופעולות שמחליפות עבודה ידנית של בדיקה, מעקב והסברים"
      className={darkMode ? 'bg-slate-900' : 'bg-slate-950 text-white'}
    >
      <div className="space-y-3">
        {insights.map((insight) => (
          <div
            key={insight.title}
            className={cls(
              'rounded-xl border p-4',
              darkMode ? 'border-white/10 bg-white/5' : 'border-white/10 bg-white/10',
            )}
          >
            <div className="text-sm font-bold">{insight.title}</div>
            <p className={cls('mt-1 text-sm leading-6', darkMode ? 'text-slate-300' : 'text-white/75')}>{insight.text}</p>
          </div>
        ))}
      </div>
    </FinanceCard>
  );
}

function metricTone(tone: 'blue' | 'emerald' | 'amber' | 'rose' | 'slate' | undefined, darkMode?: boolean) {
  if (tone === 'emerald') return darkMode ? 'text-emerald-300' : 'text-emerald-700';
  if (tone === 'amber') return darkMode ? 'text-amber-300' : 'text-amber-700';
  if (tone === 'rose') return darkMode ? 'text-rose-300' : 'text-rose-700';
  if (tone === 'slate') return darkMode ? 'text-slate-200' : 'text-slate-800';
  return darkMode ? 'text-blue-300' : 'text-blue-700';
}

function iconTone(tone: 'blue' | 'emerald' | 'amber' | 'rose' | 'slate', darkMode?: boolean) {
  const dark = {
    blue: 'bg-blue-500/15 text-blue-200',
    emerald: 'bg-emerald-500/15 text-emerald-200',
    amber: 'bg-amber-500/15 text-amber-200',
    rose: 'bg-rose-500/15 text-rose-200',
    slate: 'bg-slate-700 text-slate-200',
  };
  const light = {
    blue: 'bg-blue-50 text-blue-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    rose: 'bg-rose-50 text-rose-700',
    slate: 'bg-slate-100 text-slate-700',
  };
  return (darkMode ? dark : light)[tone];
}

function badgeTone(tone: 'blue' | 'emerald' | 'amber' | 'rose' | 'slate', darkMode?: boolean) {
  const dark = {
    blue: 'bg-blue-500/15 text-blue-200',
    emerald: 'bg-emerald-500/15 text-emerald-200',
    amber: 'bg-amber-500/15 text-amber-200',
    rose: 'bg-rose-500/15 text-rose-200',
    slate: 'bg-slate-700 text-slate-200',
  };
  const light = {
    blue: 'bg-blue-50 text-blue-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    rose: 'bg-rose-50 text-rose-700',
    slate: 'bg-slate-100 text-slate-700',
  };
  return (darkMode ? dark : light)[tone];
}
