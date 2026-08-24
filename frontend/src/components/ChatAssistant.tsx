/**
 * AI chat assistant (Wave 2 item 9.4). Every write action the assistant
 * proposes (issue_document, log_collection_attempt) shows as a pending
 * card requiring an explicit click to confirm — the backend never
 * executes it from the model's call alone (see ai_chat_service.py).
 */
import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Send, ShieldAlert, Loader2, Bot, User as UserIcon, Building2, Plus, Activity, BookOpen, ThumbsUp, ThumbsDown, HelpCircle, AlertTriangle } from 'lucide-react';
import apiService from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

interface PendingAction {
  tool: string;
  input: Record<string, unknown>;
  description: string;
}

interface ChatMessageDto {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  pending_action: PendingAction | null;
  executed: boolean;
  can_current_user_approve: boolean;
  action_status: 'pending' | 'executing' | 'executed' | 'cancelled' | 'unknown' | null;
  feedback: { category: FeedbackCategory; comment: string | null; status: string } | null;
  created_at: string | null;
}

interface PendingApproval {
  message_id: number;
  proposed_by_user_id: number;
  proposed_by_name: string | null;
  proposed_at: string | null;
  description: string | null;
  tool: string | null;
  policy_action: string | null;
  authority_scope: string;
}

type FeedbackCategory = 'helpful' | 'inaccurate' | 'unknown' | 'unsafe';

const SESSION_KEY = 'ai_chat_session_id';
const PERSONA_KEY = 'ai_chat_persona';

type PersonaKey = 'bookkeeper' | 'cfo' | 'accountant';

// Titles/descriptions mirror src/cfo/services/ai_chat_personas.py (title_he +
// the gist of each persona's prompt_addendum). Persona is a tone/foreground-
// tools axis only — never a permission gate (see that file's docstring).
const PERSONAS: { key: PersonaKey; title: string; description: string }[] = [
  {
    key: 'bookkeeper',
    title: 'מנהלת חשבונות',
    description: 'תפעולי: מסמכים חסרים, קליטת הוצאות ומוכנות דיווח מע"מ',
  },
  {
    key: 'cfo',
    title: 'מנהל כספים',
    description: 'תזרים מזומנים, גבייה והחלטות ניהוליות',
  },
  {
    key: 'accountant',
    title: 'רואה חשבון',
    description: 'מס, מע"מ ואימות דיווח לרשויות',
  },
];

function getSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = `sess-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function newSessionId(): string {
  return `sess-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function resolveSessionId(routeSessionId?: string): string {
  if (routeSessionId && /^[A-Za-z0-9_-]{1,64}$/.test(routeSessionId)) {
    localStorage.setItem(SESSION_KEY, routeSessionId);
    return routeSessionId;
  }
  return getSessionId();
}

function getStoredPersona(): PersonaKey {
  const stored = localStorage.getItem(PERSONA_KEY);
  if (stored === 'bookkeeper' || stored === 'cfo' || stored === 'accountant') return stored;
  return 'cfo';
}

function extractErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || 'משהו השתבש. נסה שוב.';
}

function actionHeading(message: ChatMessageDto): string {
  if (message.executed || message.action_status === 'executed') return 'הפעולה בוצעה';
  if (message.action_status === 'cancelled') return 'הפעולה בוטלה';
  if (message.action_status === 'executing') return 'הפעולה בביצוע';
  if (message.action_status === 'unknown') return 'תוצאת הפעולה דורשת אימות';
  return message.can_current_user_approve
    ? 'ממתין לאישור שלך'
    : 'ממתין למורשה חתימה נוסף בארגון';
}

function formatApprovalDate(value: string | null): string {
  if (!value) return 'מועד ההצעה לא זמין';
  return new Intl.DateTimeFormat('he-IL', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value));
}

