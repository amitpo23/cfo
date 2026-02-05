import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
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
} from 'lucide-react';

// Dashboard Components
import CustomerDashboard from './components/CustomerDashboard';
import DocumentManager from './components/DocumentManager';
import PaymentInterface from './components/PaymentInterface';
import AnalyticsDashboard from './components/AnalyticsDashboard';
import ForecastingDashboard from './components/ForecastingDashboard';
import BankStatementDashboard from './components/BankStatementDashboard';
import ReportsDashboard from './components/ReportsDashboard';
import BudgetDashboard from './components/BudgetDashboard';
import KPIDashboard from './components/KPIDashboard';
import AIAnalyticsDashboard from './components/AIAnalyticsDashboard';

// New Financial Operations Components
import InvoicesDashboard from './components/InvoicesDashboard';
import PaymentsDashboard from './components/PaymentsDashboard';
import AgreementCashFlowDashboard from './components/AgreementCashFlowDashboard';

// CFO Command Center Components
import CFOOverview from './components/CFOOverview';
import CFOARDashboard from './components/CFOARDashboard';
import CFOSyncDashboard from './components/CFOSyncDashboard';
import CFOAlertsTasks from './components/CFOAlertsTasks';
import CFOCashFlowProjection from './components/CFOCashFlowProjection';

