import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  ArrowLeft,
  Banknote,
  BarChart3,
  BookOpen,
  Building2,
  Check,
  FileCheck2,
  Landmark,
  Loader2,
  LockKeyhole,
  Network,
  Receipt,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  UserPlus,
  WalletCards,
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

const plans = [
  {
    id: 'company_up_to_2_5m',
    name: 'חברה / שותפות',
    price: '₪750',
    caption: 'עד 2.5 מיליון ש"ח מחזור שנתי',
    features: ['כל יכולות רצף לעסק יחיד', 'חיבור SUMIT', 'Open Finance ובנקים', 'התאמות בנק מול SUMIT', 'דוחות CFO ותזרים'],
  },
  {
    id: 'company_above_2_5m',
    name: 'חברה בצמיחה',
    price: '₪750 + ₪500',
    unit: 'לכל מיליון ש"ח נוסף',
    caption: 'מעל 2.5 מיליון ש"ח מחזור שנתי',
    featured: true,
    features: ['בסיס של ₪750 לחודש', 'תוספת ₪500 לכל מיליון ש"ח מעל 2.5M', 'בקרה על מחזור, גבייה ותזרים', 'דוחות לבנק ולניהול', 'AI Insights והתראות'],
  },
  {
    id: 'office',
    name: 'רצף Office',
    price: 'בהתאמה',
    caption: 'למשרד רו"ח או קבוצת חברות',
    features: ['ניהול תיקי לקוחות', 'אדמין רב-ארגוני', 'סנכרון רוחבי', 'דוחות לבנק', 'הרשאות וצוותים'],
  },
];

const capabilityGroups = [
  {
    title: 'ניהול כספים יומיומי',
    icon: WalletCards,
    items: ['חשבוניות, קבלות ומסמכים', 'לקוחות וספקים', 'גבייה וחובות פתוחים', 'תשלומים והוראות קבע', 'רכש, מלאי והוצאות'],
  },
  {
    title: 'CFO ודשבורדים',
    icon: BarChart3,
    items: ['תזרים יומי וחודשי', 'רווח והפסד מצטבר', 'מאזן ומאזן בוחן נגזר', 'תקציב מול ביצוע', 'דוחות לבנק ולניהול'],
  },
  {
    title: 'Open Finance',
    icon: Landmark,
    items: ['תנועות בנק וכרטיסים', 'חיבור חשבונות בהרשאה', 'התאמות בנק', 'זיהוי אנומליות ועמלות', 'תשלומים ופעולות פיננסיות לפי הרשאות'],
  },
  {
    title: 'SUMIT',
    icon: Receipt,
    items: ['מסמכי הנה"ח', 'סליקה וגבייה', 'דוחות חוב לקוחות', 'ניהול הוצאות', 'מלאי, פריטי הכנסה ותשלומים'],
  },
  {
    title: 'בקרה וציות ישראלי',
    icon: ShieldCheck,
    items: ['מע"מ וטיוטות מס', 'PCN874 readiness', 'שכר ודוחות 102/126', 'מס"ב לספקים', 'Audit trail וסטטוס סנכרון'],
  },
  {
    title: 'מנוע חכם',
    icon: Sparkles,
    items: ['תובנות AI', 'התראות חריגות', 'תחזיות', 'סינתזה בין ספרים לבנק', 'זיכרון CFO ארגוני'],
  },
];

const integrationFacts = [
  {
    title: 'SUMIT כמקור אמת חשבונאי',
    text: 'רצף משתמשת ב-SUMIT כשכבת הנהלת החשבונות הרשמית: מסמכים, גבייה, סליקה, תשלומים, דוחות חוב, מלאי והוצאות.',
    href: 'https://app.sumit.co.il/help/developers/swagger/index.html',
  },
  {
    title: 'Open Finance כשכבת בנק',
    text: 'רצף מושכת תנועות בנק, מפיקה תובנות, מריצה התאמות ומכינה dispatch ל-SUMIT במקום להשאיר את הבנק והספרים מנותקים.',
    href: 'https://openfinance-ai.com/',
  },
  {
    title: 'Hub אחד מעל הכל',
    text: 'במקום לעבור בין הנה"ח, בנקים, מס"ב, דוחות ואקסלים, רצף מציגה מצב עסקי, פעולות פתוחות ומה צריך לקרות עכשיו.',
    href: '#capabilities',
  },
];

