import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Edit3,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import api from '../services/api';
import type { CurrentUser } from './OrgSwitcher';

type MemoryCategory = 'preference' | 'business_fact' | 'correction' | 'convention';

interface MemoryRow {
  id: number;
  organization_id: number;
  user_id: number | null;
  scope: 'org' | 'user';
  content: string;
  category: MemoryCategory;
  source: 'conversation' | 'admin' | 'inferred';
  approved_at: string | null;
  approved_by: number | null;
  updated_at: string | null;
}

interface MemoryPage {
  items: MemoryRow[];
  total: number;
}

interface KnowledgeTopicSummary {
  id: string;
  source: 'rezef_kb' | 'bookkeeper_kb';
  title: string;
  summary: string;
}

interface KnowledgeIndex {
  available: boolean;
  topics: KnowledgeTopicSummary[];
  document_knowledge: {
    available: boolean;
    topics: KnowledgeTopicSummary[] | null;
    reason: string | null;
  };
}

interface KnowledgeTopic {
  available: boolean;
  id: string;
  title?: string;
  format?: 'markdown';
  content: string | null;
  reason?: string;
}

const categoryLabels: Record<MemoryCategory, string> = {
  preference: 'העדפה',
  business_fact: 'עובדה עסקית',
  correction: 'תיקון',
  convention: 'מוסכמה',
};

const sourceLabels: Record<string, string> = {
  conversation: 'שיחה',
  admin: 'אדמין',
  inferred: 'הסקת מודל',
};

function formatDate(value: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('he-IL', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value));
}

function MarkdownView({ content }: { content: string }) {
  return (
    <div className="space-y-2 leading-7 text-slate-800">
      {content.split('\n').map((line, index) => {
        const key = `${index}:${line.slice(0, 24)}`;
        if (line.startsWith('#### ')) return <h4 key={key} className="pt-3 text-base font-bold">{line.slice(5)}</h4>;
        if (line.startsWith('### ')) return <h3 key={key} className="pt-4 text-lg font-bold">{line.slice(4)}</h3>;
        if (line.startsWith('## ')) return <h2 key={key} className="pt-5 text-xl font-bold">{line.slice(3)}</h2>;
        if (line.startsWith('# ')) return <h1 key={key} className="pt-4 text-2xl font-bold">{line.slice(2)}</h1>;
        if (/^[-*] /.test(line)) return <div key={key} className="flex gap-2 pr-3"><span>•</span><span>{line.slice(2)}</span></div>;
        if (/^\d+\. /.test(line)) return <div key={key} className="pr-3">{line}</div>;
        if (line.startsWith('```')) return <div key={key} className="font-mono text-xs text-slate-400">{line}</div>;
        if (!line.trim()) return <div key={key} className="h-2" />;
        return <p key={key} className="whitespace-pre-wrap">{line}</p>;
      })}
    </div>
  );
}

