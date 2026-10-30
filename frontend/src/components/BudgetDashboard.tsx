import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts';
import api from '../services/api';
import { categoryLabel } from '../services/categoryLabels';
import ExportButtons from './ExportButtons';
import { PIE_LABEL_MIN_SHARE, pieSlices } from './budgetChart';
import { PartialDataBanner, missingAsOf } from './dashboardUi';
import { BudgetAssumptionsEditor } from './BudgetAssumptionsEditor';
import { PeriodCompareTable, PeriodControls, presetRange, type Figure, type Grain, type PeriodCompare } from './PeriodCompare';

interface BudgetComparison {
  category: string;
  kind?: string;
  planned: number | null;
  // null: the actual of the period is not known (not 0)
  actual: number | null;
  variance: number | null;
  variance_pct: number | null;
  status: string;
  driver?: boolean;
  division?: string | null;
  driverFormula?: string | null;
  quantity?: number | null;
  rate?: number | null;
  lineSource?: string | null;
  lineStatus?: string | null;
}

type BudgetSummaryMeta = {
  period?: string;
  source?: string;
  dashboardSlug?: string | null;
  totalActual?: number | null;
  message?: string | null;
  months?: { month: string; source_label?: string | null }[];
  // The dashboard comparison: revenue and costs apart, and the scope it covers.
  totals?: { revenue: KindTotal; costs: KindTotal } | null;
  scope?: string | null;
  scopeLabel?: string | null;
  scopes?: string[];
  windowStart?: string | null;
  windowEnd?: string | null;
};

type KindTotal = { budget: number | null; actual: number | null };

const SCOPE_LABELS: Record<string, string> = { combined: 'מאוחד (כל הישויות)', primary: 'הישות הראשית בלבד' };

const STATUS_LABELS: Record<string, string> = {
  on_track: 'בתקציב',
  warning: 'קרוב לחריגה',
  over_budget: 'חריגה',
  under_budget: 'מתחת לתקציב',
  critical: 'חריגה חמורה',
  unknown: 'ביצוע לא ידוע',
  missing: 'חסר',
  placeholder: 'סכום עגול — לא בסיכום',
};

