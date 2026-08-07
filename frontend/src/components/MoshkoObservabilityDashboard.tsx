import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertCircle, Coins, Loader2, MessageCircle, RefreshCw, Wrench } from 'lucide-react';
import api from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

type Channel = '' | 'web' | 'telegram' | 'whatsapp';

interface Page<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

interface Conversation {
  organization_id: number;
  user_id: number;
  session_id: string;
  channel: string;
  started_at: string | null;
  last_message_at: string | null;
  message_count: number;
}

interface TranscriptMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string | null;
}

interface Transcript {
  session_id: string;
  organization_id: number;
  user_id: number;
  messages: TranscriptMessage[];
}

interface ToolCall {
  id: number;
  organization_id: number;
  user_id: number;
  session_id: string;
  tool_name: string;
  target_system: string;
  arguments: Record<string, unknown>;
  succeeded: boolean;
  error: string | null;
  duration_ms: number;
  result_size_bytes: number | null;
  created_at: string | null;
}

interface UsageBucket {
  day: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
  cost_usd: number | null;
}

interface UsageResponse {
  summary: Omit<UsageBucket, 'day'>;
  groups: UsageBucket[];
}

const channelLabel: Record<string, string> = {
  web: 'ווב',
  telegram: 'טלגרם',
  whatsapp: 'וואטסאפ',
};

