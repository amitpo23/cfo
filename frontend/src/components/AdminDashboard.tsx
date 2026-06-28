import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Users,
  Building2,
  Shield,
  Eye,
  Edit,
  Trash2,
  Plus,
  Search,
  Check,
  X
} from 'lucide-react';
import axios from 'axios';

const API_BASE = '/api/admin';

// Types
interface Organization {
  id: number;
  name: string;
  business_type?: string;
  tax_id?: string;
  email?: string;
  phone?: string;
  integration_type: string;
  is_active: boolean;
  created_at: string;
}

interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
  organization_id?: number;
  phone?: string;
  is_active: boolean;
  last_login?: string;
  created_at: string;
}

const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: 'admin', label: 'מנהל ארגון' },
  { value: 'accountant', label: 'רואה חשבון' },
  { value: 'manager', label: 'מנהל' },
  { value: 'user', label: 'משתמש' },
  { value: 'viewer', label: 'צופה' },
];

const AdminDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'organizations' | 'users' | 'audit'>('organizations');
  const [searchTerm, setSearchTerm] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState<any>(null);

  // User modal state (separate from org modal)
  const [showUserModal, setShowUserModal] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [userError, setUserError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  // Fetch Organizations
  const { data: organizations, isLoading: loadingOrgs } = useQuery({
    queryKey: ['organizations'],
    queryFn: async () => {
      const token = localStorage.getItem('auth_token');
      const response = await axios.get<Organization[]>(`${API_BASE}/organizations`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      return response.data;
    }
  });

  // Fetch Users
  const { data: users, isLoading: loadingUsers } = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const token = localStorage.getItem('auth_token');
      const response = await axios.get<User[]>(`${API_BASE}/users`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      return response.data;
    }
  });

  // Create Organization Mutation
  const createOrgMutation = useMutation({
    mutationFn: async (data: Partial<Organization>) => {
      const token = localStorage.getItem('auth_token');
      return axios.post(`${API_BASE}/organizations`, data, {
        headers: { Authorization: `Bearer ${token}` }
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] });
      setShowModal(false);
      setEditItem(null);
    }
  });

  // Delete Organization Mutation
  const deleteOrgMutation = useMutation({
    mutationFn: async (id: number) => {
      const token = localStorage.getItem('auth_token');
      return axios.delete(`${API_BASE}/organizations/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] });
    }
  });

  // Create User Mutation
  const createUserMutation = useMutation({
    mutationFn: async (data: {
      email: string;
      password: string;
      full_name: string;
      phone?: string;
      role: string;
      organization_id?: number;
    }) => {
      const token = localStorage.getItem('auth_token');
      return axios.post(`${API_BASE}/users`, data, {
        headers: { Authorization: `Bearer ${token}` }
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setShowUserModal(false);
      setEditUser(null);
      setUserError(null);
    },
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        setUserError(err.response?.data?.detail ?? 'שגיאה ביצירת המשתמש');
      } else {
        setUserError('שגיאה ביצירת המשתמש');
      }
    }
  });

  // Update User Mutation
  const updateUserMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: { role?: string; is_active?: boolean; full_name?: string; phone?: string } }) => {
      const token = localStorage.getItem('auth_token');
      return axios.patch(`${API_BASE}/users/${id}`, data, {
        headers: { Authorization: `Bearer ${token}` }
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setShowUserModal(false);
      setEditUser(null);
      setUserError(null);
    },
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        setUserError(err.response?.data?.detail ?? 'שגיאה בעדכון המשתמש');
      } else {
        setUserError('שגיאה בעדכון המשתמש');
      }
    }
  });

  // Delete User Mutation
  const deleteUserMutation = useMutation({
    mutationFn: async (id: number) => {
      const token = localStorage.getItem('auth_token');
      return axios.delete(`${API_BASE}/users/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setUserError(null);
    },
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        setUserError(err.response?.data?.detail ?? 'שגיאה בהשבתת המשתמש');
      } else {
        setUserError('שגיאה בהשבתת המשתמש');
      }
    }
  });

  const getRoleBadgeColor = (role: string) => {
    const colors: Record<string, string> = {
      super_admin: 'bg-purple-100 text-purple-800',
      admin: 'bg-blue-100 text-blue-800',
      accountant: 'bg-green-100 text-green-800',
      manager: 'bg-yellow-100 text-yellow-800',
      user: 'bg-gray-100 text-gray-800',
      viewer: 'bg-slate-100 text-slate-800'
    };
    return colors[role] || 'bg-gray-100 text-gray-800';
  };

  const getIntegrationIcon = (type: string) => {
    const icons: Record<string, string> = {
      sumit: '🇮🇱',
      quickbooks: '📊',
      xero: '📈',
      manual: '📝'
    };
    return icons[type] || '📋';
  };

  const handleCreateUserSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setUserError(null);
    const formData = new FormData(e.currentTarget);
    const orgIdRaw = formData.get('organization_id') as string;
    const phoneRaw = formData.get('phone') as string;
    const payload = {
      email: formData.get('email') as string,
      password: formData.get('password') as string,
      full_name: formData.get('full_name') as string,
      role: formData.get('role') as string,
      ...(orgIdRaw ? { organization_id: Number(orgIdRaw) } : {}),
      ...(phoneRaw ? { phone: phoneRaw } : {}),
    };
    createUserMutation.mutate(payload);
  };

  const handleEditUserSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!editUser) return;
    setUserError(null);
    const formData = new FormData(e.currentTarget);
    const role = formData.get('role') as string;
    const isActiveCheckbox = formData.get('is_active');
    const payload: { role?: string; is_active?: boolean } = {
      role,
      is_active: isActiveCheckbox === 'on',
    };
    updateUserMutation.mutate({ id: editUser.id, data: payload });
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
          <Shield className="text-blue-600" size={36} />
          Admin Dashboard
        </h1>
        <p className="text-gray-600 mt-2">ניהול ארגונים, משתמשים והרשאות</p>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-lg shadow-sm mb-6">
        <div className="flex border-b">
          <button
            className={`flex items-center gap-2 px-6 py-4 font-medium transition-colors ${
              activeTab === 'organizations'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-gray-600 hover:text-gray-900'
            }`}
            onClick={() => setActiveTab('organizations')}
          >
            <Building2 size={20} />
            ארגונים
          </button>
          <button
            className={`flex items-center gap-2 px-6 py-4 font-medium transition-colors ${
              activeTab === 'users'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-gray-600 hover:text-gray-900'
            }`}
            onClick={() => setActiveTab('users')}
          >
            <Users size={20} />
            משתמשים
          </button>
          <button
            className={`flex items-center gap-2 px-6 py-4 font-medium transition-colors ${
              activeTab === 'audit'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-gray-600 hover:text-gray-900'
            }`}
            onClick={() => setActiveTab('audit')}
          >
            <Eye size={20} />
            לוג פעילות
          </button>
        </div>
      </div>

      {/* Search & Actions Bar */}
      <div className="bg-white rounded-lg shadow-sm p-4 mb-6 flex items-center justify-between">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={20} />
          <input
            type="text"
            placeholder="חיפוש..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {activeTab === 'organizations' && (
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={20} />
            ארגון חדש
          </button>
        )}

        {activeTab === 'users' && (
          <button
            onClick={() => {
              setEditUser(null);
              setUserError(null);
              setShowUserModal(true);
            }}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={20} />
            ➕ הוסף משתמש/לקוח
          </button>
        )}
      </div>

      {/* Delete error banner (shown outside modal, e.g. after delete) */}
      {userError && !showUserModal && activeTab === 'users' && (
        <div className="bg-red-50 border border-red-300 text-red-800 rounded-lg px-4 py-3 mb-4 flex items-center justify-between">
          <span>{userError}</span>
          <button onClick={() => setUserError(null)} className="text-red-600 hover:text-red-900">
            <X size={16} />
          </button>
        </div>
      )}

      {/* Content */}
      <div className="bg-white rounded-lg shadow-sm overflow-hidden">
        {activeTab === 'organizations' && (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    שם
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    סוג עסק
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    אינטגרציה
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    סטטוס
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    תאריך יצירה
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    פעולות
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {loadingOrgs ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-4 text-center">טוען...</td>
                  </tr>
                ) : (
                  organizations?.map((org) => (
                    <tr key={org.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center">
                          <div className="text-sm font-medium text-gray-900">{org.name}</div>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-900">{org.business_type || '-'}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          {getIntegrationIcon(org.integration_type)} {org.integration_type}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {org.is_active ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            <Check size={14} /> פעיל
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                            <X size={14} /> לא פעיל
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {new Date(org.created_at).toLocaleDateString('he-IL')}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              setEditItem(org);
                              setShowModal(true);
                            }}
                            className="text-blue-600 hover:text-blue-900"
                          >
                            <Edit size={18} />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm('האם אתה בטוח שברצונך למחוק ארגון זה?')) {
                                deleteOrgMutation.mutate(org.id);
                              }
                            }}
                            className="text-red-600 hover:text-red-900"
                          >
                            <Trash2 size={18} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'users' && (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    שם מלא
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    אימייל
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    תפקיד
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    סטטוס
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    התחברות אחרונה
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    פעולות
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {loadingUsers ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-4 text-center">טוען...</td>
                  </tr>
                ) : (
                  users?.map((user) => (
                    <tr key={user.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm font-medium text-gray-900">{user.full_name}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-500">{user.email}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${getRoleBadgeColor(user.role)}`}>
                          {user.role}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {user.is_active ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            <Check size={14} /> פעיל
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                            <X size={14} /> לא פעיל
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {user.last_login
                          ? new Date(user.last_login).toLocaleDateString('he-IL')
                          : 'אף פעם'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              setEditUser(user);
                              setUserError(null);
                              setShowUserModal(true);
                            }}
                            className="text-blue-600 hover:text-blue-900"
                          >
                            <Edit size={18} />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm('להשבית את המשתמש?')) {
                                deleteUserMutation.mutate(user.id);
                              }
                            }}
                            className="text-red-600 hover:text-red-900"
                          >
                            <Trash2 size={18} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="p-6">
            <p className="text-gray-500 text-center">לוג פעילות - בקרוב</p>
          </div>
        )}
      </div>

      {/* Modal for Create/Edit Organization */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full">
            <h3 className="text-xl font-bold mb-4">
              {editItem ? 'ערוך ארגון' : 'ארגון חדש'}
            </h3>
            <form onSubmit={(e) => {
              e.preventDefault();
              const formData = new FormData(e.currentTarget);
              const data = Object.fromEntries(formData.entries());
              createOrgMutation.mutate(data);
            }}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    שם הארגון
                  </label>
                  <input
                    name="name"
                    type="text"
                    required
                    defaultValue={editItem?.name}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    סוג עסק
                  </label>
                  <input
                    name="business_type"
                    type="text"
                    defaultValue={editItem?.business_type}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    סוג אינטגרציה
                  </label>
                  <select
                    name="integration_type"
                    defaultValue={editItem?.integration_type || 'manual'}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="manual">ידני</option>
                    <option value="sumit">SUMIT</option>
                    <option value="quickbooks">QuickBooks</option>
                    <option value="xero">Xero</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-2 mt-6">
                <button
                  type="submit"
                  className="flex-1 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
                >
                  שמור
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowModal(false);
                    setEditItem(null);
                  }}
                  className="flex-1 bg-gray-200 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-300"
                >
                  ביטול
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal for Create/Edit User */}
      {showUserModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full">
            <h3 className="text-xl font-bold mb-4">
              {editUser ? 'ערוך משתמש' : 'משתמש/לקוח חדש'}
            </h3>

            {/* Inline error inside modal */}
            {userError && (
              <div className="bg-red-50 border border-red-300 text-red-800 rounded-lg px-4 py-3 mb-4 flex items-center justify-between">
                <span>{userError}</span>
                <button onClick={() => setUserError(null)} className="text-red-600 hover:text-red-900">
                  <X size={16} />
                </button>
              </div>
            )}

            {editUser ? (
              /* Edit form — role + is_active only */
              <form onSubmit={handleEditUserSubmit}>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">תפקיד</label>
                    <select
                      name="role"
                      defaultValue={editUser.role}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    >
                      {ROLE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      name="is_active"
                      id="edit_is_active"
                      defaultChecked={editUser.is_active}
                      className="h-4 w-4 text-blue-600 border-gray-300 rounded"
                    />
                    <label htmlFor="edit_is_active" className="text-sm font-medium text-gray-700">
                      משתמש פעיל
                    </label>
                  </div>
                </div>
                <div className="flex gap-2 mt-6">
                  <button
                    type="submit"
                    disabled={updateUserMutation.isPending}
                    className="flex-1 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-60"
                  >
                    {updateUserMutation.isPending ? 'שומר...' : 'שמור'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowUserModal(false);
                      setEditUser(null);
                      setUserError(null);
                    }}
                    className="flex-1 bg-gray-200 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-300"
                  >
                    ביטול
                  </button>
                </div>
              </form>
            ) : (
              /* Create form */
              <form onSubmit={handleCreateUserSubmit}>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">אימייל</label>
                    <input
                      name="email"
                      type="email"
                      required
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">שם מלא</label>
                    <input
                      name="full_name"
                      type="text"
                      required
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      סיסמה ראשונית
                      <span className="text-gray-400 font-normal mr-1">(מינ׳ 8 תווים — הלקוח יוכל לשנותה)</span>
                    </label>
                    <input
                      name="password"
                      type="password"
                      required
                      minLength={8}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">תפקיד</label>
                    <select
                      name="role"
                      required
                      defaultValue="user"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    >
                      {ROLE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">ארגון</label>
                    <select
                      name="organization_id"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="">ללא ארגון</option>
                      {organizations?.map((org) => (
                        <option key={org.id} value={org.id}>{org.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      טלפון <span className="text-gray-400 font-normal">(אופציונלי)</span>
                    </label>
                    <input
                      name="phone"
                      type="tel"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>
                <div className="flex gap-2 mt-6">
                  <button
                    type="submit"
                    disabled={createUserMutation.isPending}
                    className="flex-1 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-60"
                  >
                    {createUserMutation.isPending ? 'יוצר...' : 'צור משתמש'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowUserModal(false);
                      setUserError(null);
                    }}
                    className="flex-1 bg-gray-200 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-300"
                  >
                    ביטול
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminDashboard;
