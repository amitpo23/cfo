import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Banknote, Download, Settings, AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';
import apiService from '../services/api';

interface Props {
  darkMode?: boolean;
}

interface MasavPaymentRow {
  beneficiary_name: string;
  bank_code: string;
  branch: string;
  account_number: string;
  amount: number;
  reference: string;
}

interface MasavPreview {
  summary: { payment_count: number; total_amount: number };
  payments: MasavPaymentRow[];
  skipped: Array<{ bill: string; vendor?: string; reason: string }>;
}

const todayISO = () => new Date().toISOString().slice(0, 10);

const MasavDashboard: React.FC<Props> = ({ darkMode }) => {
  const queryClient = useQueryClient();
  const [paymentDate, setPaymentDate] = useState(todayISO());
  const [form, setForm] = useState({
    institution_code: '',
    sending_institution: '',
    institution_name: '',
  });
  const [preview, setPreview] = useState<MasavPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const card = darkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200';
  const input = `w-full px-3 py-2 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-300'}`;

  const settingsQuery = useQuery({
    queryKey: ['masav-settings'],
    queryFn: async () => {
      const res: any = await apiService.getMasavSettings();
      if (res?.settings) setForm(res.settings);
      return res;
    },
  });

  const saveSettings = useMutation({
    mutationFn: () => apiService.saveMasavSettings(form),
    onSuccess: () => {
      setMessage('הגדרות המוסד נשמרו');
      queryClient.invalidateQueries({ queryKey: ['masav-settings'] });
    },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בשמירת ההגדרות'),
  });

  const previewMutation = useMutation({
    mutationFn: () => apiService.previewMasav(paymentDate),
    onSuccess: (data: any) => {
      setPreview(data);
      setMessage(null);
    },
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה בתצוגה מקדימה'),
  });

  const downloadMutation = useMutation({
    mutationFn: () => apiService.downloadMasav(paymentDate),
    onSuccess: (res: any) => setMessage(`הקובץ הורד. דולגו ${res.skipped} חשבוניות ללא פרטי בנק.`),
    onError: (e: any) => setMessage(e?.response?.data?.detail || 'שגיאה ביצירת הקובץ'),
  });

  const configured = settingsQuery.data?.configured;

  return (
    <div dir="rtl" className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Banknote className="w-8 h-8 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold">תשלומי ספקים — קובץ מס"ב</h1>
          <p className="text-sm text-gray-500">יצירת קובץ זיכויים להעברה לבנק</p>
        </div>
      </div>

      {message && (
        <div className={`p-3 rounded-lg border ${card}`}>{message}</div>
      )}

      {/* הגדרות מוסד */}
      <div className={`rounded-xl border p-5 ${card}`}>
        <div className="flex items-center gap-2 mb-4">
          <Settings className="w-5 h-5" />
          <h2 className="text-lg font-semibold">הגדרות מוסד מס"ב</h2>
          {configured ? (
            <span className="text-green-600 text-sm flex items-center gap-1">
              <CheckCircle className="w-4 h-4" /> מוגדר
            </span>
          ) : (
            <span className="text-amber-600 text-sm">לא מוגדר</span>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm mb-1">מספר מוסד / נושא (8 ספרות)</label>
            <input className={input} value={form.institution_code}
              onChange={(e) => setForm({ ...form, institution_code: e.target.value })} />
          </div>
          <div>
            <label className="block text-sm mb-1">מספר מוסד שולח (5 ספרות)</label>
            <input className={input} value={form.sending_institution}
              onChange={(e) => setForm({ ...form, sending_institution: e.target.value })} />
          </div>
          <div>
            <label className="block text-sm mb-1">שם המוסד</label>
            <input className={input} value={form.institution_name}
              onChange={(e) => setForm({ ...form, institution_name: e.target.value })} />
          </div>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          קודי המוסד ניתנים ע"י מס"ב בעת הצירוף. יש לאמת את מבנה הקובץ מול הבנק לפני שליחה ראשונה.
        </p>
        <button
          onClick={() => saveSettings.mutate()}
          disabled={saveSettings.isPending}
          className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saveSettings.isPending ? 'שומר...' : 'שמירת הגדרות'}
        </button>
      </div>

      {/* יצירת קובץ */}
      <div className={`rounded-xl border p-5 ${card}`}>
        <h2 className="text-lg font-semibold mb-4">יצירת קובץ תשלומים</h2>
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="block text-sm mb-1">תאריך התשלום</label>
            <input type="date" className={input} value={paymentDate}
              onChange={(e) => setPaymentDate(e.target.value)} />
          </div>
          <button
            onClick={() => previewMutation.mutate()}
            disabled={previewMutation.isPending}
            className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 disabled:opacity-50"
          >
            {previewMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'תצוגה מקדימה'}
          </button>
          <button
            onClick={() => downloadMutation.mutate()}
            disabled={downloadMutation.isPending || !configured}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            {downloadMutation.isPending ? 'מייצר...' : 'הורדת קובץ מס"ב'}
          </button>
        </div>
      </div>

      {/* תצוגה מקדימה */}
      {preview && (
        <div className={`rounded-xl border p-5 ${card}`}>
          <div className="flex gap-6 mb-4">
            <div>
              <div className="text-sm text-gray-500">מספר תנועות</div>
              <div className="text-2xl font-bold">{preview.summary.payment_count}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">סכום כולל</div>
              <div className="text-2xl font-bold">₪{preview.summary.total_amount.toLocaleString()}</div>
            </div>
          </div>

          {preview.payments.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-right border-b">
                  <th className="py-2">שם הזכאי</th>
                  <th>בנק</th>
                  <th>סניף</th>
                  <th>חשבון</th>
                  <th>סכום</th>
                  <th>אסמכתא</th>
                </tr>
              </thead>
              <tbody>
                {preview.payments.map((p, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-2">{p.beneficiary_name}</td>
                    <td>{p.bank_code}</td>
                    <td>{p.branch}</td>
                    <td>{p.account_number}</td>
                    <td>₪{p.amount.toLocaleString()}</td>
                    <td>{p.reference}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {preview.skipped.length > 0 && (
            <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800">
              <div className="flex items-center gap-2 font-semibold mb-2">
                <AlertTriangle className="w-4 h-4" />
                {preview.skipped.length} חשבוניות דולגו
              </div>
              <ul className="list-disc pr-6 text-sm space-y-1">
                {preview.skipped.map((s, i) => (
                  <li key={i}>{s.vendor || s.bill}: {s.reason}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default MasavDashboard;
