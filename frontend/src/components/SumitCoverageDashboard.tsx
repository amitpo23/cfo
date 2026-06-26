import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  CreditCard,
  Database,
  FileSpreadsheet,
  Filter,
  Landmark,
  Mail,
  Search,
  ShieldCheck,
  Users,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { FinanceCard, FinancePageShell, MetricCard, cls } from './finance-ui';

type CoverageStatus = 'ready' | 'partial' | 'blocked';

interface CoverageItem {
  module: string;
  category: string;
  status: CoverageStatus;
  capability: string;
  codeSurface: string;
  nextStep: string;
}

const coverageItems: CoverageItem[] = [
  {
    module: 'לקוחות / CRM',
    category: 'ניהול עסק',
    status: 'ready',
    capability: 'יצירה, עדכון, פרטי לקוח, הערות, חוב לקוח וכתובת פעולה.',
    codeSurface: 'accounting.py + SumitIntegration.create_customer/update_customer/get_debt',
    nextStep: 'להוסיף מסך פרופיל לקוח שמרכז חוב, מסמכים, תשלומים והערות.',
  },
  {
    module: 'הכנסות ומסמכים',
    category: 'ניהול עסק',
    status: 'ready',
    capability: 'חשבונית, קבלה, הצעת מחיר, זיכוי, PDF, שליחה, ביטול והעברה לספרים.',
    codeSurface: 'accounting.py + financial_operations.py + /accounting/documents/*',
    nextStep: 'להרחיב UI לתרחישי מסמכים עתידיים ותשלומים בתשלומים.',
  },
  {
    module: 'הוצאות וספקים',
    category: 'ניהול עסק',
    status: 'ready',
    capability: 'תיוק הוצאות, OCR, סיווג, מעקב ספקים, AP ופקודות נגזרות.',
    codeSurface: 'ExpenseFiling + CFOAPDashboard + add_expense/OCR pipeline',
    nextStep: 'לחבר SLA ספקים והתראות לפי חוזים/הסכמים.',
  },
  {
    module: 'גבייה וסליקת אשראי',
    category: 'גבייה',
    status: 'ready',
    capability: 'חיוב לקוח, קריאת תשלום, רשימת תשלומים, שמירת אמצעי תשלום ועמוד redirect.',
    codeSurface: 'payments.py + /billing/payments/charge/list/get/beginredirect',
    nextStep: 'להוסיף reconcile אוטומטי בין תשלום, חשבונית ותנועה בנקאית.',
  },
  {
    module: 'Apple Pay / Google Pay / כרטיס',
    category: 'גבייה',
    status: 'partial',
    capability: 'ב-Rezef checkout מוכן עם Stripe Checkout וארנקים דיגיטליים כאשר החשבון והדומיין מוגדרים.',
    codeSurface: 'admin.py /billing/checkout + /billing/status',
    nextStep: 'להגדיר STRIPE_SECRET_KEY, Price IDs, payment methods ואימות דומיין בפרודקשן.',
  },
  {
    module: 'דפי תשלום',
    category: 'גבייה',
    status: 'partial',
    capability: 'יש redirect תשלום וחיבור תשלום למסמך/לקוח; חסר builder ציבורי לדפי תשלום מותאמים.',
    codeSurface: 'begin_payment_redirect + PaymentInterface',
    nextStep: 'לבנות מסך יצירת דף תשלום עם סכום, לקוח, מסמך וקישור לשיתוף.',
  },
  {
    module: 'הוראות קבע',
    category: 'גבייה',
    status: 'ready',
    capability: 'רשימת הוראות ללקוח, עדכון, ביטול והגדרות recurring.',
    codeSurface: 'payments.py + SumitIntegration.list_customer_recurring/update_recurring/cancel_recurring',
    nextStep: 'להוסיף מסך ניהול מחזורי מלא עם next charge וסיכוני כשל.',
  },
  {
    module: 'החזרות / הכחשות / ביטולים',
    category: 'גבייה',
    status: 'partial',
    capability: 'רשימת תשלומים וסטטוסים קיימת; חסרים webhooks/התראות ייעודיות להכחשות והחזרים.',
    codeSurface: 'list_payments + payment status models',
    nextStep: 'להוסיף sync job להתראות failed/refunded/chargeback ומשימות גבייה.',
  },
  {
    module: 'חיוב והרשאות מס"ב',
    category: 'גבייה',
    status: 'partial',
    capability: 'קיים מסך תשלומי ספקים ויצירת קובץ מס"ב; הרשאות חיוב לקוח והחזרות מס"ב דורשות הרחבת מודל.',
    codeSurface: 'MasavDashboard + masav.py',
    nextStep: 'להוסיף mandates, failures, lifecycle והתראות שינוי הרשאה.',
  },
  {
    module: 'BlueSnap / PayPal / Bit',
    category: 'גבייה',
    status: 'blocked',
    capability: 'לא מופיע כרגע adapter ייעודי בקוד המקומי.',
    codeSurface: 'אין route/integration ייעודי',
    nextStep: 'להוסיף adapters או להשאיר דרך provider תשלום מרכזי עם webhooks למסמכים.',
  },
  {
    module: 'תקציב',
    category: 'ניהול עסק',
    status: 'ready',
    capability: 'הזנת תקציב, השוואה מול ביצוע, ניתוח סטיות ותחזית.',
    codeSurface: 'BudgetDashboard + BudgetEntry + YearComparison',
    nextStep: 'להוסיף approval workflow לשינויי תקציב.',
  },
  {
    module: 'מלאי',
    category: 'ניהול עסק',
    status: 'ready',
    capability: 'רשימת מלאי קיימת וסטטוס מלאי לפי נתוני המערכת.',
    codeSurface: 'InventoryDashboard + /admin/stock/list + /stock/stock/list',
    nextStep: 'לחבר הזמנות רכש, תנועות מלאי ועלות מלאי לדוחות רווחיות.',
  },
  {
    module: 'שיקים ומזומנים',
    category: 'ניהול עסק',
    status: 'partial',
    capability: 'ניתן לייצג כתשלומים/מסמכים, אך חסר קופת שיקים ומזומנים ייעודית.',
    codeSurface: 'payments/accounting generic surfaces',
    nextStep: 'להוסיף cash/check ledgers, deposits, withdrawals וסטטוס הפקדה.',
  },
  {
    module: 'שעון נוכחות / זמני עבודה',
    category: 'ניהול עסק',
    status: 'partial',
    capability: 'יש Payroll ושכר, אך חסר timesheet מלא לתמחור לקוחות ופרויקטים.',
    codeSurface: 'PayrollDashboard',
    nextStep: 'להוסיף TimeEntry model, approvals וחיוב לקוח לפי שעות.',
  },
  {
    module: 'דיוור, SMS והתראות',
    category: 'שיווק ותקשורת',
    status: 'ready',
    capability: 'שליחת SMS, SMS bulk, רשימות SMS, רשימות דיוור והוספה לרשימה.',
    codeSurface: 'communications.py + send_sms/send_multiple_sms/mailinglists',
    nextStep: 'להוסיף templates, triggers ותיעוד שליחת הודעות לפי אירוע כספי.',
  },
  {
    module: 'לוחות בקרה ותצוגות',
    category: 'ניהול מידע',
    status: 'ready',
    capability: 'דשבורדים כספיים, CFO command center, תזרים, AR/AP, KPIs ודוחות.',
    codeSurface: 'CFOOverview + ExecutiveDashboard + CashFlowDashboard + BusinessMenu',
    nextStep: 'להוסיף builder לתצוגות מותאמות אישית למשתמש.',
  },
  {
    module: 'ניהול מידע כללי',
    category: 'ניהול מידע',
    status: 'ready',
    capability: 'CRUD לישויות CRM, תיקיות, שדות, רשימות תצוגה ו-print HTML לישות.',
    codeSurface: 'crm/data + crm/schema + crm/views integrations',
    nextStep: 'להציג ב-UI תיקיות, שדות ותצוגות כ-no-code database.',
  },
  {
    module: 'טריגרים ואוטומציות',
    category: 'ניהול מידע',
    status: 'partial',
    capability: 'יש מנוע alerts/tasks ו-sync jobs; אין עדיין builder אוטומציות מלא ללקוח.',
    codeSurface: 'alert_engine + sync routes + BusinessMenu',
    nextStep: 'לבנות rules UI: אם אירוע כספי קורה, בצע פעולה/התראה/מסמך.',
  },
  {
    module: 'API והרשאות',
    category: 'תשתית',
    status: 'ready',
    capability: 'הרשאות משתמשים, יצירת משתמשים, roles, org scoping והפרדת tenant.',
    codeSurface: 'admin.py + auth dependencies + website/users/permissions',
    nextStep: 'להוסיף UI לניהול API keys פר עסק ולוג גישות.',
  },
  {
    module: 'הנהלת חשבונות וייצוא',
    category: 'חומרים להנהלת חשבונות',
    status: 'ready',
    capability: 'הנה"ח כפולה, מאזן בוחן, כרטסת, פקודות יומן ודוחות יומיים.',
    codeSurface: 'LedgerDashboard + DailyReportsDashboard + accounting routes',
    nextStep: 'להוסיף export format לפי יעד: חשבשבת/רו"ח/בנק.',
  },
  {
    module: 'דוחות שנתיים',
    category: 'חומרים להנהלת חשבונות',
    status: 'ready',
    capability: 'טיוטות 1301/1214, תיאומי מס, פחת, ניכויי ספקים ודוחות תמיכה.',
    codeSurface: 'AnnualReportsDashboard + tax/report modules',
    nextStep: 'להוסיף checklist חתימות/מסמכים וסטטוס הגשה.',
  },
  {
    module: 'מסוף אשראי',
    category: 'תשתית',
    status: 'partial',
    capability: 'יש charging ו-payment methods; טעינת טרנזקציות מסוף לפי טווח תאריכים לא נתמכת באותו endpoint.',
    codeSurface: 'load_billing_transactions raises documented NotImplementedError',
    nextStep: 'להשתמש ב-list_payments לסנכרון או לחבר endpoint מסוף נוסף אם קיים בחשבון.',
  },
  {
    module: 'דוא"ל יוצא ואחסון קבצים',
    category: 'תשתית',
    status: 'partial',
    capability: 'שליחת מסמך במייל קיימת; חסר מודול תשתית מלא לדומיין דוא"ל ואחסון.',
    codeSurface: 'send_document + file/OCR upload flows',
    nextStep: 'להוסיף storage provider, quotas, signed URLs ו-email domain settings.',
  },
];

