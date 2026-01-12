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
} from 'lucide-react';

import CustomerDashboard from './components/CustomerDashboard';
import DocumentManager from './components/DocumentManager';
import PaymentInterface from './components/PaymentInterface';
import AnalyticsDashboard from './components/AnalyticsDashboard';

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
          <aside className="w-64 bg-white shadow-md">
            <div className="p-6">
              <h1 className="text-2xl font-bold text-primary-600">CFO System</h1>
              <p className="text-sm text-gray-600">Financial Management</p>
            </div>
            <nav className="mt-6">
              <NavLink to="/" icon={<LayoutDashboard size={20} />} label="Dashboard" />
              <NavLink to="/customers" icon={<Users size={20} />} label="Customers" />
              <NavLink to="/documents" icon={<FileText size={20} />} label="Documents" />
              <NavLink to="/payments" icon={<CreditCard size={20} />} label="Payments" />
              <NavLink to="/analytics" icon={<BarChart3 size={20} />} label="Analytics" />
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
