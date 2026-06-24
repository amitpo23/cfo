import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleDollarSign,
  ClipboardCheck,
  CreditCard,
  Database,
  FileCheck2,
  Landmark,
  Layers3,
  LineChart,
  Loader2,
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

interface BillingStatusResponse {
  provider: 'stripe' | 'mock';
  production: boolean;
  ready: boolean;
  missing: string[];
  supports: string[];
}

const plans = [
  {
    id: 'company_up_to_2_5m',
    name: 'חברה / שותפות',
    price: '₪750',
    unit: 'לחודש',
    caption: 'עד 2.5 מיליון ש"ח מחזור שנתי',
    featured: false,
    features: ['הנה"ח כפולה', 'התאמות בנק', 'רווח והפסד יומי', 'תזרים וגבייה', 'סוכן CFO AI', 'הכנה למאזן'],
  },
  {
    id: 'company_above_2_5m',
    name: 'חברה בצמיחה',
    price: '₪750 + ₪500',
    unit: 'לכל מיליון ש"ח נוסף',
    caption: 'מעל 2.5 מיליון ש"ח מחזור שנתי',
    featured: true,
    features: ['כל יכולות החברה', 'בקרת מחזור', 'דוחות ניהול', 'דוחות לבנק', 'התראות חריגות', 'תובנות בזמן אמת'],
  },
  {
    id: 'office',
    name: 'Rezef Office',
    price: 'בהתאמה',
    unit: 'למשרד / קבוצה',
    caption: 'למשרדי רו"ח, קבוצות חברות ו-CFO חיצוני',
    featured: false,
    features: ['ניהול כמה ארגונים', 'הרשאות משתמשים', 'תצוגת על לכל הלקוחות', 'עבודה רב-תיקית'],
  },
];

const paymentTemplates = [
  { id: 'apple_pay', label: 'Apple Pay', note: 'תשלום מהיר ומאובטח' },
  { id: 'card', label: 'כרטיס אשראי', note: 'חיוב חודשי אוטומטי' },
  { id: 'google_pay', label: 'Google Pay', note: 'תשלום מהיר ומאובטח' },
  { id: 'bank_transfer', label: 'העברה בנקאית', note: 'חשבונית לתשלום ידני' },
];

const trustItems = ['הנה"ח כפולה', 'התאמות בנק', 'רווח והפסד יומי', 'תזרים', 'הכנה למאזן', 'סוכן CFO AI'];

const painBullets = [
  'לא מחכים לסוף חודש כדי להבין רווחיות',
  'לא רודפים אחרי אקסלים והתאמות ידניות',
  'לא מגלים טעויות אחרי שהנזק כבר קרה',
  'לא משלמים אלפי שקלים על עבודה חוזרת שאפשר לאוטומט',
];

const solutionCards = [
  {
    title: 'הנהלת חשבונות כפולה אוטומטית',
    text: 'פקודות יומן, סיווגים, התאמות ותיעוד פעולות בצורה מסודרת.',
    icon: BookOpen,
  },
  {
    title: 'התאמות בנק ובקרה',
    text: 'קליטת תנועות, התאמה למסמכים, זיהוי פערים, עמלות ופעולות חריגות.',
    icon: Landmark,
  },
  {
    title: 'רווח והפסד יומי',
    text: 'לא מחכים לסוף החודש. רואים רווחיות, הוצאות ומגמות בכל יום.',
    icon: LineChart,
  },
  {
    title: 'תזרים וגבייה',
    text: 'מי חייב כסף, מה צפוי להיכנס, מה עומד לצאת ואיפה יש סיכון תזרימי.',
    icon: CircleDollarSign,
  },
  {
    title: 'סוכן CFO AI',
    text: 'המערכת מסבירה מה קרה, איפה הבעיה ומה הפעולה המומלצת.',
    icon: Sparkles,
  },
  {
    title: 'הכנה למאזן ולרו"ח',
    text: 'חומר מסודר, דוחות, מאזן בוחן וחבילת עבודה שנתית.',
    icon: FileCheck2,
  },
];

