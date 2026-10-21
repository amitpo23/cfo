import React, { useEffect, useState } from 'react';
import GoogleSignInButton, { consumeGoogleAuthError } from './GoogleSignInButton';
import axios from 'axios';
import { Loader2, LogIn, UserPlus, TrendingUp } from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
interface Props {
  darkMode: boolean;
  onSuccess: () => void;
}

interface TokenResponse {
  access_token: string;
  user?: { full_name?: string; email?: string };
}

const Login: React.FC<Props> = ({ darkMode, onSuccess }) => {
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [registrationCode, setRegistrationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleForgotSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/admin/auth/request-password-reset`, { email });
      setInfo('אם הכתובת קיימת במערכת, נשלח אליה קישור לאיפוס הסיסמה.');
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'שליחת בקשת האיפוס נכשלה. נסו שוב.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/admin/auth/login' : '/admin/auth/register';
      const payload =
        mode === 'login'
          ? { email, password }
          : { email, password, full_name: fullName, registration_code: registrationCode || undefined };
      const { data } = await axios.post<TokenResponse>(`${API_BASE_URL}${endpoint}`, payload);
      localStorage.setItem('auth_token', data.access_token);
      onSuccess();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : mode === 'login'
            ? 'ההתחברות נכשלה. בדקו אימייל וסיסמה.'
            : 'ההרשמה נכשלה. נסו שוב.'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const googleError = consumeGoogleAuthError();
    if (googleError) setError(googleError);
  }, []);

  const inputClass = `w-full px-4 py-2.5 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
    darkMode
      ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
      : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
  }`;

  return (
    <div className={`flex h-screen items-center justify-center ${darkMode ? 'bg-gray-900' : 'bg-gray-50'}`} dir="rtl">
      <div className={`w-full max-w-md rounded-2xl shadow-xl p-8 ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center mb-3">
            <TrendingUp size={24} className="text-white" />
          </div>
          <h1 className={`text-2xl font-bold ${darkMode ? 'text-white' : 'text-gray-900'}`}>CFO System</h1>
          <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            {mode === 'login' ? 'התחברות למערכת' : mode === 'register' ? 'הרשמה למערכת' : 'איפוס סיסמה'}
          </p>
        </div>

        {mode === 'forgot' ? (
          <form onSubmit={handleForgotSubmit} className="space-y-4">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="אימייל"
              className={inputClass}
              autoComplete="email"
            />
            {info && (
              <div className="text-sm text-green-600 bg-green-50 dark:bg-green-900/20 rounded-lg px-3 py-2">{info}</div>
            )}
            {error && (
              <div className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">{error}</div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg transition"
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : <LogIn size={18} />}
              שליחת קישור איפוס
            </button>
            <button
              type="button"
              onClick={() => {
                setMode('login');
                setError(null);
                setInfo(null);
              }}
              className={`w-full text-sm ${darkMode ? 'text-blue-400' : 'text-blue-600'} hover:underline`}
            >
              חזרה להתחברות
            </button>
          </form>
        ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'register' && (
            <>
              <input
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="שם מלא"
                className={inputClass}
              />
              <input
                type="text"
                value={registrationCode}
                onChange={(e) => setRegistrationCode(e.target.value)}
                placeholder="קוד הרשמה"
                className={inputClass}
              />
            </>
          )}
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="אימייל"
            className={inputClass}
            autoComplete="email"
          />
          <input
            type="password"
            required
            minLength={mode === 'register' ? 8 : 6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === 'register' ? 'סיסמה (לפחות 8 תווים)' : 'סיסמה'}
            className={inputClass}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />

          {error && (
            <div className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">{error}</div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg transition"
          >
            {loading ? (
              <Loader2 size={18} className="animate-spin" />
            ) : mode === 'login' ? (
              <LogIn size={18} />
            ) : (
              <UserPlus size={18} />
            )}
            {mode === 'login' ? 'התחברות' : 'הרשמה'}
          </button>

          {mode === 'login' && (
            <button
              type="button"
              onClick={() => {
                setMode('forgot');
                setError(null);
                setInfo(null);
              }}
              className={`w-full text-sm ${darkMode ? 'text-blue-400' : 'text-blue-600'} hover:underline`}
            >
              שכחתי סיסמה
            </button>
          )}
        </form>
        )}

        {mode !== 'forgot' && (
          <>
            {mode === 'login' && (
              <div className="mt-4">
                <GoogleSignInButton />
              </div>
            )}

            <button
              type="button"
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login');
                setError(null);
              }}
              className={`w-full mt-4 text-sm ${darkMode ? 'text-blue-400' : 'text-blue-600'} hover:underline`}
            >
              {mode === 'login' ? 'אין לכם חשבון? הירשמו כאן' : 'יש לכם חשבון? התחברו כאן'}
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default Login;
