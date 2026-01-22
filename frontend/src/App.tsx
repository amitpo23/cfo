import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  LayoutDashboard,
  Users,
  FileText,
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
  PiggyBank,
  Gauge,
  Brain,
  Calculator,
} from 'lucide-react';

import CustomerDashboard from './components/CustomerDashboard';
import DocumentManager from './components/DocumentManager';
import PaymentInterface from './components/PaymentInterface';
import AnalyticsDashboard from './components/AnalyticsDashboard';
import CashFlowDashboard from './components/CashFlowDashboard';
import ForecastingDashboard from './components/ForecastingDashboard';
import BankStatementDashboard from './components/BankStatementDashboard';
import DataSyncDashboard from './components/DataSyncDashboard';
import ReportsDashboard from './components/ReportsDashboard';
import BudgetDashboard from './components/BudgetDashboard';
import ARDashboard from './components/ARDashboard';
import KPIDashboard from './components/KPIDashboard';
import AIAnalyticsDashboard from './components/AIAnalyticsDashboard';

import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className="flex h-screen bg-gray-100">
          {/* Sidebar */}
          <aside className="w-64 bg-white shadow-md overflow-y-auto">
            <div className="p-6">
              <h1 className="text-2xl font-bold text-primary-600">CFO System</h1>
              <p className="text-sm text-gray-600">Financial Management</p>
            </div>
            <nav className="mt-6">
              <div className="px-4 py-2 text-xs font-semibold text-gray-400 uppercase">Main</div>
              <NavLink to="/" icon={<LayoutDashboard size={20} />} label="Dashboard" />
              <NavLink to="/customers" icon={<Users size={20} />} label="Customers" />
              <NavLink to="/documents" icon={<FileText size={20} />} label="Documents" />
              <NavLink to="/payments" icon={<CreditCard size={20} />} label="Payments" />
              
              <div className="px-4 py-2 mt-4 text-xs font-semibold text-gray-400 uppercase">Finance</div>
              <NavLink to="/cashflow" icon={<Wallet size={20} />} label="Cash Flow" />
              <NavLink to="/budget" icon={<Target size={20} />} label="Budget" />
              <NavLink to="/ar" icon={<Receipt size={20} />} label="AR / Aging" />
              <NavLink to="/kpis" icon={<Gauge size={20} />} label="KPIs" />
              
              <div className="px-4 py-2 mt-4 text-xs font-semibold text-gray-400 uppercase">Analysis</div>
              <NavLink to="/forecasting" icon={<TrendingUp size={20} />} label="Forecasting" />
              <NavLink to="/ai-analytics" icon={<Brain size={20} />} label="AI Analytics" />
              <NavLink to="/reports" icon={<FileSpreadsheet size={20} />} label="Reports" />
              <NavLink to="/analytics" icon={<BarChart3 size={20} />} label="Analytics" />
              
              <div className="px-4 py-2 mt-4 text-xs font-semibold text-gray-400 uppercase">Integration</div>
              <NavLink to="/bank" icon={<Building2 size={20} />} label="Bank Import" />
              <NavLink to="/sync" icon={<Database size={20} />} label="Data Sync" />
              <NavLink to="/settings" icon={<Settings size={20} />} label="Settings" />
            </nav>
          </aside>

          {/* Main Content */}
          <main className="flex-1 overflow-y-auto">
            <Routes>
              <Route path="/" element={<AnalyticsDashboard />} />
              <Route path="/customers" element={<CustomerDashboard />} />
              <Route path="/documents" element={<DocumentManager />} />
              <Route path="/payments" element={<PaymentInterface />} />
              <Route path="/cashflow" element={<CashFlowDashboard />} />
              <Route path="/budget" element={<BudgetDashboard />} />
              <Route path="/ar" element={<ARDashboard />} />
              <Route path="/kpis" element={<KPIDashboard />} />
              <Route path="/forecasting" element={<ForecastingDashboard />} />
              <Route path="/ai-analytics" element={<AIAnalyticsDashboard />} />
              <Route path="/reports" element={<ReportsDashboard />} />
              <Route path="/bank" element={<BankStatementDashboard />} />
              <Route path="/sync" element={<DataSyncDashboard />} />
              <Route path="/analytics" element={<AnalyticsDashboard />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </main>
        </div>
      </Router>
    </QueryClientProvider>
  );
}

const NavLink: React.FC<{ to: string; icon: React.ReactNode; label: string }> = ({
  to,
  icon,
  label,
}) => {
  return (
    <Link
      to={to}
      className="flex items-center gap-3 px-6 py-3 text-gray-700 hover:bg-primary-50 hover:text-primary-600 transition"
    >
      {icon}
      <span className="font-medium">{label}</span>
    </Link>
  );
};

const SettingsPage: React.FC = () => {
  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-gray-800 mb-6">Settings</h1>
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-4">SUMIT API Configuration</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">API Key</label>
            <input
              type="password"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Enter your SUMIT API key"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Company ID</label>
            <input
              type="text"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Enter your company ID"
            />
          </div>
          <button className="bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition">
            Save Settings
          </button>
        </div>
      </div>
    </div>
  );
};

export default App;
