import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  ArrowLeft,
  BadgeCheck,
  BarChart3,
  BookOpen,
  Building2,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleDollarSign,
  ClipboardCheck,
  CreditCard,
  Database,
  FileCheck2,
  Landmark,
  Loader2,
  LockKeyhole,
  Network,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  UserPlus,
  Workflow,
  type LucideIcon,
} from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: { client_id: string; callback: (response: { credential?: string }) => void }) => void;
          renderButton: (element: HTMLElement, options: Record<string, string | number>) => void;
        };
      };
    };
  }
}

interface Props {
  darkMode: boolean;
  onSuccess: () => void;
}

interface TokenResponse {
  access_token: string;
  user?: { full_name?: string; email?: string };
}

interface CheckoutResponse {
  provider: 'stripe' | 'mock';
  checkout_session_id: string;
  checkout_url: string;
  payment_status: string;
  subscription_status: string;
  supports: string[];
  note?: string;
}

const plans = [
  {
    id: 'company_up_to_2_5m',
    name: 'חברה / שותפות',
    price: '₪750',
    unit: 'לחודש',
    caption: 'עד 2.5 מיליון ש"ח מחזור שנתי',
    features: ['מחלקת כספים אוטומטית', 'תזרים, AR/AP ודוחות ניהול', 'התאמות בנק ותיעוד פעולות', 'הפרדת משתמשים וארגון עצמאי'],
  },
  {
    id: 'company_above_2_5m',
    name: 'חברה בצמיחה',
    price: '₪750 + ₪500',
    unit: 'לכל מיליון נוסף',
    caption: 'מעל 2.5 מיליון ש"ח מחזור שנתי',
    featured: true,
    features: ['כל יכולות החברה', 'בקרת מחזור וחריגות', 'דוחות לבנק ולניהול', 'מרכז המלצות פיננסיות'],
  },
  {
    id: 'office',
    name: 'רצף Office',
    price: 'בהתאמה',
    unit: 'למשרד / קבוצה',
    caption: 'משרד רו"ח, קבוצת חברות או CFO חיצוני',
    features: ['ניהול תיקי לקוחות', 'אדמין רב-ארגוני', 'סנכרון רוחבי והרשאות', 'תצוגת על לכל הלקוחות'],
  },
];

const commandMetrics = [
  { label: 'תזרים 30 יום', value: '₪184K', delta: '+12%', tone: 'emerald' },
  { label: 'מי חייב לנו', value: '₪131K', delta: '11 חשבוניות', tone: 'amber' },
  { label: 'התאמות אוטומטיות', value: '87%', delta: '42 תנועות', tone: 'blue' },
  { label: 'חריגות לטיפול', value: '6', delta: '2 קריטיות', tone: 'rose' },
];

const proofPoints = [
  { label: 'ראייה מלאה', text: 'חשבוניות, תשלומים, בנקים, ספקים, לקוחות ותזרים במקום אחד', icon: Landmark },
  { label: 'עבודה אוטומטית', text: 'התאמות בנק, גבייה, תיוק הוצאות וסגירת פערים בלי אקסלים', icon: Workflow },
  { label: 'סוכן כספים', text: 'מסביר מה קורה, מה מסוכן ומה כדאי לעשות היום', icon: Sparkles },
  { label: 'ישראל', text: 'מע"מ, מס"ב, שכר, PCN874 ודוחות שנתיים בתהליכי עבודה מקומיים', icon: ShieldCheck },
];

const capabilityGroups = [
  {
    title: 'כסף נכנס',
    icon: CircleDollarSign,
    items: ['חשבוניות וקבלות', 'מי שילם ומי לא שילם', 'תזכורות גבייה', 'תחזית תקבולים לפי תאריך'],
  },
  {
    title: 'כסף יוצא',
    icon: CreditCard,
    items: ['ספקים וחשבונות לתשלום', 'תשלומי מס"ב', 'הוצאות ו-OCR', 'זיהוי חריגות ומנויים כפולים'],
  },
  {
    title: 'ספרים ודוחות',
    icon: BookOpen,
    items: ['הנה"ח כפולה אוטומטית', 'רווח והפסד יומי', 'מאזן ומאזן בוחן', 'חבילת דוחות לבנק'],
  },
  {
    title: 'בנק והתאמות',
    icon: Landmark,
    items: ['קליטת תנועות בנק', 'התאמות מול מסמכים', 'אישור התאמות והעברה לספרים', 'חריגות, עמלות ומנויים'],
  },
  {
    title: 'ניהול ו-CFO',
    icon: BarChart3,
    items: ['תזרים יומי וחודשי', 'תקציב מול ביצוע', 'תחזיות', 'סוכן המלצות פיננסיות'],
  },
  {
    title: 'ציות ישראלי',
    icon: ClipboardCheck,
    items: ['מע"מ וטיוטות מס', 'PCN874 readiness', 'שכר 102/126', 'דוח שנתי וחומר מסודר לרו"ח'],
  },
];