const anomalyItems = [
  'חיובים כפולים',
  'הוצאות חריגות',
  'לקוחות מאחרים',
  'פערים בהתאמות בנק',
  'שחיקה ברווחיות',
  'סיכון תזרימי',
  'טעויות סיווג',
  'תשלומים לא מזוהים',
];

const comparisonRows = [
  ['עובד בדיעבד', 'עובדת כל יום'],
  ['תלוי באקסלים', 'הכול במערכת אחת'],
  ['בדיקה מדגמית', 'בודקת כל פעולה'],
  ['דוחות בסוף חודש', 'רווח והפסד יומי'],
  ['מציג מספרים', 'מסבירה מה לעשות'],
  ['עולה אלפי שקלים בחודש', 'החל מ-₪750 לחודש'],
];

const commandMetrics = [
  { label: 'תזרים 30 יום', value: '₪184K', detail: '+12% מול תחזית', tone: 'emerald' },
  { label: 'מי חייב לנו', value: '₪131K', detail: '11 חשבוניות פתוחות', tone: 'amber' },
  { label: 'התאמות אוטומטיות', value: '87%', detail: '42 תנועות נסגרו', tone: 'blue' },
  { label: 'חריגות לטיפול', value: '6', detail: '2 קריטיות', tone: 'rose' },
];

const workflowSteps = [
  ['01', 'מושכים נתונים', 'בנק, חשבוניות, קבלות, ספקים, לקוחות והוצאות נכנסים למפה פיננסית אחת.'],
  ['02', 'רצף מתאימה ומסווגת', 'המערכת מחברת תשלומים למסמכים, מזהה חריגות ומכינה פקודות יומן.'],
  ['03', 'מאשרים פעולות', 'המשתמש מאשר התאמות, תשלומים, סיווגים ודוחות לפני העברה סופית.'],
  ['04', 'מקבלים תובנות', 'ה-CFO הדיגיטלי מסביר מה השתנה, מה דורש טיפול ומה כדאי לעשות.'],
];

const annualReportTemplates = [
  {
    id: 'annual_report_up_to_2_5m',
    title: 'דוח שנתי עד 2.5M',
    price: '₪3,000',
    note: 'חבילת דוח שנתי לחברה או שותפות עד 2.5 מיליון ש"ח מחזור.',
  },
  {
    id: 'annual_report_above_2_5m',
    title: 'דוח שנתי מעל 2.5M',
    price: '₪3,000 + ₪500',
    note: '₪3,000 בסיס ועוד ₪500 לכל מיליון ש"ח נוסף מעל 2.5M.',
  },
];

