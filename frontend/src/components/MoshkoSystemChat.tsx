/**
 * מושקו כצ'אט מערכת — נגיש מכל מסך, לא רק מעמוד ייעודי.
 *
 * **תיקון לנימוק המקורי (18/08/2026).** בקומיט הראשון נכתב כאן
 * ש-`/ai-chat` היה "בלי שום קישור בניווט". **זה היה שגוי** — הוא מופיע
 * ב-`navigationConfig` שב-App.tsx. הטעות נבעה מ-grep שחיפש `to="/..."`
 * בזמן שהניווט משתמש ב-`to: '/...'`.
 *
 * הערך האמיתי של הרכיב הזה שונה: הצ'אט זמין **בלי לעזוב את המסך
 * הנוכחי**. מנהל חשבונות שבודק התאמות לא צריך לנווט משם כדי לשאול —
 * וזה בדיוק הרגע שבו הוא ישאל.
 *
 * הרכיב הזה נטען ב-App **מחוץ ל-`<Routes>`**, ולכן הוא חי בכל עמוד
 * ושומר על השיחה בזמן ניווט.
 *
 * **21/08/2026 — מבוי סתום, לא עוד (משימה 1 מתוכנית השימושיות).**
 * הרכיב הזה היה מבוי סתום בשלוש דרכים, ותוקן כאן על-ידי אימוץ אותם
 * הדפוסים בדיוק כמו `ChatAssistant.tsx` (הצ'אט במסך מלא) — לא המצאת
 * מסלול מקביל:
 *  1. פעולת כתיבה שמושקו מציע (`pending_action`) לא הוצגה בכלל — השרת
 *     אמר "לאשר?" בלי שום כפתור. עכשיו יש כרטיס אישור/דחייה שקורא
 *     ל-`POST /ai/chat/confirm` / `/cancel`, כולל חמשת מצבי
 *     `action_status` (כולל `unknown`).
 *  2. ההודעות חיו רק ב-`useState` מקומי — רענון דף מחק את מה שנראה על
 *     המסך אף שהשיחה נשמרת ב-DB תחת ה-session. עכשיו ה-state היחיד הוא
 *     React Query על `['ai-chat-history', sessionId]` (אותו מפתח בדיוק
 *     ש-`invalidateQueries` כבר קרא לו, כך שהוא הפסיק להיות no-op),
 *     מול `GET /ai/chat/{session_id}` — endpoint קיים, מסונן org+user+
 *     session (ר' `ai_chat.py::get_chat_history`).
 *  3. אין בורר פרסונה — תמיד persona ברירת המחדל בשרת. עכשיו יש אותן 3
 *     הפרסונות, עם אותו מפתח `localStorage` (`ai_chat_persona`) כמו
 *     ב-`ChatAssistant`, כך שהבחירה משותפת בין הצ'אט הצף למסך המלא.
 *
 * honest-null: כשה-AI אינו מוגדר (למשל `ANTHROPIC_API_KEY` ריק), מוצגת
 * שגיאת השרת **כלשונה** בבאנר — לא הודעה גנרית ולא תשובה מומצאת.
 */
import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Bot,
  Send,
  X,
  Loader2,
  Maximize2,
  AlertTriangle,
  ShieldAlert,
} from 'lucide-react';
import apiService from '../services/api';

interface PendingAction {
  tool: string;
  input: Record<string, unknown>;
  description: string;
}

type FeedbackCategory = 'helpful' | 'inaccurate' | 'unknown' | 'unsafe';

interface ChatMessageDto {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  pending_action: PendingAction | null;
  executed: boolean;
  action_status: 'pending' | 'executing' | 'executed' | 'cancelled' | 'unknown' | null;
  feedback: { category: FeedbackCategory; comment: string | null; status: string } | null;
  created_at: string | null;
}

interface Props {
  darkMode?: boolean;
}

