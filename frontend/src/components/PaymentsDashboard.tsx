import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CreditCard,
  Send,
  Plus,
  X,
  Clock,
  Check,
  AlertTriangle,
  RefreshCw,
  Search,
  Calendar,
  Repeat,
  Mail,
  MessageSquare,
  DollarSign,
  User,
  Loader2,
  Play,
  Pause,
  Trash2,
  ChevronDown,
  ChevronUp,
  Link,
  FileText,
  Settings
} from 'lucide-react';
import api from '../services/api';

// Types
interface PaymentRequest {
  request_id: string;
  customer_id: string;
  customer_name: string;
  customer_email: string;
  amount: number;
  currency: string;
  description: string;
  status: string;
  created_at: string;
  expires_at: string;
  allowed_methods: string[];
  payment_link?: {
    url: string;
    link_id: string;
  };
}

interface StandingOrder {
  order_id: string;
  customer_id: string;
  customer_name: string;
  amount: number;
  currency: string;
  frequency: string;
  start_date: string;
  end_date?: string;
  next_charge_date: string;
  status: string;
  last_4_digits: string;
  total_charged: number;
  charge_count: number;
  description: string;
}

interface PaymentDemand {
  demand_id: string;
  customer_id: string;
  customer_name: string;
  amount: number;
  currency: string;
  due_date: string;
  description: string;
  status: string;
  payment_link?: string;
  reminder_count: number;
}