const proofPoints = [
  ['SUMIT', 'מסמכים, גבייה, סליקה, חובות, הוצאות ומלאי'],
  ['Open Finance', 'בנק, תנועות, תשלומים, תובנות והתאמות'],
  ['CFO', 'תזרים, AR/AP, תקציב, דוחות ותחזיות'],
  ['ישראל', 'מע"מ, מס"ב, שכר, דוחות מס וחשבונית ישראל'],
];

const annualReportTemplates = [
  {
    id: 'annual_report_up_to_2_5m',
    title: 'דוח שנתי לחברה עד 2.5M',
    price: '₪3,000',
    note: 'הכנת חבילת דוח שנתי לחברה או שותפות עד 2.5 מיליון ש"ח מחזור שנתי.',
  },
  {
    id: 'annual_report_above_2_5m',
    title: 'דוח שנתי מעל 2.5M',
    price: '₪3,000 + ₪500',
    note: 'בסיס של ₪3,000 ועוד ₪500 לכל מיליון ש"ח נוסף מעל 2.5M.',
  },
];

const paymentTemplates = [
  { id: 'credit_card', label: 'כרטיס אשראי', note: 'תבנית חיוב חודשי אוטומטי' },
  { id: 'bank_transfer', label: 'העברה בנקאית', note: 'תבנית חשבונית לתשלום ידני' },
  { id: 'standing_order', label: 'הוראת קבע', note: 'תבנית לחיוב קבוע' },
];

