/**
 * Customer Management Dashboard
 */
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus, Search, Mail, Phone, Edit, Trash2 } from 'lucide-react';

interface Customer {
  customer_id: string;
  name: string;
  email?: string;
  phone?: string;
  tax_id?: string;
  balance?: number;
}

export const CustomerDashboard: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');

  // Fetch customers (you'll need to implement this endpoint)
  const { data: customers, isLoading } = useQuery<Customer[]>({
    queryKey: ['customers'],
    queryFn: async () => {
      // This would need a list customers endpoint
      return [];
    },
  });

  const filteredCustomers = customers?.filter(
    (customer) =>
      customer.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      customer.email?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-800">Customers</h1>
        <button
          className="flex items-center gap-2 bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition"
        >
          <Plus size={20} />
          New Customer
        </button>
      </div>

      {/* Search Bar */}
      <div className="mb-6">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={20} />
          <input
            type="text"
            placeholder="Search customers..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
      </div>

      {/* Customers Grid */}
      {isLoading ? (
        <div className="text-center py-12">Loading...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredCustomers?.map((customer) => (
            <CustomerCard key={customer.customer_id} customer={customer} />
          ))}
        </div>
      )}

      {filteredCustomers?.length === 0 && !isLoading && (
        <div className="text-center py-12 text-gray-500">
          No customers found
        </div>
      )}
    </div>
  );
};

const CustomerCard: React.FC<{ customer: Customer }> = ({ customer }) => {
  return (
    <div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition">
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-xl font-semibold text-gray-800">{customer.name}</h3>
        <div className="flex gap-2">
          <button className="text-gray-600 hover:text-primary-600">
            <Edit size={18} />
          </button>
          <button className="text-gray-600 hover:text-red-600">
            <Trash2 size={18} />
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {customer.email && (
          <div className="flex items-center gap-2 text-gray-600">
            <Mail size={16} />
            <span className="text-sm">{customer.email}</span>
          </div>
        )}
        {customer.phone && (
          <div className="flex items-center gap-2 text-gray-600">
            <Phone size={16} />
            <span className="text-sm">{customer.phone}</span>
          </div>
        )}
      </div>

      {customer.balance !== undefined && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Balance:</span>
            <span className={`text-lg font-semibold ${customer.balance < 0 ? 'text-red-600' : 'text-green-600'}`}>
              ₪{customer.balance.toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default CustomerDashboard;
