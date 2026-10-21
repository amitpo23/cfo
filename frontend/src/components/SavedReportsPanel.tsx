import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

interface Template { template_id: string; name: string; report_type: string; }
interface Schedule { schedule_id: string; name: string; next_run: string; is_active: boolean; }
interface Run { execution_id: string; status: string; started_at: string; error_message: string | null;
  result: { download_url: string; report_id: string; format: string } | null; }
interface Envelope<T> { data: T; }

export default function SavedReportsPanel() {
  const cache = useQueryClient();
  const [templateId, setTemplateId] = useState('DEFAULT-PL');
  const [name, setName] = useState('');
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [message, setMessage] = useState('');
  const templates = useQuery({ queryKey: ['saved-report-templates'],
    queryFn: () => api.get<Envelope<Template[]>>('/financial/reports/templates') });
  const schedules = useQuery({ queryKey: ['saved-report-schedules'],
    queryFn: () => api.get<Envelope<Schedule[]>>('/financial/reports/schedules') });
  const history = useQuery({ queryKey: ['saved-report-history'],
    queryFn: () => api.get<Envelope<Run[]>>('/financial/reports/history') });
  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post(path, body),
    onSuccess: () => {
      setMessage('הפעולה נשמרה');
      cache.invalidateQueries({ queryKey: ['saved-report-templates'] });
      cache.invalidateQueries({ queryKey: ['saved-report-schedules'] });
      cache.invalidateQueries({ queryKey: ['saved-report-history'] });
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setMessage(typeof detail === 'string' ? detail : 'הפעולה נכשלה; יש לבדוק הרשאות ונתונים.');
      cache.invalidateQueries({ queryKey: ['saved-report-history'] });
    },
  });
  async function download(run: Run) {
    if (!run.result) return;
    try {
      const blob = await api.get<Blob>(run.result.download_url, { responseType: 'blob' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url;
      link.download = `${run.result.report_id}.${run.result.format === 'excel' ? 'xlsx' : run.result.format}`;
      link.click(); URL.revokeObjectURL(url);
    } catch { setMessage('הורדת הדוח נכשלה; יש לבדוק הרשאה ושלמות הקובץ.'); }
  }
  const [year, monthNumber] = month.split('-').map(Number);
  return <section dir="rtl" aria-label="דוחות שמורים" className="bg-white border rounded-xl p-4 space-y-3 min-w-0">
    <h2 className="text-xl font-bold">דוחות שמורים ותזמונים</h2>
    <p className="text-sm">דוחות ניהוליים נגזרים. שלמות המקורות והתאמה לספרים הרשמיים עדיין דורשות בדיקה.
      תזמון שומר מועד להרצה מקומית מפורשת; אין משלוח אוטומטי.</p>
    {(templates.isLoading || schedules.isLoading || history.isLoading) && <p role="status">טוען דוחות שמורים…</p>}
    {(templates.isError || schedules.isError || history.isError) && <p role="alert">לא ניתן לטעון את כל רשומות הדוחות.
      <button onClick={() => { templates.refetch(); schedules.refetch(); history.refetch(); }}>ניסיון נוסף</button></p>}
    {message && <p role="status">{message}</p>}
    <div className="flex flex-wrap gap-3">
      <label>תבנית דוח
        <select aria-label="תבנית דוח" value={templateId} onChange={e => setTemplateId(e.target.value)} className="block border rounded p-2 max-w-full">
          {templates.data?.data.filter(t => t.report_type === 'profit_loss').map(t => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}
        </select>
      </label>
      <label>תקופת דוח<input className="block border rounded p-2" type="month" value={month} onChange={e => setMonth(e.target.value)} /></label>
      <button disabled={action.isPending || !month} onClick={() => action.mutate({ path: '/financial/reports/generate',
        body: { template_id: templateId, format: 'json', parameters: { year, month: monthNumber } } })} className="border rounded p-2">הפקת דוח שמור</button>
    </div>
    <div className="flex flex-wrap gap-3 items-end">
      <label>שם תבנית חדשה<input value={name} onChange={e => setName(e.target.value)} className="block border rounded p-2" /></label>
      <button disabled={action.isPending || !name.trim()} className="border rounded p-2" onClick={() => action.mutate({ path: '/financial/reports/templates',
        body: { name, report_type: 'profit_loss', columns: [{ field_name: 'category', display_name: 'קטגוריה', data_type: 'string' },
          { field_name: 'subcategory', display_name: 'כרטיס', data_type: 'string' }, { field_name: 'amount', display_name: 'סכום', data_type: 'currency' }] } })}>שמירת תבנית</button>
      <button disabled={action.isPending || !name.trim()} className="border rounded p-2" onClick={() => action.mutate({ path: '/financial/reports/schedules',
        body: { template_id: templateId, name, frequency: 'monthly', recipients: [], delivery_method: 'download', format: 'json' } })}>שמירת תזמון חודשי</button>
    </div>
    <h3 className="font-bold">תזמונים</h3>
    {schedules.data?.data.length === 0 && <p>אין תזמונים שמורים.</p>}
    {schedules.data?.data.map(s => <div key={s.schedule_id} className="flex flex-wrap gap-3 border-b py-2">
      <span>{s.name} · {s.is_active ? 'פעיל' : 'מושהה'} · {new Date(s.next_run).toLocaleString('he-IL')}</span>
      <button disabled={action.isPending} onClick={() => action.mutate({ path: `/financial/reports/schedules/${s.schedule_id}/${s.is_active ? 'pause' : 'resume'}` })}>
        {s.is_active ? 'השהיה' : 'חידוש'}</button>
    </div>)}
    <button disabled={action.isPending} className="border rounded p-2" onClick={() => action.mutate({ path: '/financial/reports/run-scheduled' })}>הרצת תזמונים שהגיע מועדם</button>
    <h3 className="font-bold">היסטוריית הרצות</h3>
    {history.data?.data.length === 0 && <p>אין הרצות שמורות.</p>}
    {history.data?.data.map(run => <div key={run.execution_id} className="border-b py-2 break-words">
      {new Date(run.started_at).toLocaleString('he-IL')} · {run.status === 'completed' ? 'קובץ נשמר' : run.status === 'failed' ? 'נכשל' : 'בטיפול — אין להפעיל שוב'}
      {run.error_message && <p>{run.error_message}</p>}
      {run.result && <button className="underline mx-2" onClick={() => download(run)}>הורדת הקובץ השמור</button>}
    </div>)}
  </section>;
}
