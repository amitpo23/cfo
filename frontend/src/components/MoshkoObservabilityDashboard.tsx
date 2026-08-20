import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertCircle, Brain, CheckCircle2, Coins, Loader2, MessageCircle, RefreshCw, Wrench } from 'lucide-react';
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
  pending_action: { tool?: string; description?: string } | null;
  executed: boolean;
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
  message_id: number | null;
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

interface QualityFeedback {
  id: number;
  organization_id: number;
  user_id: number;
  session_id: string;
  channel: string;
  category: 'helpful' | 'inaccurate' | 'unknown' | 'unsafe';
  comment: string | null;
  question: string | null;
  answer: string;
  status: 'open' | 'reviewed' | 'resolved' | 'dismissed';
  correction: string | null;
  promoted_memory_id: number | null;
  created_at: string | null;
}

interface MoshkoGap {
  id: number;
  organization_id: number;
  user_id: number | null;
  session_id: string | null;
  message_id: number | null;
  question: string | null;
  answer: string | null;
  gap_kind: 'tool_failed' | 'model_gave_up' | 'user_flagged' | string;
  tool_name: string | null;
  error: string | null;
  status: 'open' | 'answered' | 'dismissed' | string;
  resolution: string | null;
  promoted_memory_id: number | null;
  created_at: string | null;
}

