/**
 * AI chat assistant (Wave 2 item 9.4). Every write action the assistant
 * proposes (issue_document, log_collection_attempt) shows as a pending
 * card requiring an explicit click to confirm — the backend never
 * executes it from the model's call alone (see ai_chat_service.py).
 */
import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send, ShieldAlert, Loader2, Bot, User as UserIcon, Building2 } from 'lucide-react';
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
  created_at: string | null;
}

const SESSION_KEY = 'ai_chat_session_id';

function getSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = `sess-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function extractErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || 'משהו השתבש. נסה שוב.';
}

const ChatAssistant: React.FC<{ darkMode: boolean; currentUser?: CurrentUser | null }> = ({ darkMode, currentUser }) => {
  const isOfficeManager = currentUser?.role === 'super_admin';
  const [sessionId] = useState(getSessionId);
  const [input, setInput] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery<{ messages: ChatMessageDto[] }>({
    queryKey: ['ai-chat-history', sessionId],
    queryFn: () => apiService.get(`/ai/chat/${sessionId}`),
  });
  const messages = data?.messages || [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  const sendMutation = useMutation({
    mutationFn: (text: string) =>
      apiService.post('/ai/chat', { session_id: sessionId, message: text }),
    onSuccess: () => {
      setErrorMessage(null);
      queryClient.invalidateQueries({ queryKey: ['ai-chat-history', sessionId] });
    },
    onError: (err) => setErrorMessage(extractErrorMessage(err)),
  });

  const confirmMutation = useMutation({
    mutationFn: (messageId: number) =>
      apiService.post('/ai/chat/confirm', { message_id: messageId }),
    onSuccess: () => {
      setErrorMessage(null);
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

  const cardClass = `rounded-2xl border ${
    darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
  }`;

  return (
    <div className={`p-6 h-full flex flex-col ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <div className="flex items-center gap-3 mb-1">
        <h1 className="text-3xl font-bold">עוזר CFO — AI</h1>
        {isOfficeManager && (
          <span className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ${
            darkMode ? 'bg-purple-900/40 text-purple-200' : 'bg-purple-100 text-purple-700'
          }`}>
            <Building2 size={13} />
            מצב מנהל משרד
          </span>
        )}
      </div>
      <p className={`text-sm mb-4 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
        שאל על מצב פיננסי, גיול חובות, תיקי גבייה ועוד. פעולות כתיבה (הפקת מסמך, רישום ניסיון גבייה)
        מוצגות לאישור מפורש לפני ביצוע.
        {isOfficeManager && ' במצב מנהל משרד יש לך גם כלים לצפייה בכל תיקי הלקוחות ורולאפ פיננסי חוצה-לקוחות.'}
      </p>

      {errorMessage && (
        <div className={`mb-4 px-4 py-2 rounded-lg text-sm ${
          darkMode ? 'bg-red-900/30 text-red-300' : 'bg-red-50 text-red-700'
        }`}>
          {errorMessage}
        </div>
      )}

      <div className={`${cardClass} flex-1 min-h-0 overflow-y-auto p-4 space-y-4 mb-4`}>
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
                    ממתין לאישור שלך
                  </div>
                  <p className="mb-2">{m.pending_action.description}</p>
                  <pre className="mb-2 overflow-x-auto rounded bg-black/5 p-2 text-[11px] dir-ltr text-left">
                    {JSON.stringify(m.pending_action.input, null, 2)}
                  </pre>
                  {m.executed ? (
                    <span className="text-green-600 font-medium">✓ בוצע</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => confirmMutation.mutate(m.id)}
                      disabled={confirmMutation.isPending}
                      className="px-3 py-1.5 rounded-lg bg-yellow-500 text-white text-xs font-semibold hover:bg-yellow-600 disabled:opacity-50"
                    >
                      {confirmMutation.isPending ? 'מבצע...' : 'אשר וביצוע'}
                    </button>
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
      </div>
    </div>
  );
};

export default ChatAssistant;
