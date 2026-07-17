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
  FileSearch,
  Landmark,
  Layers3,
  LineChart,
  Loader2,
  LogIn,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
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

const trustItems = ['הנהלת חשבונות', 'מנהל כספים AI', 'גבייה ותזכורות', 'דיווחים', 'דוחות לבנק', 'רנטגן עסקי בזמן אמת', 'איתור חשבוניות חסרות'];

const painBullets = [
  'משלמים בכל חודש — ומקבלים תמונת מצב כשכבר מאוחר',
  'הגבייה, המסמכים והתשלומים עדיין תלויים במרדף ידני',
  'הכסף בבנק, הנתונים באקסל והתשובות מפוזרים בין אנשים',
  'כל דוח מתחיל מחדש באיסוף, ניקוי ובדיקה של הנתונים',
];

const solutionCards = [
  {
    title: 'הנהלת חשבונות כפולה אוטומטית',
    text: 'פקודות יומן, סיווגים, התאמות ותיעוד פעולות בצורה מסודרת.',
    icon: BookOpen,
  },
  {
    title: 'התאמות בנק ובקרה',
    text: 'קליטת תנועות, התאמה למסמכים והצפה של כל תשלום שאין מולו חשבונית שנקלטה.',
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

const missingExpenseSteps = [
  {
    title: 'רצף רואה את התשלום',
    text: 'תנועות מחשבון הבנק ומכרטיסי האשראי נאספות לתמונה פיננסית אחת.',
    icon: CreditCard,
  },
  {
    title: 'רצף מחפשת את החשבונית',
    text: 'כל תשלום נבדק מול המסמכים שנקלטו ומול נתוני הנהלת החשבונות.',
    icon: FileSearch,
  },
  {
    title: 'מה שחסר קופץ לטיפול',
    text: 'מקבלים רשימה ברורה של הוצאות בלי חשבונית, במקום לגלות אותן מאוחר מדי.',
    icon: AlertTriangle,
  },
];

const businessValuePillars = [
  {
    eyebrow: 'חיסכון בעלויות',
    title: 'הנהלת חשבונות מלאה — בלי העלות המסורתית',
    text: 'רצף מחליפה חלק גדול מהעבודה הידנית והחוזרת של הנהלת החשבונות, ומאפשרת לעסק לחסוך אלפי ואף עשרות אלפי שקלים בשנה בהתאם להיקף הפעילות.',
    icon: CircleDollarSign,
  },
  {
    eyebrow: 'יעילות גבוהה',
    title: 'העבודה הכספית זורמת לבד, מקצה לקצה',
    text: 'בנק, אשראי, מסמכים, התאמות, גבייה, תזכורות והכנת דיווחים מתחברים לתהליך ממוחשב אחד — בלי להעביר קבצים ובלי לרדוף אחרי כל משימה.',
    icon: Workflow,
  },
  {
    eyebrow: 'יותר כלים ושליטה',
    title: 'כלים של מחלקת כספים — גם בלי להחזיק אחת',
    text: 'רווחיות, תקציב, תזרים, גבייה, חריגות, דוחות לבנק ומנהל כספים AI זמינים בכל רגע ומכל מקום, על בסיס אותה תמונה פיננסית.',
    icon: BarChart3,
  },
];

const rezefAdvantages = [
  'ניהול ספרים והנהלת חשבונות שוטפת',
  'סנכרון תנועות בנק וכרטיסי אשראי',
  'התאמות בנק והסבר לכל תנועה',
  'איתור הוצאות וחשבוניות חסרות',
  'גבייה ותזכורות עד שהתשלום נכנס',
  'הכנת דיווחי מע״מ ומעקב מועדי מס',
  'רווח והפסד ורווחיות בכל רגע',
  'תקציב מול ביצוע בזמן אמת',
  'תזרים מזומנים ותחזית קדימה',
  'מנהל כספים AI לשאלות ולהמלצות',
  'התראות על חריגות וסיכונים',
  'דוחות ושקיפות מול הבנק',
  'בקרה מקצועית של יועצים',
  'דוחות אישיים ותכנון מס (בטא)',
];

const financialFreedomMessages = [
  {
    title: 'חיסכון גדול בעלויות הנהלת החשבונות',
    text: 'רצף ממחשבת ומבצעת חלק גדול מהעבודה הידנית והחוזרת, ומצמצמת משמעותית את העלות החודשית של הנהלת החשבונות.',
    icon: CircleDollarSign,
  },
  {
    title: 'מנהל כספים — בלי להעסיק מנהל כספים',
    text: 'מקבלים ניתוח, תזרים, תקציב, בקרה והמלצות של CFO AI, בלי להוסיף לעסק משכורת של מנהל כספים קבוע.',
    icon: Sparkles,
  },
  {
    title: 'דוחות ניהוליים — בלי לחכות לרואה החשבון',
    text: 'רווח והפסד, רווחיות, תקציב מול ביצוע ודוחות פעילות זמינים ישירות במערכת, בלי לבקש ולהמתין שמישהו יכין אותם.',
    icon: FileCheck2,
  },
  {
    title: 'ניהול העסק בזמן אמת, מכל מקום',
    text: 'הנתונים, החריגות והמשימות זמינים מיד מהמחשב או מהטלפון, כדי לקבל החלטות כשהן חשובות — לא שבועות אחר כך.',
    icon: TrendingUp,
  },
];

const betaServices = [
  {
    title: 'דוח אישי מרצף',
    price: '₪500',
    text: 'דוח פיננסי אישי שמרכז את מצב העסק, החריגות, המגמות והפעולות המומלצות.',
    icon: BarChart3,
  },
  {
    title: 'תכנון מס עם רצף',
    price: 'בתיאום',
    text: 'תמונת מס מבוססת נתונים והיערכות מוקדמת לצעדים שכדאי לבדוק לפני סוף התקופה.',
    icon: CircleDollarSign,
  },
];

const capabilityPillars = [
  {
    title: 'הנהלת חשבונות כפולה וספרים',
    text: 'פקודות יומן, סיווגים, מאזן בוחן, רווח והפסד, חומרים למאזן ובקרת שלמות בין כל המסמכים והתנועות.',
    icon: BookOpen,
  },
  {
    title: 'בנק, התאמות ותזרים',
    text: 'קליטת תנועות, התאמות אוטומטיות, מעקב יתרות, תחזיות תזרים, חריגות בנקאיות ודוחות שמוכנים להצגה להנהלה ולבנק.',
    icon: Landmark,
  },
  {
    title: 'גבייה, לקוחות ותשלומים',
    text: 'מעקב מי חייב לנו, חשבוניות פתוחות, בקשות תשלום, סליקה, הוראות קבע, החזרות חיוב והתראות על כסף שלא צפוי להיכנס.',
    icon: CreditCard,
  },
  {
    title: 'ספקים, הוצאות ורכש',
    text: 'קליטת הוצאות, OCR, ספקים, תשלומים צפויים, ניכויים, בקרת חריגות וזיהוי הוצאות כפולות או לא מוסברות.',
    icon: ClipboardCheck,
  },
  {
    title: 'דוחות הנהלה יומיים',
    text: 'רווח והפסד יומי, תקציב מול בפועל, KPI, דוחות יומיים, דוחות שנתיים, השוואות תקופתיות ודשבורדים לכל רמת ניהול.',
    icon: BarChart3,
  },
  {
    title: 'משרד, קבוצות וחברות רבות',
    text: 'ניהול כמה חברות או לקוחות, הרשאות משתמשים, תצוגת על, הפרדת ארגונים ויכולת לעבוד כמשרד CFO או משרד מייצג.',
    icon: Layers3,
  },
  {
    title: 'AI פיננסי וזיהוי חריגות',
    text: 'סוכן CFO שמסביר מה קרה, מזהה אנומליות, מציף סיכונים, ממליץ על פעולות ומתרגם מספרים להחלטות.',
    icon: Sparkles,
  },
  {
    title: 'תפעול עסקי מלא',
    text: 'שכר, מלאי, תשלומים, מס״ב, מסמכים, לקוחות, ספקים, בנק, דוחות ובקרה במקום אחד שמדבר בשפה של העסק.',
    icon: Workflow,
  },
];

const platformProof = [
  '75+ מנועי שירות שמטפלים בלוגיקה העסקית',
  '300+ פעולות API לתהליכי כספים, דוחות ותפעול',
  'בסיס נתונים PostgreSQL עם ORM מלא',
  'אימות JWT מוכן לעבודה מרובת משתמשים',
  '357 בדיקות אוטומטיות שעוברות',
  'מוכן לפרודקשן בענן עם הפרדת ארגונים והרשאות',
];

const marketingMessages = [
  {
    title: 'להפסיק לשלם על עבודה שחוזרת על עצמה',
    text: 'מחליפה עבודה ידנית ומפוצלת שעשויה לעלות לעסק אלפי ואף עשרות אלפי שקלים בשנה.',
  },
  {
    title: 'לקבל CFO — בלי לגייס CFO',
    text: 'מנתחת תזרים, רווחיות וסיכונים ומסבירה מה השתנה, למה זה קרה ומה כדאי לבדוק עכשיו.',
  },
  {
    title: 'לתת למשימות לרוץ — לא לרדוף אחריהן',
    text: 'מטפלת בגבייה, תזכורות, התאמות, מסמכים, דיווחים ומעקב תשלומים במקום לרדוף ידנית.',
  },
  {
    title: 'לדעת מה קורה. ולהבין למה.',
    text: 'נותנת תשובות ברורות על מצב העסק, הלקוחות, ההוצאות, התזרים והפעולות שדורשות תשומת לב.',
  },
  {
    title: 'להגיע לבנק עם תשובות, לא עם הסברים',
    text: 'מייצרת תמונת מצב ודוחות מוכנים לשיתוף, כדי להגיע לשיחה על אשראי עם נתונים ברורים ועדכניים.',
  },
  {
    title: 'לראות את כל העסק — עכשיו',
    text: 'רנטגן של רווחיות, תקציב מול ביצוע ותזרים, בכל שנייה ומכל מקום — בלי לחכות לסוף החודש.',
  },
];

const fitProfiles = [
  {
    title: 'עוסק מורשה שעובד עם רואה חשבון',
    text: 'רצף מנהלת את הכסף לאורך השנה, כדי שרואה החשבון יקבל תיק מסודר — ואתם תקבלו שליטה עוד לפני הדוח השנתי.',
    icon: ClipboardCheck,
  },
  {
    title: 'חברה שמשלמת אלפי שקלים על הנהלת חשבונות',
    text: 'מפסיקים לשלם על הקלדות, מרדפים ובדיקות חוזרות. רצף מבצעת, בודקת ומעדכנת את הנתונים באופן שוטף.',
    icon: BookOpen,
  },
  {
    title: 'חברה פעילה עד ₪10 מיליון מחזור בשנה',
    text: 'מקבלים הנהלת חשבונות, גבייה, תזרים ודוחות ניהול — בלי העלות והמורכבות של מחלקת כספים מלאה.',
    icon: TrendingUp,
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
  ['כמה בעלי תפקידים ומערכות', 'מחלקת כספים במערכת אחת'],
  ['עלות חודשית גבוהה ומפוזרת', 'מסלולים החל מ־₪300 לחודש'],
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

  const goToLogin = () => {
    setMode('login');
    setTimeout(
      () => document.getElementById('signup')?.scrollIntoView({ behavior: 'smooth' }),
      50,
    );
  };

  // Open directly in login mode when arriving at /login (or any *login* path/hash).
  useEffect(() => {
    const loc = window.location;
    if (
      loc.pathname.toLowerCase().includes('login') ||
      loc.hash.toLowerCase().includes('login')
    ) {
      goToLogin();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          <div className="flex items-center gap-4">
            <a href="#top" className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-lg font-bold text-slate-950 shadow-sm">ר</div>
              <div>
                <div className="text-xl font-bold tracking-normal">רצף <span className="text-blue-200">Rezef</span></div>
                <div className="text-xs text-slate-400">Autonomous digital CFO</div>
              </div>
            </a>
            <button
              type="button"
              onClick={goToLogin}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-white shadow-md ring-1 ring-emerald-300/50 hover:bg-emerald-400"
            >
              <LogIn className="h-4 w-4" /> כניסה ללקוחות רשומים
            </button>
          </div>
          <nav className="hidden items-center gap-6 text-sm text-slate-300 lg:flex">
            <a href="#method" className="hover:text-white">השיטה</a>
            <a href="#missing-expenses" className="hover:text-white">חשבוניות חסרות</a>
            <a href="#solution" className="hover:text-white">הפתרון</a>
            <a href="#capabilities" className="hover:text-white">יכולות</a>
            <a href="#command-center" className="hover:text-white">Command Center</a>
            <a href="#plans" className="hover:text-white">תמחור</a>
            <a href="#signup" className="hover:text-white">הרשמה</a>
          </nav>
          <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-400">
            לבדוק התאמה <ArrowLeft className="h-4 w-4" />
          </a>
        </div>
      </header>

      <main id="top">
        <section className="bg-slate-950 text-white">
          <div className="mx-auto grid min-h-[calc(100vh-65px)] max-w-7xl gap-10 px-5 py-12 lg:grid-cols-[0.88fr_1.12fr] lg:items-center">
            <div className="max-w-3xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-sm font-medium text-emerald-200">
                <Sparkles className="h-4 w-4" />
                מנהל כספים + הנהלת חשבונות + כל כלי הניהול
              </div>
              <h1 className="text-4xl font-bold leading-tight tracking-normal text-white md:text-6xl">
                מחליפים מחלקת כספים שלמה במערכת אחת — ובעד חצי מהעלות.
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
                רצף מאחדת את העבודה השוטפת של הנהלת החשבונות עם הניתוח, השליטה והכלים של מנהל הכספים —
                לעוסקים מורשים ולחברות שרוצים לעבוד מהר יותר, לשלם פחות ולדעת תמיד מה קורה בכסף.
              </p>
              <div className="mt-5 rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-lg font-semibold text-blue-100">
                פחות אנשים. פחות מערכות. פחות עלויות. פי כמה יותר אוטומציה, שליטה וכלים.
              </div>
              <div className="mt-8 flex flex-wrap gap-3">
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-5 py-3 font-semibold text-white shadow-sm hover:bg-blue-400">
                  לבדוק כמה רצף יכולה לחסוך לעסק שלי <UserPlus className="h-4 w-4" />
                </a>
                <a href="#method" className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-5 py-3 font-semibold text-white hover:bg-white/10">
                  לראות מה מקבלים <BarChart3 className="h-4 w-4 text-emerald-300" />
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

        <section id="method" className="border-b border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="max-w-4xl">
              <div className="text-sm font-semibold text-blue-600">ההבטחה של רצף</div>
              <h2 className="mt-2 text-3xl font-bold leading-tight text-slate-950 md:text-5xl">
                כל מה שמחלקת כספים עושה — ממוחשב, מחובר וזמין במערכת אחת
              </h2>
              <p className="mt-4 max-w-3xl leading-8 text-slate-600">
                לא עוד אוסף של בעלי תפקידים, מערכות, קבצים ומרדפים. רצף מרכזת את העבודה הכספית של העסק,
                ממחשבת אותה ונותנת לכם כלים שעד היום היו זמינים בעיקר לחברות עם מחלקת כספים.
              </p>
            </div>
            <div className="mt-8 grid gap-4 lg:grid-cols-3">
              {businessValuePillars.map(({ eyebrow, title, text, icon: Icon }) => (
                <div key={eyebrow} className="rounded-lg border border-slate-200 bg-slate-50 p-6">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm font-bold text-blue-600">{eyebrow}</span>
                    <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-slate-950 text-white">
                      <Icon className="h-5 w-5" />
                    </div>
                  </div>
                  <h3 className="mt-5 text-xl font-bold text-slate-950">{title}</h3>
                  <p className="mt-3 text-sm leading-7 text-slate-600">{text}</p>
                </div>
              ))}
            </div>
            <div className="mt-12 rounded-lg border border-slate-200 bg-slate-950 p-6 text-white">
              <div className="max-w-3xl">
                <div className="text-sm font-semibold text-emerald-300">מה מקבלים בפועל?</div>
                <h3 className="mt-2 text-2xl font-bold md:text-3xl">לא יתרון אחד. מערכת שלמה של יתרונות.</h3>
                <p className="mt-3 leading-7 text-slate-300">
                  כל היכולות עובדות על אותה תמונה פיננסית, כך שכל תנועה, מסמך, משימה ותובנה מחוברים זה לזה.
                </p>
              </div>
              <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {rezefAdvantages.map((advantage) => (
                  <div key={advantage} className="flex items-start gap-2 rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-slate-100">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                    <span>{advantage}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="border-b border-blue-500 bg-blue-600 text-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="mx-auto max-w-4xl text-center">
              <div className="text-sm font-semibold text-blue-100">הכול מחובר. הכול זמין. הכול עובד יחד.</div>
              <h2 className="mt-3 text-3xl font-bold leading-tight md:text-5xl">
                מהבנק ועד לדוח. מהחשבונית ועד להחלטה. הכול ברצף.
              </h2>
              <p className="mx-auto mt-4 max-w-3xl leading-8 text-blue-100">
                החיסכון הגדול אינו רק במחיר. הוא גם בזמן, בתלות בבעלי תפקידים ובמהירות שבה העסק מקבל תשובות ופועל.
              </p>
            </div>
            <div className="mt-9 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {financialFreedomMessages.map(({ title, text, icon: Icon }) => (
                <div key={title} className="rounded-lg border border-white/15 bg-white/10 p-5 backdrop-blur-sm">
                  <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-white text-blue-700">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="mt-5 text-lg font-bold">{title}</h3>
                  <p className="mt-3 text-sm leading-7 text-blue-50/85">{text}</p>
                </div>
              ))}
            </div>
            <p className="mt-6 text-center text-xs leading-6 text-blue-100/80">
              רצף מצמצמת את התלות השוטפת במנהל כספים וברואה החשבון לצורך ניהול ודוחות. ביקורת, ייצוג וחתימות מקצועיות נשארים אצל הגורם המוסמך כשנדרש.
            </p>
          </div>
        </section>

        <section id="pain" className="border-b border-slate-200 bg-white">
          <div className="mx-auto grid max-w-7xl gap-8 px-5 py-16 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
            <SectionHeading
              eyebrow="למה זה נחוץ"
              title="כשהמידע מפוזר, גם העבודה מתפזרת — ואף אחד לא רואה את התמונה השלמה"
              text="הכסף בבנק, המסמכים במייל, המעקב באקסל והתמונה אצל רואה החשבון. התוצאה היא מרדף אחרי גבייה וחוסרים, דוחות שמגיעים באיחור והחלטות שמתקבלות בלי כל הנתונים."
            />
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-5">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-blue-700">
                <Workflow className="h-4 w-4" />
                רצף אוספת את כל החלקים — והופכת אותם לעבודה אחת רציפה
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {painBullets.map((item) => (
                  <Bullet key={item} text={item} />
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="missing-expenses" className="border-b border-slate-200 bg-emerald-950 text-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="grid gap-10 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
              <div>
                <div className="text-sm font-semibold text-emerald-300">שלמות: שום הוצאה לא נעלמת בדרך</div>
                <h2 className="mt-2 text-3xl font-bold leading-tight md:text-5xl">
                  הכסף יצא. החשבונית לא נקלטה. רצף מוצאת את הפער.
                </h2>
                <p className="mt-4 max-w-2xl leading-8 text-emerald-50/80">
                  רצף מראה בדיוק אילו חשבוניות חסרות: היא בודקת את התשלומים מול המסמכים ומרכזת את הפערים לטיפול.
                  בעסק עם פעילות שוטפת, איתור הוצאות שלא נקלטו עשוי להצטבר לחיסכון של אלפי ואף עשרות אלפי שקלים.
                </p>
                <div className="mt-6 flex items-start gap-3 rounded-lg border border-emerald-300/20 bg-white/10 p-4">
                  <Users className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" />
                  <div>
                    <div className="font-bold">טכנולוגיה עם גב מקצועי</div>
                    <p className="mt-1 text-sm leading-6 text-emerald-50/75">
                      מאחורי ה־AI פועלים יועצים שעוברים על התיק, בוחנים חריגים ועוזרים להפוך את המידע לפעולות נכונות.
                    </p>
                  </div>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                {missingExpenseSteps.map(({ title, text, icon: Icon }, index) => (
                  <div key={title} className="rounded-lg border border-white/10 bg-white/5 p-5">
                    <div className="flex items-center justify-between">
                      <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-emerald-300 text-emerald-950">
                        <Icon className="h-5 w-5" />
                      </div>
                      <span className="text-3xl font-bold text-white/15">0{index + 1}</span>
                    </div>
                    <h3 className="mt-5 text-lg font-bold">{title}</h3>
                    <p className="mt-2 text-sm leading-6 text-emerald-50/70">{text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="solution" className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="שני תפקידים. מערכת אחת."
            title="מנהלת חשבונות שעושה את העבודה. מנהל כספים שעוזר להחליט."
            text="רצף קולטת ומסווגת, מבצעת התאמות ומכינה את העבודה החשבונאית — ובאותו זמן מנתחת רווחיות ותזרים, מזהה סיכונים ומתרגמת את המספרים להחלטות."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {solutionCards.map((card) => (
              <SolutionCard key={card.title} {...card} />
            ))}
          </div>
        </section>

        <section id="capabilities" className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="grid gap-8 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
              <div>
                <SectionHeading
                  eyebrow="היכולות"
                  title="כל מה שמחלקת כספים עושה. מחובר למערכת אחת."
                  text="רצף בנויה כמערכת תפעול פיננסית מקצה לקצה: הנהלת חשבונות, בנק, גבייה, תשלומים, ספקים, שכר, מלאי, דוחות, תחזיות ובקרה. כל פעולה נכנסת לאותו רצף מספרים, וכל מספר נבדק מול המספרים האחרים."
                />
                <div className="mt-6 rounded-lg border border-blue-200 bg-blue-50 p-5">
                  <div className="mb-3 flex items-center gap-2 text-sm font-bold text-blue-800">
                    <ShieldCheck className="h-4 w-4" />
                    למה זה מרגיש אחרת מתוכנת הנהלת חשבונות רגילה?
                  </div>
                  <p className="text-sm leading-7 text-blue-900">
                    כי רצף לא מסתפקת ברישום הפעולה. היא בודקת אם הכסף נכנס, אם המסמך תואם,
                    אם התשלום חריג, אם התזרים נפגע, ואם יש פעולה שהעסק צריך לבצע עכשיו.
                  </p>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {capabilityPillars.map((item) => (
                  <CapabilityCard key={item.title} {...item} />
                ))}
              </div>
            </div>

            <div className="mt-10 grid gap-4 rounded-lg border border-slate-200 bg-slate-950 p-5 text-white lg:grid-cols-[0.8fr_1.2fr]">
              <div>
                <div className="text-sm font-semibold text-emerald-300">תשתית מוצר</div>
                <h3 className="mt-2 text-2xl font-bold">מתחת לשיווק יש מערכת אמיתית</h3>
                <p className="mt-3 text-sm leading-7 text-slate-300">
                  זה לא prototype של דשבורד. זו שכבת מוצר עם שירותים, הרשאות, בסיס נתונים, API ובדיקות,
                  שמיועדת להחזיק עבודה פיננסית של חברות ולקוחות מרובים.
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {platformProof.map((item) => (
                  <div key={item} className="flex items-start gap-2 rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-slate-100">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="מה משתנה בעסק"
            title="מהנהלת חשבונות בדיעבד — לניהול פיננסי שעובד בכל יום"
            text="רצף מצמצמת עלויות ועבודה ידנית, מנהלת את משימות הכספים ונותנת לבעל העסק תשובות שאפשר לפעול לפיהן."
          />
          <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {marketingMessages.map((message) => (
              <div key={message.title} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                <div className="text-sm font-semibold text-blue-600">{message.title}</div>
                <p className="mt-3 text-sm leading-7 text-slate-700">{message.text}</p>
              </div>
            ))}
          </div>
          <div className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 p-5">
            <div className="text-lg font-bold text-emerald-950">
              מהקליטה וההתאמה, דרך הגבייה והדיווחים, ועד לתזרים ולהחלטה — ברצף אחד.
            </div>
            <p className="mt-2 text-sm leading-7 text-emerald-900">
              רואה החשבון נשאר הגורם המקצועי לביקורת, לייצוג ולחתימה במקומות הנדרשים.
              רצף מחליפה את העבודה השוטפת והידנית ומוסיפה לעסק יכולת ניהול פיננסי יומיומית.
            </p>
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
              eyebrow="אמת: הרנטגן של העסק"
              title="רווחיות, תקציב ותזרים — בכל שנייה, מכל מקום"
              text="לא מחכים לסוף החודש ולא מסתפקים במספר בלי הקשר. רצף מחברת את הבנק, החשבוניות, הגבייה והתקציב לתמונה אחת חיה — ומציגה גם מה חסר ועד כמה הנתונים עדכניים."
            />
            <CommandCenterPanel />
          </div>
        </section>

        <section id="workflow" className="mx-auto max-w-7xl px-5 py-16">
          <SectionHeading
            eyebrow="פעולה: המעגל נסגר"
            title="נתון נכנס. פער מתגלה. משימה מטופלת. התמונה מתעדכנת."
            text="רצף מחברת נתונים, התאמות, משימות ותובנות לתהליך אחד. פעולות משמעותיות נשארות תחת אישור, וכל טיפול חוזר לתמונה הפיננסית ומעדכן אותה."
          />
          <div className="mt-8 grid gap-4 lg:grid-cols-4">
            {workflowSteps.map(([number, title, text]) => (
              <WorkflowStep key={number} number={number} title={title} text={text} />
            ))}
          </div>
        </section>

        <section className="border-y border-slate-200 bg-slate-950 text-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="max-w-3xl">
              <div className="text-sm font-semibold text-emerald-300">נבנתה לעסק שכבר מנהל פעילות אמיתית</div>
              <h2 className="mt-2 text-3xl font-bold leading-tight md:text-4xl">
                השירות הפיננסי הדיגיטלי שלא נעצר בעסק של אדם אחד
              </h2>
              <p className="mt-3 leading-7 text-slate-300">
                רצף מתאימה לעוסק מורשה שעובד עם רואה חשבון, לחברה עם עובדים או שותפים שמשלמת אלפי שקלים על הנהלת חשבונות,
                ולחברה פעילה עד ₪10 מיליון מחזור שצריכה ניהול כספים מלא — בלי להקים מחלקה יקרה.
              </p>
            </div>
            <div className="mt-8 grid gap-4 lg:grid-cols-3">
              {fitProfiles.map(({ title, text, icon: Icon }) => (
                <div key={title} className="rounded-lg border border-white/10 bg-white/5 p-6">
                  <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-emerald-400 text-slate-950">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="mt-5 text-xl font-bold">{title}</h3>
                  <p className="mt-3 text-sm leading-7 text-slate-300">{text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="plans" className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-16">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <SectionHeading
                eyebrow="תמחור"
                title="מחלקת כספים שלמה — בעלות שיכולה להיות פחות מחצי"
                text="מסלול לעוסק מורשה מתחיל ב־₪300 לחודש ומסלול לחברה ב־₪750. מקבלים מערכת אחת שמחברת הנהלת חשבונות, ניהול כספים וכלי שליטה שבדרך כלל מפוזרים בין כמה ספקים ומערכות."
              />
              <div className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-600">
                דוח שנתי: החל מ-₪3,000
              </div>
            </div>
            <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-lg border-2 border-emerald-500 bg-emerald-50 p-6 text-right shadow-xl shadow-emerald-100">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-2xl font-bold">עוסק מורשה</h3>
                  <span className="rounded-full bg-emerald-600 px-3 py-1 text-xs font-semibold text-white">מסלול חדש</span>
                </div>
                <p className="mt-2 min-h-[40px] text-sm leading-5 text-slate-600">עד 2.5 מיליון ש״ח מחזור שנתי</p>
                <div className="mt-5 flex items-end gap-2">
                  <span className="text-4xl font-bold">₪300</span>
                  <span className="pb-1 text-sm text-slate-500">לחודש</span>
                </div>
                <ul className="mt-5 space-y-2 text-sm text-slate-600">
                  {['איתור חשבוניות חסרות', 'התאמות בנק', 'תזרים ותובנות', 'בקרה של יועצים'].map((feature) => (
                    <li key={feature} className="flex gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-5 rounded-lg bg-white px-3 py-2 text-xs leading-5 text-emerald-800">
                  ההצטרפות למסלול תיפתח בקרוב. פרטי המסלול מוצגים כעת בפרסום בלבד.
                </div>
              </div>
              {plans.map((plan) => (
                <PlanCard key={plan.id} plan={plan} selected={selectedPlan === plan.id} onSelect={() => setSelectedPlan(plan.id)} />
              ))}
            </div>
            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              {annualReportTemplates.map((template) => (
                <AnnualReportCard key={template.id} {...template} />
              ))}
            </div>
            <p className="mt-4 text-xs leading-6 text-slate-500">
              * שיעור החיסכון בפועל תלוי בהיקף הפעילות, מספר המסמכים והשירותים שהעסק משלם עליהם כיום.
              {' '}
              * שירות הדוח השנתי מבוצע בשיתוף משרד רואי חשבון חיצוני, לצורך שמירה על אי תלות בין מערכת הנהלת החשבונות
              לבין הגורם המבצע את המאזן והדוח השנתי. המחיר המופחת מתאפשר כאשר הנהלת החשבונות מנוהלת באופן שוטף ומסודר
              ברצף, כך שחבילת העבודה השנתית מגיעה מוכנה, מתועדת ונוחה לבדיקה מקצועית.
            </p>

            <div className="mt-12 border-t border-slate-200 pt-10">
              <SectionHeading
                eyebrow="שירותים חדשים · בטא"
                title="לא רק דוחות. תשובות ופעולות שמותאמות לעסק שלכם."
                text="שירותי הבטא משלבים את נתוני רצף עם מעבר מקצועי, כדי להפוך את המספרים לתמונה אישית ולתכנון קדימה."
              />
              <div className="mt-7 grid gap-4 lg:grid-cols-2">
                {betaServices.map(({ title, price, text, icon: Icon }) => (
                  <div key={title} className="rounded-lg border border-violet-200 bg-violet-50 p-6">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-violet-600 text-white">
                          <Icon className="h-5 w-5" />
                        </div>
                        <h3 className="text-xl font-bold">{title}</h3>
                      </div>
                      <span className="rounded-full bg-violet-600 px-3 py-1 text-xs font-bold text-white">בטא</span>
                    </div>
                    <div className="mt-5 text-3xl font-bold text-violet-950">{price}</div>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{text}</p>
                    <p className="mt-4 text-xs leading-5 text-violet-800">
                      השירות נמצא בתקופת בטא, ניתן בכפוף להתאמה ולבדיקה מקצועית ואינו מחליף ייעוץ מס מוסמך.
                    </p>
                  </div>
                ))}
              </div>
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
              <h2 className="text-4xl font-bold leading-tight">להפסיק לשלם יותר — ולקבל פחות שליטה</h2>
              <p className="mt-4 max-w-2xl leading-8 text-white/70">
                רצף ממחשבת את הנהלת החשבונות ואת ניהול הכספים של העסק: כל מה שקרה, כל מה שחסר וכל מה שצריך לעשות עכשיו — גבייה, דיווחים, דוחות, תזרים ותובנות במערכת אחת.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-5 py-3 font-semibold text-white hover:bg-blue-400">
                  לבדוק את החיסכון לעסק שלי <ArrowLeft className="h-4 w-4" />
                </a>
                <a href="#signup" className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-5 py-3 font-semibold text-white hover:bg-white/10">
                  לקבוע הדגמה <ClipboardCheck className="h-4 w-4" />
                </a>
              </div>
              <div className="mt-8 grid gap-4 sm:grid-cols-2">
                <SignupPoint icon={BuildingIcon} text="ארגון נפרד לכל חברה או לקוח" />
                <SignupPoint icon={Database} text="נתונים והרשאות מופרדים" />
                <SignupPoint icon={Landmark} text="קליטת נתונים פיננסיים לאחר הכניסה" />
                <SignupPoint icon={TrendingUp} text="רנטגן של רווחיות, תקציב ותזרים בזמן אמת" />
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

function CapabilityCard({ title, text, icon: Icon }: { title: string; text: string; icon: LucideIcon }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-5">
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
          <Icon className="h-5 w-5" />
        </div>
        <h3 className="text-base font-bold text-slate-950">{title}</h3>
      </div>
      <p className="text-sm leading-6 text-slate-600">{text}</p>
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