const toneClasses: Record<string, string> = {
  emerald: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200',
  amber: 'border-amber-400/25 bg-amber-400/10 text-amber-200',
  blue: 'border-blue-400/25 bg-blue-400/10 text-blue-200',
  rose: 'border-rose-400/25 bg-rose-400/10 text-rose-200',
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
  const [billingStatus, setBillingStatus] = useState<BillingStatusResponse | null>(null);
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

  useEffect(() => {
    let cancelled = false;
    axios
      .get<BillingStatusResponse>(`${API_BASE_URL}/admin/billing/status`)
      .then(({ data }) => {
        if (!cancelled) setBillingStatus(data);
      })
      .catch(() => {
        if (!cancelled) setBillingStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
      <header className="sticky top-0 z-40 border-b border-white/10 bg-slate-950/92 text-white backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3">
          <a href="#top" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-lg font-bold text-slate-950 shadow-sm">ר</div>
            <div>
              <div className="text-xl font-bold tracking-normal">רצף <span className="text-blue-200">Rezef</span></div>
              <div className="text-xs text-slate-400">Autonomous digital CFO</div>
            </div>
          </a>
          <nav className="hidden items-center gap-6 text-sm text-slate-300 lg:flex">
            <a href="#pain" className="hover:text-white">הכאב</a>
            <a href="#solution" className="hover:text-white">הפתרון</a>
            <a href="#command-center" className="hover:text-white">Command Center</a>
            <a href="#plans" className="hover:text-white">תמחור</a>
            <a href="#signup" className="hover:text-white">הרשמה</a>
          </nav>
          <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-400">
            להתחיל עם רצף <ArrowLeft className="h-4 w-4" />
          </a>
        </div>
      </header>

      <main id="top">
        <section className="bg-slate-950 text-white">
          <div className="mx-auto grid min-h-[calc(100vh-65px)] max-w-7xl gap-10 px-5 py-12 lg:grid-cols-[0.88fr_1.12fr] lg:items-center">
            <div className="max-w-3xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-sm font-medium text-emerald-200">
                <Sparkles className="h-4 w-4" />
                רצף היא לא עוד תוכנת הנהלת חשבונות
              </div>
              <h1 className="text-4xl font-bold leading-tight tracking-normal text-white md:text-6xl">
                CFO דיגיטלי שמנהל את הכסף של החברה — החל מ-₪750 לחודש
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
                רצף מחליפה תהליך הנהלת חשבונות ידני ויקר במערכת אוטומטית שמבצעת הנהלת חשבונות כפולה,
                התאמות בנק, דוחות, גבייה, תזרים ותובנות AI בזמן אמת.
              </p>
              <div className="mt-5 rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-lg font-semibold text-blue-100">
                מנהל חשבונות רושם את העבר. רצף עוזרת לנהל את העתיד.
              </div>
              <div className="mt-8 flex flex-wrap gap-3">
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-5 py-3 font-semibold text-white shadow-sm hover:bg-blue-400">
                  להתחיל עם רצף <UserPlus className="h-4 w-4" />
                </a>
                <a href="#command-center" className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-5 py-3 font-semibold text-white hover:bg-white/10">
                  לראות את המערכת <BarChart3 className="h-4 w-4 text-emerald-300" />
                </a>
              </div>
              <div className="mt-8 flex flex-wrap gap-2 text-sm text-slate-300">
                {trustItems.map((item) => (
                  <span key={item} className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                    {item}
                  </span>
                ))}
              </div>
            </div>

            <CommandCenterMockup />
          </div>
        </section>

        <section id="pain" className="border-b border-slate-200 bg-white">
          <div className="mx-auto grid max-w-7xl gap-8 px-5 py-16 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
            <SectionHeading
              eyebrow="הכאב"
              title="למה לשלם אלפי שקלים בחודש ועדיין לא לדעת מה קורה בעסק?"
              text="ברוב החברות הנהלת החשבונות מתבצעת בדיעבד. בסוף החודש מקבלים דוחות, אבל הבעיות כבר קרו: לקוחות שלא שילמו, הוצאות חריגות, חיובים כפולים, טעויות התאמה ולחץ תזרימי."
            />
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-5">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-blue-700">
                <Workflow className="h-4 w-4" />
                רצף הופכת את התהליך ליומי, אוטומטי וחכם
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {painBullets.map((item) => (
                  <Bullet key={item} text={item} />
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="solution" className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="הפתרון"
            title="רצף לא רק מנהלת ספרים. היא מנהלת את הכסף."
            text="המערכת קולטת תנועות בנק, חשבוניות, קבלות, ספקים, לקוחות והוצאות — ומחברת הכול לתמונה פיננסית אחת. היא מבצעת התאמות, יוצרת פקודות יומן, בודקת חריגות, מנהלת גבייה ומכינה חומר מסודר לרו״ח ולמאזן."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {solutionCards.map((card) => (
              <SolutionCard key={card.title} {...card} />
            ))}
          </div>
        </section>

        <section className="border-y border-slate-200 bg-slate-950 text-white">
          <div className="mx-auto grid max-w-7xl gap-8 px-5 py-16 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
            <div>
              <div className="text-sm font-semibold text-emerald-300">ההבטחה</div>
              <h2 className="mt-2 text-3xl font-bold leading-tight md:text-4xl">
                מה אם מנהל החשבונות שלך היה בודק 100% מהפעולות?
              </h2>
              <p className="mt-4 leading-8 text-slate-300">
                מנהל חשבונות אנושי לא באמת יכול לעבור כל יום על כל תנועה, כל חיוב, כל עמלה,
                כל לקוח וכל ספק. רצף כן.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {anomalyItems.map((item) => (
                <div key={item} className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-slate-100">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-300" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="השוואה"
            title="תהליך ידני מול רצף"
            text="ההבדל הוא לא רק מחיר. ההבדל הוא מעבר מעבודה בדיעבד לבקרה יומית שמסבירה מה לעשות."
          />
          <div className="mt-8 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="grid grid-cols-2 bg-slate-950 px-4 py-3 text-sm font-semibold text-white">
              <div>תהליך ידני</div>
              <div>רצף</div>
            </div>
            {comparisonRows.map(([manual, rezef]) => (
              <div key={manual} className="grid grid-cols-1 border-b border-slate-200 last:border-b-0 md:grid-cols-2">
                <div className="border-b border-slate-100 p-4 text-sm text-slate-600 md:border-b-0 md:border-l">{manual}</div>
                <div className="bg-emerald-50 p-4 text-sm font-semibold text-emerald-900">{rezef}</div>
              </div>
            ))}
          </div>
        </section>

        <section id="command-center" className="border-y border-slate-200 bg-white">
          <div className="mx-auto grid max-w-7xl gap-8 px-5 py-16 lg:grid-cols-[0.85fr_1.15fr] lg:items-center">
            <SectionHeading
              eyebrow="Command Center"
              title="תמונת מצב פיננסית אחת לכל החברה"
              text="במקום לפזר נתונים בין בנק, חשבוניות, אקסלים, רו״ח ומיילים — רצף מרכזת את כל המספרים במקום אחד."
            />
            <CommandCenterPanel />
          </div>
        </section>

        <section id="workflow" className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="איך זה עובד"
            title="כל מספר נבדק מול כל מספר אחר"
            text="רצף בונה שכבה אחת שמחברת נתונים, התאמות, פעולות ותובנות — ואז משאירה למשתמש לאשר את מה שחשוב."
          />
          <div className="mt-8 grid gap-4 lg:grid-cols-4">
            {workflowSteps.map(([number, title, text]) => (
              <WorkflowStep key={number} number={number} title={title} text={text} />
            ))}
          </div>
        </section>

        <section id="plans" className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <SectionHeading
                eyebrow="תמחור"
                title="מחיר של תוכנה. עבודה של מחלקת כספים."
                text="מתחילים במחיר ברור, מקבלים הנהלת חשבונות כפולה, התאמות בנק, רווח והפסד יומי, תזרים וסוכן CFO AI."
              />
              <div className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-600">
                דוח שנתי: החל מ-₪3,000
              </div>
            </div>
            <div className="mt-8 grid gap-4 lg:grid-cols-3">
              {plans.map((plan) => (
                <PlanCard key={plan.id} plan={plan} selected={selectedPlan === plan.id} onSelect={() => setSelectedPlan(plan.id)} />
              ))}
            </div>
            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              {annualReportTemplates.map((template) => (
                <AnnualReportCard key={template.id} {...template} />
              ))}
            </div>
          </div>
        </section>

        <section className="bg-slate-950 px-5 py-16 text-white">
          <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[1fr_480px] lg:items-start">
            <div>
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-sm text-blue-200">
                <ShieldCheck className="h-4 w-4" />
                CFO דיגיטלי לחברה שעובדת בזמן אמת
              </div>
              <h2 className="text-4xl font-bold leading-tight">תפסיקו לנהל את הכסף בדיעבד</h2>
              <p className="mt-4 max-w-2xl leading-8 text-white/70">
                רצף נותנת לחברה שלך הנהלת חשבונות, בקרה, תזרים ותובנות בזמן אמת — במחיר שמתחיל מ-₪750 לחודש.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-5 py-3 font-semibold text-white hover:bg-blue-400">
                  להתחיל עכשיו <ArrowLeft className="h-4 w-4" />
                </a>
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-5 py-3 font-semibold text-white hover:bg-white/10">
                  לקבוע הדגמה <ClipboardCheck className="h-4 w-4" />
                </a>
              </div>
              <div className="mt-8 grid gap-4 sm:grid-cols-2">
                <SignupPoint icon={BuildingIcon} text="ארגון נפרד לכל חברה או לקוח" />
                <SignupPoint icon={Database} text="נתונים והרשאות מופרדים" />
                <SignupPoint icon={Landmark} text="קליטת נתונים פיננסיים לאחר הכניסה" />
                <SignupPoint icon={TrendingUp} text="תזרים ותובנות בזמן אמת" />
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
              billingStatus={billingStatus}
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

const BuildingIcon = Layers3;

function CommandCenterMockup() {
  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] shadow-2xl">
      <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.04] px-5 py-4">
        <div>
          <div className="text-sm text-slate-400">Rezef Command Center</div>
          <div className="text-lg font-bold text-white">תמונת מצב פיננסית</div>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-sm font-medium text-emerald-200">
          <CheckCircle2 className="h-4 w-4" />
          live CFO
        </div>
      </div>
      <div className="grid gap-4 p-5 lg:grid-cols-[1fr_280px]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {commandMetrics.map((metric) => (
              <Metric key={metric.label} {...metric} dark />
            ))}
          </div>
          <div className="rounded-lg border border-white/10 bg-slate-900 p-4">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-bold text-white">רווח והפסד מצטבר</div>
                <div className="text-xs text-slate-400">ינואר עד היום</div>
              </div>
              <div className="rounded-full bg-white/5 px-3 py-1 text-xs text-slate-300">Daily P&L</div>
            </div>
            <div className="flex h-44 items-end gap-2">
              {[42, 58, 37, 72, 64, 81, 76, 92, 69, 88, 98, 84].map((height, index) => (
                <div key={height + index} className="flex flex-1 flex-col items-center gap-2">
                  <div className="w-full rounded-t bg-blue-400" style={{ height: `${height}%` }} />
                  <div className="h-1 w-full rounded bg-emerald-400" />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="space-y-4">
          <div className="rounded-lg border border-white/10 bg-slate-900 p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-bold text-white">רצף פעולות</span>
              <Sparkles className="h-5 w-5 text-amber-300" />
            </div>
            {[
              ['בנק', 'משיכת תנועות חדשות', 'בוצע'],
              ['גבייה', 'התאמת תקבולים', 'אישור'],
              ['CFO', 'דוח תזרים לבנק', 'מוכן'],
              ['ספקים', 'תשלומים קרובים', 'סיכון'],
            ].map(([source, action, status]) => (
              <div key={action} className="flex items-center justify-between border-t border-white/10 py-3 text-sm">
                <div>
                  <div className="font-medium text-white">{action}</div>
                  <div className="text-xs text-slate-400">{source}</div>
                </div>
                <div className="rounded-full bg-white/5 px-2 py-1 text-xs text-slate-300">{status}</div>
              </div>
            ))}
          </div>
          <div className="rounded-lg border border-blue-400/25 bg-blue-400/10 p-4">
            <div className="flex items-center gap-2 text-sm font-bold text-blue-100">
              <Sparkles className="h-4 w-4" />
              המלצה פיננסית
            </div>
            <p className="mt-3 text-sm leading-6 text-blue-100/85">
              תשלומי ספקים ב-14 יום הקרובים צורכים מעל 75% מהיתרה. בדקו דחייה לספקים לא קריטיים מול גבייה צפויה.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function CommandCenterPanel() {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-950 p-5 text-white shadow-xl">
      <div className="grid gap-3 sm:grid-cols-2">
        {commandMetrics.map((metric) => (
          <Metric key={metric.label} {...metric} dark />
        ))}
      </div>
      <div className="mt-4 rounded-lg border border-white/10 bg-white/5 p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-bold">רווח והפסד מצטבר</div>
            <div className="text-xs text-slate-400">ינואר עד היום</div>
          </div>
          <LineChart className="h-5 w-5 text-emerald-300" />
        </div>
        <div className="flex h-32 items-end gap-2">
          {[42, 58, 37, 72, 64, 81, 76, 92, 69, 88, 98, 84].map((height, index) => (
            <div key={height + index} className="w-full rounded-t bg-blue-400" style={{ height: `${height}%` }} />
          ))}
        </div>
      </div>
      <div className="mt-4 rounded-lg border border-blue-400/25 bg-blue-400/10 p-4 text-sm leading-6 text-blue-100">
        <b>המלצה פיננסית:</b> תשלומי ספקים ב-14 יום הקרובים צורכים מעל 75% מהיתרה. בדקו דחייה לספקים לא קריטיים מול גבייה צפויה.
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: string;
  dark?: boolean;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4">
      <div className="text-xs font-medium text-slate-400">{label}</div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="text-3xl font-bold text-white">{value}</div>
        <div className={`rounded-full border px-2 py-1 text-xs ${toneClasses[tone]}`}>{detail}</div>
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

function Bullet({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm font-medium text-slate-700">
      <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
      <span>{text}</span>
    </div>
  );
}

function SolutionCard({ title, text, icon: Icon }: { title: string; text: string; icon: LucideIcon }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
        <Icon className="h-6 w-6" />
      </div>
      <h3 className="text-lg font-bold text-slate-950">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
    </div>
  );
}

function WorkflowStep({ number, title, text }: { number: string; title: string; text: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-5 flex items-center justify-between">
        <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-slate-950 text-white">
          <Workflow className="h-5 w-5" />
        </div>
        <div className="text-3xl font-bold text-slate-200">{number}</div>
      </div>
      <h3 className="text-lg font-bold">{title}</h3>
      <p className="mt-3 text-sm leading-6 text-slate-600">{text}</p>
    </div>
  );
}

function PlanCard({ plan, selected, onSelect }: { plan: typeof plans[number]; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`text-right rounded-lg border p-6 transition ${
        selected ? 'border-blue-500 bg-white shadow-xl shadow-blue-100' : 'border-slate-200 bg-white shadow-sm hover:border-slate-300'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-2xl font-bold">{plan.name}</h3>
        {plan.featured && <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-semibold text-white">מומלץ</span>}
      </div>
      <p className="mt-2 min-h-[40px] text-sm leading-5 text-slate-600">{plan.caption}</p>
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

function AnnualReportCard({ title, price, note }: { title: string; price: string; note: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-5">
      <div className="flex items-center gap-3">
        <FileCheck2 className="h-5 w-5 text-blue-600" />
        <h3 className="text-lg font-bold">{title}</h3>
      </div>
      <div className="mt-4 text-3xl font-bold">{price}</div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{note}</p>
    </div>
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
  billingStatus,
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
  billingStatus: BillingStatusResponse | null;
  checkoutLoading: boolean;
  onPrepareCheckout: () => void;
  onSubmit: (event: React.FormEvent) => void;
}) {
  const hasCheckout = Boolean(checkout?.checkout_session_id);
  const liveBillingReady = billingStatus?.ready ?? false;
  const billingBlocked = billingStatus?.production && !billingStatus.ready;

  return (
    <form id="signup" onSubmit={onSubmit} className="rounded-lg bg-white p-6 text-slate-950 shadow-2xl">
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
          <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="mb-3 text-sm font-semibold">תשלום מאובטח</div>
            <div className={`mb-3 rounded-lg border px-3 py-2 text-xs leading-5 ${
              liveBillingReady
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : billingBlocked
                  ? 'border-amber-200 bg-amber-50 text-amber-800'
                  : 'border-blue-200 bg-blue-50 text-blue-800'
            }`}>
              {liveBillingReady
                ? 'גבייה חיה פעילה: כרטיס אשראי וארנקים דיגיטליים זמינים ב-checkout.'
                : billingBlocked
                  ? 'גבייה חיה עדיין מחכה להגדרת סודות תשלום, Price IDs ואימות דומיין לארנקים דיגיטליים.'
                  : 'ב-preview/local אפשר לבדוק onboarding עם checkout מדומה; בפרודקשן נדרש חיבור תשלום חי.'}
            </div>
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
                checkout מוכן: {checkout.provider === 'stripe' ? 'תשלום מאובטח' : 'מצב בדיקה'} · session {checkout.checkout_session_id.slice(0, 14)}...
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
          <div>גבייה חיה: {liveBillingReady ? 'פעילה' : billingBlocked ? 'דורשת הגדרות בפרודקשן' : 'מצב בדיקה/הכנה'}</div>
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
    <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80">
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