const ChatAssistant: React.FC<{ darkMode: boolean; currentUser?: CurrentUser | null }> = ({ darkMode, currentUser }) => {
  const isOfficeManager = currentUser?.role === 'super_admin';
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState(() => resolveSessionId(routeSessionId));
  const [input, setInput] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [persona, setPersona] = useState<PersonaKey>(getStoredPersona);
  const [activeTab, setActiveTab] = useState<'chat' | 'approvals'>('chat');
  const [feedbackEditor, setFeedbackEditor] = useState<{ messageId: number; category: FeedbackCategory } | null>(null);
  const [feedbackComment, setFeedbackComment] = useState('');
  const queryClient = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (routeSessionId && /^[A-Za-z0-9_-]{1,64}$/.test(routeSessionId)) {
      localStorage.setItem(SESSION_KEY, routeSessionId);
      setSessionId(routeSessionId);
    }
  }, [routeSessionId]);

  const handlePersonaChange = (key: PersonaKey) => {
    setPersona(key);
    localStorage.setItem(PERSONA_KEY, key);
  };

  const { data } = useQuery<{ messages: ChatMessageDto[] }>({
    queryKey: ['ai-chat-history', sessionId],
    queryFn: () => apiService.get(`/ai/chat/${sessionId}`),
  });
  const messages = data?.messages || [];
  const {
    data: pendingApprovalsData,
    isLoading: pendingApprovalsLoading,
    error: pendingApprovalsError,
  } = useQuery<{ items: PendingApproval[] }>({
    queryKey: ['ai-chat-pending-approvals'],
    queryFn: () => apiService.get('/ai/chat/pending-approvals'),
  });
  const pendingApprovals = pendingApprovalsData?.items || [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  const sendMutation = useMutation({
    mutationFn: (text: string) =>
      apiService.post('/ai/chat', { session_id: sessionId, message: text, persona }),
    onSuccess: () => {
      setErrorMessage(null);
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    },
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
  });

  const confirmMutation = useMutation({
    mutationFn: (messageId: number) =>
      apiService.post('/ai/chat/confirm', { message_id: messageId }),
    onSuccess: () => setErrorMessage(null),
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
    // גם בכשל: השרת כבר עשוי היה לשמור action_status="unknown" (ניסיון
    // ביצוע שתוצאתו לא ודאה) לפני שהשגיאה חזרה — בלי רענון כאן הכרטיס
    // נשאר "ממתין לאישור" עם כפתור אשר חי, אף שהוא כבר לא רלוונטי.
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
      queryClient.invalidateQueries({ queryKey: ['ai-chat-pending-approvals'] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (messageId: number) =>
      apiService.post('/ai/chat/cancel', { message_id: messageId }),
    onSuccess: () => setErrorMessage(null),
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
      queryClient.invalidateQueries({ queryKey: ['ai-chat-pending-approvals'] });
    },
  });

  const feedbackMutation = useMutation({
    mutationFn: ({ messageId, category, comment }: { messageId: number; category: FeedbackCategory; comment?: string }) =>
      apiService.post(`/ai/chat/${messageId}/feedback`, { category, comment }),
    onSuccess: () => {
      setErrorMessage(null);
      setFeedbackEditor(null);
      setFeedbackComment('');
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    },
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
  });

  const handleSend = () => {
    const text = input.trim();
    if (!text || sendMutation.isPending) return;
    setInput('');
    sendMutation.mutate(text);
  };

  const handleNewConversation = () => {
    const id = newSessionId();
    localStorage.setItem(SESSION_KEY, id);
    setSessionId(id);
    navigate(`/agent/${id}`);
  };

  const cardClass = `rounded-2xl border ${
    darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
  }`;

  return (
    <div className={`p-6 h-full flex flex-col ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <div className="flex flex-wrap items-center gap-3 mb-1">
        <h1 className="text-3xl font-bold">מושקו — סוכן ה־CFO</h1>
        {isOfficeManager && (
          <span className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ${
            darkMode ? 'bg-purple-900/40 text-purple-200' : 'bg-purple-100 text-purple-700'
          }`}>
            <Building2 size={13} />
            מצב מנהל משרד
          </span>
        )}
        <button
          type="button"
          onClick={handleNewConversation}
          className={`mr-auto flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium ${
            darkMode ? 'border-gray-700 hover:bg-gray-800' : 'border-gray-200 bg-white hover:bg-gray-50'
          }`}
        >
          <Plus size={16} /> שיחה חדשה
        </button>
      </div>
      <p className={`text-sm mb-3 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
        שאל על מצב פיננסי, גיול חובות, תיקי גבייה ועוד. פעולות כתיבה (הפקת מסמך, רישום ניסיון גבייה)
        מוצגות לאישור מפורש לפני ביצוע.
        {isOfficeManager && ' במצב מנהל משרד יש לך גם כלים לצפייה בכל תיקי הלקוחות ורולאפ פיננסי חוצה-לקוחות.'}
      </p>

      <div className={`mb-3 flex flex-wrap items-center gap-3 text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
        <span dir="ltr">Session: {sessionId}</span>
        {isOfficeManager && (
          <>
            <Link to="/admin-moshko" className="flex items-center gap-1 text-violet-600 hover:underline">
              <Activity size={13} /> ניטור כל השיחות
            </Link>
            <Link to="/admin-moshko-knowledge" className="flex items-center gap-1 text-violet-600 hover:underline">
              <BookOpen size={13} /> ניהול הידע של מושקו
            </Link>
          </>
        )}
      </div>

      <div role="tablist" aria-label="מסכי מושקו" className="mb-4 flex gap-2 border-b border-gray-200">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'chat'}
          onClick={() => setActiveTab('chat')}
          className={`border-b-2 px-4 py-2 text-sm font-medium ${
            activeTab === 'chat'
              ? 'border-blue-600 text-blue-600'
              : `border-transparent ${darkMode ? 'text-gray-400' : 'text-gray-500'}`
          }`}
        >
          שיחה
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'approvals'}
          onClick={() => setActiveTab('approvals')}
          className={`flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium ${
            activeTab === 'approvals'
              ? 'border-amber-500 text-amber-600'
              : `border-transparent ${darkMode ? 'text-gray-400' : 'text-gray-500'}`
          }`}
        >
          ממתין לאישורי
          {pendingApprovals.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
              {pendingApprovals.length}
            </span>
          )}
        </button>
      </div>

      {activeTab === 'chat' && <><div className="flex flex-wrap items-center gap-2 mb-1">
        {PERSONAS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => handlePersonaChange(p.key)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              persona === p.key
                ? 'bg-blue-600 text-white'
                : darkMode
                ? 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {p.title}
          </button>
        ))}
      </div>
      <p className={`text-xs mb-4 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
        {PERSONAS.find((p) => p.key === persona)?.description}
      </p></>}

      {errorMessage && (
        <div className={`mb-4 px-4 py-2 rounded-lg text-sm ${
          darkMode ? 'bg-red-900/30 text-red-300' : 'bg-red-50 text-red-700'
        }`}>
          {errorMessage}
        </div>
      )}

      {activeTab === 'chat' ? <><div className={`${cardClass} flex-1 min-h-0 overflow-y-auto p-4 space-y-4 mb-4`}>
        {messages.length === 0 && (
          <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
            <Bot size={40} className="mx-auto mb-3 opacity-50" />
            <p>התחל שיחה עם העוזר</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
              m.role === 'user' ? 'bg-blue-500' : 'bg-gray-500'
            } text-white`}>
              {m.role === 'user' ? <UserIcon size={16} /> : <Bot size={16} />}
            </div>
            <div className={`max-w-[75%] rounded-xl px-4 py-2 ${
              m.role === 'user'
                ? 'bg-blue-500 text-white'
                : darkMode ? 'bg-gray-700' : 'bg-gray-100'
            }`}>
              <p className="whitespace-pre-wrap text-sm">{m.content}</p>
              {m.pending_action && (
                <div className={`mt-3 rounded-lg border p-3 text-xs ${
                  darkMode ? 'border-yellow-600 bg-yellow-900/20' : 'border-yellow-300 bg-yellow-50'
                }`}>
                  <div className="flex items-center gap-2 font-semibold text-yellow-600 mb-1">
                    <ShieldAlert size={14} />
                    {actionHeading(m)}
                  </div>
                  <p className="mb-2">{m.pending_action.description}</p>
                  <pre className="mb-2 overflow-x-auto rounded bg-black/5 p-2 text-[11px] dir-ltr text-left">
                    {JSON.stringify(m.pending_action.input, null, 2)}
                  </pre>
                  {m.executed || m.action_status === 'executed' ? (
                    <span className="text-green-600 font-medium">✓ בוצע</span>
                  ) : m.action_status === 'cancelled' ? (
                    <span className="text-gray-500 font-medium">בוטל</span>
                  ) : m.action_status === 'executing' ? (
                    <span className="text-blue-600 font-medium">בביצוע — לא יופעל שוב</span>
                  ) : m.action_status === 'unknown' ? (
                    <span className="text-red-600 font-medium">תוצאה לא ידועה — נדרש אימות ידני</span>
                  ) : (
                    <div className="flex gap-2">
                      {m.can_current_user_approve && (
                        <button
                          type="button"
                          onClick={() => confirmMutation.mutate(m.id)}
                          disabled={confirmMutation.isPending || cancelMutation.isPending}
                          className="px-3 py-1.5 rounded-lg bg-yellow-500 text-white text-xs font-semibold hover:bg-yellow-600 disabled:opacity-50"
                        >
                          {confirmMutation.isPending ? 'מבצע...' : 'אשר וביצוע'}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => cancelMutation.mutate(m.id)}
                        disabled={confirmMutation.isPending || cancelMutation.isPending}
                        className="px-3 py-1.5 rounded-lg border border-gray-400 text-xs font-semibold hover:bg-black/5 disabled:opacity-50"
                      >
                        {cancelMutation.isPending ? 'מבטל...' : 'ביטול'}
                      </button>
                    </div>
                  )}
                </div>
              )}
              {m.role === 'assistant' && (
                <div className={`mt-2 border-t pt-2 ${darkMode ? 'border-gray-600' : 'border-gray-200'}`}>
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className={darkMode ? 'text-gray-400' : 'text-gray-500'}>
                      {m.feedback ? `נשלח: ${m.feedback.category}` : 'התשובה עזרה?'}
                    </span>
                    <button type="button" title="מועיל" aria-label="סמן תשובה כמועילה" disabled={feedbackMutation.isPending}
                      onClick={() => feedbackMutation.mutate({ messageId: m.id, category: 'helpful' })}
                      className="rounded p-1 text-emerald-600 hover:bg-emerald-100 disabled:opacity-50"><ThumbsUp size={14} /></button>
                    <button type="button" title="לא מדויק" aria-label="דווח על תשובה לא מדויקת" disabled={feedbackMutation.isPending}
                      onClick={() => { setFeedbackEditor({ messageId: m.id, category: 'inaccurate' }); setFeedbackComment(m.feedback?.comment || ''); }}
                      className="rounded p-1 text-amber-600 hover:bg-amber-100 disabled:opacity-50"><ThumbsDown size={14} /></button>
                    <button type="button" title="מושקו לא ידע" aria-label="דווח שמושקו לא ידע" disabled={feedbackMutation.isPending}
                      onClick={() => { setFeedbackEditor({ messageId: m.id, category: 'unknown' }); setFeedbackComment(m.feedback?.comment || ''); }}
                      className="rounded p-1 text-blue-600 hover:bg-blue-100 disabled:opacity-50"><HelpCircle size={14} /></button>
                    <button type="button" title="תשובה לא בטוחה" aria-label="דווח על תשובה לא בטוחה" disabled={feedbackMutation.isPending}
                      onClick={() => { setFeedbackEditor({ messageId: m.id, category: 'unsafe' }); setFeedbackComment(m.feedback?.comment || ''); }}
                      className="rounded p-1 text-red-600 hover:bg-red-100 disabled:opacity-50"><AlertTriangle size={14} /></button>
                  </div>
                  {feedbackEditor?.messageId === m.id && (
                    <div className="mt-2 space-y-2">
                      <textarea value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)}
                        maxLength={2000} rows={2} placeholder="מה היה חסר או לא מדויק?"
                        className={`w-full rounded-lg border p-2 text-xs ${darkMode ? 'border-gray-600 bg-gray-800' : 'border-gray-300 bg-white'}`} />
                      <div className="flex gap-2">
                        <button type="button" disabled={feedbackMutation.isPending}
                          onClick={() => feedbackMutation.mutate({ messageId: m.id, category: feedbackEditor.category, comment: feedbackComment })}
                          className="rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50">שליחה לבדיקה</button>
                        <button type="button" onClick={() => { setFeedbackEditor(null); setFeedbackComment(''); }}
                          className="rounded border px-2.5 py-1 text-xs">ביטול</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {sendMutation.isPending && (
          <div className="flex gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-500 text-white">
              <Bot size={16} />
            </div>
            <div className={`rounded-xl px-4 py-2 ${darkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
              <Loader2 size={16} className="animate-spin" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSend(); }}
          placeholder="שאל משהו..."
          className={`flex-1 px-4 py-3 rounded-xl border ${
            darkMode ? 'bg-gray-800 border-gray-700' : 'border-gray-300'
          }`}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={sendMutation.isPending || !input.trim()}
          className="px-5 py-3 rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Send size={18} />
        </button>
      </div></> : (
        <section className={`${cardClass} flex-1 min-h-0 overflow-y-auto p-4`}>
          <div className="mb-4">
            <h2 className="text-lg font-semibold">פעולות שממתינות להחלטתך</h2>
            <p className={`mt-1 text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              מוצגות רק פעולות בלתי־הפיכות בארגון שעבורן יש לך סמכות חתימה פעילה ומתאימה.
            </p>
          </div>
          {pendingApprovalsLoading && (
            <div className={`flex items-center gap-2 py-8 text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              <Loader2 size={16} className="animate-spin" /> טוען אישורים…
            </div>
          )}
          {pendingApprovalsError && (
            <div className={`rounded-lg p-3 text-sm ${darkMode ? 'bg-red-900/30 text-red-300' : 'bg-red-50 text-red-700'}`}>
              {extractErrorMessage(pendingApprovalsError)}
            </div>
          )}
          {!pendingApprovalsLoading && !pendingApprovalsError && pendingApprovals.length === 0 && (
            <div className={`rounded-xl border border-dashed p-8 text-center text-sm ${darkMode ? 'border-gray-700 text-gray-400' : 'border-gray-300 text-gray-500'}`}>
              אין פעולות שממתינות לאישורך בארגון זה.
            </div>
          )}
          <div className="space-y-3">
            {pendingApprovals.map((approval) => (
              <article key={approval.message_id} className={`rounded-xl border p-4 ${darkMode ? 'border-gray-700 bg-gray-900/30' : 'border-gray-200 bg-gray-50'}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="font-semibold">
                      {approval.description || 'לא נשמר תיאור לפעולה זו'}
                    </h3>
                    <p className={`mt-1 text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                      הציע: {approval.proposed_by_name || `שם לא זמין (משתמש #${approval.proposed_by_user_id})`}
                      {' · '}{formatApprovalDate(approval.proposed_at)}
                    </p>
                  </div>
                  <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800">
                    {approval.authority_scope}
                  </span>
                </div>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => confirmMutation.mutate(approval.message_id)}
                    disabled={confirmMutation.isPending || cancelMutation.isPending}
                    className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50"
                  >
                    {confirmMutation.isPending ? 'מבצע…' : 'אישור וביצוע'}
                  </button>
                  <button
                    type="button"
                    onClick={() => cancelMutation.mutate(approval.message_id)}
                    disabled={confirmMutation.isPending || cancelMutation.isPending}
                    className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                  >
                    {cancelMutation.isPending ? 'דוחה…' : 'דחייה'}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

export default ChatAssistant;