import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Navigation configuration
const navigationConfig = [
  {
    section: 'CFO',
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Command Center', description: 'CFO overview' },
      { to: '/cashflow', icon: Wallet, label: 'Cash Flow', description: 'Projections & scenarios' },
      { to: '/ar', icon: Receipt, label: 'AR / Collections', description: 'Aging & follow-up' },
      { to: '/ap', icon: CreditCard, label: 'AP / Payables', description: 'Bills & payments' },
      { to: '/budget', icon: Target, label: 'Budget', description: 'Budget vs actual' },
    ]
  },
  {
    section: 'Operations',
    items: [
      { to: '/invoices', icon: FileCheck, label: 'Invoices', description: 'Create & manage invoices' },
      { to: '/payment-requests', icon: Banknote, label: 'Payment Requests', description: 'Requests & standing orders' },
      { to: '/agreements', icon: ScrollText, label: 'Agreements', description: 'Contracts & cash flow' },
      { to: '/payments', icon: CreditCard, label: 'Payments', description: 'Payment processing' },
    ]
  },
  {
    section: 'Monitoring',
    items: [
      { to: '/alerts', icon: Bell, label: 'Alerts & Tasks', description: 'Action items' },
      { to: '/kpis', icon: Gauge, label: 'KPIs', description: 'Performance metrics' },
      { to: '/reports', icon: FileSpreadsheet, label: 'Reports', description: 'Generate & export' },
    ]
  },
  {
    section: 'Analysis',
    items: [
      { to: '/forecasting', icon: TrendingUp, label: 'Forecasting', description: 'ML predictions' },
      { to: '/ai-analytics', icon: Brain, label: 'AI Analytics', description: 'AI-powered insights' },
      { to: '/analytics', icon: BarChart3, label: 'Analytics', description: 'Data analytics' },
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
                    <h1 className={`text-xl font-bold ${darkMode ? 'text-white' : 'text-gray-800'}`}>CFO System</h1>
                    <p className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Financial Management</p>
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
                    <span className={`text-sm font-medium ${darkMode ? 'text-white' : 'text-gray-700'}`}>Admin</span>
                    <ChevronDown size={16} className={darkMode ? 'text-gray-400' : 'text-gray-500'} />
                  </button>
                  {showUserMenu && (
                    <UserDropdown darkMode={darkMode} onClose={() => setShowUserMenu(false)} />
                  )}
                </div>
              </div>
            </header>

            {/* Main Content */}
            <main className={`flex-1 overflow-y-auto ${darkMode ? 'bg-gray-900' : 'bg-gray-50'}`}>
              <Routes>
                {/* CFO Command Center */}
                <Route path="/" element={<CFOOverview darkMode={darkMode} />} />
                <Route path="/cashflow" element={<CFOCashFlowProjection darkMode={darkMode} />} />
                <Route path="/ar" element={<CFOARDashboard darkMode={darkMode} />} />
                <Route path="/ap" element={<CFOARDashboard darkMode={darkMode} />} />
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
                <Route path="/analytics" element={<AnalyticsDashboard />} />
                <Route path="/settings" element={<SettingsPage darkMode={darkMode} />} />

                {/* Financial Operations */}
                <Route path="/invoices" element={<InvoicesDashboard />} />
                <Route path="/payment-requests" element={<PaymentsDashboard />} />
                <Route path="/agreements" element={<AgreementCashFlowDashboard />} />
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
const UserDropdown: React.FC<{ darkMode: boolean; onClose: () => void }> = ({ darkMode, onClose: _onClose }) => {
  return (
    <div className={`absolute right-0 mt-2 w-56 rounded-xl shadow-xl border ${
      darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
    } z-50`}>
      <div className={`p-4 border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <p className={`font-semibold ${darkMode ? 'text-white' : 'text-gray-900'}`}>Admin User</p>
        <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>admin@company.com</p>
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
        <button className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition text-red-500 hover:bg-red-50 ${
          darkMode ? 'hover:bg-red-900/20' : ''
        }`}>
          <LogOut size={18} />
          <span className="text-sm">Logout</span>
        </button>
      </div>
    </div>
  );
};

// DashboardHome replaced by CFOOverview component

// Settings Page Component
const SettingsPage: React.FC<{ darkMode: boolean }> = ({ darkMode }) => {
  return (
    <div className={`p-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <h1 className="text-3xl font-bold mb-8">Settings</h1>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* API Configuration */}
        <div className={`p-6 rounded-2xl ${
          darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
        }`}>
          <h2 className="text-xl font-semibold mb-6">SUMIT API Configuration</h2>
          <div className="space-y-4">
            <div>
              <label className={`block text-sm font-medium mb-2 ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                API Key
              </label>
              <input
                type="password"
                className={`w-full px-4 py-3 rounded-xl border ${
                  darkMode 
                    ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' 
                    : 'bg-white border-gray-300 text-gray-900'
                } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                placeholder="Enter your SUMIT API key"
              />
            </div>
            <div>
              <label className={`block text-sm font-medium mb-2 ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Company ID
              </label>
              <input
                type="text"
                className={`w-full px-4 py-3 rounded-xl border ${
                  darkMode 
                    ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' 
                    : 'bg-white border-gray-300 text-gray-900'
                } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                placeholder="Enter your company ID"
              />
            </div>
            <button className="w-full bg-blue-600 text-white px-4 py-3 rounded-xl hover:bg-blue-700 transition font-medium">
              Save API Settings
            </button>
          </div>
        </div>

        {/* Company Info */}
        <div className={`p-6 rounded-2xl ${
          darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
        }`}>
          <h2 className="text-xl font-semibold mb-6">Company Information</h2>
          <div className="space-y-4">
            <div>
              <label className={`block text-sm font-medium mb-2 ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Company Name
              </label>
              <input
                type="text"
                className={`w-full px-4 py-3 rounded-xl border ${
                  darkMode 
                    ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' 
                    : 'bg-white border-gray-300 text-gray-900'
                } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                placeholder="Your Company Ltd."
              />
            </div>
            <div>
              <label className={`block text-sm font-medium mb-2 ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Tax ID (ח.פ.)
              </label>
              <input
                type="text"
                className={`w-full px-4 py-3 rounded-xl border ${
                  darkMode 
                    ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' 
                    : 'bg-white border-gray-300 text-gray-900'
                } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                placeholder="51XXXXXXX"
              />
            </div>
            <button className="w-full bg-blue-600 text-white px-4 py-3 rounded-xl hover:bg-blue-700 transition font-medium">
              Save Company Info
            </button>
          </div>
        </div>

        {/* Notification Settings */}
        <div className={`p-6 rounded-2xl ${
          darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
        }`}>
          <h2 className="text-xl font-semibold mb-6">Notifications</h2>
          <div className="space-y-4">
            {[
              { label: 'Email notifications for payments', checked: true },
              { label: 'SMS alerts for failed charges', checked: false },
              { label: 'Weekly financial summary', checked: true },
              { label: 'Agreement renewal reminders', checked: true },
            ].map((setting, index) => (
              <label key={index} className="flex items-center justify-between cursor-pointer">
                <span className={darkMode ? 'text-gray-300' : 'text-gray-700'}>{setting.label}</span>
                <div className={`w-12 h-6 rounded-full relative transition ${
                  setting.checked ? 'bg-blue-600' : darkMode ? 'bg-gray-600' : 'bg-gray-300'
                }`}>
                  <div className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${
                    setting.checked ? 'translate-x-7' : 'translate-x-1'
                  }`}></div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* System Info */}
        <div className={`p-6 rounded-2xl ${
          darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
        }`}>
          <h2 className="text-xl font-semibold mb-6">System Information</h2>
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className={darkMode ? 'text-gray-400' : 'text-gray-500'}>Version</span>
              <span className="font-medium">1.0.0</span>
            </div>
            <div className="flex justify-between">
              <span className={darkMode ? 'text-gray-400' : 'text-gray-500'}>API Status</span>
              <span className="text-green-500 font-medium flex items-center gap-2">
                <span className="w-2 h-2 bg-green-500 rounded-full"></span>
                Connected
              </span>
            </div>
            <div className="flex justify-between">
              <span className={darkMode ? 'text-gray-400' : 'text-gray-500'}>Last Sync</span>
              <span className="font-medium">2 min ago</span>
            </div>
            <div className="flex justify-between">
              <span className={darkMode ? 'text-gray-400' : 'text-gray-500'}>Environment</span>
              <span className="font-medium">Production</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
