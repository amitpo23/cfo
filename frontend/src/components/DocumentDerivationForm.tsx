import { useState } from 'react';
import api from '../services/api';

type Source = { id: number; filename: string; version: number; status: string; media_type: string; expense_id: number | null };
type Selection = { source: Source; pages: string };
function pages(value: string): number[] {
  const result: number[] = [];
  for (const part of value.split(',')) {
    const match = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) throw new Error('יש להזין מספרי עמודים או טווח, לדוגמה 1,3-5');
    const start = Number(match[1]), end = Number(match[2] || match[1]);
    if (start < 1 || end < start || end > 100) throw new Error('טווח העמודים אינו תקין; עד 100 עמודים');
    for (let page = start; page <= end; page++) result.push(page);
  }
  return result;
}
export default function DocumentDerivationForm({ documents, onComplete }: { documents: Source[]; onComplete: () => void }) {
  const [selected, setSelected] = useState<Selection[]>([]);
  const [groups, setGroups] = useState('');
  const [reason, setReason] = useState('');
  const [filename, setFilename] = useState('מסמך מאוחד.pdf');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const eligible = documents.filter(row => row.media_type === 'application/pdf' && !row.expense_id &&
    !['processing', 'created', 'duplicate', 'superseded'].includes(row.status));
  async function save() {
    setBusy(true); setMessage('');
    try {
      const outputs = selected.length === 1 ? groups.split(';').map((group, i) => ({
        filename: `${selected[0].source.filename.replace(/\.pdf$/i, '')} — חלק ${i + 1}.pdf`,
        pages: pages(group).map(page => ({ document_id: selected[0].source.id, page })),
      })) : [{ filename, pages: selected.flatMap(item => pages(item.pages).map(page => ({ document_id: item.source.id, page }))) }];
      const result = await api.post<{ outputs: { document_id: number }[] }>('/expenses/intake/derive', {
        parents: selected.map(item => ({ document_id: item.source.id, version: item.source.version })), outputs, reason,
      });
      setMessage(`נשמרו ${result.outputs.length} מסמכים בתור. המקורות נשמרו לעיון ונחסמו מטיפול כפול.`);
      setSelected([]); setGroups(''); setReason(''); onComplete();
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setMessage(error instanceof Error && !detail ? error.message : typeof detail === 'string' ? detail : 'הפעולה נכשלה. יש לבדוק את המקור, העמודים, הגרסה וההרשאות.');
    } finally { setBusy(false); }
  }
  return <details className="border rounded p-3 space-y-3" aria-label="פיצול ומיזוג מסמכים">
    <summary className="cursor-pointer font-semibold">ארגון עמודי PDF — פיצול או מיזוג</summary>
    <p className="text-sm">יש לבדוק את המקור לפני הבחירה. כל עמוד חייב להיכלל פעם אחת. המקורות נשמרים לעיון בלבד לאחר הפעולה; המסמכים החדשים ממתינים לחילוץ ובדיקה.</p>
    {eligible.length === 0 && <p>אין מסמכי PDF מתאימים בעמוד זה.</p>}
    <fieldset disabled={busy} className="space-y-2">
      <legend>בחירת מקורות — מסמך אחד לפיצול, או כמה למיזוג לפי סדר הבחירה</legend>
      {eligible.map(row => <label key={row.id} className="block break-words">
        <input type="checkbox" checked={selected.some(item => item.source.id === row.id)} onChange={event =>
          setSelected(event.target.checked ? [...selected, { source: row, pages: '' }] : selected.filter(item => item.source.id !== row.id))} /> {row.filename}
      </label>)}
    </fieldset>
    {selected.length > 0 && <form className="space-y-3" onSubmit={event => { event.preventDefault(); void save(); }}>
      {selected.length === 1 ? <label className="block">קבוצות עמודים לפיצול — נקודה־פסיק בין מסמכים, לדוגמה 1;2-3
        <input dir="ltr" className="block border p-2 rounded w-full min-w-0" required value={groups} onChange={event => setGroups(event.target.value)} />
      </label> : <>
        {selected.map((item, index) => <label key={item.source.id} className="block break-words">עמודים מתוך {item.source.filename} — מקום {index + 1} בסדר המיזוג
          <input dir="ltr" className="block border p-2 rounded w-full min-w-0" required value={item.pages} onChange={event =>
            setSelected(selected.map(other => other.source.id === item.source.id ? { ...other, pages: event.target.value } : other))} />
        </label>)}
        <label className="block">שם המסמך המאוחד<input className="block border p-2 rounded w-full min-w-0" required maxLength={255} value={filename} onChange={event => setFilename(event.target.value)} /></label>
      </>}
      <label className="block">סיבת הפיצול או המיזוג<textarea className="block border p-2 rounded w-full min-w-0" required minLength={20} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <button disabled={busy} className="border rounded p-2" type="submit">{busy ? 'שומר…' : 'אישור ושמירת חלוקת העמודים'}</button>
    </form>}
    {message && <p role="status" className="break-words">{message}</p>}
  </details>;
}
