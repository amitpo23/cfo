import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import api from './services/api';
import OrgSwitcher, { CurrentUser } from './components/OrgSwitcher';
import {
  LayoutDashboard,
  Users,
  CreditCard,
  BarChart3,
  Settings,
  TrendingUp,
  Wallet,
  Database,
  Building2,
  FileSpreadsheet,
  Target,
  Receipt,
  Gauge,
  Brain,
  FileCheck,
  Banknote,
  Package,
  Landmark,
  Sparkles,
  Calculator,
  BookOpen,
  FileWarning,
  Cpu,
  LayoutGrid,
  ScrollText,
  ChevronLeft,
  ChevronRight,
  Bell,
  Search,
  User,
  LogOut,
  Moon,
  Sun,
  HelpCircle,
  ChevronDown,
  ClipboardCheck,
  MessageCircle,
  FileX,
} from 'lucide-react';

// Dashboard Components
import CustomerDashboard from './components/CustomerDashboard';
import DocumentManager from './components/DocumentManager';
import PaymentInterface from './components/PaymentInterface';
import ForecastingDashboard from './components/ForecastingDashboard';
import BankStatementDashboard from './components/BankStatementDashboard';
import BankInsightsDashboard from './components/BankInsightsDashboard';
import OfficeDashboard from './components/OfficeDashboard';
import AdminClientsDashboard from './components/AdminClientsDashboard';
import CalculatorsDashboard from './components/CalculatorsDashboard';
import PayrollDashboard from './components/PayrollDashboard';
import OpenFinanceOpsDashboard from './components/OpenFinanceOpsDashboard';
import LedgerDashboard from './components/LedgerDashboard';
import DailyReportsDashboard from './components/DailyReportsDashboard';
import SuppliersMissingInvoices from './components/SuppliersMissingInvoices';
import AnnualReportsDashboard from './components/AnnualReportsDashboard';
import EngineDashboard from './components/EngineDashboard';
import BusinessMenuDashboard from './components/BusinessMenuDashboard';
import SumitCoverageDashboard from './components/SumitCoverageDashboard';
import ReportsDashboard from './components/ReportsDashboard';
import BudgetDashboard from './components/BudgetDashboard';
import KPIDashboard from './components/KPIDashboard';
import AIAnalyticsDashboard from './components/AIAnalyticsDashboard';
import ChatAssistant from './components/ChatAssistant';

// New Financial Operations Components
import InvoicesDashboard from './components/InvoicesDashboard';
import PaymentsDashboard from './components/PaymentsDashboard';
import AgreementCashFlowDashboard from './components/AgreementCashFlowDashboard';
import MasavDashboard from './components/MasavDashboard';
import InventoryDashboard from './components/InventoryDashboard';
import BankReportDashboard from './components/BankReportDashboard';
import ExecutiveDashboard from './components/ExecutiveDashboard';
import BudgetEntry from './components/BudgetEntry';
import YearComparison from './components/YearComparison';
import ExpenseFiling from './components/ExpenseFiling';

// CFO Command Center Components
import CFOOverview from './components/CFOOverview';
import CFOARDashboard from './components/CFOARDashboard';
import CFOAPDashboard from './components/CFOAPDashboard';
import CFOSyncDashboard from './components/CFOSyncDashboard';
import SettingsPage from './components/SettingsPage';
import CFOAlertsTasks from './components/CFOAlertsTasks';
import CFOCashFlowProjection from './components/CFOCashFlowProjection';
import CashFlowDashboard from './components/CashFlowDashboard';

import RezefLanding from './components/RezefLanding';

import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const AUTH_BYPASS = import.meta.env.VITE_AUTH_BYPASS === 'true';