const workflow = [
  {
    title: 'כל תנועה נכנסת למפה אחת',
    text: 'המערכת מושכת תנועות, מסמכים ופעולות כספיות ומבינה מה שייך למה.',
    icon: Landmark,
  },
  {
    title: 'התאמות, סיווגים ואישורים',
    text: 'רצף מתאימה תשלומים לחשבוניות, מזהה חריגות ומכינה פעולות לאישור.',
    icon: Workflow,
  },
  {
    title: 'דוחות ותובנות בזמן אמת',
    text: 'הסוכן מסביר מה השתנה, מי חייב כסף, מה עומד לצאת ומה כדאי לעשות.',
    icon: Sparkles,
  },
];

const agentInsights = [
  'לקוח מרכזי מאחר בתשלום ב-18 יום ועלול לפגוע בתזרים של השבוע הבא.',
  'זוהתה הוצאה חוזרת כפולה בקטגוריית תוכנה. מומלץ לבטל מנוי אחד.',
  'אפשר לדחות שני תשלומי ספקים לא קריטיים בלי לפגוע בפעילות.',
  'הרווחיות החודשית נשחקת בגלל עלייה בהוצאות רכש מול מחזור יציב.',
];

const annualReportTemplates = [
  {
    id: 'annual_report_up_to_2_5m',
    title: 'דוח שנתי עד 2.5M',
    price: '₪3,000',
    note: 'חבילת דוח שנתי לחברה או שותפות עד 2.5 מיליון ש"ח מחזור שנתי.',
  },
  {
    id: 'annual_report_above_2_5m',
    title: 'דוח שנתי מעל 2.5M',
    price: '₪3,000 + ₪500',
    note: 'בסיס של ₪3,000 ועוד ₪500 לכל מיליון ש"ח נוסף מעל 2.5M.',
  },
];

const paymentTemplates = [
  { id: 'apple_pay', label: 'Apple Pay', note: 'תשלום מהיר ומאובטח' },
  { id: 'card', label: 'כרטיס אשראי', note: 'חיוב חודשי אוטומטי' },
  { id: 'google_pay', label: 'Google Pay', note: 'תשלום מהיר ומאובטח' },
  { id: 'bank_transfer', label: 'העברה בנקאית', note: 'חשבונית לתשלום ידני' },
];

const toneClasses: Record<string, string> = {
  emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  amber: 'border-amber-200 bg-amber-50 text-amber-700',
  blue: 'border-blue-200 bg-blue-50 text-blue-700',
  rose: 'border-rose-200 bg-rose-50 text-rose-700',
};

