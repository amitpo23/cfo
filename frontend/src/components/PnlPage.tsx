import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { PeriodCompareTable, PeriodControls, presetRange, type Grain, type PeriodCompare } from './PeriodCompare';
import { PartialDataBanner } from './dashboardUi';

const initial = presetRange('month');

export default function PnlPage() {
  const [grain, setGrain] = useState<Grain>('month');
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const report = useQuery({
    queryKey: ['cashflow-period', grain, start, end],
    queryFn: () => api.get<PeriodCompare>(`/cashflow/period?grain=${grain}&start=${start}&end=${end}`),
  });
  const slug = report.data?.dashboard_slug;

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">רווח והפסד</h1>
          <p className="mt-1 text-gray-600">ספרים (מסמכים שתויקו) · בנק (BOOKED) · תקציב. חסר אינו 0.</p>
          <p className="mt-1 text-sm text-gray-500">
            <Link className="underline" to="/budget">תקציב מול ביצוע</Link>
            {slug ? <> · <Link className="underline" to={`/d/${encodeURIComponent(slug)}?tab=bva`}>אותו תקציב בדשבורד</Link></> : null}
          </p>
        </div>
        <PeriodControls
          grain={grain}
          start={start}
          end={end}
          onGrain={(next) => {
            const range = presetRange(next);
            setGrain(next);
            setStart(range.start);
            setEnd(range.end);
          }}
          onStart={setStart}
          onEnd={setEnd}
        />
      </div>
      <PartialDataBanner
        text={report.data?.partial_banner?.text_he}
        extra={report.data?.unclassified_outflows?.label_he
          ? `${report.data.unclassified_outflows.label_he} (${report.data.unclassified_outflows.count})`
          : null}
      />
      {report.isError ? <p className="text-gray-600">אין רווח והפסד להצגה עד שנבחר ארגון פעיל.</p> : (
        <PeriodCompareTable report={report.data ?? null} booksFirst />
      )}
    </div>
  );
}