interface BudgetAlert {
  category: string;
  alert_type: string;
  message: string;
  severity: string;
  current_spend: number | null;
  budget: number | null;
  percentage_used: number | null;
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8', '#82ca9d'];

export const BudgetDashboard: React.FC = () => {
  const opening = presetRange('month');
  const [grain, setGrain] = useState<Grain>('month');
  const [rangeStart, setRangeStart] = useState(opening.start);
  const [rangeEnd, setRangeEnd] = useState(opening.end);
  const [scope, setScope] = useState<string | null>(null);
  const [showScenario, setShowScenario] = useState(false);
  const [scenarioParams, setScenarioParams] = useState({
    revenue_change_pct: 0,
    expense_change_pct: 0,
  });

  const anchorYear = Number(rangeStart.slice(0, 4));
  const anchorMonth = Number(rangeStart.slice(5, 7));
  const { data: periodReport, isLoading: loadingPeriod, isError: periodFailed } = useQuery({
    queryKey: ['cashflow-period', grain, rangeStart, rangeEnd],
    queryFn: () => api.get<PeriodCompare>(`/cashflow/period?grain=${grain}&start=${rangeStart}&end=${rangeEnd}`),
  });

  // Category detail for the month the range starts in. The quarter total above
  // comes from /cashflow/period and does not multiply that month by three.
  const { data: budgetResult, isLoading: loadingBudget, isError: budgetFailed } = useQuery({
    queryKey: ['budget-vs-actual', anchorYear, anchorMonth, scope],
    queryFn: async () => {
      const res = await api.get<{ status: string; data: any }>('/api/financial/budget/vs-actual', {
        params: { year: anchorYear, month: anchorMonth, period: 'month', ...(scope ? { scope } : {}) },
      });
      const data = res?.data ?? {};
      const summary: BudgetSummaryMeta = {
        period: data.period,
        source: data.source,
        dashboardSlug: data.dashboard_slug ?? null,
        totalActual: data.total_actual === undefined ? undefined : data.total_actual,
        message: data.message ?? null,
        months: Array.isArray(data.months) ? data.months : undefined,
        totals: data.totals ?? null,
        scope: data.scope ?? null,
        scopeLabel: data.scope_label ?? null,
        scopes: Array.isArray(data.scopes) ? data.scopes : undefined,
        windowStart: data.window_start ?? null,
        windowEnd: data.window_end ?? null,
      };
      const categories: any[] = data.categories ?? [];
      const known = (value: unknown) => (typeof value === 'number' ? value : null);
      const rows = categories.map((c: any): BudgetComparison => ({
        category: c.driver ? (c.category_hebrew || c.category_name) : categoryLabel(c.category_id || c.category_name, c.category_hebrew),
        kind: c.kind,
        planned: c.budget_amount == null ? null : c.budget_amount,
        actual: known(c.actual_amount),
        variance: known(c.variance),
        variance_pct: known(c.variance_percentage),
        status: c.line_status === 'missing' ? 'missing' : c.status,
        driver: Boolean(c.driver),
        division: c.division ?? null,
        driverFormula: c.driver_formula ?? null,
        quantity: c.quantity ?? null,
        rate: c.rate ?? null,
        lineSource: c.line_source ?? null,
        lineStatus: c.line_status ?? null,
      }));
      return { rows, meta: summary };
    },
  });
  const budgetData = budgetResult?.rows;
  const meta: BudgetSummaryMeta = budgetResult?.meta ?? {};

  // Fetch budget alerts — backend מחזיר {status, data: [...]}
  const { data: alerts, isLoading: loadingAlerts } = useQuery({
    queryKey: ['budget-alerts', scope],
    queryFn: async () => {
      const res = await api.get<{ status: string; data: any[] }>('/api/financial/budget/alerts', {
        params: scope ? { scope } : {},
      });
      const list: any[] = res?.data ?? [];
      return list.map((a: any): BudgetAlert => ({
        category: categoryLabel(a.category, a.category_hebrew),
        alert_type: a.alert_type,
        message: a.message,
        severity: a.severity,
        current_spend: typeof a.actual_amount === 'number' ? a.actual_amount : null,
        budget: typeof a.budget_amount === 'number' ? a.budget_amount : null,
        percentage_used: typeof a.percentage_used === 'number' ? a.percentage_used : null,
      }));
    },
  });

  // Scenario analysis mutation — unwrap {status, data}
  const scenarioMutation = useMutation({
    mutationFn: async (params: typeof scenarioParams) => {
      const res = await api.post<{ status: string; data: {
        projected_revenue: number;
        projected_expenses: number;
        projected_net_income: number;
      } }>('/api/financial/budget/scenario', params);
      return res.data;
    },
  });

  const handleRunScenario = () => {
    scenarioMutation.mutate(scenarioParams);
  };

  // A missing category stays out of the total. It is not added as 0.
  const [openRow, setOpenRow] = useState<string | null>(null);
  const sumKnown = (key: 'planned' | 'actual'): number | null => {
    const rows = budgetData ?? [];
    if (rows.length === 0) return null;
    let total = 0;
    for (const row of rows) {
      const value = row[key];
      if (value == null) return null;
      total += value;
    }
    return total;
  };
  const plannedTotal = sumKnown('planned');
  const actualTotal = sumKnown('actual');
  const totalVariance = plannedTotal == null || actualTotal == null ? null : plannedTotal - actualTotal;
  const totalVariancePct = totalVariance == null || !plannedTotal ? null : (totalVariance / plannedTotal) * 100;

  const formatCurrency = (value: number | null) => (value === null ? missingAsOf(rangeEnd) : `₪${value.toLocaleString()}`);
  const periodTotals = periodReport?.totals;
  const figureText = (figure: Figure | undefined) => {
    if (!periodReport) return loadingPeriod ? 'טוען…' : missingAsOf(rangeEnd);
    if (figure?.amount == null) return missingAsOf(figure?.as_of ?? periodReport.as_of);
    return `₪${figure.amount.toLocaleString()}`;
  };
  const byKind = meta.totals ?? null;
  // The pie splits the cost budget (all rows on a page without kinds).
  const slices = pieSlices((budgetData ?? []).filter((row) => (!row.kind || row.kind === 'cost') && row.planned != null) as { category: string; planned: number }[]);
  const sourceLabels = [...new Set((meta.months ?? []).map((m) => m.source_label).filter(Boolean))];

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return 'bg-red-100 text-red-800 border-red-300';
      case 'warning': return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'info': return 'bg-blue-100 text-blue-800 border-blue-300';
      default: return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'under_budget': return '✅';
      case 'on_track': return '🔵';
      case 'over_budget': return '⚠️';
      case 'critical': return '🔴';
      default: return '⚪';
    }
  };

  if ((loadingBudget || loadingPeriod || loadingAlerts) && !budgetResult && !periodReport) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if ((budgetFailed && periodFailed) || (!budgetResult && !periodReport)) {
    return (
      <div className="p-6 bg-gray-50 min-h-screen" dir="rtl">
        <h1 className="text-3xl font-bold text-gray-900">ניהול תקציב</h1>
        <p className="mt-3 text-gray-600">אין נתוני תקציב להצגה עד שנבחר ארגון פעיל.</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">תקציב מול ביצוע</h1>
          <p className="text-gray-600 mt-1">ספרים, בנק ותקציב לאותו טווח. חודש שמולא לא מוכפל ברבעון.</p>
          {meta.source === 'dashboard' ? (
            <p className="text-sm text-gray-500 mt-1" data-scope={meta.scope ?? ''}>
              מחושב באותה פונקציה ובאותו חלון כמו לשונית "תקציב מול ביצוע" בדשבורד
              {meta.scopeLabel ? <> · היקף: <strong>{meta.scopeLabel}</strong></> : null}
              {meta.scope === 'combined' ? ' (כמו "מאוחד" בדשבורד)' : meta.scope === 'primary' ? ' (כמו לשונית הישות בדשבורד)' : null}
              {sourceLabels.length > 0 ? <> · מקור הביצוע: {sourceLabels.join(' / ')}</> : null}
              {meta.dashboardSlug ? (
                <> · <a className="underline" href={`/d/${encodeURIComponent(meta.dashboardSlug)}?tab=bva`}>פתח בדשבורד</a></>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="flex gap-4">
          {meta.scopes && meta.scopes.length > 1 ? (
            <select
              value={scope ?? meta.scope ?? ''}
              onChange={(e) => setScope(e.target.value)}
              className="rounded-lg border-gray-300 shadow-sm px-4 py-2"
              aria-label="היקף"
            >
              {meta.scopes.map((key) => <option key={key} value={key}>{SCOPE_LABELS[key] ?? key}</option>)}
            </select>
          ) : null}
          <PeriodControls
            grain={grain}
            start={rangeStart}
            end={rangeEnd}
            onGrain={(next) => {
              const range = presetRange(next);
              setGrain(next);
              setRangeStart(range.start);
              setRangeEnd(range.end);
            }}
            onStart={setRangeStart}
            onEnd={setRangeEnd}
          />
          <button
            onClick={() => setShowScenario(!showScenario)}
            className="bg-purple-600 text-white px-4 py-2 rounded-lg hover:bg-purple-700"
          >
            ניתוח תרחישים
          </button>
          <ExportButtons
            title="ניהול תקציב"
            columns={[
              { key: 'category', label: 'קטגוריה' },
              { key: 'planned', label: 'תקציב' },
              { key: 'actual', label: 'ביצוע' },
              { key: 'variance', label: 'סטייה' },
              { key: 'variance_pct', label: 'אחוז סטייה' },
              { key: 'status', label: 'סטטוס' },
            ]}
            rows={(budgetData || []).map((item) => ({
              category: item.category,
              planned: item.planned,
              actual: item.actual,
              variance: item.variance,
              variance_pct: item.variance_pct === null ? missingAsOf() : `${item.variance_pct.toFixed(1)}%`,
              status: STATUS_LABELS[item.status] ?? item.status,
            }))}
            summary={[
              { label: 'תקציב מתוכנן', value: formatCurrency(plannedTotal) },
              { label: 'ביצוע בפועל', value: formatCurrency(actualTotal) },
              { label: 'סטייה', value: formatCurrency(totalVariance) },
            ]}
          />
        </div>
      </div>

      <PartialDataBanner
        text={periodReport?.partial_banner?.text_he}
        extra={periodReport?.unclassified_outflows?.label_he
          ? `${periodReport.unclassified_outflows.label_he} (${periodReport.unclassified_outflows.count})`
          : null}
      />
      <PeriodCompareTable report={periodReport ?? null} booksFirst />
      <BudgetAssumptionsEditor start={rangeStart} end={rangeEnd} slug={periodReport?.dashboard_slug ?? meta.dashboardSlug} />

      {/* Headline cards: the period payload /pnl and /cashflow read for this range. */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {([['revenue', 'הכנסות'], ['costs', 'הוצאות'], ['net', 'נטו']] as const).map(([key, label]) => {
          const books = periodTotals?.books[key];
          const budget = periodTotals?.budget[key];
          return (
            <div key={key} className="bg-white rounded-xl shadow-sm p-6 border border-gray-100" data-total={key}>
              <h3 className="text-sm font-medium text-gray-500">{label}: ספרים מול תקציב</h3>
              <p className="text-2xl font-bold text-gray-900 mt-2">{figureText(books)}</p>
              <p className="text-sm text-gray-500">תקציב: {figureText(budget)}</p>
            </div>
          );
        })}
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-500">התראות פעילות</h3>
          <p className="text-2xl font-bold text-orange-600 mt-2">{alerts?.length || 0}</p>
        </div>
      </div>

      <h2 className="text-lg font-semibold text-gray-800">פירוט קטגוריות לחודש {rangeStart.slice(0, 7)}</h2>
      {byKind ? (
        <p className="text-sm text-gray-500">
          פירוט החודש: הכנסות {formatCurrency(byKind.revenue.actual)} מול תקציב {formatCurrency(byKind.revenue.budget)} ·
          הוצאות {formatCurrency(byKind.costs.actual)} מול תקציב {formatCurrency(byKind.costs.budget)}
        </p>
      ) : (
        <p className="text-sm text-gray-500">
          פירוט החודש: תקציב {formatCurrency(plannedTotal)} · ביצוע {formatCurrency(actualTotal)} · סטייה {formatCurrency(totalVariance)}
          {totalVariancePct == null ? '' : ` (${totalVariancePct.toFixed(1)}%)`}
        </p>
      )}

      {/* Alerts Section */}
      {alerts && alerts.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">התראות תקציב</h2>
          <div className="space-y-3">
            {alerts.map((alert, index) => (
              <div
                key={index}
                className={`p-4 rounded-lg border ${getSeverityColor(alert.severity)}`}
              >
                <div className="flex justify-between items-start">
                  <div>
                    <h4 className="font-semibold">{alert.category}</h4>
                    <p className="text-sm mt-1">{alert.message}</p>
                  </div>
                  <div className="text-left">
                    <span className="text-lg font-bold">
                      {alert.percentage_used == null ? missingAsOf(rangeEnd) : `${alert.percentage_used.toFixed(0)}%`}
                    </span>
                    <p className="text-xs">מהתקציב</p>
                  </div>
                </div>
                {alert.percentage_used == null ? null : (
                <div className="mt-3">
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${
                        alert.percentage_used > 100 ? 'bg-red-500' : 
                        alert.percentage_used > 80 ? 'bg-yellow-500' : 'bg-green-500'
                      }`}
                      style={{ width: `${Math.min(alert.percentage_used, 100)}%` }}
                    ></div>
                  </div>
                </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Budget vs Actual Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">תקציב מול ביצוע</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={budgetData ?? []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="category" />
              <YAxis tickFormatter={(v) => `₪${(v / 1000).toFixed(0)}K`} />
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Legend />
              <Bar dataKey="planned" fill="#8884d8" name="תקציב" />
              <Bar dataKey="actual" fill="#82ca9d" name="ביצוע" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
          <h2 className="text-xl font-bold text-gray-900 mb-4">פילוח תקציב ההוצאות</h2>
          {slices.length === 0 ? <p className="text-gray-500">אין תקציב הוצאות בתקופה.</p> : (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={slices}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="45%"
                outerRadius={90}
                labelLine={false}
                isAnimationActive={false}
                // Only the share, inside large slices; the legend carries the names.
                label={({ percent, cx, cy, midAngle, innerRadius, outerRadius }) => {
                  if (percent < PIE_LABEL_MIN_SHARE) return null;
                  const radius = innerRadius + (outerRadius - innerRadius) * 0.6;
                  const angle = (-midAngle * Math.PI) / 180;
                  return (
                    <text x={cx + radius * Math.cos(angle)} y={cy + radius * Math.sin(angle)} fill="#fff"
                      textAnchor="middle" dominantBaseline="central" fontSize={12} direction="ltr">
                      {`${(percent * 100).toFixed(0)}%`}
                    </text>
                  );
                }}
              >
                {slices.map((slice, index) => (
                  <Cell key={slice.name} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => formatCurrency(value)} />
              <Legend layout="horizontal" verticalAlign="bottom" align="center"
                wrapperStyle={{ direction: 'rtl', fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Budget Details Table */}
      <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 mb-4">פירוט תקציבי</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">קטגוריה</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">תקציב</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">ביצוע</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">סטייה</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">%</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">סטטוס</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {budgetData?.map((item, index) => (
                <tr key={`${item.category}-${index}`} className="hover:bg-gray-50 cursor-pointer" onClick={() => setOpenRow(openRow === item.category ? null : item.category)}>
                  <td className="px-6 py-4 text-sm font-medium text-gray-900">
                    {item.division ? <span className="text-gray-500">{item.division} · </span> : null}
                    {item.category}
                    {openRow === item.category && item.driver ? (
                      <p className="mt-1 text-xs font-normal text-gray-500">
                        {item.driverFormula || 'אין נוסחה'}
                        {item.quantity != null && item.rate != null ? ` · ${item.quantity} × ${item.rate}` : ''}
                        {item.lineSource ? ` · מקור: ${item.lineSource}` : ''}
                        {item.lineStatus === 'missing' ? ' · חסר' : item.lineStatus === 'assumption' ? ' · הנחה' : item.lineStatus === 'confirmed' ? ' · מאושר' : ''}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatCurrency(item.planned)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatCurrency(item.actual)}
                  </td>
                  <td className={`px-6 py-4 whitespace-nowrap text-sm font-medium ${
                    item.variance == null ? 'text-gray-400' : item.variance >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {formatCurrency(item.variance)}
                  </td>
                  <td className={`px-6 py-4 whitespace-nowrap text-sm ${
                    item.variance_pct == null ? 'text-gray-400' : item.variance_pct >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {item.variance_pct === null ? missingAsOf(rangeEnd) : `${item.variance_pct.toFixed(1)}%`}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    {getStatusIcon(item.status)} {STATUS_LABELS[item.status] ?? item.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Scenario Analysis Modal */}
      {showScenario && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-lg w-full mx-4">
            <h2 className="text-xl font-bold text-gray-900 mb-4">ניתוח תרחישים</h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  שינוי בהכנסות (%)
                </label>
                <input
                  type="range"
                  min="-50"
                  max="50"
                  value={scenarioParams.revenue_change_pct}
                  onChange={(e) => setScenarioParams({
                    ...scenarioParams,
                    revenue_change_pct: Number(e.target.value)
                  })}
                  className="w-full"
                />
                <span className={`text-lg font-bold ${
                  scenarioParams.revenue_change_pct >= 0 ? 'text-green-600' : 'text-red-600'
                }`}>
                  {scenarioParams.revenue_change_pct > 0 ? '+' : ''}{scenarioParams.revenue_change_pct}%
                </span>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  שינוי בהוצאות (%)
                </label>
                <input
                  type="range"
                  min="-50"
                  max="50"
                  value={scenarioParams.expense_change_pct}
                  onChange={(e) => setScenarioParams({
                    ...scenarioParams,
                    expense_change_pct: Number(e.target.value)
                  })}
                  className="w-full"
                />
                <span className={`text-lg font-bold ${
                  scenarioParams.expense_change_pct <= 0 ? 'text-green-600' : 'text-red-600'
                }`}>
                  {scenarioParams.expense_change_pct > 0 ? '+' : ''}{scenarioParams.expense_change_pct}%
                </span>
              </div>

              {scenarioMutation.data && (
                <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-semibold mb-2">תוצאות התרחיש:</h4>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-sm text-gray-500">הכנסות צפויות</p>
                      <p className="text-lg font-bold">
                        {formatCurrency(scenarioMutation.data.projected_revenue)}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">הוצאות צפויות</p>
                      <p className="text-lg font-bold">
                        {formatCurrency(scenarioMutation.data.projected_expenses)}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">רווח נקי צפוי</p>
                      <p className={`text-lg font-bold ${
                        scenarioMutation.data.projected_net_income >= 0 ? 'text-green-600' : 'text-red-600'
                      }`}>
                        {formatCurrency(scenarioMutation.data.projected_net_income)}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={handleRunScenario}
                disabled={scenarioMutation.isPending}
                className="flex-1 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {scenarioMutation.isPending ? 'מחשב...' : 'הרץ תרחיש'}
              </button>
              <button
                onClick={() => setShowScenario(false)}
                className="flex-1 bg-gray-200 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-300"
              >
                סגור
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BudgetDashboard;