const RezefLanding: React.FC<Props> = ({ darkMode: _darkMode, onSuccess }) => {
  const [mode, setMode] = useState<'register' | 'login'>('register');
  const [selectedPlan, setSelectedPlan] = useState('company_above_2_5m');
  const [annualRevenue, setAnnualRevenue] = useState('up_to_2_5m');
  const [annualReportRequested, setAnnualReportRequested] = useState(true);
  const [paymentTemplate, setPaymentTemplate] = useState('card');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [registrationCode, setRegistrationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkout, setCheckout] = useState<CheckoutResponse | null>(null);
  const googleButtonRef = useRef<HTMLDivElement | null>(null);

  const selectedPlanName = useMemo(
    () => plans.find((plan) => plan.id === selectedPlan)?.name || plans[1].name,
    [selectedPlan],
  );

  const completeLogin = (data: TokenResponse) => {
    localStorage.setItem('auth_token', data.access_token);
    localStorage.setItem('rezef_selected_plan', selectedPlan);
    onSuccess();
  };

  const checkoutSessionId = checkout?.checkout_session_id;
  const paymentStatus = checkout?.payment_status;

  const prepareCheckout = async () => {
    setError(null);
    setCheckoutLoading(true);
    try {
      const { data } = await axios.post<CheckoutResponse>(`${API_BASE_URL}/admin/billing/checkout`, {
        selected_plan: selectedPlan,
        annual_revenue: annualRevenue,
        annual_report_requested: annualReportRequested,
        payment_template: paymentTemplate,
        email: email || undefined,
        success_path: '/',
        cancel_path: '/',
      });
      setCheckout(data);
      if (data.provider === 'stripe' && data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'לא הצלחנו להכין תשלום. אפשר לנסות שוב או להמשיך עם קוד הרשמה.');
    } finally {
      setCheckoutLoading(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/admin/auth/login' : '/admin/auth/register';
      const payload =
        mode === 'login'
          ? { email, password }
          : {
              email,
              password,
              full_name: fullName,
              registration_code: registrationCode || undefined,
              selected_plan: selectedPlan,
              annual_revenue: annualRevenue,
              annual_report_requested: annualReportRequested,
              payment_template: paymentTemplate,
              checkout_session_id: checkoutSessionId,
              payment_status: paymentStatus,
            };
      const { data } = await axios.post<TokenResponse>(`${API_BASE_URL}${endpoint}`, payload);
      completeLogin(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : mode === 'login'
            ? 'ההתחברות נכשלה. בדקו אימייל וסיסמה.'
            : 'ההרשמה נכשלה. בדקו את הפרטים או את קוד ההרשמה.',
      );
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleCredential = async (credential?: string) => {
    if (!credential) return;
    setError(null);
    setLoading(true);
    try {
      const { data } = await axios.post<TokenResponse>(`${API_BASE_URL}/admin/auth/google`, {
        id_token: credential,
        registration_code: registrationCode || undefined,
        selected_plan: selectedPlan,
        annual_revenue: annualRevenue,
        annual_report_requested: annualReportRequested,
        payment_template: paymentTemplate,
        checkout_session_id: checkoutSessionId,
        payment_status: paymentStatus,
      });
      completeLogin(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'התחברות Google נכשלה.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !googleButtonRef.current) return;

    const render = () => {
      if (!window.google || !googleButtonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => handleGoogleCredential(response.credential),
      });
      googleButtonRef.current.innerHTML = '';
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        theme: 'outline',
        size: 'large',
        width: 320,
        text: mode === 'login' ? 'signin_with' : 'signup_with',
      });
    };

    if (window.google) {
      render();
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = render;
    document.head.appendChild(script);
  }, [mode, registrationCode, selectedPlan, checkoutSessionId, paymentStatus]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get('session_id');
    const checkoutResult = params.get('checkout');
    if (!sessionId || !checkoutResult) return;
    setCheckout({
      provider: checkoutResult === 'mock' ? 'mock' : 'stripe',
      checkout_session_id: sessionId,
      checkout_url: window.location.href,
      payment_status: checkoutResult === 'success' ? 'paid' : checkoutResult === 'mock' ? 'mock_ready' : 'pending',
      subscription_status: checkoutResult === 'success' ? 'active' : 'pending',
      supports: ['card', 'apple_pay', 'google_pay'],
    });
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950" dir="rtl">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3">
          <a href="#top" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-950 text-lg font-bold text-white shadow-sm">ר</div>
            <div>
              <div className="text-xl font-bold tracking-normal">רצף <span className="text-slate-500">Rezef</span></div>
              <div className="text-xs text-slate-500">Finance operating system</div>
            </div>
          </a>
          <nav className="hidden items-center gap-6 text-sm text-slate-600 lg:flex">
            <a href="#capabilities" className="hover:text-slate-950">יכולות</a>
            <a href="#workflow" className="hover:text-slate-950">איך זה עובד</a>
            <a href="#plans" className="hover:text-slate-950">תוכניות</a>
            <a href="#annual-report" className="hover:text-slate-950">דוח שנתי</a>
            <a href="#signup" className="hover:text-slate-950">הרשמה</a>
          </nav>
          <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700">
            התחילו <ArrowLeft className="h-4 w-4" />
          </a>
        </div>
      </header>

      <main id="top">
        <section className="border-b border-slate-200 bg-white">
          <div className="mx-auto grid min-h-[calc(100vh-65px)] max-w-7xl gap-10 px-5 py-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
            <div className="max-w-3xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm font-medium text-blue-700">
                <Network className="h-4 w-4" />
                CFO, הנהלת חשבונות, בנק ותזרים ברצף עבודה אחד
              </div>
              <h1 className="text-5xl font-bold leading-tight tracking-normal text-slate-950 md:text-7xl">
                מחלקת כספים אוטונומית לעסק שלך.
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
                רצף מחליפה את עבודת הנהלת החשבונות השוטפת בטכנולוגיה שמבצעת עבורך
                התאמות, סיווגים, גבייה, תשלומים ודוחות. במקום לחכות לסוף חודש,
                אתה יודע בכל יום מי שילם, מי חייב, מה עומד לצאת ומה מצב הרווחיות.
              </p>
              <div className="mt-5 grid gap-2 text-sm font-medium text-slate-700 sm:grid-cols-2">
                {[
                  'חיסכון בעלויות הנהלת חשבונות ותפעול כספים',
                  'רווח והפסד יומי, תזרים ודוחות לבנק',
                  'התאמות בנק אוטומטיות וזיהוי חריגות',
                  'סוכן פיננסי שמסביר מה לעשות עכשיו',
                ].map((item) => (
                  <div key={item} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <Check className="h-4 w-4 shrink-0 text-emerald-600" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
              <div className="mt-8 flex flex-wrap gap-3">
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-5 py-3 font-semibold text-white shadow-sm hover:bg-slate-800">
                  הרשמה ובחירת תוכנית <UserPlus className="h-4 w-4" />
                </a>
                <a href="#capabilities" className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-5 py-3 font-semibold text-slate-950 hover:bg-slate-100">
                  לראות את המערכת <Sparkles className="h-4 w-4 text-amber-500" />
                </a>
              </div>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {proofPoints.map((point) => (
                  <ProofPoint key={point.label} {...point} />
                ))}
              </div>
            </div>

            <ProductCockpit />
          </div>
        </section>

        <section className="border-b border-slate-200 bg-slate-950 text-white">
          <div className="mx-auto grid max-w-7xl gap-0 px-5 py-6 md:grid-cols-4">
            {[
              ['Autonomous finance', 'מחליף עבודת הנהלת חשבונות שוטפת'],
              ['Daily P&L', 'רווח והפסד יומי ולא רק בסוף חודש'],
              ['Auto reconciliation', 'התאמות בנק ותיעוד פעולות'],
              ['Cost control', 'פחות עלויות תפעול ויותר שליטה'],
            ].map(([title, text]) => (
              <div key={title} className="border-white/10 py-4 md:border-l md:px-6">
                <div className="text-sm font-semibold text-blue-200">{title}</div>
                <div className="mt-1 text-sm text-white/70">{text}</div>
              </div>
            ))}
          </div>
        </section>

        <section id="capabilities" className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="מה יש בפנים"
            title="המערכת שעושה את עבודת הכספים השוטפת"
            text="רצף לא רק מציגה נתונים. היא מבצעת את העבודה: מזהה פערים, מתאימה תנועות, מסמנת חריגות, מנהלת גבייה, מכינה דוחות ונותנת הוראות פעולה ברורות."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {capabilityGroups.map((group) => (
              <Capability key={group.title} {...group} />
            ))}
          </div>
        </section>

        <section id="workflow" className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <SectionHeading
              eyebrow="איך זה עובד"
              title="כל הכסף, כל המסמכים וכל ההחלטות ברצף אחד."
              text="הרעיון הוא מרכז שליטה תפעולי: קליטה, התאמה, בקרה, אישור פעולה, דוחות חיים והמלצות שמסבירות מה לעשות."
            />
            <div className="mt-8 grid gap-4 lg:grid-cols-3">
              {workflow.map((step, index) => (
                <WorkflowStep key={step.title} index={index + 1} {...step} />
              ))}
            </div>
            <div className="mt-8 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-6">
                <div className="flex items-center gap-3">
                  <ShieldCheck className="h-6 w-6 text-emerald-600" />
                  <h3 className="text-xl font-bold">הנהלת חשבונות שוטפת בלי צוות פנימי כבד</h3>
                </div>
                <p className="mt-3 leading-7 text-slate-600">
                  המערכת מבצעת סיווג, התאמה, מעקב גבייה, בקרת ספקים והכנת דוחות שוטפים.
                  במקום לרדוף אחרי אקסלים וצוות תפעולי יקר, העסק מקבל תמונת מצב יומית ופעולות מוכנות לאישור.
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-6">
                <div className="flex items-center gap-3">
                  <LockKeyhole className="h-6 w-6 text-blue-600" />
                  <h3 className="text-xl font-bold">ארגון נפרד לכל עסק</h3>
                </div>
                <p className="mt-3 leading-7 text-slate-600">
                  כל עסק נפתח בסביבה עצמאית עם משתמשים, הרשאות, נתונים ותהליכי עבודה משלו.
                  מתאים לעסק יחיד, קבוצת חברות או משרד שמנהל כמה תיקים במקביל.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="הסוכן הפיננסי"
            title="לא רק דשבורד. מנהל כספים דיגיטלי שמדבר איתך."
            text="הסוכן מנתח תנועות, גבייה, הוצאות, רווחיות ותזרים. הוא מסביר למה המספר השתנה, איפה יש סיכון ומה הפעולה המומלצת כדי לנהל את העסק טוב יותר."
          />
          <div className="mt-8 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <Sparkles className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-lg font-bold">מה הסוכן עושה בפועל</div>
                  <div className="text-sm text-slate-500">ניתוח, הסבר, התרעה ופעולה</div>
                </div>
              </div>
              <div className="space-y-3">
                {agentInsights.map((insight) => (
                  <div key={insight} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700">
                    {insight}
                  </div>
                ))}
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {[
                ['גבייה', 'מי חייב, כמה זמן, ומה כדאי לשלוח עכשיו כדי להכניס כסף בזמן.'],
                ['רווחיות', 'רווח והפסד יומי, שחיקת מרווחים וזיהוי הוצאות שפוגעות ברווח.'],
                ['בנק', 'התאמות אוטומטיות, חריגות, עמלות, תשלומים לא מזוהים ותנועות חשודות.'],
                ['תזרים', 'תחזית מזומנים, סיכוני מחסור, דחיית ספקים ותזמון גבייה.'],
              ].map(([title, text]) => (
                <div key={title} className="rounded-lg border border-slate-200 bg-slate-50 p-5">
                  <div className="text-lg font-bold">{title}</div>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="plans" className="mx-auto max-w-7xl px-5 py-16">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <SectionHeading
              eyebrow="תמחור"
              title="תוכניות לפי מחזור ותפעול"
              text="המחירים לפני מע״מ. הבחירה נשמרת בהרשמה ומשמשת לפתיחת הארגון והגדרת השירות."
            />
            <div className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 shadow-sm">
              מעל 2.5M: ₪500 לכל מיליון ש"ח נוסף
            </div>
          </div>
          <div className="mt-8 grid gap-4 lg:grid-cols-3">
            {plans.map((plan) => (
              <PlanCard key={plan.id} plan={plan} selected={selectedPlan === plan.id} onSelect={() => setSelectedPlan(plan.id)} />
            ))}
          </div>
        </section>

        <section id="annual-report" className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <SectionHeading
              eyebrow="שירות משלים"
              title="דוח שנתי לחברות ושותפויות"
              text="תבנית שירות להכנת חבילת דוח שנתי על בסיס הנתונים שנצברו במערכת לאורך השנה."
            />
            <div className="mt-8 grid gap-4 lg:grid-cols-2">
              {annualReportTemplates.map((template) => (
                <div key={template.id} className="rounded-lg border border-slate-200 bg-slate-50 p-6">
                  <div className="flex items-center gap-3">
                    <FileCheck2 className="h-6 w-6 text-blue-600" />
                    <h3 className="text-xl font-bold">{template.title}</h3>
                  </div>
                  <div className="mt-5 flex items-end gap-2">
                    <span className="text-4xl font-bold">{template.price}</span>
                    <span className="pb-1 text-sm text-slate-500">לדוח שנתי</span>
                  </div>
                  <p className="mt-4 text-sm leading-6 text-slate-600">{template.note}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="signup" className="bg-slate-950 px-5 py-16 text-white">
          <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[1fr_480px] lg:items-start">
            <div>
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-sm text-blue-200">
                <BadgeCheck className="h-4 w-4" />
                פתיחת ארגון עצמאי עם הרשאות וחיבורים נפרדים
              </div>
              <h2 className="text-4xl font-bold leading-tight">פותחים רצף ומתחילים לנהל כספים אוטומטית.</h2>
              <p className="mt-4 max-w-2xl leading-8 text-white/70">
                התוכנית שנבחרה: <b className="text-white">{selectedPlanName}</b>. אחרי הכניסה נפתח ארגון עצמאי,
                מגדירים משתמשים והרשאות, ומפעילים את תהליכי הכספים של העסק.
              </p>
              <div className="mt-8 grid gap-4 sm:grid-cols-2">
                <SignupPoint icon={Building2} text="ארגון נפרד לכל עסק או לקוח" />
                <SignupPoint icon={Database} text="בסיס נתונים ונתונים org-scoped" />
                <SignupPoint icon={Landmark} text="קליטת נתונים פיננסיים לאחר הכניסה" />
                <SignupPoint icon={TrendingUp} text="תזרים, תחזיות וסוכן המלצות בזמן אמת" />
              </div>
            </div>

            <SignupForm
              mode={mode}
              setMode={setMode}
              selectedPlan={selectedPlan}
              setSelectedPlan={setSelectedPlan}
              annualRevenue={annualRevenue}
              setAnnualRevenue={setAnnualRevenue}
              annualReportRequested={annualReportRequested}
              setAnnualReportRequested={setAnnualReportRequested}
              paymentTemplate={paymentTemplate}
              setPaymentTemplate={setPaymentTemplate}
              email={email}
              setEmail={setEmail}
              password={password}
              setPassword={setPassword}
              fullName={fullName}
              setFullName={setFullName}
              registrationCode={registrationCode}
              setRegistrationCode={setRegistrationCode}
              selectedPlanName={selectedPlanName}
              error={error}
              loading={loading}
              googleButtonRef={googleButtonRef}
              checkout={checkout}
              checkoutLoading={checkoutLoading}
              onPrepareCheckout={prepareCheckout}
              onSubmit={handleSubmit}
            />
          </div>
        </section>
      </main>
    </div>
  );
};

function ProductCockpit() {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 shadow-2xl">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
        <div>
          <div className="text-sm text-slate-500">Rezef Command Center</div>
          <div className="text-lg font-bold">תמונת מצב פיננסית</div>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
          <CheckCircle2 className="h-4 w-4" />
          live controls
        </div>
      </div>
      <div className="grid gap-4 p-5 lg:grid-cols-[1fr_280px]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {commandMetrics.map((metric) => (
              <div key={metric.label} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="text-xs font-medium text-slate-500">{metric.label}</div>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <div className="text-3xl font-bold">{metric.value}</div>
                  <div className={`rounded-full border px-2 py-1 text-xs ${toneClasses[metric.tone]}`}>{metric.delta}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-bold">רווח והפסד מצטבר</div>
                <div className="text-xs text-slate-500">ינואר עד היום · נגזר מהנתונים</div>
              </div>
              <div className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">לבדיקת רו"ח</div>
            </div>
            <div className="flex h-44 items-end gap-2">
              {[42, 58, 37, 72, 64, 81, 76, 92, 69, 88, 98, 84].map((height, index) => (
                <div key={index} className="flex flex-1 flex-col items-center gap-2">
                  <div className="w-full rounded-t bg-blue-500" style={{ height: `${height}%` }} />
                  <div className="h-1 w-full rounded bg-emerald-500" />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-bold">רצף פעולות</span>
              <Sparkles className="h-5 w-5 text-amber-500" />
            </div>
            {[
              ['בנק', 'משיכת תנועות חדשות', 'בוצע'],
              ['גבייה', 'התאמת תקבולים', 'אישור'],
              ['CFO', 'דוח תזרים לבנק', 'מוכן'],
              ['ספקים', 'מס"ב ספקים', 'טיוטה'],
            ].map(([source, action, status]) => (
              <div key={action} className="flex items-center justify-between border-t border-slate-100 py-3 text-sm">
                <div>
                  <div className="font-medium">{action}</div>
                  <div className="text-xs text-slate-500">{source}</div>
                </div>
                <div className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">{status}</div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <div className="flex items-center gap-2 text-sm font-bold text-blue-800">
              <Sparkles className="h-4 w-4" />
              המלצה פיננסית
            </div>
            <p className="mt-3 text-sm leading-6 text-blue-900">
              תשלומי ספקים ב-14 יום הקרובים צורכים מעל 75% מהיתרה. בדקו דחייה לספקים לא קריטיים מול גבייה צפויה.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProofPoint({ label, text, icon: Icon }: { label: string; text: string; icon: LucideIcon }) {
  return (
    <div className="flex gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="text-sm font-bold">{label}</div>
        <div className="mt-1 text-xs leading-5 text-slate-600">{text}</div>
      </div>
    </div>
  );
}

function SectionHeading({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <div className="max-w-3xl">
      <div className="text-sm font-semibold text-blue-600">{eyebrow}</div>
      <h2 className="mt-2 text-3xl font-bold leading-tight text-slate-950 md:text-4xl">{title}</h2>
      <p className="mt-3 leading-7 text-slate-600">{text}</p>
    </div>
  );
}

function Capability({ title, icon: Icon, items }: { title: string; icon: LucideIcon; items: string[] }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
          <Icon className="h-6 w-6" />
        </div>
        <h3 className="text-lg font-bold">{title}</h3>
      </div>
      <ul className="mt-4 space-y-2 text-sm text-slate-600">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WorkflowStep({ index, title, text, icon: Icon }: { index: number; title: string; text: string; icon: LucideIcon }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-6">
      <div className="flex items-center justify-between">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-950 text-white">
          <Icon className="h-6 w-6" />
        </div>
        <div className="text-3xl font-bold text-slate-200">{String(index).padStart(2, '0')}</div>
      </div>
      <h3 className="mt-5 text-xl font-bold">{title}</h3>
      <p className="mt-3 leading-7 text-slate-600">{text}</p>
    </div>
  );
}

function PlanCard({ plan, selected, onSelect }: { plan: typeof plans[number]; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`text-right rounded-xl border p-6 transition ${
        selected ? 'border-blue-500 bg-white shadow-xl shadow-blue-100' : 'border-slate-200 bg-white shadow-sm hover:border-slate-300'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-2xl font-bold">{plan.name}</h3>
        {plan.featured && <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-semibold text-white">מומלץ</span>}
      </div>
      <p className="mt-2 text-sm text-slate-600">{plan.caption}</p>
      <div className="mt-5 flex items-end gap-2">
        <span className="text-4xl font-bold">{plan.price}</span>
        <span className="pb-1 text-sm text-slate-500">{plan.unit}</span>
      </div>
      <ul className="mt-5 space-y-2 text-sm text-slate-600">
        {plan.features.map((feature) => (
          <li key={feature} className="flex gap-2">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            <span>{feature}</span>
          </li>
        ))}
      </ul>
    </button>
  );
}

function SignupForm({
  mode,
  setMode,
  selectedPlan,
  setSelectedPlan,
  annualRevenue,
  setAnnualRevenue,
  annualReportRequested,
  setAnnualReportRequested,
  paymentTemplate,
  setPaymentTemplate,
  email,
  setEmail,
  password,
  setPassword,
  fullName,
  setFullName,
  registrationCode,
  setRegistrationCode,
  selectedPlanName,
  error,
  loading,
  googleButtonRef,
  checkout,
  checkoutLoading,
  onPrepareCheckout,
  onSubmit,
}: {
  mode: 'register' | 'login';
  setMode: (mode: 'register' | 'login') => void;
  selectedPlan: string;
  setSelectedPlan: (value: string) => void;
  annualRevenue: string;
  setAnnualRevenue: (value: string) => void;
  annualReportRequested: boolean;
  setAnnualReportRequested: (value: boolean) => void;
  paymentTemplate: string;
  setPaymentTemplate: (value: string) => void;
  email: string;
  setEmail: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  fullName: string;
  setFullName: (value: string) => void;
  registrationCode: string;
  setRegistrationCode: (value: string) => void;
  selectedPlanName: string;
  error: string | null;
  loading: boolean;
  googleButtonRef: React.RefObject<HTMLDivElement>;
  checkout: CheckoutResponse | null;
  checkoutLoading: boolean;
  onPrepareCheckout: () => void;
  onSubmit: (event: React.FormEvent) => void;
}) {
  const hasCheckout = Boolean(checkout?.checkout_session_id);

  return (
    <form onSubmit={onSubmit} className="rounded-2xl bg-white p-6 text-slate-950 shadow-2xl">
      <div className="mb-5 grid grid-cols-2 rounded-lg bg-slate-100 p-1 text-sm">
        <button type="button" onClick={() => setMode('register')}
          className={`rounded-md px-3 py-2 font-semibold ${mode === 'register' ? 'bg-white shadow-sm' : 'text-slate-500'}`}>
          הרשמה
        </button>
        <button type="button" onClick={() => setMode('login')}
          className={`rounded-md px-3 py-2 font-semibold ${mode === 'login' ? 'bg-white shadow-sm' : 'text-slate-500'}`}>
          התחברות
        </button>
      </div>

      {mode === 'register' && (
        <>
          <LandingSelect label="תוכנית" value={selectedPlan} onChange={setSelectedPlan}>
            {plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name}</option>)}
          </LandingSelect>
          <LandingSelect label="מחזור שנתי" value={annualRevenue} onChange={setAnnualRevenue}>
            <option value="up_to_2_5m">עד 2.5 מיליון ש"ח</option>
            <option value="above_2_5m">מעל 2.5 מיליון ש"ח</option>
          </LandingSelect>
          <LandingSelect label="תבנית תשלום" value={paymentTemplate} onChange={setPaymentTemplate}>
            {paymentTemplates.map((template) => (
              <option key={template.id} value={template.id}>{template.label} - {template.note}</option>
            ))}
          </LandingSelect>
          <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="mb-3 text-sm font-semibold">תשלום מאובטח</div>
            <div className="grid grid-cols-3 gap-2 text-xs">
              {[
                ['apple_pay', 'Apple Pay'],
                ['card', 'כרטיס אשראי'],
                ['google_pay', 'Google Pay'],
              ].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setPaymentTemplate(id)}
                  className={`rounded-lg border px-2 py-2 font-medium transition ${
                    paymentTemplate === id
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={onPrepareCheckout}
              disabled={checkoutLoading}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
            >
              {checkoutLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />}
              {hasCheckout ? 'עדכן checkout' : 'המשך לתשלום מאובטח'}
            </button>
            {checkout && (
              <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800">
                checkout מוכן: {checkout.provider === 'stripe' ? 'תשלום מאובטח' : 'מצב בדיקה'} · session {checkout.checkout_session_id.slice(0, 14)}…
                {checkout.note && <div className="mt-1 text-emerald-700">{checkout.note}</div>}
              </div>
            )}
          </div>
          <label className="mb-4 flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
            <input
              type="checkbox"
              checked={annualReportRequested}
              onChange={(event) => setAnnualReportRequested(event.target.checked)}
              className="mt-1"
            />
            <span>להוסיף תבנית דוח שנתי: ₪3,000 עד 2.5M, ומעל זה ₪500 לכל מיליון ש"ח נוסף.</span>
          </label>
          <LandingInput value={fullName} onChange={setFullName} placeholder="שם מלא" required />
          <LandingInput value={registrationCode} onChange={setRegistrationCode} placeholder="קוד הרשמה אם נדרש" />
        </>
      )}
      <LandingInput type="email" value={email} onChange={setEmail} placeholder="אימייל" required />
      <LandingInput type="password" value={password} onChange={setPassword} placeholder="סיסמה" required minLength={6} />

      {error && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {mode === 'register' && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
          <div className="font-semibold text-slate-950">סיכום הרשמה ותשלום</div>
          <div>תוכנית: {selectedPlanName}</div>
          <div>מחזור: {annualRevenue === 'up_to_2_5m' ? 'עד 2.5 מיליון ש"ח' : 'מעל 2.5 מיליון ש"ח'}</div>
          <div>תשלום: {paymentTemplates.find((template) => template.id === paymentTemplate)?.label}</div>
          <div>Checkout: {hasCheckout ? 'מוכן לפתיחת tenant' : 'טרם הוכן'}</div>
          <div>דוח שנתי: {annualReportRequested ? 'כלול כתבנית שירות' : 'לא נבחר כרגע'}</div>
        </div>
      )}

      <button type="submit" disabled={loading}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-60">
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : mode === 'login' ? <ChevronLeft className="h-4 w-4" /> : <UserPlus className="h-4 w-4" />}
        {mode === 'login' ? 'כניסה למערכת' : `הרשמה ל-${selectedPlanName}`}
      </button>

      {GOOGLE_CLIENT_ID && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="mb-3 text-center text-xs font-medium text-slate-600">
            או הרשמה עם Google, כולל החבילה וה-checkout שנבחרו
          </div>
          <div className="flex justify-center">
          <div ref={googleButtonRef} />
          </div>
        </div>
      )}
    </form>
  );
}

function SignupPoint({ icon: Icon, text }: { icon: LucideIcon; text: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-3 text-sm text-white/80">
      <Icon className="h-5 w-5 text-blue-300" />
      <span>{text}</span>
    </div>
  );
}

function LandingSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="mb-4 block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500">
        {children}
      </select>
    </label>
  );
}

function LandingInput({
  value,
  onChange,
  placeholder,
  type = 'text',
  required = false,
  minLength,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: string;
  required?: boolean;
  minLength?: number;
}) {
  return (
    <input
      type={type}
      required={required}
      minLength={minLength}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="mb-4 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
    />
  );
}

export default RezefLanding;