const gapKindLabel: Record<string, string> = {
  tool_failed: 'כלי נכשל',
  model_gave_up: 'מושקו ויתר',
  user_flagged: 'דגל משתמש',
};

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
  const [feedback, setFeedback] = useState<Page<QualityFeedback> | null>(null);
  const [gaps, setGaps] = useState<MoshkoGap[] | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [transcriptToolCalls, setTranscriptToolCalls] = useState<ToolCall[]>([]);
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
  const [feedbackStatus, setFeedbackStatus] = useState('open');
  const [feedbackCategory, setFeedbackCategory] = useState('');
  const [correctionDrafts, setCorrectionDrafts] = useState<Record<number, string>>({});
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [gapDrafts, setGapDrafts] = useState<Record<number, string>>({});
  const [gapBusyId, setGapBusyId] = useState<number | null>(null);

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
      const feedbackParams: Record<string, string | number> = { limit: 100 };
      if (organizationId) feedbackParams.organization_id = Number(organizationId);
      if (userId) feedbackParams.user_id = Number(userId);
      if (channel) feedbackParams.channel = channel;
      if (feedbackStatus) feedbackParams.status = feedbackStatus;
      if (feedbackCategory) feedbackParams.category = feedbackCategory;
      const gapParams: Record<string, string | number> = { status: 'open', limit: 100 };
      if (organizationId) gapParams.organization_id = Number(organizationId);
      const [conversationData, toolData, usageData, feedbackData, gapData] = await Promise.all([
        api.get<Page<Conversation>>('/admin/moshko/conversations', { params }),
        api.get<Page<ToolCall>>('/admin/moshko/tool-calls', { params: toolParams }),
        api.get<UsageResponse>('/admin/moshko/usage', { params: { ...params, group_by: 'day' } }),
        api.get<Page<QualityFeedback>>('/admin/moshko/feedback', { params: feedbackParams }),
        api.get<{ gaps: MoshkoGap[] }>('/admin/moshko/gaps', { params: gapParams }),
      ]);
      setConversations(conversationData);
      setToolCalls(toolData);
      setUsage(usageData);
      setFeedback(feedbackData);
      setGaps(gapData.gaps);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'טעינת נתוני מושקו נכשלה');
    } finally {
      setLoading(false);
    }
  }, [channel, currentUser?.role, feedbackCategory, feedbackStatus, organizationId, params, success, targetSystem, userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openTranscript = async (row: Conversation) => {
    setTranscriptLoading(true);
    setError(null);
    try {
      // ה-API של tool-calls אינו תומך בסינון session_id בצד השרת — מסננים
      // בצד הלקוח לפי ה-session_id שחוזר בכל שורה (בהיקף ארגון+משתמש).
      const [transcriptData, sessionToolData] = await Promise.all([
        api.get<Transcript>(
          `/admin/moshko/conversations/${encodeURIComponent(row.session_id)}`,
          { params: { organization_id: row.organization_id, user_id: row.user_id } },
        ),
        api.get<Page<ToolCall>>('/admin/moshko/tool-calls', {
          params: { organization_id: row.organization_id, user_id: row.user_id, limit: 500 },
        }),
      ]);
      setTranscript(transcriptData);
      setTranscriptToolCalls(
        sessionToolData.items.filter((call) => call.session_id === row.session_id),
      );
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'טעינת התמלול נכשלה');
    } finally {
      setTranscriptLoading(false);
    }
  };

  const reviewGap = async (row: MoshkoGap, action: 'answer' | 'promote' | 'dismiss') => {
    const resolution = (gapDrafts[row.id] ?? row.resolution ?? '').trim();
    if (action !== 'dismiss' && !resolution) {
      setError('נדרשת תשובה/הקשר לפני מענה לפער.');
      return;
    }
    setGapBusyId(row.id);
    setError(null);
    try {
      await api.patch(`/admin/moshko/gaps/${row.id}`,
        action === 'dismiss'
          ? { status: 'dismissed' }
          : {
              status: 'answered',
              resolution,
              promote_to_memory: action === 'promote',
            },
      );
      await load();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'שמירת המענה לפער נכשלה');
    } finally {
      setGapBusyId(null);
    }
  };

  const reviewFeedback = async (row: QualityFeedback, promoteToMemory: boolean) => {
    const correction = (correctionDrafts[row.id] ?? row.correction ?? '').trim();
    if (promoteToMemory && !correction) {
      setError('נדרש תיקון לפני הפיכתו לידע מאושר.');
      return;
    }
    setReviewingId(row.id);
    setError(null);
    try {
      await api.patch(`/admin/moshko/feedback/${row.id}`, {
        correction: correction || undefined,
        status: promoteToMemory ? 'resolved' : 'reviewed',
        promote_to_memory: promoteToMemory,
      });
      await load();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'שמירת ביקורת מושקו נכשלה');
    } finally {
      setReviewingId(null);
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
          <select value={feedbackStatus} onChange={(event) => setFeedbackStatus(event.target.value)} className="rounded-lg border px-3 py-2">
            <option value="">כל סטטוסי האיכות</option><option value="open">פתוח לבדיקה</option><option value="reviewed">נבדק</option><option value="resolved">נפתר</option><option value="dismissed">נדחה</option>
          </select>
          <select value={feedbackCategory} onChange={(event) => setFeedbackCategory(event.target.value)} className="rounded-lg border px-3 py-2">
            <option value="">כל סוגי המשוב</option><option value="inaccurate">לא מדויק</option><option value="unknown">לא ידע</option><option value="unsafe">לא בטוח</option><option value="helpful">מועיל</option>
          </select>
        </section>

        {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><AlertCircle size={18} />{error}</div>}
        {loading ? (
          <div className="flex items-center justify-center gap-3 rounded-xl border bg-white p-16 text-slate-500"><Loader2 className="animate-spin" /> טוען נתונים…</div>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
              <div className="rounded-xl border bg-white p-5 shadow-sm"><MessageCircle className="mb-3 text-blue-600" /><div className="text-3xl font-bold">{conversations?.total ?? 0}</div><div className="text-sm text-slate-500">שיחות מסוננות</div></div>
              <div className="rounded-xl border bg-white p-5 shadow-sm"><Wrench className="mb-3 text-amber-600" /><div className="text-3xl font-bold">{toolCalls?.total ?? 0}</div><div className="text-sm text-slate-500">קריאות כלים</div></div>
              <div className="rounded-xl border bg-white p-5 shadow-sm"><Coins className="mb-3 text-emerald-600" /><div className="text-3xl font-bold">{formatCost(usage?.summary.cost_usd ?? null)}</div><div className="text-sm text-slate-500">עלות מתומחרת; לא ידוע נשאר NULL</div></div>
              <div className="rounded-xl border bg-white p-5 shadow-sm"><Brain className="mb-3 text-violet-600" /><div className="text-3xl font-bold">{feedback?.total ?? 0}</div><div className="text-sm text-slate-500">פריטי איכות בתור</div></div>
              <div className="rounded-xl border bg-white p-5 shadow-sm"><AlertCircle className="mb-3 text-rose-600" /><div className="text-3xl font-bold">{gaps?.length ?? 0}</div><div className="text-sm text-slate-500">פערי יכולת פתוחים</div></div>
            </section>

            <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
              <div className="border-b p-4">
                <h2 className="text-lg font-semibold">תור איכות ואימון מושקו</h2>
                <p className="text-sm text-slate-500">כל תיקון נשמר רק בארגון שממנו הגיעה השיחה; קידום לידע דורש פעולה מפורשת.</p>
              </div>
              <div className="max-h-[700px] divide-y overflow-auto">
                {(feedback?.items || []).map((row) => (
                  <article key={row.id} className="space-y-3 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                      <span className="font-semibold text-slate-800">{row.category} · ארגון {row.organization_id} · משתמש {row.user_id} · {channelLabel[row.channel] || row.channel}</span>
                      <span>{formatDate(row.created_at)} · {row.status}</span>
                    </div>
                    <div className="grid gap-3 lg:grid-cols-2">
                      <div className="rounded-lg bg-blue-50 p-3 text-sm"><div className="mb-1 text-xs font-semibold text-blue-700">השאלה</div>{row.question || 'לא נמצאה שאלה קודמת'}</div>
                      <div className="rounded-lg bg-slate-100 p-3 text-sm"><div className="mb-1 text-xs font-semibold text-slate-600">תשובת מושקו</div>{row.answer}</div>
                    </div>
                    {row.comment && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm"><strong>הערת המשתמש:</strong> {row.comment}</div>}
                    <textarea
                      value={correctionDrafts[row.id] ?? row.correction ?? ''}
                      onChange={(event) => setCorrectionDrafts((current) => ({ ...current, [row.id]: event.target.value }))}
                      rows={2}
                      maxLength={8000}
                      placeholder="כתוב תשובה מתקנת מדויקת לארגון הזה"
                      className="w-full rounded-lg border p-3 text-sm"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={reviewingId === row.id} onClick={() => void reviewFeedback(row, false)} className="rounded-lg border px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50">
                        סמן כנבדק
                      </button>
                      <button type="button" disabled={reviewingId === row.id} onClick={() => void reviewFeedback(row, true)} className="flex items-center gap-2 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50">
                        {reviewingId === row.id ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} אשר והוסף לידע הארגוני
                      </button>
                    </div>
                  </article>
                ))}
                {!feedback?.items.length && <p className="p-6 text-sm text-slate-500">אין פריטי משוב במסנן שנבחר.</p>}
              </div>
            </section>

            <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
              <div className="border-b p-4">
                <h2 className="text-lg font-semibold">פערי יכולת וכישלונות</h2>
                <p className="text-sm text-slate-500">כלים שנפלו, שאלות שמושקו ויתר עליהן ודגלים של משתמשים — מענה כאן סוגר את הפער, וקידום לידע משפיע מהשיחה הבאה.</p>
              </div>
              <div className="max-h-[700px] divide-y overflow-auto">
                {(gaps || []).map((row) => (
                  <article key={row.id} className="space-y-3 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                      <span className="font-semibold text-slate-800">
                        <span className="rounded bg-rose-50 px-2 py-0.5 text-rose-700">{gapKindLabel[row.gap_kind] || row.gap_kind}</span>
                        <span className="mr-2">ארגון {row.organization_id}{row.user_id !== null ? ` · משתמש ${row.user_id}` : ''}</span>
                        {row.tool_name && <span className="mr-2 font-mono text-slate-600">כלי: {row.tool_name}</span>}
                      </span>
                      <span>{formatDate(row.created_at)} · {row.status}</span>
                    </div>
                    <div className="grid gap-3 lg:grid-cols-2">
                      <div className="rounded-lg bg-blue-50 p-3 text-sm"><div className="mb-1 text-xs font-semibold text-blue-700">השאלה</div>{row.question || 'לא נשמרה שאלה'}</div>
                      <div className="rounded-lg bg-slate-100 p-3 text-sm">
                        <div className="mb-1 text-xs font-semibold text-slate-600">{row.error ? 'השגיאה' : 'התשובה'}</div>
                        {row.error || row.answer || '—'}
                      </div>
                    </div>
                    <textarea
                      value={gapDrafts[row.id] ?? row.resolution ?? ''}
                      onChange={(event) => setGapDrafts((current) => ({ ...current, [row.id]: event.target.value }))}
                      rows={2}
                      maxLength={8000}
                      placeholder="תשובה/הקשר — מה מושקו היה צריך לדעת או לענות כאן"
                      className="w-full rounded-lg border p-3 text-sm"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={gapBusyId === row.id} onClick={() => void reviewGap(row, 'answer')} className="rounded-lg border px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50">
                        ענה
                      </button>
                      <button type="button" disabled={gapBusyId === row.id} onClick={() => void reviewGap(row, 'promote')} className="flex items-center gap-2 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50">
                        {gapBusyId === row.id ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} ענה וקדם לידע
                      </button>
                      <button type="button" disabled={gapBusyId === row.id} onClick={() => void reviewGap(row, 'dismiss')} className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50">
                        בטל
                      </button>
                    </div>
                  </article>
                ))}
                {!gaps?.length && <p className="p-6 text-sm text-slate-500">אין פערים פתוחים במסנן שנבחר.</p>}
              </div>
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
                  {!transcriptLoading && transcript?.messages.map((message) => {
                    const messageToolCalls = transcriptToolCalls.filter((call) => call.message_id === message.id);
                    return (
                      <div key={message.id} className={`max-w-[88%] rounded-xl p-3 text-sm ${message.role === 'user' ? 'mr-auto bg-blue-50 text-blue-950' : 'ml-auto bg-slate-100'}`}>
                        <div className="mb-1 text-xs font-semibold text-slate-500">{message.role === 'user' ? 'משתמש' : 'מושקו'} · {formatDate(message.created_at)}</div>
                        <div className="whitespace-pre-wrap">{message.content}</div>
                        {message.role === 'assistant' && message.pending_action && (
                          <div className="mt-2 flex flex-wrap items-center gap-1 text-xs">
                            <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800">פעולה הוצעה{message.pending_action.tool ? ` · ${message.pending_action.tool}` : ''}</span>
                            {!message.executed && <span className="rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-700">לא אושרה</span>}
                          </div>
                        )}
                        {messageToolCalls.length > 0 && (
                          <div className="mt-2 space-y-1 border-t border-slate-200 pt-2">
                            {messageToolCalls.map((call) => (
                              <div key={call.id} className="flex flex-wrap items-center gap-2 text-xs">
                                <span className={`rounded-full px-2 py-0.5 font-medium ${call.succeeded ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-700'}`}>
                                  {call.tool_name} · {call.succeeded ? 'הצליח' : 'נכשל'}
                                </span>
                                <span className="tabular-nums text-slate-400">{call.duration_ms}ms</span>
                                {!call.succeeded && call.error && <span className="text-red-700">{call.error}</span>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
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