const RezefLanding: React.FC<Props> = ({ darkMode: _darkMode, onSuccess }) => {
  const [mode, setMode] = useState<'register' | 'login'>('register');
  const [selectedPlan, setSelectedPlan] = useState('company_above_2_5m');
  const [annualRevenue, setAnnualRevenue] = useState('up_to_2_5m');
  const [annualReportRequested, setAnnualReportRequested] = useState(true);
  const [paymentTemplate, setPaymentTemplate] = useState('credit_card');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [registrationCode, setRegistrationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
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
            : 'ההרשמה נכשלה. בדקו את הפרטים או את קוד ההרשמה.'
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
  }, [mode, registrationCode, selectedPlan]);

  return (
    <div className="min-h-screen bg-[#f7f4ef] text-[#17211f]" dir="rtl">
      <header className="sticky top-0 z-40 border-b border-[#d9d1c4] bg-[#f7f4ef]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
          <a href="#top" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-[#17211f] text-lg font-bold text-white">ר</div>
            <div>
              <div className="text-xl font-bold tracking-normal">רצף <span className="text-[#69736f]">Rezef</span></div>
              <div className="text-xs text-[#69736f]">CFO hub לעסק ישראלי</div>
            </div>
          </a>
          <nav className="hidden items-center gap-6 text-sm text-[#4e5a56] md:flex">
            <a href="#capabilities" className="hover:text-[#17211f]">יכולות</a>
            <a href="#integrations" className="hover:text-[#17211f]">אינטגרציות</a>
            <a href="#plans" className="hover:text-[#17211f]">תוכניות</a>
            <a href="#annual-report" className="hover:text-[#17211f]">דוח שנתי</a>
            <a href="#signup" className="hover:text-[#17211f]">הרשמה</a>
          </nav>
          <a href="#signup" className="inline-flex items-center gap-2 rounded-md bg-[#1d4f43] px-4 py-2 text-sm font-semibold text-white hover:bg-[#183f36]">
            התחילו רצף <ArrowLeft className="h-4 w-4" />
          </a>
        </div>
      </header>

      <main id="top">
        <section className="relative overflow-hidden border-b border-[#d9d1c4]">
          <div className="absolute inset-0 opacity-[0.09]" style={{ backgroundImage: 'radial-gradient(#17211f 1px, transparent 1px)', backgroundSize: '18px 18px' }} />
          <div className="relative mx-auto grid min-h-[calc(100vh-73px)] max-w-7xl gap-10 px-5 py-12 lg:grid-cols-[1fr_0.9fr] lg:items-center">
            <div className="max-w-3xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#c6bba9] bg-white/70 px-3 py-1 text-sm text-[#4e5a56]">
                <Network className="h-4 w-4 text-[#1d4f43]" />
                רצף מחבר הנהלת חשבונות, בנקים, תזרים ותפעול כספים
              </div>
              <h1 className="text-5xl font-bold leading-tight tracking-normal md:text-7xl">
                רצף אחד לכל הכסף של העסק.
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-[#4e5a56]">
                Rezef היא מערכת CFO ו-finance operations שמחברת בין SUMIT, Open Finance, בנקים,
                תשלומים, דוחות, תזרים, גבייה והוצאות. לא עוד איים של נתונים: רצף אחד שמראה מה קרה,
                מה חסר, ומה צריך לבצע עכשיו.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <a href="#signup" className="inline-flex items-center gap-2 rounded-md bg-[#17211f] px-5 py-3 font-semibold text-white hover:bg-[#283330]">
                  הרשמה ובחירת תוכנית <UserPlus className="h-4 w-4" />
                </a>
                <a href="#capabilities" className="inline-flex items-center gap-2 rounded-md border border-[#b9ad9b] bg-white px-5 py-3 font-semibold text-[#17211f] hover:bg-[#f0ebe3]">
                  לראות יכולות <Sparkles className="h-4 w-4" />
                </a>
              </div>
              <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {proofPoints.map(([label, text]) => (
                  <div key={label} className="border-r-2 border-[#1d4f43] pr-3">
                    <div className="text-sm font-bold">{label}</div>
                    <div className="mt-1 text-xs leading-5 text-[#69736f]">{text}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="relative">
              <div className="rounded-md border border-[#c7bdac] bg-[#17211f] p-4 shadow-2xl">
                <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3 text-white">
                  <div>
                    <div className="text-sm text-white/60">Rezef Command Center</div>
                    <div className="text-lg font-semibold">תמונת מצב פיננסית</div>
                  </div>
                  <LockKeyhole className="h-5 w-5 text-emerald-300" />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <PreviewMetric label="תזרים 30 יום" value="₪184K" tone="green" />
                  <PreviewMetric label="חובות לגבייה" value="₪131K" tone="amber" />
                  <PreviewMetric label="התאמות בנק" value="87%" tone="blue" />
                  <PreviewMetric label="מסמכים חריגים" value="6" tone="red" />
                </div>
                <div className="mt-4 rounded-md bg-white p-4 text-[#17211f]">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="font-semibold">רצף הפעולות להיום</span>
                    <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700">חי</span>
                  </div>
                  {[
                    ['Open Finance', 'משיכת תנועות בנק חדשות', 'בוצע'],
                    ['SUMIT', 'התאמת תקבולים לחשבוניות', 'דורש אישור'],
                    ['CFO', 'דוח תזרים לבנק', 'מוכן'],
                    ['AP', 'מס"ב ספקים לתשלום', 'טיוטה'],
                  ].map(([source, action, status]) => (
                    <div key={action} className="flex items-center justify-between border-t border-[#eee8df] py-3 text-sm">
                      <div>
                        <div className="font-medium">{action}</div>
                        <div className="text-xs text-[#69736f]">{source}</div>
                      </div>
                      <div className="rounded-full bg-[#f1eee8] px-2 py-1 text-xs">{status}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="capabilities" className="mx-auto max-w-7xl px-5 py-16">
          <div className="max-w-3xl">
            <h2 className="text-3xl font-bold">מה רצף יודעת לעשות</h2>
            <p className="mt-3 text-[#69736f]">
              זה לא עוד דשבורד. זו שכבת עבודה מעל הנהלת החשבונות, הבנקים והניהול השוטף.
            </p>
          </div>
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {capabilityGroups.map((group) => {
              const Icon = group.icon;
              return (
                <div key={group.title} className="rounded-md border border-[#d7cebf] bg-white p-5">
                  <Icon className="h-6 w-6 text-[#1d4f43]" />
                  <h3 className="mt-4 text-lg font-bold">{group.title}</h3>
                  <ul className="mt-4 space-y-2 text-sm text-[#4e5a56]">
                    {group.items.map((item) => (
                      <li key={item} className="flex items-start gap-2">
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </section>

        <section id="integrations" className="border-y border-[#d9d1c4] bg-[#efe9df]">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="grid gap-8 lg:grid-cols-[0.8fr_1.2fr] lg:items-start">
              <div>
                <h2 className="text-3xl font-bold">מבוססת על מה שכבר עובד</h2>
                <p className="mt-3 leading-7 text-[#5f6965]">
                  SUMIT נשארת מערכת הנהלת החשבונות הרשמית. Open Finance מביא את שכבת הבנק.
                  רצף היא ה-hub שמחבר, מנתח, מסנכרן ומתרגם את הכל לפעולות.
                </p>
              </div>
              <div className="grid gap-4">
                {integrationFacts.map((fact) => (
                  <a key={fact.title} href={fact.href} target={fact.href.startsWith('http') ? '_blank' : undefined} rel="noreferrer"
                    className="rounded-md border border-[#d0c5b4] bg-white p-5 hover:border-[#1d4f43]">
                    <div className="flex items-center gap-3">
                      <FileCheck2 className="h-5 w-5 text-[#1d4f43]" />
                      <h3 className="font-bold">{fact.title}</h3>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-[#5f6965]">{fact.text}</p>
                  </a>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="plans" className="mx-auto max-w-7xl px-5 py-16">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-3xl font-bold">בחרו תוכנית</h2>
              <p className="mt-3 text-[#69736f]">הבחירה נשמרת בהרשמה ותשמש להפעלת הארגון וההרשאות.</p>
            </div>
            <div className="rounded-full border border-[#d7cebf] bg-white px-4 py-2 text-sm text-[#69736f]">
              המחירים לפני מע"מ · מעל 2.5M: ₪500 לכל מיליון ש"ח נוסף
            </div>
          </div>
          <div className="mt-8 grid gap-4 lg:grid-cols-3">
            {plans.map((plan) => (
              <button key={plan.id} type="button" onClick={() => setSelectedPlan(plan.id)}
                className={`text-right rounded-md border p-6 transition ${
                  selectedPlan === plan.id
                    ? 'border-[#1d4f43] bg-white shadow-xl'
                    : 'border-[#d7cebf] bg-white/70 hover:bg-white'
                }`}>
                {plan.featured && <div className="mb-3 inline-flex rounded-full bg-[#1d4f43] px-3 py-1 text-xs font-semibold text-white">מומלץ</div>}
                <h3 className="text-2xl font-bold">{plan.name}</h3>
                <p className="mt-1 text-sm text-[#69736f]">{plan.caption}</p>
                <div className="mt-5 flex items-end gap-1">
                  <span className="text-4xl font-bold">{plan.price}</span>
                  <span className="pb-1 text-sm text-[#69736f]">{plan.unit || 'לחודש'}</span>
                </div>
                <ul className="mt-5 space-y-2 text-sm text-[#4e5a56]">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
              </button>
            ))}
          </div>
        </section>

        <section id="annual-report" className="border-y border-[#d9d1c4] bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h2 className="text-3xl font-bold">דוח שנתי לחברות ושותפויות</h2>
                <p className="mt-3 text-[#69736f]">
                  תבנית שירות נפרדת להכנת חבילת הדוח השנתי על בסיס הנתונים שנאספו ברצף, SUMIT והבנק.
                </p>
              </div>
              <div className="rounded-full bg-[#f1eee8] px-4 py-2 text-sm text-[#5f6965]">
                לפני מע"מ · לפי מחזור שנתי
              </div>
            </div>
            <div className="mt-8 grid gap-4 lg:grid-cols-2">
              {annualReportTemplates.map((template) => (
                <div key={template.id} className="rounded-md border border-[#d7cebf] bg-[#f7f4ef] p-6">
                  <div className="flex items-center gap-3">
                    <FileCheck2 className="h-6 w-6 text-[#1d4f43]" />
                    <h3 className="text-xl font-bold">{template.title}</h3>
                  </div>
                  <div className="mt-5 flex items-end gap-2">
                    <span className="text-4xl font-bold">{template.price}</span>
                    <span className="pb-1 text-sm text-[#69736f]">לדוח שנתי</span>
                  </div>
                  <p className="mt-4 text-sm leading-6 text-[#5f6965]">{template.note}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="signup" className="border-t border-[#d9d1c4] bg-[#17211f] px-5 py-16 text-white">
          <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[1fr_460px] lg:items-start">
            <div>
              <h2 className="text-4xl font-bold">פותחים רצף ומחברים את הכספים.</h2>
              <p className="mt-4 max-w-2xl leading-8 text-white/70">
                הרשמה יוצרת ארגון נפרד, עם אפשרות לחיבור credentials משלו ל-SUMIT ול-Open Finance.
                התוכנית שנבחרה: <b className="text-white">{selectedPlanName}</b>.
              </p>
              <div className="mt-8 grid gap-4 sm:grid-cols-2">
                <SignupPoint icon={Building2} text="ארגון נפרד לכל עסק או לקוח" />
                <SignupPoint icon={Banknote} text="חיבור בנק ו-SUMIT לאחר הכניסה" />
                <SignupPoint icon={BookOpen} text="הנהלת חשבונות כפולה נגזרת ודוחות" />
                <SignupPoint icon={TrendingUp} text="תזרים, תחזיות והתראות בזמן אמת" />
              </div>
            </div>

            <form onSubmit={handleSubmit} className="rounded-md bg-white p-6 text-[#17211f] shadow-2xl">
              <div className="mb-5 flex rounded-md bg-[#f1eee8] p-1 text-sm">
                <button type="button" onClick={() => setMode('register')}
                  className={`flex-1 rounded px-3 py-2 font-semibold ${mode === 'register' ? 'bg-white shadow-sm' : 'text-[#69736f]'}`}>
                  הרשמה
                </button>
                <button type="button" onClick={() => setMode('login')}
                  className={`flex-1 rounded px-3 py-2 font-semibold ${mode === 'login' ? 'bg-white shadow-sm' : 'text-[#69736f]'}`}>
                  התחברות
                </button>
              </div>

              {mode === 'register' && (
                <>
                  <label className="mb-1 block text-sm font-medium">תוכנית</label>
                  <select value={selectedPlan} onChange={(event) => setSelectedPlan(event.target.value)}
                    className="mb-4 w-full rounded-md border border-[#cfc6b8] px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1d4f43]">
                    {plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name}</option>)}
                  </select>
                  <label className="mb-1 block text-sm font-medium">מחזור שנתי</label>
                  <select value={annualRevenue} onChange={(event) => setAnnualRevenue(event.target.value)}
                    className="mb-4 w-full rounded-md border border-[#cfc6b8] px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1d4f43]">
                    <option value="up_to_2_5m">עד 2.5 מיליון ש"ח</option>
                    <option value="above_2_5m">מעל 2.5 מיליון ש"ח</option>
                  </select>
                  <label className="mb-1 block text-sm font-medium">תבנית תשלום</label>
                  <select value={paymentTemplate} onChange={(event) => setPaymentTemplate(event.target.value)}
                    className="mb-4 w-full rounded-md border border-[#cfc6b8] px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1d4f43]">
                    {paymentTemplates.map((template) => (
                      <option key={template.id} value={template.id}>{template.label} - {template.note}</option>
                    ))}
                  </select>
                  <label className="mb-4 flex items-start gap-2 rounded-md bg-[#f7f4ef] p-3 text-sm">
                    <input
                      type="checkbox"
                      checked={annualReportRequested}
                      onChange={(event) => setAnnualReportRequested(event.target.checked)}
                      className="mt-1"
                    />
                    <span>
                      להוסיף תבנית דוח שנתי: ₪3,000 עד 2.5M, ומעל זה ₪500 לכל מיליון ש"ח נוסף.
                    </span>
                  </label>
                  <LandingInput value={fullName} onChange={setFullName} placeholder="שם מלא" required />
                  <LandingInput value={registrationCode} onChange={setRegistrationCode} placeholder="קוד הרשמה אם נדרש" />
                </>
              )}
              <LandingInput type="email" value={email} onChange={setEmail} placeholder="אימייל" required />
              <LandingInput type="password" value={password} onChange={setPassword} placeholder="סיסמה" required minLength={6} />

              {error && <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

              {mode === 'register' && (
                <div className="mb-4 rounded-md border border-[#e0d8ca] bg-[#fbfaf7] p-3 text-xs leading-5 text-[#5f6965]">
                  <div className="font-semibold text-[#17211f]">סיכום תבנית הרשמה ותשלום</div>
                  <div>תוכנית: {selectedPlanName}</div>
                  <div>מחזור: {annualRevenue === 'up_to_2_5m' ? 'עד 2.5 מיליון ש"ח' : 'מעל 2.5 מיליון ש"ח'}</div>
                  <div>תשלום: {paymentTemplates.find((template) => template.id === paymentTemplate)?.label}</div>
                  <div>דוח שנתי: {annualReportRequested ? 'כלול כתבנית שירות' : 'לא נבחר כרגע'}</div>
                </div>
              )}

              <button type="submit" disabled={loading}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-[#1d4f43] px-4 py-3 font-semibold text-white hover:bg-[#183f36] disabled:opacity-60">
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                {mode === 'login' ? 'כניסה למערכת' : `הרשמה ל-${selectedPlanName}`}
              </button>

              {GOOGLE_CLIENT_ID && (
                <div className="mt-4 flex justify-center">
                  <div ref={googleButtonRef} />
                </div>
              )}
            </form>
          </div>
        </section>
      </main>
    </div>
  );
};

function PreviewMetric({ label, value, tone }: { label: string; value: string; tone: 'green' | 'amber' | 'blue' | 'red' }) {
  const colors = {
    green: 'text-emerald-300',
    amber: 'text-amber-300',
    blue: 'text-sky-300',
    red: 'text-rose-300',
  };
  return (
    <div className="rounded-md border border-white/10 bg-white/5 p-4">
      <div className="text-xs text-white/50">{label}</div>
      <div className={`mt-2 text-2xl font-bold ${colors[tone]}`}>{value}</div>
    </div>
  );
}

function SignupPoint({ icon: Icon, text }: { icon: any; text: string }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-white/10 bg-white/5 p-3 text-sm text-white/80">
      <Icon className="h-5 w-5 text-emerald-300" />
      <span>{text}</span>
    </div>
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
      className="mb-4 w-full rounded-md border border-[#cfc6b8] px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1d4f43]"
    />
  );
}

export default RezefLanding;
