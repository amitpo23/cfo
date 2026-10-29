import { useEffect, useState } from 'react';
import api from '../services/api';

type Invitation = { organization_id: number; name: string; role: string };

export default function PendingInvitations({ darkMode }: { darkMode: boolean }) {
  const [items, setItems] = useState<Invitation[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api.get<{ items: Invitation[] }>('/admin/memberships/pending')
      .then((body) => { if (!cancelled) setItems(body.items || []); })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, []);

  if (items.length === 0) return null;

  async function accept(organizationId: number) {
    setBusyId(organizationId);
    setError('');
    try {
      await api.post('/admin/memberships/accept', { organization_id: organizationId });
      window.location.reload();
    } catch {
      setError('קבלת ההזמנה נכשלה.');
      setBusyId(null);
    }
  }

  return (
    <section
      dir="rtl"
      className={`border-b px-4 py-3 ${darkMode ? 'border-amber-800 bg-amber-950 text-amber-50' : 'border-amber-200 bg-amber-50 text-amber-950'}`}
      aria-label="הזמנות ממתינות"
    >
      <p className="text-sm font-medium">יש הזמנות לארגונים שעדיין לא אושרו. בלי קבלה הארגון לא מופיע במחליף.</p>
      {error ? <p className="mt-1 text-sm">{error}</p> : null}
      <ul className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <li key={item.organization_id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${darkMode ? 'border-amber-700' : 'border-amber-300 bg-white'}`}>
            <span>{item.name}</span>
            <button
              type="button"
              className="rounded-md bg-emerald-700 px-2 py-1 text-white disabled:opacity-50"
              disabled={busyId === item.organization_id}
              onClick={() => void accept(item.organization_id)}
            >
              {busyId === item.organization_id ? 'מקבל…' : 'קבל הזמנה'}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
