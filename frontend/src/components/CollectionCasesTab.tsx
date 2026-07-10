/**
 * Manual collection-case worklist (Wave 2 item 7.3, frontend half).
 * Separate from automated SMS/email reminders — this tracks a human
 * collector's calls/emails and outcomes per overdue contact.
 */
import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Phone, RefreshCw } from 'lucide-react';
import apiService from '../services/api';

interface CollectionCase {
  id: number;
  contact_id: number;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  invoice_ids: number[];
  total_balance: number;
  status: 'open' | 'promised' | 'paid' | 'escalated';
  attempts: Array<{ date: string; channel: string; outcome: string; notes: string }>;
  promise_date: string | null;
}

const STATUS_LABELS: Record<string, string> = {
  open: 'פתוח',
  promised: 'הובטח תשלום',
  paid: 'שולם',
  escalated: 'הוסלם',
};

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-gray-100 text-gray-700',
  promised: 'bg-yellow-100 text-yellow-700',
  paid: 'bg-green-100 text-green-700',
  escalated: 'bg-red-100 text-red-700',
};

const OUTCOME_OPTIONS = [
  { value: 'promised', label: 'הבטיח לשלם' },
  { value: 'paid', label: 'שילם' },
  { value: 'escalate', label: 'להסלים' },
  { value: 'no_answer', label: 'לא ענה' },
  { value: 'refused', label: 'סירב' },
];

const fmt = (n: number) =>
  new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS', maximumFractionDigits: 0 }).format(n);

const CollectionCasesTab: React.FC<{ darkMode: boolean }> = ({ darkMode }) => {
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [expandedCaseId, setExpandedCaseId] = useState<number | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<{ cases: CollectionCase[] }>({
    queryKey: ['collection-cases', statusFilter],
    queryFn: () => apiService.get('/collections/cases', { params: statusFilter ? { status: statusFilter } : {} }),
  });

  const openCasesMutation = useMutation({
    mutationFn: () => apiService.post<{ opened: number }>('/collections/open'),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['collection-cases'] });
      setStatusMessage(`נפתחו ${res.opened} תיקי גבייה חדשים`);
      setTimeout(() => setStatusMessage(null), 4000);
    },
  });

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  }`;

  const cases = data?.cases || [];

  return (
    <div className="space-y-4">
      {statusMessage && (
        <div className="px-4 py-2 rounded-lg bg-green-100 text-green-800 text-sm">{statusMessage}</div>
      )}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {['', 'open', 'promised', 'paid', 'escalated'].map((s) => (
            <button
              key={s || 'all'}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium ${
                statusFilter === s
                  ? 'bg-blue-500 text-white'
                  : darkMode
                    ? 'bg-gray-700 text-gray-300'
                    : 'bg-gray-100 text-gray-600'
              }`}
            >
              {s ? STATUS_LABELS[s] : 'הכל'}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => openCasesMutation.mutate()}
          disabled={openCasesMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition disabled:opacity-50"
        >
          <RefreshCw size={18} className={openCasesMutation.isPending ? 'animate-spin' : ''} />
          פתח תיקים לחובות בפיגור
        </button>
      </div>

      <div className={cardClass}>
        {isLoading ? (
          <div className="animate-pulse h-8 bg-gray-300 rounded w-1/3" />
        ) : cases.length === 0 ? (
          <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
            <Phone size={48} className="mx-auto mb-3 opacity-50" />
            <p>אין תיקי גבייה{statusFilter ? ` בסטטוס "${STATUS_LABELS[statusFilter]}"` : ''}</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="text-right py-3 px-2 text-sm font-medium">לקוח</th>
                <th className="text-right py-3 px-2 text-sm font-medium">יתרת חוב</th>
                <th className="text-right py-3 px-2 text-sm font-medium">סטטוס</th>
                <th className="text-right py-3 px-2 text-sm font-medium">הבטחת תשלום</th>
                <th className="text-right py-3 px-2 text-sm font-medium">ניסיונות</th>
                <th className="text-right py-3 px-2 text-sm font-medium">פעולות</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <React.Fragment key={c.id}>
                  <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                    <td className="py-3 px-2 text-sm">
                      <div className="font-medium">{c.contact_name || `#${c.contact_id}`}</div>
                      {c.contact_phone && <div className="text-xs text-gray-500">{c.contact_phone}</div>}
                    </td>
                    <td className="py-3 px-2 text-sm font-semibold">{fmt(c.total_balance)}</td>
                    <td className="py-3 px-2 text-sm">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[c.status]}`}>
                        {STATUS_LABELS[c.status]}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-sm">{c.promise_date || '—'}</td>
                    <td className="py-3 px-2 text-sm">{c.attempts.length}</td>
                    <td className="py-3 px-2 text-sm">
                      <button
                        type="button"
                        onClick={() => setExpandedCaseId(expandedCaseId === c.id ? null : c.id)}
                        className="text-blue-500 hover:text-blue-600 text-xs"
                      >
                        {expandedCaseId === c.id ? 'סגור' : 'רשום ניסיון'}
                      </button>
                    </td>
                  </tr>
                  {expandedCaseId === c.id && (
                    <tr>
                      <td colSpan={6} className="py-3 px-2">
                        <LogAttemptForm caseId={c.id} darkMode={darkMode} onDone={() => setExpandedCaseId(null)} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

const LogAttemptForm: React.FC<{ caseId: number; darkMode: boolean; onDone: () => void }> = ({
  caseId,
  darkMode,
  onDone,
}) => {
  const [channel, setChannel] = useState('phone');
  const [outcome, setOutcome] = useState('promised');
  const [notes, setNotes] = useState('');
  const [promiseDate, setPromiseDate] = useState('');
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      apiService.post(`/collections/cases/${caseId}/attempt`, {
        channel,
        outcome,
        notes,
        promise_date: outcome === 'promised' && promiseDate ? promiseDate : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collection-cases'] });
      onDone();
    },
  });

  const inputClass = `px-3 py-2 rounded-lg border text-sm ${
    darkMode ? 'bg-gray-700 border-gray-600' : 'border-gray-300'
  }`;

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div>
        <label className="block text-xs mb-1">ערוץ</label>
        <select value={channel} onChange={(e) => setChannel(e.target.value)} className={inputClass}>
          <option value="phone">טלפון</option>
          <option value="email">אימייל</option>
          <option value="sms">SMS</option>
        </select>
      </div>
      <div>
        <label className="block text-xs mb-1">תוצאה</label>
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className={inputClass}>
          {OUTCOME_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      {outcome === 'promised' && (
        <div>
          <label className="block text-xs mb-1">תאריך הבטחה</label>
          <input
            type="date"
            value={promiseDate}
            onChange={(e) => setPromiseDate(e.target.value)}
            className={inputClass}
          />
        </div>
      )}
      <div className="flex-1 min-w-[160px]">
        <label className="block text-xs mb-1">הערות</label>
        <input
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="פרטי השיחה..."
          className={`w-full ${inputClass}`}
        />
      </div>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
      >
        {mutation.isPending ? 'שומר...' : 'שמור'}
      </button>
    </div>
  );
};

export default CollectionCasesTab;
