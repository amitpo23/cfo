import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Package, RefreshCw, AlertTriangle, XCircle, Plus } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

interface InventoryRow {
  id: number;
  sku?: string;
  name: string;
  quantity: number;
  unit: string;
  unit_cost: number;
  unit_price: number;
  reorder_level: number;
  value: number;
  status: 'ok' | 'low' | 'out_of_stock';
  source: string;
  last_updated?: string;
}

interface InventoryReport {
  items: InventoryRow[];
  summary: {
    total_items: number;
    total_units: number;
    total_value: number;
    low_stock_count: number;
    out_of_stock_count: number;
  };
}

const emptyItem = { name: '', sku: '', unit: 'יחידה', quantity: 0, unit_cost: 0, unit_price: 0, reorder_level: 0 };

const InventoryDashboard: React.FC<Props> = ({ darkMode }) => {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<any>(emptyItem);

  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';
  const input = `w-full px-3 py-2 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`;

  const { data, isLoading } = useQuery({
    queryKey: ['inventory-report'],
    queryFn: async () => {
      const res: any = await apiService.getInventoryReport();
      return res.data as InventoryReport;
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => apiService.syncInventory(),
    onSuccess: (res: any) => {
      setMessage(`סונכרנו ${res?.data?.synced ?? 0} פריטים מ-SUMIT`);
      queryClient.invalidateQueries({ queryKey: ['inventory-report'] });
    },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בסנכרון'),
  });

  const saveMutation = useMutation({
    mutationFn: () => apiService.saveInventoryItem(form),
    onSuccess: () => {
      setMessage('הפריט נשמר');
      setShowForm(false);
      setForm(emptyItem);
      queryClient.invalidateQueries({ queryKey: ['inventory-report'] });
    },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בשמירה'),
  });

  const summary = data?.summary;
  const statusBadge = (s: string) =>
    s === 'out_of_stock'
      ? <span className="text-red-600 flex items-center gap-1"><XCircle className="w-4 h-4" />אזל</span>
      : s === 'low'
        ? <span className="text-amber-600 flex items-center gap-1"><AlertTriangle className="w-4 h-4" />נמוך</span>
        : <span className="text-green-600">תקין</span>;

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Package className="w-8 h-8 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold">דוח מלאי קיים</h1>
            <p className="text-sm text-gray-500">מלאי, שערוך והתראות מלאי נמוך</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowForm(!showForm)}
            className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 flex items-center gap-2">
            <Plus className="w-4 h-4" /> פריט
          </button>
          <button onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} /> סנכרון מ-SUMIT
          </button>
        </div>
      </div>

      {message && <div className={`p-3 rounded-lg border ${card}`}>{message}</div>}

      {showForm && (
        <div className={`rounded-xl border p-5 ${card}`}>
          <h2 className="text-lg font-semibold mb-4">הוספת / עדכון פריט</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div><label className="block text-sm mb-1">שם</label>
              <input className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">מק"ט</label>
              <input className={input} value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">כמות</label>
              <input type="number" className={input} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="block text-sm mb-1">יחידה</label>
              <input className={input} value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></div>
            <div><label className="block text-sm mb-1">עלות ליחידה</label>
              <input type="number" className={input} value={form.unit_cost} onChange={(e) => setForm({ ...form, unit_cost: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="block text-sm mb-1">מחיר מכירה</label>
              <input type="number" className={input} value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="block text-sm mb-1">סף התראה</label>
              <input type="number" className={input} value={form.reorder_level} onChange={(e) => setForm({ ...form, reorder_level: parseFloat(e.target.value) || 0 })} /></div>
          </div>
          <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !form.name}
            className="mt-4 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
            {saveMutation.isPending ? 'שומר...' : 'שמירה'}
          </button>
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className={`rounded-xl border p-4 ${card}`}>
            <div className="text-sm text-gray-500">סך פריטים</div>
            <div className="text-2xl font-bold">{summary.total_items}</div>
          </div>
          <div className={`rounded-xl border p-4 ${card}`}>
            <div className="text-sm text-gray-500">שווי מלאי כולל</div>
            <div className="text-2xl font-bold">₪{summary.total_value.toLocaleString()}</div>
          </div>
          <div className={`rounded-xl border p-4 ${card}`}>
            <div className="text-sm text-gray-500">מלאי נמוך</div>
            <div className="text-2xl font-bold text-amber-600">{summary.low_stock_count}</div>
          </div>
          <div className={`rounded-xl border p-4 ${card}`}>
            <div className="text-sm text-gray-500">אזל מהמלאי</div>
            <div className="text-2xl font-bold text-red-600">{summary.out_of_stock_count}</div>
          </div>
        </div>
      )}

      <div className={`rounded-xl border p-5 ${card}`}>
        {isLoading ? (
          <div className="text-center py-8 text-gray-500">טוען...</div>
        ) : !data || data.items.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            אין פריטי מלאי. הוסף פריט ידנית או סנכרן מ-SUMIT.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-right border-b">
                <th className="py-2">שם</th>
                <th>מק"ט</th>
                <th>כמות</th>
                <th>יחידה</th>
                <th>עלות</th>
                <th>שווי</th>
                <th>סטטוס</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it) => (
                <tr key={it.id} className="border-b">
                  <td className="py-2">{it.name}</td>
                  <td>{it.sku || '-'}</td>
                  <td>{it.quantity.toLocaleString()}</td>
                  <td>{it.unit}</td>
                  <td>₪{it.unit_cost.toLocaleString()}</td>
                  <td>₪{it.value.toLocaleString()}</td>
                  <td>{statusBadge(it.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default InventoryDashboard;
