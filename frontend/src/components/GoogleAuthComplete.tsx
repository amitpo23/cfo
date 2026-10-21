import { useEffect, useState } from 'react';
import axios from 'axios';
import { GOOGLE_AUTH_ERRORS } from './GoogleSignInButton';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

/**
 * /auth/complete — סוף זרימת Google. השרת מחזיר קוד חד-פעמי (120 שניות) ב-fragment
 * של ה-URL; ה-fragment אינו נשלח לשרתים ואינו נכנס ל-Referer. הקוד מוחלף ב-POST
 * ב-JWT הרגיל של רצף, שנשמר כמו בכניסת סיסמה.
 */
function safeNext(value: string | null): string {
  return value && /^\/(?![/\\])/.test(value) ? value : '/';
}

export default function GoogleAuthComplete() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const code = params.get('code');
    const next = safeNext(params.get('next'));
    window.history.replaceState({}, '', window.location.pathname);
    if (!code) {
      setError(GOOGLE_AUTH_ERRORS.code_invalid);
      return;
    }
    axios
      // withCredentials: עוגיית הקישור-לדפדפן (HttpOnly) חייבת להישלח עם ההחלפה.
      .post<{ access_token: string }>(`${API_BASE_URL}/auth/google/exchange`, { code }, { withCredentials: true })
      .then(({ data }) => {
        localStorage.setItem('auth_token', data.access_token);
        // ארגון פעיל של סשן קודם אינו שייך בהכרח לזהות החדשה.
        localStorage.removeItem('active_org_id');
        window.location.replace(next);
      })
      .catch((err) => {
        const detail = err?.response?.data?.detail;
        setError(typeof detail === 'string' ? detail : GOOGLE_AUTH_ERRORS.code_invalid);
      });
  }, []);

  return (
    <main dir="rtl" className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 text-center shadow-xl">
        {error ? (
          <>
            <p className="text-red-600">{error}</p>
            <a href="/login" className="mt-4 inline-block text-sm text-blue-600 hover:underline">
              חזרה להתחברות
            </a>
          </>
        ) : (
          <p className="text-gray-600">משלים התחברות עם Google…</p>
        )}
      </div>
    </main>
  );
}