// Status badge component
const StatusBadge: React.FC<{ status: string; type?: 'request' | 'order' | 'demand' }> = ({ status, type }) => {
  const getStatusStyle = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'paid':
      case 'active':
        return 'bg-green-100 text-green-800';
      case 'sent':
      case 'opened':
        return 'bg-blue-100 text-blue-800';
      case 'draft':
      case 'pending':
        return 'bg-gray-100 text-gray-800';
      case 'expired':
      case 'cancelled':
      case 'suspended':
        return 'bg-red-100 text-red-800';
      case 'partial':
        return 'bg-yellow-100 text-yellow-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      draft: 'טיוטה',
      sent: 'נשלחה',
      opened: 'נפתחה',
      completed: 'הושלמה',
      paid: 'שולמה',
      partial: 'חלקית',
      cancelled: 'בוטלה',
      expired: 'פג תוקף',
      failed: 'נכשלה',
      active: 'פעילה',
      suspended: 'מושהית',
      pending: 'ממתינה'
    };
    return labels[status.toLowerCase()] || status;
  };

  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusStyle(status)}`}>
      {getStatusLabel(status)}
    </span>
  );
};

// Frequency label helper
const getFrequencyLabel = (frequency: string) => {
  const labels: Record<string, string> = {
    weekly: 'שבועי',
    bi_weekly: 'דו-שבועי',
    monthly: 'חודשי',
    quarterly: 'רבעוני',
    yearly: 'שנתי'
  };
  return labels[frequency] || frequency;
};

// Create Payment Request Modal
const CreatePaymentRequestModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: any) => void;
  isLoading: boolean;
}> = ({ isOpen, onClose, onSubmit, isLoading }) => {
  const [formData, setFormData] = useState({
    customer_id: '',
    customer_name: '',
    customer_email: '',
    customer_phone: '',
    amount: 0,
    description: '',
    allowed_methods: ['credit_card', 'bank_transfer'],
    expires_in_days: 30,
    installments_allowed: false,
    max_installments: 12
  });

  const paymentMethods = [
    { value: 'credit_card', label: 'כרטיס אשראי' },
    { value: 'bank_transfer', label: 'העברה בנקאית' },
    { value: 'bit', label: 'ביט' },
    { value: 'cash', label: 'מזומן' },
    { value: 'check', label: 'המחאה' }
  ];

  const toggleMethod = (method: string) => {
    if (formData.allowed_methods.includes(method)) {
      setFormData({
        ...formData,
        allowed_methods: formData.allowed_methods.filter(m => m !== method)
      });
    } else {
      setFormData({
        ...formData,
        allowed_methods: [...formData.allowed_methods, method]
      });
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold text-gray-800">בקשת תשלום חדשה</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X className="h-6 w-6" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מזהה לקוח</label>
              <input
                type="text"
                value={formData.customer_id}
                onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                placeholder="C-001"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">שם לקוח</label>
              <input
                type="text"
                value={formData.customer_name}
                onChange={(e) => setFormData({ ...formData, customer_name: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">אימייל</label>
              <input
                type="email"
                value={formData.customer_email}
                onChange={(e) => setFormData({ ...formData, customer_email: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">טלפון</label>
              <input
                type="tel"
                value={formData.customer_phone}
                onChange={(e) => setFormData({ ...formData, customer_phone: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">סכום (₪)</label>
            <input
              type="number"
              value={formData.amount}
              onChange={(e) => setFormData({ ...formData, amount: parseFloat(e.target.value) || 0 })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              min="0"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">תיאור</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
              rows={2}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">אמצעי תשלום מותרים</label>
            <div className="flex flex-wrap gap-2">
              {paymentMethods.map(method => (
                <button
                  key={method.value}
                  type="button"
                  onClick={() => toggleMethod(method.value)}
                  className={`px-3 py-1 rounded-full text-sm ${
                    formData.allowed_methods.includes(method.value)
                      ? 'bg-blue-100 text-blue-800 border-2 border-blue-300'
                      : 'bg-gray-100 text-gray-600 border-2 border-transparent'
                  }`}
                >
                  {method.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תוקף (ימים)</label>
              <input
                type="number"
                value={formData.expires_in_days}
                onChange={(e) => setFormData({ ...formData, expires_in_days: parseInt(e.target.value) || 30 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="1"
              />
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input
                type="checkbox"
                id="installments"
                checked={formData.installments_allowed}
                onChange={(e) => setFormData({ ...formData, installments_allowed: e.target.checked })}
                className="rounded border-gray-300 text-blue-600"
              />
              <label htmlFor="installments" className="text-sm text-gray-700">אפשר תשלומים</label>
            </div>
          </div>

          {formData.installments_allowed && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מקסימום תשלומים</label>
              <input
                type="number"
                value={formData.max_installments}
                onChange={(e) => setFormData({ ...formData, max_installments: parseInt(e.target.value) || 12 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="2"
                max="36"
              />
            </div>
          )}

          <div className="flex justify-end gap-3 mt-6">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
            >
              ביטול
            </button>
            <button
              onClick={() => onSubmit(formData)}
              disabled={isLoading || !formData.customer_name || !formData.amount}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              צור בקשה
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Create Standing Order Modal
const CreateStandingOrderModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: any) => void;
  isLoading: boolean;
}> = ({ isOpen, onClose, onSubmit, isLoading }) => {
  const [formData, setFormData] = useState({
    customer_id: '',
    customer_name: '',
    amount: 0,
    frequency: 'monthly',
    description: '',
    start_date: new Date().toISOString().split('T')[0],
    end_date: '',
    card_details: {
      card_number: '',
      expiry_month: '',
      expiry_year: '',
      cvv: '',
      holder_name: ''
    }
  });

  const frequencies = [
    { value: 'weekly', label: 'שבועי' },
    { value: 'bi_weekly', label: 'דו-שבועי' },
    { value: 'monthly', label: 'חודשי' },
    { value: 'quarterly', label: 'רבעוני' },
    { value: 'yearly', label: 'שנתי' }
  ];

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold text-gray-800">הוראת קבע חדשה</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X className="h-6 w-6" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מזהה לקוח</label>
              <input
                type="text"
                value={formData.customer_id}
                onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">שם לקוח</label>
              <input
                type="text"
                value={formData.customer_name}
                onChange={(e) => setFormData({ ...formData, customer_name: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">סכום חיוב (₪)</label>
              <input
                type="number"
                value={formData.amount}
                onChange={(e) => setFormData({ ...formData, amount: parseFloat(e.target.value) || 0 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="0"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תדירות</label>
              <select
                value={formData.frequency}
                onChange={(e) => setFormData({ ...formData, frequency: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              >
                {frequencies.map(f => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">תיאור</label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תאריך התחלה</label>
              <input
                type="date"
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תאריך סיום (אופציונלי)</label>
              <input
                type="date"
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          {/* Card Details */}
          <div className="border-t pt-4 mt-4">
            <h3 className="font-medium text-gray-700 mb-3 flex items-center gap-2">
              <CreditCard className="h-4 w-4" />
              פרטי כרטיס אשראי
            </h3>
            
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">שם בעל הכרטיס</label>
                <input
                  type="text"
                  value={formData.card_details.holder_name}
                  onChange={(e) => setFormData({
                    ...formData,
                    card_details: { ...formData.card_details, holder_name: e.target.value }
                  })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">מספר כרטיס</label>
                <input
                  type="text"
                  value={formData.card_details.card_number}
                  onChange={(e) => setFormData({
                    ...formData,
                    card_details: { ...formData.card_details, card_number: e.target.value }
                  })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2"
                  placeholder="1234 5678 9012 3456"
                />
              </div>
              
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">חודש</label>
                  <input
                    type="text"
                    value={formData.card_details.expiry_month}
                    onChange={(e) => setFormData({
                      ...formData,
                      card_details: { ...formData.card_details, expiry_month: e.target.value }
                    })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2"
                    placeholder="MM"
                    maxLength={2}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">שנה</label>
                  <input
                    type="text"
                    value={formData.card_details.expiry_year}
                    onChange={(e) => setFormData({
                      ...formData,
                      card_details: { ...formData.card_details, expiry_year: e.target.value }
                    })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2"
                    placeholder="YY"
                    maxLength={2}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">CVV</label>
                  <input
                    type="text"
                    value={formData.card_details.cvv}
                    onChange={(e) => setFormData({
                      ...formData,
                      card_details: { ...formData.card_details, cvv: e.target.value }
                    })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2"
                    placeholder="123"
                    maxLength={4}
                  />
                </div>
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-3 mt-6">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
            >
              ביטול
            </button>
            <button
              onClick={() => onSubmit(formData)}
              disabled={isLoading || !formData.customer_name || !formData.amount}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Repeat className="h-4 w-4" />}
              צור הוראת קבע
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Main Component
const PaymentsDashboard: React.FC = () => {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'requests' | 'standing' | 'demands'>('requests');
  const [showCreateRequestModal, setShowCreateRequestModal] = useState(false);
  const [showCreateOrderModal, setShowCreateOrderModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  // Queries
  const { data: paymentRequests = [], isLoading: loadingRequests } = useQuery({
    queryKey: ['payment-requests'],
    queryFn: async () => {
      const response = await api.get('/financial/payments/requests');
      return response.data;
    }
  });

  const { data: standingOrders = [], isLoading: loadingOrders } = useQuery({
    queryKey: ['standing-orders'],
    queryFn: async () => {
      const response = await api.get('/financial/payments/standing-orders');
      return response.data;
    }
  });

  const { data: paymentDemands = [], isLoading: loadingDemands } = useQuery({
    queryKey: ['payment-demands'],
    queryFn: async () => {
      const response = await api.get('/financial/payments/demands');
      return response.data;
    }
  });

  // Mutations
  const createRequestMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await api.post('/financial/payments/requests', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-requests'] });
      setShowCreateRequestModal(false);
    }
  });

  const sendRequestMutation = useMutation({
    mutationFn: async (requestId: string) => {
      const response = await api.post(`/financial/payments/requests/${requestId}/send`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-requests'] });
    }
  });

  const createOrderMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await api.post('/financial/payments/standing-orders', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['standing-orders'] });
      setShowCreateOrderModal(false);
    }
  });

  const chargeOrderMutation = useMutation({
    mutationFn: async (orderId: string) => {
      const response = await api.post(`/financial/payments/standing-orders/${orderId}/charge`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['standing-orders'] });
    }
  });

  const cancelOrderMutation = useMutation({
    mutationFn: async (orderId: string) => {
      const response = await api.delete(`/financial/payments/standing-orders/${orderId}`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['standing-orders'] });
    }
  });

  const runScheduledMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/financial/payments/standing-orders/run-scheduled');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['standing-orders'] });
    }
  });

  // Calculate statistics
  const stats = {
    totalRequests: paymentRequests.length,
    pendingAmount: paymentRequests
      .filter((r: PaymentRequest) => !['completed', 'paid'].includes(r.status.toLowerCase()))
      .reduce((sum: number, r: PaymentRequest) => sum + r.amount, 0),
    activeOrders: standingOrders.filter((o: StandingOrder) => o.status === 'active').length,
    monthlyRecurring: standingOrders
      .filter((o: StandingOrder) => o.status === 'active')
      .reduce((sum: number, o: StandingOrder) => sum + o.amount, 0)
  };

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">ניהול תשלומים</h1>
          <p className="text-gray-600">בקשות תשלום, הוראות קבע ודרישות</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => runScheduledMutation.mutate()}
            disabled={runScheduledMutation.isPending}
            className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2"
          >
            <Play className={`h-4 w-4 ${runScheduledMutation.isPending ? 'animate-pulse' : ''}`} />
            הרץ חיובים מתוזמנים
          </button>
          <button
            onClick={() => setShowCreateOrderModal(true)}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2"
          >
            <Repeat className="h-4 w-4" />
            הוראת קבע
          </button>
          <button
            onClick={() => setShowCreateRequestModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
          >
            <Plus className="h-4 w-4" />
            בקשת תשלום
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 rounded-lg">
              <Send className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">בקשות תשלום</p>
              <p className="text-xl font-bold">{stats.totalRequests}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-100 rounded-lg">
              <Clock className="h-5 w-5 text-yellow-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">ממתין לתשלום</p>
              <p className="text-xl font-bold">₪{stats.pendingAmount.toLocaleString('he-IL')}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 rounded-lg">
              <Repeat className="h-5 w-5 text-green-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">הוראות קבע פעילות</p>
              <p className="text-xl font-bold">{stats.activeOrders}</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 rounded-lg">
              <DollarSign className="h-5 w-5 text-purple-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">הכנסה חוזרת</p>
              <p className="text-xl font-bold">₪{stats.monthlyRecurring.toLocaleString('he-IL')}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-8">
          <button
            onClick={() => setActiveTab('requests')}
            className={`py-3 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'requests'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Send className="h-4 w-4 inline-block ml-2" />
            בקשות תשלום ({paymentRequests.length})
          </button>
          <button
            onClick={() => setActiveTab('standing')}
            className={`py-3 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'standing'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Repeat className="h-4 w-4 inline-block ml-2" />
            הוראות קבע ({standingOrders.length})
          </button>
          <button
            onClick={() => setActiveTab('demands')}
            className={`py-3 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'demands'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <FileText className="h-4 w-4 inline-block ml-2" />
            דרישות תשלום ({paymentDemands.length})
          </button>
        </nav>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute right-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
        <input
          type="text"
          placeholder="חיפוש לפי שם לקוח..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full pr-10 pl-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Payment Requests Tab */}
      {activeTab === 'requests' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {loadingRequests ? (
            <div className="p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
            </div>
          ) : paymentRequests.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <Send className="h-12 w-12 mx-auto text-gray-300 mb-3" />
              <p>אין בקשות תשלום</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">לקוח</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סכום</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תיאור</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תוקף</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סטטוס</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">פעולות</th>
                </tr>
              </thead>
              <tbody>
                {paymentRequests
                  .filter((r: PaymentRequest) => 
                    r.customer_name?.toLowerCase().includes(searchTerm.toLowerCase())
                  )
                  .map((request: PaymentRequest) => (
                    <tr key={request.request_id} className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <User className="h-4 w-4 text-gray-400" />
                          <span>{request.customer_name}</span>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-medium">
                        ₪{request.amount?.toLocaleString('he-IL')}
                      </td>
                      <td className="py-3 px-4 text-gray-600">{request.description}</td>
                      <td className="py-3 px-4">
                        {new Date(request.expires_at).toLocaleDateString('he-IL')}
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={request.status} />
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex gap-2">
                          {request.status === 'draft' && (
                            <button
                              onClick={() => sendRequestMutation.mutate(request.request_id)}
                              className="p-1 text-gray-400 hover:text-blue-600"
                              title="שלח"
                            >
                              <Send className="h-4 w-4" />
                            </button>
                          )}
                          {request.payment_link && (
                            <button
                              onClick={() => navigator.clipboard.writeText(request.payment_link!.url)}
                              className="p-1 text-gray-400 hover:text-green-600"
                              title="העתק קישור"
                            >
                              <Link className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Standing Orders Tab */}
      {activeTab === 'standing' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {loadingOrders ? (
            <div className="p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
            </div>
          ) : standingOrders.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <Repeat className="h-12 w-12 mx-auto text-gray-300 mb-3" />
              <p>אין הוראות קבע</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">לקוח</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סכום</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תדירות</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">חיוב הבא</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">כרטיס</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סטטוס</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">פעולות</th>
                </tr>
              </thead>
              <tbody>
                {standingOrders
                  .filter((o: StandingOrder) => 
                    o.customer_name?.toLowerCase().includes(searchTerm.toLowerCase())
                  )
                  .map((order: StandingOrder) => (
                    <tr key={order.order_id} className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">{order.customer_name}</td>
                      <td className="py-3 px-4 font-medium">
                        ₪{order.amount?.toLocaleString('he-IL')}
                      </td>
                      <td className="py-3 px-4">{getFrequencyLabel(order.frequency)}</td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-1">
                          <Calendar className="h-4 w-4 text-gray-400" />
                          {new Date(order.next_charge_date).toLocaleDateString('he-IL')}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-1">
                          <CreditCard className="h-4 w-4 text-gray-400" />
                          •••• {order.last_4_digits}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={order.status} />
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex gap-2">
                          {order.status === 'active' && (
                            <>
                              <button
                                onClick={() => chargeOrderMutation.mutate(order.order_id)}
                                className="p-1 text-gray-400 hover:text-green-600"
                                title="חייב עכשיו"
                              >
                                <Play className="h-4 w-4" />
                              </button>
                              <button
                                onClick={() => cancelOrderMutation.mutate(order.order_id)}
                                className="p-1 text-gray-400 hover:text-red-600"
                                title="בטל"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Payment Demands Tab */}
      {activeTab === 'demands' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {loadingDemands ? (
            <div className="p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
            </div>
          ) : paymentDemands.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <FileText className="h-12 w-12 mx-auto text-gray-300 mb-3" />
              <p>אין דרישות תשלום</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">לקוח</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סכום</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תיאור</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תאריך יעד</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תזכורות</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סטטוס</th>
                </tr>
              </thead>
              <tbody>
                {paymentDemands
                  .filter((d: PaymentDemand) => 
                    d.customer_name?.toLowerCase().includes(searchTerm.toLowerCase())
                  )
                  .map((demand: PaymentDemand) => (
                    <tr key={demand.demand_id} className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">{demand.customer_name}</td>
                      <td className="py-3 px-4 font-medium">
                        ₪{demand.amount?.toLocaleString('he-IL')}
                      </td>
                      <td className="py-3 px-4 text-gray-600">{demand.description}</td>
                      <td className="py-3 px-4">
                        {new Date(demand.due_date).toLocaleDateString('he-IL')}
                      </td>
                      <td className="py-3 px-4">
                        <span className="text-sm text-gray-500">{demand.reminder_count}</span>
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={demand.status} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Modals */}
      <CreatePaymentRequestModal
        isOpen={showCreateRequestModal}
        onClose={() => setShowCreateRequestModal(false)}
        onSubmit={createRequestMutation.mutate}
        isLoading={createRequestMutation.isPending}
      />
      
      <CreateStandingOrderModal
        isOpen={showCreateOrderModal}
        onClose={() => setShowCreateOrderModal(false)}
        onSubmit={createOrderMutation.mutate}
        isLoading={createOrderMutation.isPending}
      />
    </div>
  );
};

export default PaymentsDashboard;