const categories = ['הכל', ...Array.from(new Set(coverageItems.map((item) => item.category)))];
const statusLabels: Record<CoverageStatus, string> = {
  ready: 'מוכן',
  partial: 'חלקי',
  blocked: 'חסום',
};

const statusTone: Record<CoverageStatus, string> = {
  ready: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  partial: 'border-amber-200 bg-amber-50 text-amber-700',
  blocked: 'border-rose-200 bg-rose-50 text-rose-700',
};

const statusIcon = {
  ready: CheckCircle2,
  partial: AlertTriangle,
  blocked: ShieldCheck,
};

export default function SumitCoverageDashboard({ darkMode = false }: { darkMode?: boolean }) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('הכל');
  const [status, setStatus] = useState<'all' | CoverageStatus>('all');

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return coverageItems.filter((item) => {
      const matchesQuery =
        !normalized ||
        [item.module, item.category, item.capability, item.codeSurface, item.nextStep].some((part) =>
          part.toLowerCase().includes(normalized),
        );
      const matchesCategory = category === 'הכל' || item.category === category;
      const matchesStatus = status === 'all' || item.status === status;
      return matchesQuery && matchesCategory && matchesStatus;
    });
  }, [category, query, status]);

  const counts = useMemo(
    () => ({
      ready: coverageItems.filter((item) => item.status === 'ready').length,
      partial: coverageItems.filter((item) => item.status === 'partial').length,
      blocked: coverageItems.filter((item) => item.status === 'blocked').length,
      total: coverageItems.length,
    }),
    [],
  );

  return (
    <FinancePageShell
      darkMode={darkMode}
      eyebrow="SUMIT API Coverage"
      title="מפת כיסוי מודולי SUMIT"
      description="מסך בקרה פנימי שממפה את המודולים העסקיים מול היכולות שכבר מחוברות בקוד, מה חלקי ומה צריך להשלים כדי לתת חוויה מלאה בתוך רצף."
      icon={ClipboardCheck}
      metrics={[
        { label: 'מודולים ממופים', value: String(counts.total), tone: 'slate' },
        { label: 'מוכנים לעבודה', value: String(counts.ready), tone: 'emerald' },
        { label: 'חלקיים / דורשים UI', value: String(counts.partial), tone: 'amber' },
        { label: 'דורשים adapter', value: String(counts.blocked), tone: 'rose' },
      ]}
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard darkMode={darkMode} icon={CreditCard} label="גבייה" value="כיסוי רחב" detail="חיובים, תשלומים, הוראות קבע ו-checkout" tone="blue" />
        <MetricCard darkMode={darkMode} icon={FileSpreadsheet} label="ספרים" value="פעיל" detail={'מסמכים, דוחות, הנה"ח כפולה ודוחות שנתיים'} tone="emerald" />
        <MetricCard darkMode={darkMode} icon={Users} label="CRM" value="מחובר" detail="לקוחות, תיקיות, שדות, תצוגות וישויות" tone="slate" />
        <MetricCard darkMode={darkMode} icon={Workflow} label="השלמות" value={String(counts.partial + counts.blocked)} detail="מסכים, webhooks ו-adapters לתשלום" tone="amber" />
      </div>

      <FinanceCard darkMode={darkMode} title="סינון מודולים" subtitle="חפש לפי מודול, יכולת, route או הצעד הבא" icon={Filter}>
        <div className="grid gap-3 lg:grid-cols-[1fr_220px_220px]">
          <label className={cls('relative block', darkMode ? 'text-slate-100' : 'text-slate-900')}>
            <Search className={cls('absolute right-3 top-3 h-4 w-4', darkMode ? 'text-slate-400' : 'text-slate-500')} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="חיפוש מודול, route או יכולת"
              className={cls(
                'w-full rounded-lg border px-10 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500',
                darkMode ? 'border-slate-700 bg-slate-900 text-slate-100' : 'border-slate-200 bg-white text-slate-950',
              )}
            />
          </label>
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className={cls(
              'rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500',
              darkMode ? 'border-slate-700 bg-slate-900 text-slate-100' : 'border-slate-200 bg-white text-slate-950',
            )}
          >
            {categories.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as 'all' | CoverageStatus)}
            className={cls(
              'rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500',
              darkMode ? 'border-slate-700 bg-slate-900 text-slate-100' : 'border-slate-200 bg-white text-slate-950',
            )}
          >
            <option value="all">כל הסטטוסים</option>
            <option value="ready">מוכן</option>
            <option value="partial">חלקי</option>
            <option value="blocked">חסום</option>
          </select>
        </div>
      </FinanceCard>

      <div className="grid gap-4 xl:grid-cols-2">
        {filtered.map((item) => {
          const Icon = statusIcon[item.status];
          return (
            <FinanceCard key={`${item.category}-${item.module}`} darkMode={darkMode} className="h-full">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className={cls('text-xs font-semibold', darkMode ? 'text-blue-200' : 'text-blue-700')}>{item.category}</div>
                  <h2 className="mt-1 text-xl font-bold tracking-normal">{item.module}</h2>
                </div>
                <span className={cls('inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold', statusTone[item.status])}>
                  <Icon className="h-3.5 w-3.5" />
                  {statusLabels[item.status]}
                </span>
              </div>
              <div className="mt-5 grid gap-3">
                <CoverageRow darkMode={darkMode} icon={Database} label="יכולת קיימת" value={item.capability} />
                <CoverageRow darkMode={darkMode} icon={Landmark} label="מימוש בקוד" value={item.codeSurface} />
                <CoverageRow darkMode={darkMode} icon={Mail} label="צעד הבא" value={item.nextStep} />
              </div>
            </FinanceCard>
          );
        })}
      </div>

      {filtered.length === 0 && (
        <FinanceCard darkMode={darkMode}>
          <div className="py-10 text-center text-sm text-slate-500">לא נמצאו מודולים שתואמים לסינון.</div>
        </FinanceCard>
      )}
    </FinancePageShell>
  );
}

function CoverageRow({
  darkMode,
  icon: Icon,
  label,
  value,
}: {
  darkMode?: boolean;
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className={cls('flex gap-3 rounded-lg border p-3', darkMode ? 'border-slate-700 bg-slate-900/50' : 'border-slate-200 bg-slate-50')}>
      <div className={cls('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', darkMode ? 'bg-slate-800 text-blue-200' : 'bg-white text-blue-700')}>
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <div className={cls('text-xs font-semibold', darkMode ? 'text-slate-400' : 'text-slate-500')}>{label}</div>
        <div className="mt-1 text-sm leading-6">{value}</div>
      </div>
    </div>
  );
}
