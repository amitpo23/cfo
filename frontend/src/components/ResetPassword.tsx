import React, { useMemo, useState } from 'react';
import axios from 'axios';
import { KeyRound, Loader2 } from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

interface Props {
  darkMode: boolean;
}

/**
 * מסך איפוס סיסמה — שלב ב' של "שכחתי סיסמה".
 * נטען לפני שער ההתחברות (route ציבורי /reset-password?token=...),
 * קורא את הטוקן מה-URL ושולח אותו יחד עם הסיסמה החדשה ל-API.
 */
const ResetPassword: React.FC<Props> = ({ darkMode }) => {
  const token = useMemo(
    () => new URLSearchParams(window.location.search).get('token') || '',
    [],
  );
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const inputClass = `w-full px-4 py-2.5 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
    darkMode
      ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
      : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
  }`;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (newPassword.length < 8) {
      setError('הסיסמה חייבת להכיל לפחות 8 תווים.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('הסיסמאות אינן תואמות.');
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/admin/auth/reset-password`, {
        token,
        new_password: newPassword,
      });
      setSuccess(true);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'איפוס הסיסמה נכשל. בקשו קישור חדש ונסו שוב.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`flex h-screen items-center justify-center ${darkMode ? 'bg-gray-900' : 'bg-gray-50'}`} dir="rtl">
      <div className={`w-full max-w-md rounded-2xl shadow-xl p-8 ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center mb-3">
            <KeyRound size={24} className="text-white" />
          </div>
          <h1 className={`text-2xl font-bold ${darkMode ? 'text-white' : 'text-gray-900'}`}>איפוס סיסמה</h1>
        </div>

        {!token ? (
          <div className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
            הקישור חסר טוקן איפוס. בקשו קישור חדש דרך "שכחתי סיסמה" במסך ההתחברות.
          </div>
        ) : success ? (
          <div className="space-y-4">
            <div className="text-sm text-green-600 bg-green-50 dark:bg-green-900/20 rounded-lg px-3 py-2">
              הסיסמה אופסה בהצלחה. אפשר להתחבר עם הסיסמה החדשה.
            </div>
            <a
              href="/"
              className="block w-full text-center bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-lg transition"
            >
              לכניסה למערכת
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              type="password"
              required
              minLength={8}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="סיסמה חדשה (לפחות 8 תווים)"
              className={inputClass}
              autoComplete="new-password"
            />
            <input
              type="password"
              required
              minLength={8}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="אימות סיסמה חדשה"
              className={inputClass}
              autoComplete="new-password"
            />
            {error && (
              <div className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">{error}</div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg transition"
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : <KeyRound size={18} />}
              איפוס סיסמה
            </button>
            <a
              href="/"
              className={`block text-center text-sm ${darkMode ? 'text-blue-400' : 'text-blue-600'} hover:underline`}
            >
              חזרה למסך ההתחברות
            </a>
          </form>
        )}
      </div>
    </div>
  );
};

export default ResetPassword;
