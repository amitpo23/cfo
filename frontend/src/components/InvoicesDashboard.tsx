import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileText,
  Send,
  Download,
  Plus,
  X,
  Check,
  Clock,
  AlertTriangle,
  RefreshCw,
  Search,
  Filter,
  Mail,
  CreditCard,
  Building,
  Loader2,
  ChevronDown,
  ChevronUp,
  Receipt,
  FileInput,
  FileMinus
} from 'lucide-react';
import api from '../services/api';

// Types
interface InvoiceItem {
  description: string;
  quantity: number;
  unit_price: number;
  vat_rate: number;
  discount: number;
}

interface Invoice {
  invoice_id: string;
  customer_id: string;
  customer_name: string;
  customer_email?: string;
  document_type: string;
  document_number?: string;
  status: string;
  issue_date: string;
  due_date: string;
  items: InvoiceItem[];
  subtotal: number;
  total_vat: number;
  total: number;
  currency: string;
  notes?: string;
  sumit_document_id?: string;
}

interface ReceivedInvoice {
  received_invoice_id: string;
  vendor_name: string;
  invoice_number: string;
  amount: number;
  vat_amount: number;
  total: number;
  issue_date: string;
  due_date: string;
  category: string;
  status: string;
  description: string;
}

interface InvoiceSummary {
  total_invoices: number;
  total_revenue: number;
  total_outstanding: number;
  total_overdue: number;
  aging: {
    current: number;
    '1_30_days': number;
    '31_60_days': number;
    '61_90_days': number;
    over_90_days: number;
  };
}