/** מזהה שיחה יציב לכל טאב — כדי שניווט בין עמודים לא יפתח שיחה חדשה. */
function useSessionId(): string {
  const [id] = useState(() => {
    const existing = sessionStorage.getItem('moshko-system-session');
    if (existing) return existing;
    const fresh = `sys-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    sessionStorage.setItem('moshko-system-session', fresh);
    return fresh;
  });
  return id;
}

// אותו מפתח בדיוק כמו ChatAssistant.tsx — כך שבחירת פרסונה משותפת בין
// הצ'אט הצף למסך המלא, ולא שני מקורות-אמת נפרדים.
const PERSONA_KEY = 'ai_chat_persona';

type PersonaKey = 'bookkeeper' | 'cfo' | 'accountant';

// כותרות/תיאורים תואמים ל-src/cfo/services/ai_chat_personas.py ולאותה
// רשימה ב-ChatAssistant.tsx — פרסונה היא ציר טון/כלים-מוצעים בלבד,
// לעולם לא שער הרשאות (ר' ה-docstring שם).
const PERSONAS: { key: PersonaKey; title: string }[] = [
  { key: 'bookkeeper', title: 'מנהלת חשבונות' },
  { key: 'cfo', title: 'מנהל כספים' },
  { key: 'accountant', title: 'רואה חשבון' },
];

function getStoredPersona(): PersonaKey {
  const stored = localStorage.getItem(PERSONA_KEY);
  if (stored === 'bookkeeper' || stored === 'cfo' || stored === 'accountant') return stored;
  return 'cfo';
}

function extractErrorMessage(err: unknown): string {
  // honest-null: מציגים את מה שהשרת אמר, לא ניסוח מרוכך.
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  const message = (err as { message?: string })?.message;
  return detail || message || 'הבקשה נכשלה ללא פירוט מהשרת.';
}

const MoshkoSystemChat: React.FC<Props> = ({ darkMode = false }) => {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  // הד אופטימי: הטקסט שנשלח אך עדיין לא חזר מה-DB דרך היסטוריית ה-session
  // (סבב ה-LLM לוקח כמה שניות) — בלעדיו ההודעה של המשתמש עצמו נעלמת עד
  // שהתשובה מוכנה, ורק "חושב…" מוצג. מנוקה כש-send מסתיים (הצלחה או כשל).
  const [pendingEcho, setPendingEcho] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [persona, setPersona] = useState<PersonaKey>(getStoredPersona);
  // טיוטת הערה פתוחה (אחרי 👎/❓) — הודעה אחת בכל רגע.
  const [feedbackDraft, setFeedbackDraft] = useState<
    { messageId: number; category: 'inaccurate' | 'unknown'; comment: string } | null
  >(null);
  const [feedbackBusyId, setFeedbackBusyId] = useState<number | null>(null);
  const [feedbackErrors, setFeedbackErrors] = useState<Record<number, string>>({});
  const sessionId = useSessionId();
  const queryClient = useQueryClient();
  const endRef = useRef<HTMLDivElement>(null);

  const { data, isLoading: historyLoading } = useQuery<{ messages: ChatMessageDto[] }>({
    queryKey: ['ai-chat-history', sessionId],
    queryFn: () => apiService.get(`/ai/chat/${sessionId}`),
    // נטען "בפתיחה" — אין טעם לקרוא היסטוריה לפני שהמשתמש פתח את הפאנל.
    enabled: open,
  });
  const messages = data?.messages || [];

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, open, pendingEcho]);

  const handlePersonaChange = (key: PersonaKey) => {
    setPersona(key);
    localStorage.setItem(PERSONA_KEY, key);
  };

  const send = useMutation({
    mutationFn: (message: string) =>
      apiService.post('/ai/chat', { session_id: sessionId, message, persona }),
    onSuccess: () => {
      setErrorMessage(null);
      setPendingEcho(null);
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    },
    onError: (err) => {
      setPendingEcho(null);
      setErrorMessage(extractErrorMessage(err));
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (messageId: number) =>
      apiService.post('/ai/chat/confirm', { message_id: messageId }),
    onSuccess: () => setErrorMessage(null),
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
    // גם בכשל: השרת כבר עשוי היה לשמור action_status="unknown" (ניסיון
    // ביצוע שתוצאתו לא ודאה) לפני שהשגיאה חזרה — בלי רענון כאן הכרטיס
    // נשאר "ממתין לאישור" עם כפתור אשר חי, אף שהוא כבר לא רלוונטי.
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] }),
  });

  const cancelMutation = useMutation({
    mutationFn: (messageId: number) =>
      apiService.post('/ai/chat/cancel', { message_id: messageId }),
    onSuccess: () => {
      setErrorMessage(null);
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    },
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
  });

  const sendFeedback = async (
    messageId: number,
    category: FeedbackCategory,
    comment?: string,
  ) => {
    setFeedbackBusyId(messageId);
    setFeedbackErrors((prev) => {
      const next = { ...prev };
      delete next[messageId];
      return next;
    });
    try {
      await apiService.post(`/ai/chat/${messageId}/feedback`, {
        category,
        comment: comment?.trim() || null,
      });
      setFeedbackDraft((current) =>
        current?.messageId === messageId ? null : current,
      );
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    } catch (err) {
      // honest-null: מציגים את שגיאת השרת כלשונה.
      setFeedbackErrors((prev) => ({ ...prev, [messageId]: extractErrorMessage(err) }));
    } finally {
      setFeedbackBusyId(null);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || send.isPending) return;
    setText('');
    setPendingEcho(trimmed);
    send.mutate(trimmed);
  };

  const panelBg = darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200';
  const textMain = darkMode ? 'text-gray-100' : 'text-gray-900';
  const textDim = darkMode ? 'text-gray-400' : 'text-gray-500';

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        aria-label="פתיחת מושקו — מנהל החשבונות"
        title="מושקו — מנהל החשבונות"
        className="fixed bottom-6 left-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400"
      >
        <Bot size={24} />
      </button>
    );
  }

  return (
    <div
      dir="rtl"
      className={`fixed bottom-6 left-6 z-50 flex h-[34rem] w-[24rem] max-w-[calc(100vw-3rem)] flex-col rounded-xl border shadow-2xl ${panelBg}`}
    >
      <header className={`flex items-center justify-between border-b px-4 py-3 ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <div className="flex items-center gap-2">
          <Bot size={18} className="text-blue-600" />
          <span className={`text-sm font-semibold ${textMain}`}>מושקו</span>
          <span className={`text-xs ${textDim}`}>מנהל החשבונות</span>
        </div>
        <div className="flex items-center gap-1">
          <Link
            to="/ai-chat"
            title="פתיחה במסך מלא"
            className={`rounded p-1.5 transition hover:bg-gray-100 ${darkMode ? 'hover:bg-gray-700' : ''}`}
          >
            <Maximize2 size={15} className={textDim} />
          </Link>
          <button
            onClick={() => setOpen(false)}
            aria-label="סגירה"
            className={`rounded p-1.5 transition hover:bg-gray-100 ${darkMode ? 'hover:bg-gray-700' : ''}`}
          >
            <X size={16} className={textDim} />
          </button>
        </div>
      </header>

      <div className={`flex flex-wrap items-center gap-1 border-b px-3 py-2 ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        {PERSONAS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => handlePersonaChange(p.key)}
            className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
              persona === p.key
                ? 'bg-blue-600 text-white'
                : darkMode
                ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {p.title}
          </button>
        ))}
      </div>

      {errorMessage && (
        <div className={`mx-3 mt-2 rounded-lg px-3 py-2 text-xs ${darkMode ? 'bg-red-900/30 text-red-300' : 'bg-red-50 text-red-700'}`}>
          <AlertTriangle size={12} className="ml-1 inline align-text-top" />
          {errorMessage}
        </div>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {historyLoading && (
          <div className={`flex items-center gap-2 text-sm ${textDim}`}>
            <Loader2 size={14} className="animate-spin" />
            טוען היסטוריה…
          </div>
        )}
        {!historyLoading && messages.length === 0 && (
          <p className={`text-sm leading-relaxed ${textDim}`}>
            שאל על מאזן בוחן, רווח והפסד, התאמות, מנות או תיוק הוצאות.
            מושקו קורא את הנתונים של רצף — לא מבצע קריאות לספקים.
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className="text-right">
            <div
              className={`inline-block max-w-[90%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : darkMode
                  ? 'bg-gray-700 text-gray-100'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              {m.content}
            </div>

            {m.pending_action && (
              <div
                className={`mt-2 inline-block w-full max-w-[90%] rounded-lg border p-3 text-right text-xs ${
                  darkMode ? 'border-yellow-600 bg-yellow-900/20' : 'border-yellow-300 bg-yellow-50'
                }`}
              >
                <div className="mb-1 flex items-center gap-2 font-semibold text-yellow-600">
                  <ShieldAlert size={14} />
                  ממתין לאישור שלך
                </div>
                <p className="mb-2">{m.pending_action.description}</p>
                <pre dir="ltr" className="mb-2 overflow-x-auto rounded bg-black/5 p-2 text-left text-[11px]">
                  {JSON.stringify(m.pending_action.input, null, 2)}
                </pre>
                {m.executed || m.action_status === 'executed' ? (
                  <span className="font-medium text-green-600">✓ בוצע</span>
                ) : m.action_status === 'cancelled' ? (
                  <span className={`font-medium ${textDim}`}>בוטל</span>
                ) : m.action_status === 'executing' ? (
                  <span className="font-medium text-blue-600">בביצוע — לא יופעל שוב</span>
                ) : m.action_status === 'unknown' ? (
                  <span className="font-medium text-red-600">תוצאה לא ידועה — נדרש אימות ידני</span>
                ) : (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => confirmMutation.mutate(m.id)}
                      disabled={confirmMutation.isPending || cancelMutation.isPending}
                      className="rounded-lg bg-yellow-500 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-yellow-600 disabled:opacity-50"
                    >
                      {confirmMutation.isPending ? 'מבצע...' : 'אשר וביצוע'}
                    </button>
                    <button
                      type="button"
                      onClick={() => cancelMutation.mutate(m.id)}
                      disabled={confirmMutation.isPending || cancelMutation.isPending}
                      className="rounded-lg border border-gray-400 px-3 py-1.5 text-xs font-semibold transition hover:bg-black/5 disabled:opacity-50"
                    >
                      {cancelMutation.isPending ? 'מבטל...' : 'ביטול'}
                    </button>
                  </div>
                )}
              </div>
            )}

            {m.role === 'assistant' && (
              <div className="mt-1 space-y-1">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    title="תשובה מועילה"
                    aria-label="תשובה מועילה"
                    disabled={feedbackBusyId === m.id}
                    onClick={() => void sendFeedback(m.id, 'helpful')}
                    className={`rounded px-1.5 py-0.5 text-xs transition disabled:opacity-40 ${
                      m.feedback?.category === 'helpful'
                        ? 'bg-emerald-100 ring-1 ring-emerald-400'
                        : darkMode
                        ? 'hover:bg-gray-700'
                        : 'hover:bg-gray-100'
                    }`}
                  >
                    👍
                  </button>
                  <button
                    type="button"
                    title="תשובה לא מדויקת"
                    aria-label="תשובה לא מדויקת"
                    disabled={feedbackBusyId === m.id}
                    onClick={() =>
                      setFeedbackDraft({ messageId: m.id, category: 'inaccurate', comment: '' })
                    }
                    className={`rounded px-1.5 py-0.5 text-xs transition disabled:opacity-40 ${
                      m.feedback?.category === 'inaccurate'
                        ? 'bg-red-100 ring-1 ring-red-400'
                        : darkMode
                        ? 'hover:bg-gray-700'
                        : 'hover:bg-gray-100'
                    }`}
                  >
                    👎
                  </button>
                  <button
                    type="button"
                    title="מושקו לא ידע לענות"
                    disabled={feedbackBusyId === m.id}
                    onClick={() =>
                      setFeedbackDraft({ messageId: m.id, category: 'unknown', comment: '' })
                    }
                    className={`rounded px-1.5 py-0.5 text-xs transition disabled:opacity-40 ${
                      m.feedback?.category === 'unknown'
                        ? 'bg-amber-100 ring-1 ring-amber-400'
                        : darkMode
                        ? 'hover:bg-gray-700'
                        : 'hover:bg-gray-100'
                    } ${textDim}`}
                  >
                    ❓ לא ידע
                  </button>
                  {feedbackBusyId === m.id && (
                    <Loader2 size={12} className={`animate-spin ${textDim}`} />
                  )}
                </div>
                {feedbackDraft?.messageId === m.id && (
                  <div className="flex items-center gap-1">
                    <input
                      value={feedbackDraft.comment}
                      onChange={(e) =>
                        setFeedbackDraft({ ...feedbackDraft, comment: e.target.value })
                      }
                      placeholder="הערה (אופציונלי)…"
                      aria-label="הערה לפידבק"
                      className={`flex-1 rounded border px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                        darkMode
                          ? 'border-gray-600 bg-gray-900 text-gray-100 placeholder-gray-500'
                          : 'border-gray-300 bg-white text-gray-900 placeholder-gray-400'
                      }`}
                    />
                    <button
                      type="button"
                      disabled={feedbackBusyId === m.id}
                      onClick={() =>
                        void sendFeedback(feedbackDraft.messageId, feedbackDraft.category, feedbackDraft.comment)
                      }
                      className="rounded bg-blue-600 px-2 py-1 text-xs text-white transition hover:bg-blue-700 disabled:opacity-40"
                    >
                      שלח
                    </button>
                  </div>
                )}
                {feedbackErrors[m.id] && (
                  <p className="text-xs text-amber-700">{feedbackErrors[m.id]}</p>
                )}
              </div>
            )}
          </div>
        ))}
        {pendingEcho && (
          <div className="text-right">
            <div className="inline-block max-w-[90%] whitespace-pre-wrap rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">
              {pendingEcho}
            </div>
          </div>
        )}
        {send.isPending && (
          <div className={`flex items-center gap-2 text-sm ${textDim}`}>
            <Loader2 size={14} className="animate-spin" />
            חושב…
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={submit}
        className={`flex items-center gap-2 border-t px-3 py-2 ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="שאלה למושקו…"
          aria-label="הודעה למושקו"
          className={`flex-1 rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
            darkMode
              ? 'border-gray-600 bg-gray-900 text-gray-100 placeholder-gray-500'
              : 'border-gray-300 bg-white text-gray-900 placeholder-gray-400'
          }`}
        />
        <button
          type="submit"
          disabled={!text.trim() || send.isPending}
          aria-label="שליחה"
          className="rounded-lg bg-blue-600 p-2 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
};

export default MoshkoSystemChat;