export default function MoshkoKnowledgeDashboard({
  currentUser,
}: {
  currentUser: CurrentUser | null;
}) {
  const [tab, setTab] = useState<'memory' | 'knowledge'>('memory');
  const [memory, setMemory] = useState<MemoryPage | null>(null);
  const [knowledge, setKnowledge] = useState<KnowledgeIndex | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<KnowledgeTopic | null>(null);
  const [loading, setLoading] = useState(true);
  const [topicLoading, setTopicLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [organizationId, setOrganizationId] = useState('');
  const [userId, setUserId] = useState('');
  const [category, setCategory] = useState('');
  const [source, setSource] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editCategory, setEditCategory] = useState<MemoryCategory>('business_fact');
  const [newContent, setNewContent] = useState('');
  const [newCategory, setNewCategory] = useState<MemoryCategory>('business_fact');
  const [newUserId, setNewUserId] = useState('');
  const [saving, setSaving] = useState(false);

  const isAuthorized = currentUser?.role === 'admin' || currentUser?.role === 'super_admin';
  const isSuper = currentUser?.role === 'super_admin';

  const memoryParams = useMemo(() => {
    const params: Record<string, string | number> = { limit: 200 };
    if (organizationId) params.organization_id = Number(organizationId);
    if (userId) params.user_id = Number(userId);
    if (category) params.category = category;
    if (source) params.source = source;
    return params;
  }, [category, organizationId, source, userId]);

  const load = useCallback(async () => {
    if (!isAuthorized) return;
    setLoading(true);
    setError(null);
    try {
      const [memoryResponse, knowledgeResponse] = await Promise.all([
        api.get<MemoryPage>('/admin/moshko/memory', { params: memoryParams }),
        api.get<KnowledgeIndex>('/admin/moshko/knowledge'),
      ]);
      setMemory(memoryResponse);
      setKnowledge(knowledgeResponse);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'טעינת הידע של מושקו נכשלה');
    } finally {
      setLoading(false);
    }
  }, [isAuthorized, memoryParams]);

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = (row: MemoryRow) => {
    setEditingId(row.id);
    setEditContent(row.content);
    setEditCategory(row.category);
  };

  const saveEdit = async (row: MemoryRow) => {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/admin/moshko/memory/${row.id}`, {
        content: editContent,
        category: editCategory,
      });
      setEditingId(null);
      await load();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'שמירת הזיכרון נכשלה');
    } finally {
      setSaving(false);
    }
  };

  const toggleApproval = async (row: MemoryRow) => {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/admin/moshko/memory/${row.id}`, { approved: row.approved_at === null });
      await load();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'עדכון האישור נכשל');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row: MemoryRow) => {
    if (!window.confirm(`למחוק את הזיכרון “${row.content}”? הפעולה תתועד ביומן הביקורת.`)) return;
    setSaving(true);
    setError(null);
    try {
      await api.delete(`/admin/moshko/memory/${row.id}`);
      await load();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'מחיקת הזיכרון נכשלה');
    } finally {
      setSaving(false);
    }
  };

  const createMemory = async () => {
    const targetOrg = isSuper ? Number(organizationId) : currentUser?.organization_id;
    if (!targetOrg) {
      setError('יש לבחור ארגון לפני יצירת זיכרון');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post('/admin/moshko/memory', {
        organization_id: targetOrg,
        user_id: newUserId ? Number(newUserId) : null,
        content: newContent,
        category: newCategory,
      });
      setNewContent('');
      setNewUserId('');
      await load();
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'יצירת הזיכרון נכשלה');
    } finally {
      setSaving(false);
    }
  };

  const openTopic = async (topic: KnowledgeTopicSummary) => {
    setTopicLoading(true);
    setError(null);
    try {
      setSelectedTopic(await api.get<KnowledgeTopic>(
        `/admin/moshko/knowledge/${encodeURIComponent(topic.id)}`,
      ));
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'טעינת נושא הידע נכשלה');
    } finally {
      setTopicLoading(false);
    }
  };

  if (currentUser === null) {
    return <div dir="rtl" className="p-8 text-slate-500">טוען הרשאות…</div>;
  }
  if (!isAuthorized) {
    return (
      <div dir="rtl" className="m-8 rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">
        המסך זמין למנהל ארגון או למנהל־על בלבד.
      </div>
    );
  }

  return (
    <div dir="rtl" className="min-h-full bg-slate-50 p-6 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold"><BookOpen className="text-violet-600" /> הידע של מושקו</h1>
            <p className="mt-1 text-sm text-slate-500">ניהול זיכרון לומד וצפייה במרכז הידע המקצועי</p>
          </div>
          <button onClick={() => void load()} className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2 text-sm hover:bg-slate-100">
            <RefreshCw size={16} /> רענון
          </button>
        </header>

        <div className="flex gap-2 rounded-xl border bg-white p-2 shadow-sm">
          <button onClick={() => setTab('memory')} className={`rounded-lg px-4 py-2 text-sm font-medium ${tab === 'memory' ? 'bg-violet-600 text-white' : 'hover:bg-slate-100'}`}>זיכרון לומד</button>
          <button onClick={() => setTab('knowledge')} className={`rounded-lg px-4 py-2 text-sm font-medium ${tab === 'knowledge' ? 'bg-violet-600 text-white' : 'hover:bg-slate-100'}`}>ידע מקצועי</button>
        </div>

        {error ? <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><AlertCircle size={18} />{error}</div> : null}
        {loading ? (
          <div className="flex items-center justify-center gap-3 rounded-xl border bg-white p-16 text-slate-500"><Loader2 className="animate-spin" /> טוען…</div>
        ) : tab === 'memory' ? (
          <>
            <section className="grid gap-3 rounded-xl border bg-white p-4 shadow-sm md:grid-cols-4">
              {isSuper ? <input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} inputMode="numeric" placeholder="מזהה ארגון" className="rounded-lg border px-3 py-2" /> : null}
              <input value={userId} onChange={(event) => setUserId(event.target.value)} inputMode="numeric" placeholder="סינון משתמש" className="rounded-lg border px-3 py-2" />
              <select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border px-3 py-2">
                <option value="">כל הקטגוריות</option>
                {Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              <select value={source} onChange={(event) => setSource(event.target.value)} className="rounded-lg border px-3 py-2">
                <option value="">כל המקורות</option><option value="conversation">שיחה</option><option value="admin">אדמין</option><option value="inferred">הסקת מודל</option>
              </select>
            </section>

            <section className="rounded-xl border bg-white p-4 shadow-sm">
              <h2 className="mb-3 flex items-center gap-2 font-semibold"><Plus size={18} /> זיכרון ידני חדש</h2>
              <div className="grid gap-3 md:grid-cols-[1fr_180px_160px_auto]">
                <input value={newContent} onChange={(event) => setNewContent(event.target.value)} placeholder="עובדה, העדפה, תיקון או מוסכמה" className="rounded-lg border px-3 py-2" />
                <select value={newCategory} onChange={(event) => setNewCategory(event.target.value as MemoryCategory)} className="rounded-lg border px-3 py-2">
                  {Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
                <input value={newUserId} onChange={(event) => setNewUserId(event.target.value)} inputMode="numeric" placeholder="משתמש אישי (ריק=עסק)" className="rounded-lg border px-3 py-2" />
                <button disabled={saving || !newContent.trim()} onClick={() => void createMemory()} className="rounded-lg bg-violet-600 px-4 py-2 text-white disabled:opacity-50">יצירה ואישור</button>
              </div>
            </section>

            <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
              <div className="flex items-center justify-between border-b p-4"><h2 className="font-semibold">זיכרונות ({memory?.total ?? 0})</h2><span className="text-xs text-slate-500">זיכרון אישי גלוי רק לבעליו או למנהל־על</span></div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600"><tr><th className="p-3 text-right">תוכן</th><th className="p-3 text-right">קטגוריה</th><th className="p-3 text-right">Scope / מקור</th><th className="p-3 text-right">אישור</th><th className="p-3 text-right">עודכן</th><th className="p-3 text-right">פעולות</th></tr></thead>
                  <tbody>
                    {(memory?.items || []).map((row) => (
                      <tr key={row.id} className="border-t align-top">
                        <td className="min-w-[320px] p-3">
                          {editingId === row.id ? <textarea value={editContent} onChange={(event) => setEditContent(event.target.value)} rows={3} className="w-full rounded-lg border p-2" /> : <div className="whitespace-pre-wrap">{row.content}</div>}
                        </td>
                        <td className="p-3">{editingId === row.id ? <select value={editCategory} onChange={(event) => setEditCategory(event.target.value as MemoryCategory)} className="rounded-lg border px-2 py-1">{Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select> : categoryLabels[row.category]}</td>
                        <td className="p-3"><div>{row.scope === 'org' ? `עסק #${row.organization_id}` : `משתמש #${row.user_id}`}</div><div className="text-xs text-slate-500">{sourceLabels[row.source]}</div></td>
                        <td className="p-3">{row.approved_at ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700"><ShieldCheck size={14} /> מאושר</span> : <span className="rounded-full bg-amber-50 px-2 py-1 text-xs text-amber-700">לא אושר</span>}</td>
                        <td className="whitespace-nowrap p-3 text-xs text-slate-500">{formatDate(row.updated_at)}</td>
                        <td className="p-3">
                          <div className="flex flex-wrap gap-2">
                            {editingId === row.id ? <><button disabled={saving} onClick={() => void saveEdit(row)} title="שמירה" className="rounded border p-2 text-emerald-700"><Save size={15} /></button><button onClick={() => setEditingId(null)} title="ביטול" className="rounded border p-2"><X size={15} /></button></> : <button onClick={() => startEdit(row)} title="עריכה" className="rounded border p-2"><Edit3 size={15} /></button>}
                            <button disabled={saving} onClick={() => void toggleApproval(row)} title={row.approved_at ? 'ביטול אישור' : 'אישור'} className="rounded border p-2 text-emerald-700"><CheckCircle2 size={15} /></button>
                            <button disabled={saving} onClick={() => void remove(row)} title="מחיקה" className="rounded border p-2 text-red-600"><Trash2 size={15} /></button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
            <aside className="overflow-hidden rounded-xl border bg-white shadow-sm">
              <h2 className="border-b p-4 font-semibold">נושאים</h2>
              {!knowledge?.document_knowledge.available ? <div className="m-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><AlertCircle className="mb-1" size={17} />{knowledge?.document_knowledge.reason}</div> : null}
              <div className="max-h-[680px] overflow-y-auto">
                {(knowledge?.topics || []).map((topic) => <button key={topic.id} onClick={() => void openTopic(topic)} className={`w-full border-b p-4 text-right hover:bg-slate-50 ${selectedTopic?.id === topic.id ? 'bg-violet-50' : ''}`}><span className="block font-medium">{topic.title}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{topic.summary}</span></button>)}
              </div>
            </aside>
            <main className="min-h-[520px] rounded-xl border bg-white p-6 shadow-sm">
              {topicLoading ? <Loader2 className="mx-auto mt-20 animate-spin text-slate-400" /> : selectedTopic?.content ? <><h2 className="mb-5 border-b pb-3 text-xl font-bold">{selectedTopic.title}</h2><MarkdownView content={selectedTopic.content} /></> : <div className="mt-20 text-center text-slate-500"><BookOpen className="mx-auto mb-3" />בחר נושא כדי לקרוא את תוכנו.</div>}
            </main>
          </div>
        )}
      </div>
    </div>
  );
}