function formatDate(value: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('he-IL', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
}

function formatCost(value: number | null) {
  return value === null ? 'לא ידוע' : `$${value.toFixed(4)}`;
}

export default function MoshkoObservabilityDashboard({
  currentUser,
}: {
  currentUser: CurrentUser | null;
}) {
  const [conversations, setConversations] = useState<Page<Conversation> | null>(null);
  const [toolCalls, setToolCalls] = useState<Page<ToolCall> | null>(null);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [loading, setLoading] = useState(true);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [organizationId, setOrganizationId] = useState('');
  const [userId, setUserId] = useState('');
  const [channel, setChannel] = useState<Channel>('');
  const [targetSystem, setTargetSystem] = useState('');
  const [success, setSuccess] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const params = useMemo(() => {
    const result: Record<string, string | number | boolean> = { limit: 50 };
    if (organizationId) result.organization_id = Number(organizationId);
    if (userId) result.user_id = Number(userId);
    if (channel) result.channel = channel;
    if (dateFrom) result.date_from = `${dateFrom}T00:00:00`;
    if (dateTo) result.date_to = `${dateTo}T23:59:59`;
    return result;
  }, [organizationId, userId, channel, dateFrom, dateTo]);

  const load = useCallback(async () => {
    if (currentUser?.role !== 'super_admin') return;
    setLoading(true);
    setError(null);
    try {
      const toolParams = { ...params };
      if (targetSystem) toolParams.target_system = targetSystem;
      if (success) toolParams.succeeded = success === 'success';
      const [conversationData, toolData, usageData] = await Promise.all([
        api.get<Page<Conversation>>('/admin/moshko/conversations', { params }),
        api.get<Page<ToolCall>>('/admin/moshko/tool-calls', { params: toolParams }),
        api.get<UsageResponse>('/admin/moshko/usage', { params: { ...params, group_by: 'day' } }),
      ]);
      setConversations(conversationData);
      setToolCalls(toolData);
      setUsage(usageData);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'טעינת נתוני מושקו נכשלה');
    } finally {
      setLoading(false);
    }
  }, [currentUser?.role, params, success, targetSystem]);

  useEffect(() => {
    void load();
  }, [load]);

  const openTranscript = async (row: Conversation) => {
    setTranscriptLoading(true);
    setError(null);
    try {
      setTranscript(await api.get<Transcript>(
        `/admin/moshko/conversations/${encodeURIComponent(row.session_id)}`,
        { params: { organization_id: row.organization_id, user_id: row.user_id } },
      ));
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'טעינת התמלול נכשלה');
    } finally {
      setTranscriptLoading(false);
    }
  };

  if (currentUser === null) {
    return <div dir="rtl" className="p-8 text-slate-500">טוען הרשאות…</div>;
  }
  if (currentUser.role !== 'super_admin') {
    return (
      <div dir="rtl" className="m-8 rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">
        המסך זמין למנהל־על בלבד.
      </div>
    );
  }

  const maxDailyTokens = Math.max(
    1,
    ...(usage?.groups || []).map((bucket) => bucket.input_tokens + bucket.output_tokens),
  );

  return (
    <div dir="rtl" className="min-h-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold"><Activity className="text-violet-600" /> ניטור מושקו</h1>
            <p className="mt-1 text-sm text-slate-500">שיחות, קריאות כלים וצריכת LLM — לכל הארגונים</p>
          </div>
          <button onClick={() => void load()} className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2 text-sm hover:bg-slate-100">
            <RefreshCw size={16} /> רענון
          </button>
        </header>

        <section className="grid gap-3 rounded-xl border bg-white p-4 shadow-sm md:grid-cols-4 lg:grid-cols-7">
          <input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} inputMode="numeric" placeholder="מזהה ארגון" className="rounded-lg border px-3 py-2" />
          <input value={userId} onChange={(event) => setUserId(event.target.value)} inputMode="numeric" placeholder="מזהה משתמש" className="rounded-lg border px-3 py-2" />
          <select value={channel} onChange={(event) => setChannel(event.target.value as Channel)} className="rounded-lg border px-3 py-2">
            <option value="">כל הערוצים</option><option value="web">ווב</option><option value="telegram">טלגרם</option><option value="whatsapp">וואטסאפ</option>
          </select>
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="rounded-lg border px-3 py-2" aria-label="מתאריך" />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="rounded-lg border px-3 py-2" aria-label="עד תאריך" />
          <select value={targetSystem} onChange={(event) => setTargetSystem(event.target.value)} className="rounded-lg border px-3 py-2">
            <option value="">כל היעדים</option><option value="sumit">SUMIT</option><option value="open_finance">Open Finance</option><option value="rezef_db">DB רצף</option><option value="local">מקומי</option>
          </select>
          <select value={success} onChange={(event) => setSuccess(event.target.value)} className="rounded-lg border px-3 py-2">
            <option value="">כל התוצאות</option><option value="success">הצלחה</option><option value="failure">כשל</option>
          </select>
        </section>

        {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><AlertCircle size={18} />{error}</div>}
        {loading ? (
          <div className="flex items-center justify-center gap-3 rounded-xl border bg-white p-16 text-slate-500"><Loader2 className="animate-spin" /> טוען נתונים…</div>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border bg-white p-5 shadow-sm"><MessageCircle className="mb-3 text-blue-600" /><div className="text-3xl font-bold">{conversations?.total ?? 0}</div><div className="text-sm text-slate-500">שיחות מסוננות</div></div>
              <div className="rounded-xl border bg-white p-5 shadow-sm"><Wrench className="mb-3 text-amber-600" /><div className="text-3xl font-bold">{toolCalls?.total ?? 0}</div><div className="text-sm text-slate-500">קריאות כלים</div></div>
              <div className="rounded-xl border bg-white p-5 shadow-sm"><Coins className="mb-3 text-emerald-600" /><div className="text-3xl font-bold">{formatCost(usage?.summary.cost_usd ?? null)}</div><div className="text-sm text-slate-500">עלות מתומחרת; לא ידוע נשאר NULL</div></div>
            </section>

            <section className="rounded-xl border bg-white p-5 shadow-sm">
              <h2 className="mb-4 text-lg font-semibold">טוקנים ועלות לפי יום</h2>
              <div className="space-y-3">
                {(usage?.groups || []).map((bucket) => {
                  const tokens = bucket.input_tokens + bucket.output_tokens;
                  return (
                    <div key={bucket.day} className="grid grid-cols-[90px_1fr_120px] items-center gap-3 text-sm">
                      <span>{bucket.day}</span>
                      <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-violet-500" style={{ width: `${Math.max((tokens / maxDailyTokens) * 100, 2)}%` }} /></div>
                      <span className="text-left tabular-nums">{tokens.toLocaleString('he-IL')} · {formatCost(bucket.cost_usd)}</span>
                    </div>
                  );
                })}
                {!usage?.groups.length && <p className="text-sm text-slate-500">אין נתוני שימוש בטווח שנבחר.</p>}
              </div>
            </section>

            <div className="grid gap-6 xl:grid-cols-2">
              <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
                <h2 className="border-b p-4 text-lg font-semibold">שיחות אחרונות</h2>
                <div className="max-h-[520px] overflow-auto">
                  {(conversations?.items || []).map((row) => (
                    <button key={`${row.organization_id}:${row.user_id}:${row.session_id}`} onClick={() => void openTranscript(row)} className="grid w-full grid-cols-[1fr_auto] gap-3 border-b p-4 text-right hover:bg-slate-50">
                      <span><span className="font-medium">{channelLabel[row.channel] || row.channel}</span><span className="mr-2 text-xs text-slate-400">ארגון {row.organization_id} · משתמש {row.user_id}</span><span className="mt-1 block truncate text-sm text-slate-500">{row.session_id}</span></span>
                      <span className="text-left text-xs text-slate-500">{row.message_count} הודעות<br />{formatDate(row.last_message_at)}</span>
                    </button>
                  ))}
                </div>
              </section>

              <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
                <h2 className="border-b p-4 text-lg font-semibold">תמלול מלא</h2>
                <div className="max-h-[520px] space-y-3 overflow-auto p-4">
                  {transcriptLoading && <Loader2 className="mx-auto animate-spin text-slate-400" />}
                  {!transcriptLoading && transcript?.messages.map((message) => (
                    <div key={message.id} className={`max-w-[88%] rounded-xl p-3 text-sm ${message.role === 'user' ? 'mr-auto bg-blue-50 text-blue-950' : 'ml-auto bg-slate-100'}`}>
                      <div className="mb-1 text-xs font-semibold text-slate-500">{message.role === 'user' ? 'משתמש' : 'מושקו'} · {formatDate(message.created_at)}</div>
                      <div className="whitespace-pre-wrap">{message.content}</div>
                    </div>
                  ))}
                  {!transcriptLoading && !transcript && <p className="text-sm text-slate-500">בחר שיחה כדי לצפות בתמלול.</p>}
                </div>
              </section>
            </div>

            <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
              <h2 className="border-b p-4 text-lg font-semibold">קריאות כלים</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="p-3 text-right">זמן</th><th className="p-3 text-right">כלי</th><th className="p-3 text-right">יעד</th><th className="p-3 text-right">תוצאה</th><th className="p-3 text-right">משך</th><th className="p-3 text-right">ארגומנטים מחוטאים</th></tr></thead>
                  <tbody>{(toolCalls?.items || []).map((call) => <tr key={call.id} className="border-t align-top"><td className="whitespace-nowrap p-3">{formatDate(call.created_at)}</td><td className="p-3 font-medium">{call.tool_name}<div className="text-xs text-slate-400">ארגון {call.organization_id}</div></td><td className="p-3">{call.target_system}</td><td className={`p-3 ${call.succeeded ? 'text-emerald-700' : 'text-red-700'}`}>{call.succeeded ? 'הצליח' : call.error || 'נכשל'}</td><td className="p-3 tabular-nums">{call.duration_ms}ms</td><td className="max-w-sm p-3"><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(call.arguments, null, 2)}</pre></td></tr>)}</tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
