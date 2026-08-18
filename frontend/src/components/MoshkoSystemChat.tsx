/**
 * מושקו כצ'אט מערכת — נגיש מכל מסך, לא רק מעמוד ייעודי.
 *
 * הפער שתוקן (18/08/2026): `ChatAssistant` היה קיים כ-route בלבד
 * (`/ai-chat`), **ובלי שום קישור אליו בניווט**. כלומר מנהל החשבונות של
 * המערכת היה נגיש רק למי שמקליד את הכתובת ידנית.
 *
 * הרכיב הזה נטען ב-App **מחוץ ל-`<Routes>`**, ולכן הוא חי בכל עמוד
 * ושומר על השיחה בזמן ניווט.
 *
 * honest-null: כשה-AI אינו מוגדר (למשל `ANTHROPIC_API_KEY` ריק), מוצגת
 * שגיאת השרת **כלשונה**. לא הודעה גנרית ולא תשובה מומצאת — משתמש שרואה
 * "משהו השתבש" מנחש; משתמש שרואה "ANTHROPIC_API_KEY חסר" יודע מה לתקן.
 */
import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Bot, Send, X, Loader2, Maximize2, AlertTriangle } from 'lucide-react';
import apiService from '../services/api';

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  error?: boolean;
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

const MoshkoSystemChat: React.FC<Props> = ({ darkMode = false }) => {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const sessionId = useSessionId();
  const queryClient = useQueryClient();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, open]);

  const send = useMutation({
    mutationFn: (message: string) =>
      apiService.post('/ai/chat', { session_id: sessionId, message }),
    onSuccess: (data: any) => {
      const reply =
        data?.reply ?? data?.content ?? data?.message ?? '';
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: reply || 'לא התקבלה תשובה.' },
      ]);
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    },
    onError: (err: any) => {
      // honest-null: מציגים את מה שהשרת אמר, לא ניסוח מרוכך.
      const detail =
        err?.response?.data?.detail ??
        err?.message ??
        'הבקשה נכשלה ללא פירוט מהשרת.';
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: String(detail), error: true },
      ]);
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || send.isPending) return;
    setMessages((prev) => [...prev, { role: 'user', content: trimmed }]);
    setText('');
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
      className={`fixed bottom-6 left-6 z-50 flex h-[32rem] w-[24rem] max-w-[calc(100vw-3rem)] flex-col rounded-xl border shadow-2xl ${panelBg}`}
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

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <p className={`text-sm leading-relaxed ${textDim}`}>
            שאל על מאזן בוחן, רווח והפסד, התאמות, מנות או תיוק הוצאות.
            מושקו קורא את הנתונים של רצף — לא מבצע קריאות לספקים.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-right'}>
            <div
              className={`inline-block max-w-[90%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : m.error
                  ? 'bg-amber-50 text-amber-900 ring-1 ring-amber-300'
                  : darkMode
                  ? 'bg-gray-700 text-gray-100'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              {m.error && (
                <AlertTriangle size={14} className="ml-1 inline align-text-top" />
              )}
              {m.content}
            </div>
          </div>
        ))}
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