// Navigation configuration
const navigationConfig = [
  {
    section: 'CFO',
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Command Center', description: 'CFO overview' },
      { to: '/ai-chat', icon: MessageCircle, label: 'עוזר AI', description: 'שיחה עם עוזר ה-CFO — פעולות כתיבה דורשות אישור' },
      { to: '/executive', icon: Gauge, label: 'דשבורד מנהלים', description: '8 פאנלים של מצב העסק' },
      { to: '/cashflow', icon: Wallet, label: 'Cash Flow', description: 'Projections & scenarios' },
      { to: '/cashflow-detail', icon: TrendingUp, label: 'תזרים — מפורט', description: 'חודשי/יומי, burn-rate ויחסי נזילות' },
      { to: '/ar', icon: Receipt, label: 'AR / Collections', description: 'Aging & follow-up' },
      { to: '/ap', icon: CreditCard, label: 'AP / Payables', description: 'Bills & payments' },
      { to: '/budget', icon: Target, label: 'Budget', description: 'Budget vs actual' },
      { to: '/budget-entry', icon: Target, label: 'הזנת תקציב', description: 'הזנה ידנית / ייבוא Excel' },
      { to: '/year-comparison', icon: BarChart3, label: 'השוואה שנתית', description: 'מול שנה קודמת' },
    ]
  },
  {
    section: 'Operations',
    items: [
      { to: '/invoices', icon: FileCheck, label: 'Invoices', description: 'Create & manage invoices' },
      { to: '/documents', icon: ScrollText, label: 'הוצאת מסמכים', description: 'חשבונית/הצעת מחיר/הזמנה/תעודת משלוח' },
      { to: '/payment-requests', icon: Banknote, label: 'Payment Requests', description: 'Requests & standing orders' },
      { to: '/agreements', icon: ScrollText, label: 'Agreements', description: 'Contracts & cash flow' },
      { to: '/expenses', icon: Receipt, label: 'תיוק הוצאות', description: 'הוצאות ותיוקן ב-SUMIT' },
      { to: '/payments', icon: CreditCard, label: 'Payments', description: 'Payment processing' },
      { to: '/masav', icon: Banknote, label: 'תשלומי ספקים (מס"ב)', description: 'יצירת קובץ מס"ב' },
      { to: '/inventory', icon: Package, label: 'מלאי', description: 'דוח מלאי קיים' },
    ]
  },
  {
    section: 'Monitoring',
    items: [
      { to: '/alerts', icon: Bell, label: 'Alerts & Tasks', description: 'Action items' },
      { to: '/kpis', icon: Gauge, label: 'KPIs', description: 'Performance metrics' },
      { to: '/reports', icon: FileSpreadsheet, label: 'Reports', description: 'Generate & export' },
      { to: '/bank-report', icon: Landmark, label: 'דוח לבנק', description: 'דוח מצב עסקי לבנק' },
      { to: '/business-menu', icon: LayoutGrid, label: 'תפריט יכולות', description: 'סילבוס מלא של כל מה שהמערכת עושה לעסק — עם סטטוס חי' },
      { to: '/sumit-coverage', icon: ClipboardCheck, label: 'כיסוי מודולי SUMIT', description: 'מפת API: מוכן, חלקי, חסום' },
      { to: '/engine', icon: Cpu, label: 'המנוע המאחד', description: 'מרכז בקרה אחד מעל הכל — סטטוס, הנה"ח, סינתזה ודוחות' },
      { to: '/bank-insights', icon: Sparkles, label: 'תובנות בנק', description: 'אנומליות, מנויים, עמלות וחיסכון מדפי הבנק' },
      { to: '/office', icon: Building2, label: 'ניהול משרד', description: 'תיקי לקוחות, סנכרון רוחבי והתאמות נדרשות' },
      { to: '/admin-clients', icon: Database, label: 'אדמין — כל הלקוחות', description: 'תצוגת על של כל תיקי הלקוחות' },
      { to: '/calculators', icon: Calculator, label: 'מחשבונים', description: 'חישובי שכר/מס/ב"ל דטרמיניסטיים, בלי צ\'אט' },
      { to: '/payroll', icon: Users, label: 'שכר', description: 'עובדים, תלושים ודוח 102/126' },
      { to: '/ledger', icon: BookOpen, label: 'הנה"ח כפולה', description: 'מאזן בוחן, פקודות יומן וכרטסת — נגזר מהמסמכים' },
      { to: '/daily-reports', icon: TrendingUp, label: 'דוחות יומיים', description: 'רווח/הפסד מצטבר, גיול חובות וספקים תוך-חודשי' },
      { to: '/suppliers-missing-invoices', icon: FileX, label: 'ספקים חסרי חשבונית', description: 'ספקים ששולם להם בבנק/אשראי בלי מסמך תואם — מע"מ תשומות שלא נקלט' },
      { to: '/annual-reports', icon: FileWarning, label: 'דוחות שנתיים', description: 'טיוטת 1301 (יחיד) / 1214 (חברה) — לבדיקת רו"ח' },
      { to: '/of-ops', icon: CreditCard, label: 'Open Finance תפעול', description: 'תשלומים, אשראי, לקוחות וסוחרים' },
    ]
  },
  {
    section: 'Analysis',
    items: [
      { to: '/forecasting', icon: TrendingUp, label: 'Forecasting', description: 'ML predictions' },
      { to: '/ai-analytics', icon: Brain, label: 'AI Analytics', description: 'AI-powered insights' },
    ]
  },
  {
    section: 'System',
    items: [
      { to: '/sync', icon: Database, label: 'Data Sync', description: 'Sync runs & logs' },
      { to: '/customers', icon: Users, label: 'Customers', description: 'Customer management' },
      { to: '/bank', icon: Building2, label: 'Bank Import', description: 'Bank statements' },
      { to: '/settings', icon: Settings, label: 'Settings', description: 'System settings' },
    ]
  }
];

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const [authed, setAuthed] = useState(() => AUTH_BYPASS || Boolean(localStorage.getItem('auth_token')));
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);

  // Resolve the real signed-in identity (drives the header label + the
  // super-admin org switcher). Previously the header showed a hardcoded
  // "Admin User", so a super_admin had no way to see their role or switch org.
  useEffect(() => {
    if (!authed) return;
    api.get<CurrentUser>('/admin/auth/me')
      .then(setCurrentUser)
      .catch(() => setCurrentUser(null));
  }, [authed]);

  if (!authed && !AUTH_BYPASS) {
    return <RezefLanding darkMode={darkMode} onSuccess={() => setAuthed(true)} />;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className={`flex h-screen ${darkMode ? 'dark bg-gray-900' : 'bg-gray-50'}`}>
          {/* Sidebar */}
          <aside className={`${sidebarCollapsed ? 'w-20' : 'w-72'} ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'} border-r shadow-lg transition-all duration-300 flex flex-col overflow-hidden`}>
            {/* Logo Section */}
            <div className={`p-4 border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center shadow-lg">
                  <span className="text-white font-bold text-lg">₪</span>
                </div>
                {!sidebarCollapsed && (
                  <div>
                    <h1 className={`text-xl font-bold ${darkMode ? 'text-white' : 'text-gray-800'}`}>רצף Rezef</h1>
                    <p className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>CFO Operating System</p>
                  </div>
                )}
              </div>
            </div>
            
            {/* Navigation */}
            <nav className="flex-1 overflow-y-auto py-4">
              {navigationConfig.map((group) => (
                <div key={group.section} className="mb-4">
                  {!sidebarCollapsed && (
                    <div className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                      {group.section}
                    </div>
                  )}
                  {group.items.map((item) => (
                    <NavItem
                      key={item.to}
                      to={item.to}
                      icon={<item.icon size={20} />}
                      label={item.label}
                      description={item.description}
                      collapsed={sidebarCollapsed}
                      darkMode={darkMode}
                    />
                  ))}
                </div>
              ))}
            </nav>

            {/* Collapse Button */}
            <div className={`p-4 border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <button
                onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
                className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg transition ${
                  darkMode 
                    ? 'text-gray-400 hover:bg-gray-700 hover:text-white' 
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`}
              >
                {sidebarCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
                {!sidebarCollapsed && <span className="text-sm">Collapse</span>}
              </button>
            </div>
          </aside>

          {/* Main Content Area */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Top Header Bar */}
            <header className={`h-16 border-b ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'} shadow-sm flex items-center justify-between px-6`}>
              {/* Search Bar */}
              <div className="flex-1 max-w-md">
                <div className={`relative flex items-center ${darkMode ? 'bg-gray-700' : 'bg-gray-100'} rounded-lg`}>
                  <Search size={18} className={`absolute left-3 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`} />
                  <input
                    type="text"
                    placeholder="Search customers, invoices, reports..."
                    className={`w-full pl-10 pr-4 py-2 rounded-lg border-0 bg-transparent ${
                      darkMode ? 'text-white placeholder-gray-400' : 'text-gray-900 placeholder-gray-500'
                    } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                  />
                </div>
              </div>

              {/* Right Side Actions */}
              <div className="flex items-center gap-4">
                {/* Super-admin: act-as-client organization switcher */}
                {currentUser && <OrgSwitcher currentUser={currentUser} darkMode={darkMode} />}

                {/* Dark Mode Toggle */}
                <button
                  onClick={() => setDarkMode(!darkMode)}
                  className={`p-2 rounded-lg transition ${
                    darkMode ? 'text-gray-400 hover:bg-gray-700 hover:text-white' : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {darkMode ? <Sun size={20} /> : <Moon size={20} />}
                </button>

                {/* Help */}
                <button className={`p-2 rounded-lg transition ${
                  darkMode ? 'text-gray-400 hover:bg-gray-700 hover:text-white' : 'text-gray-600 hover:bg-gray-100'
                }`}>
                  <HelpCircle size={20} />
                </button>

                {/* Notifications */}
                <div className="relative">
                  <button
                    onClick={() => setShowNotifications(!showNotifications)}
                    className={`p-2 rounded-lg transition relative ${
                      darkMode ? 'text-gray-400 hover:bg-gray-700 hover:text-white' : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    <Bell size={20} />
                    <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full"></span>
                  </button>
                  {showNotifications && (
                    <NotificationsDropdown darkMode={darkMode} onClose={() => setShowNotifications(false)} />
                  )}
                </div>

                {/* User Menu */}
                <div className="relative">
                  <button
                    onClick={() => setShowUserMenu(!showUserMenu)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg transition ${
                      darkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-100'
                    }`}
                  >
                    <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                      <User size={16} className="text-white" />
                    </div>
                    <span className={`text-sm font-medium ${darkMode ? 'text-white' : 'text-gray-700'}`}>
                      {currentUser?.full_name || 'Admin'}
                    </span>
                    <ChevronDown size={16} className={darkMode ? 'text-gray-400' : 'text-gray-500'} />
                  </button>
                  {showUserMenu && (
                    <UserDropdown darkMode={darkMode} currentUser={currentUser} onClose={() => setShowUserMenu(false)} />
                  )}
                </div>
              </div>
            </header>

            {/* Main Content */}
            <main className={`flex-1 overflow-y-auto ${darkMode ? 'bg-gray-900' : 'bg-gray-50'}`}>
              <Routes>
                {/* CFO Command Center */}
                <Route path="/" element={<CFOOverview darkMode={darkMode} />} />
                <Route path="/ai-chat" element={<ChatAssistant darkMode={darkMode} currentUser={currentUser} />} />
                <Route path="/cashflow" element={<CFOCashFlowProjection darkMode={darkMode} />} />
                <Route path="/cashflow-detail" element={<CashFlowDashboard />} />
                <Route path="/ar" element={<CFOARDashboard darkMode={darkMode} />} />
                <Route path="/ap" element={<CFOAPDashboard darkMode={darkMode} />} />
                <Route path="/alerts" element={<CFOAlertsTasks darkMode={darkMode} />} />
                <Route path="/tasks" element={<CFOAlertsTasks darkMode={darkMode} />} />
                <Route path="/sync" element={<CFOSyncDashboard darkMode={darkMode} />} />

                {/* Existing pages */}
                <Route path="/customers" element={<CustomerDashboard />} />
                <Route path="/documents" element={<DocumentManager />} />
                <Route path="/payments" element={<PaymentInterface />} />
                <Route path="/budget" element={<BudgetDashboard />} />
                <Route path="/kpis" element={<KPIDashboard />} />
                <Route path="/forecasting" element={<ForecastingDashboard />} />
                <Route path="/ai-analytics" element={<AIAnalyticsDashboard />} />
                <Route path="/reports" element={<ReportsDashboard />} />
                <Route path="/bank" element={<BankStatementDashboard />} />
                <Route path="/bank-insights" element={<BankInsightsDashboard />} />
                <Route path="/office" element={<OfficeDashboard />} />
                <Route path="/admin-clients" element={<AdminClientsDashboard />} />
                <Route path="/calculators" element={<CalculatorsDashboard />} />
                <Route path="/payroll" element={<PayrollDashboard />} />
                <Route path="/of-ops" element={<OpenFinanceOpsDashboard />} />
                <Route path="/ledger" element={<LedgerDashboard />} />
                <Route path="/daily-reports" element={<DailyReportsDashboard />} />
                <Route path="/suppliers-missing-invoices" element={<SuppliersMissingInvoices />} />
                <Route path="/annual-reports" element={<AnnualReportsDashboard />} />
                <Route path="/engine" element={<EngineDashboard />} />
                <Route path="/business-menu" element={<BusinessMenuDashboard />} />
                <Route path="/sumit-coverage" element={<SumitCoverageDashboard darkMode={darkMode} />} />
                {/* /analytics used to render a fully hardcoded-mock dashboard
                    (revenue/customers/documents all fake, no API call at
                    all) -- retired in favor of the real dashboards below. */}
                <Route path="/analytics" element={<Navigate to="/kpis" replace />} />
                <Route path="/settings" element={<SettingsPage darkMode={darkMode} />} />

                {/* Financial Operations */}
                <Route path="/invoices" element={<InvoicesDashboard />} />
                <Route path="/payment-requests" element={<PaymentsDashboard />} />
                <Route path="/agreements" element={<AgreementCashFlowDashboard />} />
                <Route path="/masav" element={<MasavDashboard darkMode={darkMode} />} />
                <Route path="/inventory" element={<InventoryDashboard darkMode={darkMode} />} />
                <Route path="/bank-report" element={<BankReportDashboard darkMode={darkMode} />} />
                <Route path="/executive" element={<ExecutiveDashboard darkMode={darkMode} />} />
                <Route path="/budget-entry" element={<BudgetEntry darkMode={darkMode} />} />
                <Route path="/year-comparison" element={<YearComparison darkMode={darkMode} />} />
                <Route path="/expenses" element={<ExpenseFiling darkMode={darkMode} />} />
              </Routes>
            </main>
          </div>
        </div>
      </Router>
    </QueryClientProvider>
  );
}
// Navigation Item Component
interface NavItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  description?: string;
  collapsed: boolean;
  darkMode: boolean;
}

const NavItem: React.FC<NavItemProps> = ({ to, icon, label, description, collapsed, darkMode }) => {
  const location = useLocation();
  const isActive = location.pathname === to;

  return (
    <Link
      to={to}
      className={`flex items-center gap-3 mx-2 px-3 py-2.5 rounded-lg transition-all duration-200 group ${
        isActive
          ? darkMode
            ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/25'
            : 'bg-blue-50 text-blue-600 border border-blue-200'
          : darkMode
            ? 'text-gray-400 hover:bg-gray-700 hover:text-white'
            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
      }`}
      title={collapsed ? label : undefined}
    >
      <span className={`flex-shrink-0 ${isActive ? '' : 'group-hover:scale-110 transition-transform'}`}>
        {icon}
      </span>
      {!collapsed && (
        <div className="flex-1 min-w-0">
          <span className="font-medium text-sm block truncate">{label}</span>
          {description && !isActive && (
            <span className={`text-xs truncate block ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              {description}
            </span>
          )}
        </div>
      )}
      {isActive && !collapsed && (
        <span className="w-1.5 h-1.5 bg-current rounded-full flex-shrink-0"></span>
      )}
    </Link>
  );
};

// Notifications Dropdown
const NotificationsDropdown: React.FC<{ darkMode: boolean; onClose: () => void }> = ({ darkMode, onClose: _onClose }) => {
  const notifications = [
    { id: 1, title: 'Invoice #1234 paid', time: '5 min ago', type: 'success' },
    { id: 2, title: 'Payment request pending', time: '1 hour ago', type: 'warning' },
    { id: 3, title: 'New customer registered', time: '2 hours ago', type: 'info' },
    { id: 4, title: 'Agreement expires soon', time: '1 day ago', type: 'warning' },
  ];

  return (
    <div className={`absolute right-0 mt-2 w-80 rounded-xl shadow-xl border ${
      darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
    } z-50`}>
      <div className={`p-4 border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <h3 className={`font-semibold ${darkMode ? 'text-white' : 'text-gray-900'}`}>Notifications</h3>
      </div>
      <div className="max-h-80 overflow-y-auto">
        {notifications.map((notif) => (
          <div
            key={notif.id}
            className={`p-4 border-b last:border-b-0 cursor-pointer transition ${
              darkMode ? 'border-gray-700 hover:bg-gray-700' : 'border-gray-100 hover:bg-gray-50'
            }`}
          >
            <div className="flex items-start gap-3">
              <div className={`w-2 h-2 rounded-full mt-2 ${
                notif.type === 'success' ? 'bg-green-500' :
                notif.type === 'warning' ? 'bg-yellow-500' : 'bg-blue-500'
              }`}></div>
              <div className="flex-1">
                <p className={`text-sm font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>{notif.title}</p>
                <p className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>{notif.time}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className={`p-3 border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <button className="w-full text-center text-sm text-blue-500 hover:text-blue-600 font-medium">
          View all notifications
        </button>
      </div>
    </div>
  );
};

// User Dropdown
const ROLE_LABELS: Record<string, string> = {
  super_admin: 'מנהל על',
  admin: 'מנהל',
  user: 'משתמש',
};

const UserDropdown: React.FC<{ darkMode: boolean; currentUser: CurrentUser | null; onClose: () => void }> = ({ darkMode, currentUser, onClose: _onClose }) => {
  return (
    <div className={`absolute right-0 mt-2 w-56 rounded-xl shadow-xl border ${
      darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
    } z-50`}>
      <div className={`p-4 border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <p className={`font-semibold ${darkMode ? 'text-white' : 'text-gray-900'}`}>{currentUser?.full_name || 'משתמש'}</p>
        <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>{currentUser?.email || ''}</p>
        {currentUser?.role && (
          <span className={`inline-block mt-2 text-[11px] px-2 py-0.5 rounded-full ${
            currentUser.role === 'super_admin'
              ? (darkMode ? 'bg-purple-900/40 text-purple-200' : 'bg-purple-100 text-purple-700')
              : (darkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600')
          }`}>
            {ROLE_LABELS[currentUser.role] || currentUser.role}
          </span>
        )}
      </div>
      <div className="p-2">
        <button className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition ${
          darkMode ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-100'
        }`}>
          <User size={18} />
          <span className="text-sm">Profile</span>
        </button>
        <button className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition ${
          darkMode ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-100'
        }`}>
          <Settings size={18} />
          <span className="text-sm">Settings</span>
        </button>
        <button
          onClick={() => {
            localStorage.removeItem('auth_token');
            window.location.href = '/';
          }}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition text-red-500 hover:bg-red-50 ${
            darkMode ? 'hover:bg-red-900/20' : ''
          }`}
        >
          <LogOut size={18} />
          <span className="text-sm">Logout</span>
        </button>
      </div>
    </div>
  );
};

// DashboardHome replaced by CFOOverview component

export default App;
