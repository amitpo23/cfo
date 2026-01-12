/**
 * Document Creation and Management Component
 */
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, FileText, Download, Send, X } from 'lucide-react';
import { format } from 'date-fns';
import apiService from '../services/api';

interface Document {
  document_id: string;
  document_number: string;
  document_type: string;
  customer_id: string;
  total_amount: number;
  status: string;
  issue_date: string;
  due_date?: string;
}

interface DocumentItem {
  description: string;
  quantity: number;
  price: number;
}

export const DocumentManager: React.FC = () => {
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const queryClient = useQueryClient();

  const { data: documents, isLoading } = useQuery<Document[]>({
    queryKey: ['documents', filterType],
    queryFn: async () => {
      const params = filterType !== 'all' ? { document_type: filterType } : {};
      return apiService.listDocuments(params);
    },
  });

  const sendDocumentMutation = useMutation({
    mutationFn: ({ documentId, email }: { documentId: string; email: string }) =>
      apiService.sendDocument(documentId, email),
    onSuccess: () => {
      alert('Document sent successfully!');
    },
  });

  const downloadPdf = async (documentId: string) => {
    try {
      const blob = await apiService.downloadDocumentPdf(documentId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `document_${documentId}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error('Error downloading PDF:', error);
    }
  };

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-800">Documents</h1>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="flex items-center gap-2 bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition"
        >
          <Plus size={20} />
          New Document
        </button>
      </div>

      {/* Filter Tabs */}
      <div className="mb-6 flex gap-2 border-b border-gray-200">
        {['all', 'invoice', 'receipt', 'quote', 'credit_note'].map((type) => (
          <button
            key={type}
            onClick={() => setFilterType(type)}
            className={`px-4 py-2 font-medium transition ${
              filterType === type
                ? 'text-primary-600 border-b-2 border-primary-600'
                : 'text-gray-600 hover:text-gray-800'
            }`}
          >
            {type.charAt(0).toUpperCase() + type.slice(1).replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Documents Table */}
      {isLoading ? (
        <div className="text-center py-12">Loading...</div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Document #
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Date
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Amount
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {documents?.map((doc) => (
                <tr key={doc.document_id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    {doc.document_number}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {doc.document_type}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {format(new Date(doc.issue_date), 'MMM dd, yyyy')}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    ₪{doc.total_amount.toFixed(2)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                        doc.status === 'paid'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}
                    >
                      {doc.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => downloadPdf(doc.document_id)}
                        className="text-gray-600 hover:text-primary-600"
                        title="Download PDF"
                      >
                        <Download size={18} />
                      </button>
                      <button
                        onClick={() => {
                          const email = prompt('Enter email address:');
                          if (email) {
                            sendDocumentMutation.mutate({
                              documentId: doc.document_id,
                              email,
                            });
                          }
                        }}
                        className="text-gray-600 hover:text-primary-600"
                        title="Send by Email"
                      >
                        <Send size={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isCreateModalOpen && (
        <CreateDocumentModal onClose={() => setIsCreateModalOpen(false)} />
      )}
    </div>
  );
};

const CreateDocumentModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [items, setItems] = useState<DocumentItem[]>([
    { description: '', quantity: 1, price: 0 },
  ]);

  const addItem = () => {
    setItems([...items, { description: '', quantity: 1, price: 0 }]);
  };

  const removeItem = (index: number) => {
    setItems(items.filter((_, i) => i !== index));
  };

  const total = items.reduce((sum, item) => sum + item.quantity * item.price, 0);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-gray-200 flex justify-between items-center">
          <h2 className="text-2xl font-bold text-gray-800">Create New Document</h2>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-800">
            <X size={24} />
          </button>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Document Type
              </label>
              <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500">
                <option value="invoice">Invoice</option>
                <option value="receipt">Receipt</option>
                <option value="quote">Quote</option>
                <option value="credit_note">Credit Note</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Customer
              </label>
              <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500">
                <option value="">Select customer...</option>
              </select>
            </div>
          </div>

          {/* Items */}
          <div className="mb-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold text-gray-800">Items</h3>
              <button
                onClick={addItem}
                className="text-primary-600 hover:text-primary-700 text-sm font-medium"
              >
                + Add Item
              </button>
            </div>

            {items.map((item, index) => (
              <div key={index} className="grid grid-cols-12 gap-4 mb-4">
                <input
                  type="text"
                  placeholder="Description"
                  className="col-span-6 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  value={item.description}
                  onChange={(e) => {
                    const newItems = [...items];
                    newItems[index].description = e.target.value;
                    setItems(newItems);
                  }}
                />
                <input
                  type="number"
                  placeholder="Qty"
                  className="col-span-2 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  value={item.quantity}
                  onChange={(e) => {
                    const newItems = [...items];
                    newItems[index].quantity = parseFloat(e.target.value) || 0;
                    setItems(newItems);
                  }}
                />
                <input
                  type="number"
                  placeholder="Price"
                  className="col-span-3 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  value={item.price}
                  onChange={(e) => {
                    const newItems = [...items];
                    newItems[index].price = parseFloat(e.target.value) || 0;
                    setItems(newItems);
                  }}
                />
                {items.length > 1 && (
                  <button
                    onClick={() => removeItem(index)}
                    className="col-span-1 text-red-600 hover:text-red-700"
                  >
                    <X size={20} />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Total */}
          <div className="border-t border-gray-200 pt-4 mb-6">
            <div className="flex justify-between items-center text-xl font-bold">
              <span>Total:</span>
              <span>₪{total.toFixed(2)}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-4">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition"
            >
              Cancel
            </button>
            <button className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition">
              Create Document
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DocumentManager;
