import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

type Preview = { page: number; page_count: number; media_type: 'image/png'; content_base64: string; source_sha256: string };

/** Local raster preview; original bytes remain available separately for download. */
export default function DocumentSourcePreview({ documentId }: { documentId: number }) {
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ['document-source-preview', documentId, page],
    queryFn: () => api.get<Preview>(`/expenses/intake/${documentId}/preview?page=${page}`), retry: false });
  return <div className="space-y-2 min-w-0" aria-label="תצוגת עמודי מקור">
    {query.isFetching && <p role="status">טוען תצוגת עמוד מהמקור השמור…</p>}
    {query.isError && <p role="alert">לא ניתן להציג את העמוד. יש לבדוק את המקור השמור; ניתן להורידו לעיון. <button onClick={() => query.refetch()} className="underline">ניסיון נוסף לתצוגה</button></p>}
    {query.data && <>
      <p>עמוד {query.data.page} מתוך {query.data.page_count} — תצוגה בלבד, המקור נשמר ללא שינוי</p>
      <img src={`data:image/png;base64,${query.data.content_base64}`} alt="תצוגת עמוד מקור" className="w-full border rounded" />
    </>}
    <div className="flex flex-wrap gap-2">
      <button disabled={page <= 1 || query.isFetching} onClick={() => setPage(value => value - 1)} className="border rounded p-2 disabled:opacity-50">עמוד קודם</button>
      <button disabled={!query.data || page >= query.data.page_count || query.isFetching} onClick={() => setPage(value => value + 1)} className="border rounded p-2 disabled:opacity-50">עמוד הבא</button>
    </div>
  </div>;
}