// Status badge component
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const getStatusStyle = (status: string) => {
    switch (status.toLowerCase()) {
      case 'paid':
        return 'bg-green-100 text-green-800';
      case 'sent':
        return 'bg-blue-100 text-blue-800';
      case 'draft':
        return 'bg-gray-100 text-gray-800';
      case 'overdue':
        return 'bg-red-100 text-red-800';
      case 'cancelled':
        return 'bg-orange-100 text-orange-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      draft: 'טיוטה',
      sent: 'נשלחה',
      paid: 'שולמה',
      overdue: 'באיחור',
      cancelled: 'בוטלה',
      partial: 'שולמה חלקית',
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

// Invoice creation modal
const CreateInvoiceModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: any) => void;
  isLoading: boolean;
}> = ({ isOpen, onClose, onSubmit, isLoading }) => {
  const [formData, setFormData] = useState({
    customer_id: '',
    customer_name: '',
    customer_email: '',
    document_type: 'invoice',
    items: [{ description: '', quantity: 1, unit_price: 0, vat_rate: 17, discount: 0 }],
    notes: '',
    send_to_sumit: true
  });

  const addItem = () => {
    setFormData({
      ...formData,
      items: [...formData.items, { description: '', quantity: 1, unit_price: 0, vat_rate: 17, discount: 0 }]
    });
  };

  const removeItem = (index: number) => {
    setFormData({
      ...formData,
      items: formData.items.filter((_, i) => i !== index)
    });
  };

  const updateItem = (index: number, field: string, value: any) => {
    const newItems = [...formData.items];
    newItems[index] = { ...newItems[index], [field]: value };
    setFormData({ ...formData, items: newItems });
  };

  const calculateTotal = () => {
    return formData.items.reduce((sum, item) => {
      const subtotal = item.quantity * item.unit_price * (1 - item.discount / 100);
      const vat = subtotal * (item.vat_rate / 100);
      return sum + subtotal + vat;
    }, 0);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] overflow-y-auto p-6">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold text-gray-800">יצירת חשבונית חדשה</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X className="h-6 w-6" />
          </button>
        </div>

        <div className="space-y-6">
          {/* Customer Details */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מזהה לקוח</label>
              <input
                type="text"
                value={formData.customer_id}
                onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500"
                placeholder="C-001"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">שם לקוח</label>
              <input
                type="text"
                value={formData.customer_name}
                onChange={(e) => setFormData({ ...formData, customer_name: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500"
                placeholder="שם הלקוח"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">אימייל</label>
              <input
                type="email"
                value={formData.customer_email}
                onChange={(e) => setFormData({ ...formData, customer_email: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500"
                placeholder="email@example.com"
              />
            </div>
          </div>

          {/* Document Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">סוג מסמך</label>
            <select
              value={formData.document_type}
              onChange={(e) => setFormData({ ...formData, document_type: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500"
            >
              <option value="invoice">חשבונית מס</option>
              <option value="receipt">קבלה</option>
              <option value="quote">הצעת מחיר</option>
              <option value="proforma">חשבון עסקה</option>
              <option value="credit_note">חשבונית זיכוי</option>
            </select>
          </div>

          {/* Items */}
          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="block text-sm font-medium text-gray-700">פריטים</label>
              <button
                type="button"
                onClick={addItem}
                className="text-blue-600 hover:text-blue-800 text-sm flex items-center gap-1"
              >
                <Plus className="h-4 w-4" />
                הוסף פריט
              </button>
            </div>
            
            <div className="space-y-3">
              {formData.items.map((item, index) => (
                <div key={index} className="bg-gray-50 rounded-lg p-4 relative">
                  <button
                    type="button"
                    onClick={() => removeItem(index)}
                    className="absolute top-2 left-2 text-red-500 hover:text-red-700"
                  >
                    <X className="h-4 w-4" />
                  </button>
                  
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-500 mb-1">תיאור</label>
                      <input
                        type="text"
                        value={item.description}
                        onChange={(e) => updateItem(index, 'description', e.target.value)}
                        className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                        placeholder="תיאור הפריט"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">כמות</label>
                      <input
                        type="number"
                        value={item.quantity}
                        onChange={(e) => updateItem(index, 'quantity', parseFloat(e.target.value))}
                        className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                        min="0"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">מחיר</label>
                      <input
                        type="number"
                        value={item.unit_price}
                        onChange={(e) => updateItem(index, 'unit_price', parseFloat(e.target.value))}
                        className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                        min="0"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">מע"מ %</label>
                      <input
                        type="number"
                        value={item.vat_rate}
                        onChange={(e) => updateItem(index, 'vat_rate', parseFloat(e.target.value))}
                        className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                        min="0"
                        max="100"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">הערות</label>
            <textarea
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500"
              rows={3}
              placeholder="הערות נוספות..."
            />
          </div>

          {/* Send to SUMIT */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="send_to_sumit"
              checked={formData.send_to_sumit}
              onChange={(e) => setFormData({ ...formData, send_to_sumit: e.target.checked })}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <label htmlFor="send_to_sumit" className="text-sm text-gray-700">
              הפק ושלח ל-SUMIT
            </label>
          </div>

          {/* Total */}
          <div className="bg-blue-50 rounded-lg p-4">
            <div className="flex justify-between items-center text-lg font-bold">
              <span>סה"כ לתשלום:</span>
              <span>₪{calculateTotal().toLocaleString('he-IL', { minimumFractionDigits: 2 })}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
            >
              ביטול
            </button>
            <button
              onClick={() => onSubmit(formData)}
              disabled={isLoading || !formData.customer_name || formData.items.length === 0}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              צור חשבונית
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Receive Invoice Modal
const ReceiveInvoiceModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: any) => void;
  isLoading: boolean;
}> = ({ isOpen, onClose, onSubmit, isLoading }) => {
  const [formData, setFormData] = useState({
    vendor_name: '',
    vendor_id: '',
    invoice_number: '',
    amount: 0,
    vat_amount: 0,
    total: 0,
    issue_date: new Date().toISOString().split('T')[0],
    due_date: '',
    description: '',
    category: 'general',
    record_in_sumit: true
  });

  const categories = [
    { value: 'general', label: 'כללי' },
    { value: 'office', label: 'משרד' },
    { value: 'marketing', label: 'שיווק' },
    { value: 'professional', label: 'שירותים מקצועיים' },
    { value: 'rent', label: 'שכירות' },
    { value: 'utilities', label: 'חשמל/מים' },
    { value: 'inventory', label: 'מלאי' },
    { value: 'equipment', label: 'ציוד' }
  ];

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold text-gray-800">קליטת חשבונית ספק</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X className="h-6 w-6" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">שם ספק</label>
              <input
                type="text"
                value={formData.vendor_name}
                onChange={(e) => setFormData({ ...formData, vendor_name: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                placeholder="שם הספק"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מספר חשבונית</label>
              <input
                type="text"
                value={formData.invoice_number}
                onChange={(e) => setFormData({ ...formData, invoice_number: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                placeholder="INV-001"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">סכום לפני מע"מ</label>
              <input
                type="number"
                value={formData.amount}
                onChange={(e) => {
                  const amount = parseFloat(e.target.value) || 0;
                  const vat = amount * 0.17;
                  setFormData({ ...formData, amount, vat_amount: vat, total: amount + vat });
                }}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="0"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">מע"מ</label>
              <input
                type="number"
                value={formData.vat_amount}
                onChange={(e) => setFormData({ ...formData, vat_amount: parseFloat(e.target.value) || 0 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="0"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">סה"כ</label>
              <input
                type="number"
                value={formData.total}
                onChange={(e) => setFormData({ ...formData, total: parseFloat(e.target.value) || 0 })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
                min="0"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תאריך חשבונית</label>
              <input
                type="date"
                value={formData.issue_date}
                onChange={(e) => setFormData({ ...formData, issue_date: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">תאריך לתשלום</label>
              <input
                type="date"
                value={formData.due_date}
                onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">קטגוריה</label>
            <select
              value={formData.category}
              onChange={(e) => setFormData({ ...formData, category: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2"
            >
              {categories.map(cat => (
                <option key={cat.value} value={cat.value}>{cat.label}</option>
              ))}
            </select>
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

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="record_in_sumit"
              checked={formData.record_in_sumit}
              onChange={(e) => setFormData({ ...formData, record_in_sumit: e.target.checked })}
              className="rounded border-gray-300 text-blue-600"
            />
            <label htmlFor="record_in_sumit" className="text-sm text-gray-700">
              רשום ב-SUMIT
            </label>
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
              disabled={isLoading || !formData.vendor_name || !formData.invoice_number}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileInput className="h-4 w-4" />}
              קלוט חשבונית
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Main Component
const InvoicesDashboard: React.FC = () => {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'outgoing' | 'incoming'>('outgoing');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showReceiveModal, setShowReceiveModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [expandedInvoice, setExpandedInvoice] = useState<string | null>(null);

  // Queries
  const { data: invoices = [], isLoading: loadingInvoices } = useQuery({
    queryKey: ['invoices', statusFilter],
    queryFn: async () => {
      const params = statusFilter ? `?status=${statusFilter}` : '';
      const response = await api.get(`/financial/invoices${params}`);
      return response.data;
    }
  });

  const { data: receivedInvoices = [], isLoading: loadingReceived } = useQuery({
    queryKey: ['received-invoices'],
    queryFn: async () => {
      const response = await api.get('/financial/invoices/received');
      return response.data;
    }
  });

  const { data: summary } = useQuery({
    queryKey: ['invoice-summary'],
    queryFn: async () => {
      const response = await api.get('/financial/invoices/summary');
      return response.data;
    }
  });

  // Mutations
  const createInvoiceMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await api.post('/financial/invoices', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invoices'] });
      queryClient.invalidateQueries({ queryKey: ['invoice-summary'] });
      setShowCreateModal(false);
    }
  });

  const receiveInvoiceMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await api.post('/financial/invoices/receive', data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['received-invoices'] });
      setShowReceiveModal(false);
    }
  });

  const sendRemindersMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/financial/invoices/reminders');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invoices'] });
    }
  });

  const syncInvoicesMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/financial/invoices/sync');
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invoices'] });
      queryClient.invalidateQueries({ queryKey: ['invoice-summary'] });
    }
  });

  // Filter invoices by search term
  const filteredInvoices = invoices.filter((inv: Invoice) =>
    inv.customer_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    inv.document_number?.includes(searchTerm)
  );

  const filteredReceived = receivedInvoices.filter((inv: ReceivedInvoice) =>
    inv.vendor_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    inv.invoice_number?.includes(searchTerm)
  );

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">ניהול חשבוניות</h1>
          <p className="text-gray-600">הפקה, קליטה וניהול חשבוניות</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => syncInvoicesMutation.mutate()}
            disabled={syncInvoicesMutation.isPending}
            className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${syncInvoicesMutation.isPending ? 'animate-spin' : ''}`} />
            סנכרון SUMIT
          </button>
          <button
            onClick={() => setShowReceiveModal(true)}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2"
          >
            <FileInput className="h-4 w-4" />
            קליטת חשבונית
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
          >
            <Plus className="h-4 w-4" />
            חשבונית חדשה
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-100 rounded-lg">
                <FileText className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">סה"כ חשבוניות</p>
                <p className="text-xl font-bold">{summary.total_invoices || 0}</p>
              </div>
            </div>
          </div>
          
          <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-green-100 rounded-lg">
                <Check className="h-5 w-5 text-green-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">הכנסות</p>
                <p className="text-xl font-bold">₪{(summary.total_revenue || 0).toLocaleString('he-IL')}</p>
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
                <p className="text-xl font-bold">₪{(summary.total_outstanding || 0).toLocaleString('he-IL')}</p>
              </div>
            </div>
          </div>
          
          <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-red-100 rounded-lg">
                <AlertTriangle className="h-5 w-5 text-red-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">באיחור</p>
                <p className="text-xl font-bold">₪{(summary.total_overdue || 0).toLocaleString('he-IL')}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-8">
          <button
            onClick={() => setActiveTab('outgoing')}
            className={`py-3 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'outgoing'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <FileText className="h-4 w-4 inline-block ml-2" />
            חשבוניות יוצאות ({filteredInvoices.length})
          </button>
          <button
            onClick={() => setActiveTab('incoming')}
            className={`py-3 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'incoming'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <FileInput className="h-4 w-4 inline-block ml-2" />
            חשבוניות נכנסות ({filteredReceived.length})
          </button>
        </nav>
      </div>

      {/* Filters */}
      <div className="flex gap-4 items-center">
        <div className="flex-1 relative">
          <Search className="absolute right-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
          <input
            type="text"
            placeholder="חיפוש לפי שם או מספר חשבונית..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pr-10 pl-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2"
        >
          <option value="">כל הסטטוסים</option>
          <option value="draft">טיוטה</option>
          <option value="sent">נשלחה</option>
          <option value="paid">שולמה</option>
          <option value="overdue">באיחור</option>
        </select>
        {activeTab === 'outgoing' && (
          <button
            onClick={() => sendRemindersMutation.mutate()}
            disabled={sendRemindersMutation.isPending}
            className="px-4 py-2 bg-yellow-500 text-white rounded-lg hover:bg-yellow-600 flex items-center gap-2"
          >
            <Mail className="h-4 w-4" />
            שלח תזכורות
          </button>
        )}
      </div>

      {/* Outgoing Invoices Table */}
      {activeTab === 'outgoing' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {loadingInvoices ? (
            <div className="p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
              <p className="mt-2 text-gray-500">טוען חשבוניות...</p>
            </div>
          ) : filteredInvoices.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <FileText className="h-12 w-12 mx-auto text-gray-300 mb-3" />
              <p>לא נמצאו חשבוניות</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">מספר</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">לקוח</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תאריך</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סכום</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סטטוס</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">פעולות</th>
                </tr>
              </thead>
              <tbody>
                {filteredInvoices.map((invoice: Invoice) => (
                  <React.Fragment key={invoice.invoice_id}>
                    <tr className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">
                        <button
                          onClick={() => setExpandedInvoice(
                            expandedInvoice === invoice.invoice_id ? null : invoice.invoice_id
                          )}
                          className="flex items-center gap-2 text-blue-600 hover:text-blue-800"
                        >
                          {expandedInvoice === invoice.invoice_id ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                          {invoice.document_number || invoice.invoice_id}
                        </button>
                      </td>
                      <td className="py-3 px-4">{invoice.customer_name}</td>
                      <td className="py-3 px-4">{new Date(invoice.issue_date).toLocaleDateString('he-IL')}</td>
                      <td className="py-3 px-4 font-medium">
                        ₪{invoice.total?.toLocaleString('he-IL', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={invoice.status} />
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex gap-2">
                          <button className="p-1 text-gray-400 hover:text-blue-600" title="שלח">
                            <Send className="h-4 w-4" />
                          </button>
                          <button className="p-1 text-gray-400 hover:text-green-600" title="הורד PDF">
                            <Download className="h-4 w-4" />
                          </button>
                          <button className="p-1 text-gray-400 hover:text-purple-600" title="זיכוי">
                            <FileMinus className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {expandedInvoice === invoice.invoice_id && (
                      <tr>
                        <td colSpan={6} className="bg-gray-50 px-4 py-3">
                          <div className="text-sm">
                            <h4 className="font-medium mb-2">פריטים:</h4>
                            <table className="w-full">
                              <thead>
                                <tr className="text-gray-500">
                                  <th className="text-right py-1">תיאור</th>
                                  <th className="text-right py-1">כמות</th>
                                  <th className="text-right py-1">מחיר</th>
                                  <th className="text-right py-1">סה"כ</th>
                                </tr>
                              </thead>
                              <tbody>
                                {invoice.items?.map((item, idx) => (
                                  <tr key={idx}>
                                    <td className="py-1">{item.description}</td>
                                    <td className="py-1">{item.quantity}</td>
                                    <td className="py-1">₪{item.unit_price}</td>
                                    <td className="py-1">₪{(item.quantity * item.unit_price).toLocaleString()}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Incoming Invoices Table */}
      {activeTab === 'incoming' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {loadingReceived ? (
            <div className="p-8 text-center">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
              <p className="mt-2 text-gray-500">טוען חשבוניות...</p>
            </div>
          ) : filteredReceived.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <FileInput className="h-12 w-12 mx-auto text-gray-300 mb-3" />
              <p>לא נמצאו חשבוניות נכנסות</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">מספר</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">ספק</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">קטגוריה</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">תאריך</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סכום</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">סטטוס</th>
                </tr>
              </thead>
              <tbody>
                {filteredReceived.map((invoice: ReceivedInvoice) => (
                  <tr key={invoice.received_invoice_id} className="border-t border-gray-100 hover:bg-gray-50">
                    <td className="py-3 px-4 font-medium text-blue-600">
                      {invoice.invoice_number}
                    </td>
                    <td className="py-3 px-4">{invoice.vendor_name}</td>
                    <td className="py-3 px-4">
                      <span className="px-2 py-1 bg-gray-100 rounded-full text-xs">
                        {invoice.category}
                      </span>
                    </td>
                    <td className="py-3 px-4">{new Date(invoice.issue_date).toLocaleDateString('he-IL')}</td>
                    <td className="py-3 px-4 font-medium">
                      ₪{invoice.total?.toLocaleString('he-IL', { minimumFractionDigits: 2 })}
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={invoice.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Modals */}
      <CreateInvoiceModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={createInvoiceMutation.mutate}
        isLoading={createInvoiceMutation.isPending}
      />
      
      <ReceiveInvoiceModal
        isOpen={showReceiveModal}
        onClose={() => setShowReceiveModal(false)}
        onSubmit={receiveInvoiceMutation.mutate}
        isLoading={receiveInvoiceMutation.isPending}
      />
    </div>
  );
};

export default InvoicesDashboard;
