/**
 * Payment Processing Interface
 */
import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { CreditCard, DollarSign } from 'lucide-react';
import apiService from '../services/api';

interface Payment {
  payment_id: string;
  amount: number;
  currency: string;
  status: string;
  created_at: string;
  card_last_4?: string;
}

export const PaymentInterface: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'charge' | 'history'>('charge');

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-gray-800 mb-6">Payments</h1>

      {/* Tabs */}
      <div className="mb-6 flex gap-2 border-b border-gray-200">
        <button
          onClick={() => setActiveTab('charge')}
          className={`px-4 py-2 font-medium transition ${
            activeTab === 'charge'
              ? 'text-primary-600 border-b-2 border-primary-600'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          Process Payment
        </button>
        <button
          onClick={() => setActiveTab('history')}
          className={`px-4 py-2 font-medium transition ${
            activeTab === 'history'
              ? 'text-primary-600 border-b-2 border-primary-600'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          Payment History
        </button>
      </div>

      {activeTab === 'charge' ? <ChargeForm /> : <PaymentHistory />}
    </div>
  );
};

const ChargeForm: React.FC = () => {
  const [formData, setFormData] = useState({
    customer_id: '',
    amount: '',
    description: '',
    card_number: '',
    expiry_month: '',
    expiry_year: '',
    cvv: '',
    holder_name: '',
  });

  interface ChargeData {
    customer_id: string;
    amount: number;
    currency: string;
    description: string;
    card: {
      card_number: string;
      expiry_month: string;
      expiry_year: string;
      cvv: string;
      holder_name: string;
    };
  }

  const chargeMutation = useMutation<unknown, Error, ChargeData>({
    mutationFn: (data) => apiService.chargeCustomer(data),
    onSuccess: () => {
      alert('Payment processed successfully!');
      // Reset form
      setFormData({
        customer_id: '',
        amount: '',
        description: '',
        card_number: '',
        expiry_month: '',
        expiry_year: '',
        cvv: '',
        holder_name: '',
      });
    },
    onError: () => {
      alert('Payment failed. Please try again.');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    chargeMutation.mutate({
      customer_id: formData.customer_id,
      amount: parseFloat(formData.amount),
      currency: 'ILS',
      description: formData.description,
      card: {
        card_number: formData.card_number,
        expiry_month: formData.expiry_month,
        expiry_year: formData.expiry_year,
        cvv: formData.cvv,
        holder_name: formData.holder_name,
      },
    });
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="bg-white rounded-lg shadow-md p-8">
        <div className="flex items-center gap-3 mb-6">
          <CreditCard className="text-primary-600" size={32} />
          <h2 className="text-2xl font-bold text-gray-800">Process Payment</h2>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Customer Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Customer
            </label>
            <select
              value={formData.customer_id}
              onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              required
            >
              <option value="">Select customer...</option>
            </select>
          </div>

          {/* Amount */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Amount (₪)
            </label>
            <div className="relative">
              <DollarSign className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={20} />
              <input
                type="number"
                step="0.01"
                value={formData.amount}
                onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="0.00"
                required
              />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Description
            </label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Payment description"
            />
          </div>

          {/* Card Details */}
          <div className="border-t border-gray-200 pt-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">Card Details</h3>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Card Number
                </label>
                <input
                  type="text"
                  value={formData.card_number}
                  onChange={(e) => setFormData({ ...formData, card_number: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="1234 5678 9012 3456"
                  maxLength={19}
                  required
                />
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Month
                  </label>
                  <input
                    type="text"
                    value={formData.expiry_month}
                    onChange={(e) => setFormData({ ...formData, expiry_month: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="MM"
                    maxLength={2}
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Year
                  </label>
                  <input
                    type="text"
                    value={formData.expiry_year}
                    onChange={(e) => setFormData({ ...formData, expiry_year: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="YY"
                    maxLength={2}
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    CVV
                  </label>
                  <input
                    type="text"
                    value={formData.cvv}
                    onChange={(e) => setFormData({ ...formData, cvv: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="123"
                    maxLength={4}
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Cardholder Name
                </label>
                <input
                  type="text"
                  value={formData.holder_name}
                  onChange={(e) => setFormData({ ...formData, holder_name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="John Doe"
                  required
                />
              </div>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={chargeMutation.isPending}
            className="w-full bg-primary-600 text-white py-3 rounded-lg hover:bg-primary-700 transition disabled:opacity-50 disabled:cursor-not-allowed font-semibold"
          >
            {chargeMutation.isPending ? 'Processing...' : 'Process Payment'}
          </button>
        </form>
      </div>
    </div>
  );
};

const PaymentHistory: React.FC = () => {
  const { data: payments, isLoading } = useQuery<Payment[]>({
    queryKey: ['payments'],
    queryFn: async (): Promise<Payment[]> => {
      const response = await apiService.listPayments();
      return response as Payment[];
    },
  });

  if (isLoading) {
    return <div className="text-center py-12">Loading...</div>;
  }

  if (!payments || payments.length === 0) {
    return <div className="text-center py-12 text-gray-500">No payments found</div>;
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Date
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Amount
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Card
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Status
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              ID
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {payments.map((payment: Payment) => (
            <tr key={payment.payment_id} className="hover:bg-gray-50">
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                {new Date(payment.created_at).toLocaleDateString()}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                {payment.currency} {payment.amount.toFixed(2)}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {payment.card_last_4 ? `****${payment.card_last_4}` : '-'}
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                <span
                  className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                    payment.status === 'completed'
                      ? 'bg-green-100 text-green-800'
                      : payment.status === 'failed'
                      ? 'bg-red-100 text-red-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}
                >
                  {payment.status}
                </span>
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">
                {payment.payment_id.substring(0, 8)}...
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default PaymentInterface;
