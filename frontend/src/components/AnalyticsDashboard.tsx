/**
 * Analytics and Reports Dashboard
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { TrendingUp, TrendingDown, DollarSign, Users, FileText, CreditCard } from 'lucide-react';
import apiService from '../services/api';

export const AnalyticsDashboard: React.FC = () => {
  const { data: balance } = useQuery({
    queryKey: ['balance'],
    queryFn: () => apiService.getBalance(),
  });

  // Mock data for charts
  const revenueData = [
    { month: 'Jan', revenue: 45000 },
    { month: 'Feb', revenue: 52000 },
    { month: 'Mar', revenue: 48000 },
    { month: 'Apr', revenue: 61000 },
    { month: 'May', revenue: 55000 },
    { month: 'Jun', revenue: 67000 },
  ];

  const documentTypeData = [
    { name: 'Invoices', value: 45 },
    { name: 'Receipts', value: 30 },
    { name: 'Quotes', value: 15 },
    { name: 'Credit Notes', value: 10 },
  ];

  const COLORS = ['#0ea5e9', '#10b981', '#f59e0b', '#ef4444'];

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-gray-800 mb-8">Analytics & Reports</h1>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Total Revenue"
          value="₪328,000"
          change="+12.5%"
          icon={<DollarSign size={24} />}
          trend="up"
        />
        <StatCard
          title="Active Customers"
          value="156"
          change="+8.2%"
          icon={<Users size={24} />}
          trend="up"
        />
        <StatCard
          title="Documents Issued"
          value="342"
          change="+15.3%"
          icon={<FileText size={24} />}
          trend="up"
        />
        <StatCard
          title="Payments Processed"
          value="289"
          change="-3.1%"
          icon={<CreditCard size={24} />}
          trend="down"
        />
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Revenue Trend */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold text-gray-800 mb-4">Revenue Trend</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={revenueData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="revenue"
                stroke="#0ea5e9"
                strokeWidth={2}
                dot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Document Types Distribution */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold text-gray-800 mb-4">Document Types</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={documentTypeData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                {documentTypeData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Monthly Revenue Bar Chart */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-4">Monthly Revenue Comparison</h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={revenueData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Bar dataKey="revenue" fill="#0ea5e9" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

interface StatCardProps {
  title: string;
  value: string;
  change: string;
  icon: React.ReactNode;
  trend: 'up' | 'down';
}

const StatCard: React.FC<StatCardProps> = ({ title, value, change, icon, trend }) => {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex justify-between items-start mb-4">
        <div className="p-2 bg-primary-100 rounded-lg text-primary-600">{icon}</div>
        <div className={`flex items-center gap-1 text-sm font-medium ${
          trend === 'up' ? 'text-green-600' : 'text-red-600'
        }`}>
          {trend === 'up' ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
          {change}
        </div>
      </div>
      <h3 className="text-gray-600 text-sm font-medium mb-1">{title}</h3>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
};

export default AnalyticsDashboard;
