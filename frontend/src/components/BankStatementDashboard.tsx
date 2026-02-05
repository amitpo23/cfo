import React, { useState, useCallback } from 'react';
import {
  Upload,
  FileSpreadsheet,
  CheckCircle,
  AlertCircle,
  TrendingUp,
  RefreshCw,
  PieChart,
  Repeat
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart as RechartsPie,
  Pie,
  Cell,
  BarChart,
  Bar
} from 'recharts';
import api from '../services/api';

// צבעים לקטגוריות
const CATEGORY_COLORS: Record<string, string> = {
  salary: '#22c55e',
  utilities: '#ef4444',
  rent: '#f59e0b',
  groceries: '#3b82f6',
  transportation: '#8b5cf6',
  insurance: '#ec4899',
  bank_fees: '#6b7280',
  credit_card: '#14b8a6',
  transfer: '#06b6d4',
  loan: '#f97316',
  investment: '#84cc16',
  other: '#a855f7'
};

const CATEGORY_NAMES: Record<string, string> = {
  salary: 'משכורות',
  utilities: 'חשבונות',
  rent: 'שכירות',
  groceries: 'מכולת',
  transportation: 'תחבורה',
  insurance: 'ביטוח',
  bank_fees: 'עמלות בנק',
  credit_card: 'כרטיסי אשראי',
  transfer: 'העברות',
  loan: 'הלוואות',
  investment: 'השקעות',
  other: 'אחר'
};

const BANK_FORMATS = [
  { id: 'auto', name: 'זיהוי אוטומטי' },
  { id: 'leumi', name: 'בנק לאומי' },
  { id: 'hapoalim', name: 'בנק הפועלים' },
  { id: 'discount', name: 'בנק דיסקונט' },
  { id: 'mizrahi', name: 'בנק מזרחי-טפחות' },
  { id: 'isracard', name: 'ישראכרט' },
  { id: 'cal', name: 'כאל' },
  { id: 'max', name: 'מקס' },
  { id: 'generic', name: 'גנרי' }
];

interface Transaction {
  date: string;
  description: string;
  amount: number;
  balance?: number;
  category: string;
  is_debit: boolean;
}

interface ImportResult {
  success: boolean;
  parsed_transactions: number;
  created_transactions: number;
  duplicates_skipped: number;
  analysis: {
    total_transactions: number;
    total_income: number;
    total_expenses: number;
    net_flow: number;
    date_range: { start: string; end: string };
    category_breakdown: Record<string, { count: number; total: number }>;
  };
  transactions: Transaction[];
}

interface SpendingPattern {
  category: string;
  total: number;
  count: number;
  percentage: number;
  average: number;
}

interface RecurringTransaction {
  description: string;
  amount: number;
  occurrences: number;
  frequency: string;
  average_interval_days: number;
  last_occurrence: string;
  category: string;
}

interface SpendingPatternsResponse {
  patterns?: SpendingPattern[];
  total_spending?: number;
  transaction_count?: number;
}

interface RecurringResponse {
  recurring_transactions?: RecurringTransaction[];
}

export const BankStatementDashboard: React.FC = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [bankFormat, setBankFormat] = useState('auto');
  const [autoCategorize, setAutoCategorize] = useState(true);
  const [createTransactions, setCreateTransactions] = useState(true);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [activeTab, setActiveTab] = useState<'import' | 'analysis' | 'recurring'>('import');
  
  const queryClient = useQueryClient();

  // שליפת דפוסי הוצאות
  const { data: spendingPatterns, isLoading: patternsLoading } = useQuery<SpendingPatternsResponse>({
    queryKey: ['spendingPatterns'],
    queryFn: async () => {
      return api.get<SpendingPatternsResponse>('/api/sync/bank/spending-patterns');
    }
  });

  // שליפת עסקאות חוזרות
  const { data: recurringData, isLoading: recurringLoading } = useQuery<RecurringResponse>({
    queryKey: ['recurringTransactions'],
    queryFn: async () => {
      return api.get<RecurringResponse>('/api/sync/bank/recurring');
    }
  });

  // מוטציה לייבוא דף בנק
  const importMutation = useMutation<ImportResult, Error, File>({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('bank_format', bankFormat);
      formData.append('auto_categorize', String(autoCategorize));
      formData.append('create_transactions', String(createTransactions));

      return api.post<ImportResult>('/api/sync/bank/import', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
    },
    onSuccess: (data) => {
      setImportResult(data);
      queryClient.invalidateQueries({ queryKey: ['spendingPatterns'] });
      queryClient.invalidateQueries({ queryKey: ['recurringTransactions'] });
    }
  });

  // מוטציה לניתוח בלבד (ללא שמירה)
  const parseMutation = useMutation<ImportResult, Error, File>({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('bank_format', bankFormat);

      return api.post<ImportResult>('/api/sync/bank/parse', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
    },
    onSuccess: (data) => {
      setImportResult(data);
    }
  });

  const handleFileSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setImportResult(null);
    }
  }, []);

  const handleImport = useCallback(() => {
    if (selectedFile) {
      importMutation.mutate(selectedFile);
    }
  }, [selectedFile, importMutation]);

  const handlePreview = useCallback(() => {
    if (selectedFile) {
      parseMutation.mutate(selectedFile);
    }
  }, [selectedFile, parseMutation]);

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('he-IL', {
      style: 'currency',
      currency: 'ILS'
    }).format(amount);
  };

  // נתוני פאי לקטגוריות
  const categoryPieData = importResult?.analysis?.category_breakdown
    ? Object.entries(importResult.analysis.category_breakdown).map(([key, value]) => ({
        name: CATEGORY_NAMES[key] || key,
        value: value.total,
        color: CATEGORY_COLORS[key] || '#a855f7'
      }))
    : [];

  // נתוני דפוסי הוצאות
  const patternBarData = spendingPatterns?.patterns?.map((p: SpendingPattern) => ({
    category: CATEGORY_NAMES[p.category] || p.category,
    total: p.total,
    count: p.count,
    color: CATEGORY_COLORS[p.category] || '#a855f7'
  })) || [];

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">קליטת דפי בנק</h1>
          <p className="text-gray-500 mt-1">ייבוא וניתוח דפי בנק וכרטיסי אשראי</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setActiveTab('import')}
            className={`px-4 py-2 rounded-lg transition-colors ${
              activeTab === 'import' 
                ? 'bg-blue-600 text-white' 
                : 'bg-white text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Upload className="w-4 h-4 inline-block ml-2" />
            ייבוא
          </button>
          <button
            onClick={() => setActiveTab('analysis')}
            className={`px-4 py-2 rounded-lg transition-colors ${
              activeTab === 'analysis' 
                ? 'bg-blue-600 text-white' 
                : 'bg-white text-gray-700 hover:bg-gray-100'
            }`}
          >
            <PieChart className="w-4 h-4 inline-block ml-2" />
            ניתוח
          </button>
          <button
            onClick={() => setActiveTab('recurring')}
            className={`px-4 py-2 rounded-lg transition-colors ${
              activeTab === 'recurring' 
                ? 'bg-blue-600 text-white' 
                : 'bg-white text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Repeat className="w-4 h-4 inline-block ml-2" />
            עסקאות חוזרות
          </button>
        </div>
      </div>

      {/* Import Tab */}
      {activeTab === 'import' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Upload Section */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-xl font-semibold mb-4">העלאת קובץ</h2>
            
            {/* File Drop Zone */}
            <label className="block border-2 border-dashed border-gray-300 rounded-xl p-8 text-center cursor-pointer hover:border-blue-500 transition-colors">
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={handleFileSelect}
                className="hidden"
              />
              <FileSpreadsheet className="w-12 h-12 mx-auto text-gray-400 mb-4" />
              {selectedFile ? (
                <div>
                  <p className="text-green-600 font-medium">{selectedFile.name}</p>
                  <p className="text-gray-500 text-sm">
                    {(selectedFile.size / 1024).toFixed(1)} KB
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-gray-600">גרור קובץ לכאן או לחץ לבחירה</p>
                  <p className="text-gray-400 text-sm mt-1">CSV, XLSX, XLS</p>
                </div>
              )}
            </label>

            {/* Options */}
            <div className="mt-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  פורמט בנק
                </label>
                <select
                  value={bankFormat}
                  onChange={(e) => setBankFormat(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  {BANK_FORMATS.map(format => (
                    <option key={format.id} value={format.id}>
                      {format.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoCategorize}
                    onChange={(e) => setAutoCategorize(e.target.checked)}
                    className="w-4 h-4 text-blue-600 rounded"
                  />
                  <span className="text-sm text-gray-700">קטגוריזציה אוטומטית</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={createTransactions}
                    onChange={(e) => setCreateTransactions(e.target.checked)}
                    className="w-4 h-4 text-blue-600 rounded"
                  />
                  <span className="text-sm text-gray-700">שמירה במערכת</span>
                </label>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-3 mt-6">
                <button
                  onClick={handlePreview}
                  disabled={!selectedFile || parseMutation.isPending}
                  className="flex-1 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
                >
                  {parseMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 inline-block ml-2 animate-spin" />
                  ) : null}
                  תצוגה מקדימה
                </button>
                <button
                  onClick={handleImport}
                  disabled={!selectedFile || importMutation.isPending}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                  {importMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 inline-block ml-2 animate-spin" />
                  ) : (
                    <Upload className="w-4 h-4 inline-block ml-2" />
                  )}
                  ייבוא
                </button>
              </div>
            </div>
          </div>

          {/* Results Section */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-xl font-semibold mb-4">תוצאות ייבוא</h2>
            
            {importResult ? (
              <div className="space-y-4">
                {/* Status */}
                <div className={`flex items-center gap-2 p-3 rounded-lg ${
                  importResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                }`}>
                  {importResult.success ? (
                    <CheckCircle className="w-5 h-5" />
                  ) : (
                    <AlertCircle className="w-5 h-5" />
                  )}
                  <span>
                    {importResult.success 
                      ? `נקלטו ${importResult.created_transactions} עסקאות בהצלחה`
                      : 'שגיאה בקליטה'
                    }
                  </span>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <p className="text-sm text-gray-500">סה"כ עסקאות</p>
                    <p className="text-2xl font-bold">{importResult.parsed_transactions}</p>
                  </div>
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <p className="text-sm text-gray-500">כפילויות</p>
                    <p className="text-2xl font-bold">{importResult.duplicates_skipped}</p>
                  </div>
                </div>

                {/* Financial Summary */}
                {importResult.analysis && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg">
                      <span className="text-green-700">סה"כ הכנסות</span>
                      <span className="font-bold text-green-700">
                        {formatCurrency(importResult.analysis.total_income)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-red-50 rounded-lg">
                      <span className="text-red-700">סה"כ הוצאות</span>
                      <span className="font-bold text-red-700">
                        {formatCurrency(importResult.analysis.total_expenses)}
                      </span>
                    </div>
                    <div className={`flex items-center justify-between p-3 rounded-lg ${
                      importResult.analysis.net_flow >= 0 ? 'bg-blue-50' : 'bg-orange-50'
                    }`}>
                      <span className={importResult.analysis.net_flow >= 0 ? 'text-blue-700' : 'text-orange-700'}>
                        תזרים נקי
                      </span>
                      <span className={`font-bold ${
                        importResult.analysis.net_flow >= 0 ? 'text-blue-700' : 'text-orange-700'
                      }`}>
                        {formatCurrency(importResult.analysis.net_flow)}
                      </span>
                    </div>
                  </div>
                )}

                {/* Category Pie Chart */}
                {categoryPieData.length > 0 && (
                  <div className="h-64">
                    <h3 className="text-sm font-medium text-gray-700 mb-2">פילוח לפי קטגוריה</h3>
                    <ResponsiveContainer width="100%" height="100%">
                      <RechartsPie>
                        <Pie
                          data={categoryPieData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={80}
                          label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                        >
                          {categoryPieData.map((_entry, index) => (
                            <Cell key={`cell-${index}`} fill={_entry.color} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value: number) => formatCurrency(value)} />
                      </RechartsPie>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <FileSpreadsheet className="w-16 h-16 mx-auto mb-4" />
                <p>בחר קובץ לייבוא כדי לראות תוצאות</p>
              </div>
            )}
          </div>

          {/* Transactions Table */}
          {importResult?.transactions && importResult.transactions.length > 0 && (
            <div className="lg:col-span-2 bg-white rounded-xl shadow-sm p-6">
              <h2 className="text-xl font-semibold mb-4">רשימת עסקאות</h2>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b">
                      <th className="text-right py-3 px-4 text-sm font-medium text-gray-500">תאריך</th>
                      <th className="text-right py-3 px-4 text-sm font-medium text-gray-500">תיאור</th>
                      <th className="text-right py-3 px-4 text-sm font-medium text-gray-500">קטגוריה</th>
                      <th className="text-right py-3 px-4 text-sm font-medium text-gray-500">סכום</th>
                      <th className="text-right py-3 px-4 text-sm font-medium text-gray-500">יתרה</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.transactions.slice(0, 50).map((tx, index) => (
                      <tr key={index} className="border-b hover:bg-gray-50">
                        <td className="py-3 px-4 text-sm">{tx.date}</td>
                        <td className="py-3 px-4 text-sm">{tx.description}</td>
                        <td className="py-3 px-4">
                          <span 
                            className="px-2 py-1 rounded-full text-xs"
                            style={{ 
                              backgroundColor: `${CATEGORY_COLORS[tx.category] || '#a855f7'}20`,
                              color: CATEGORY_COLORS[tx.category] || '#a855f7'
                            }}
                          >
                            {CATEGORY_NAMES[tx.category] || tx.category}
                          </span>
                        </td>
                        <td className={`py-3 px-4 text-sm font-medium ${
                          tx.is_debit ? 'text-red-600' : 'text-green-600'
                        }`}>
                          {tx.is_debit ? '-' : '+'}{formatCurrency(Math.abs(tx.amount))}
                        </td>
                        <td className="py-3 px-4 text-sm">
                          {tx.balance ? formatCurrency(tx.balance) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {importResult.transactions.length > 50 && (
                  <p className="text-center text-gray-500 text-sm mt-4">
                    מוצגות 50 עסקאות מתוך {importResult.transactions.length}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Analysis Tab */}
      {activeTab === 'analysis' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Spending Patterns */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-xl font-semibold mb-4">דפוסי הוצאות</h2>
            {patternsLoading ? (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
              </div>
            ) : (spendingPatterns?.patterns ?? []).length > 0 ? (
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={patternBarData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tickFormatter={(v) => formatCurrency(v)} />
                    <YAxis type="category" dataKey="category" width={100} />
                    <Tooltip formatter={(value: number) => formatCurrency(value)} />
                    <Bar dataKey="total" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <PieChart className="w-16 h-16 mx-auto mb-4" />
                <p>אין מספיק נתונים לניתוח</p>
                <p className="text-sm mt-1">ייבא דפי בנק כדי לראות ניתוח</p>
              </div>
            )}
          </div>

          {/* Summary Stats */}
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-xl font-semibold mb-4">סיכום הוצאות</h2>
            {(spendingPatterns?.patterns ?? []).length > 0 ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-blue-50 p-4 rounded-lg">
                    <p className="text-sm text-blue-600">סה"כ הוצאות</p>
                    <p className="text-2xl font-bold text-blue-700">
                      {formatCurrency(spendingPatterns?.total_spending ?? 0)}
                    </p>
                  </div>
                  <div className="bg-purple-50 p-4 rounded-lg">
                    <p className="text-sm text-purple-600">מספר עסקאות</p>
                    <p className="text-2xl font-bold text-purple-700">
                      {spendingPatterns?.transaction_count}
                    </p>
                  </div>
                </div>

                {/* Category List */}
                <div className="space-y-2 mt-4">
                  {(spendingPatterns?.patterns || []).map((pattern: SpendingPattern, index: number) => (
                    <div key={index} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div className="flex items-center gap-3">
                        <div 
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: CATEGORY_COLORS[pattern.category] || '#a855f7' }}
                        />
                        <span className="font-medium">
                          {CATEGORY_NAMES[pattern.category] || pattern.category}
                        </span>
                        <span className="text-sm text-gray-500">
                          ({pattern.count} עסקאות)
                        </span>
                      </div>
                      <div className="text-left">
                        <p className="font-bold">{formatCurrency(pattern.total)}</p>
                        <p className="text-xs text-gray-500">{pattern.percentage.toFixed(1)}%</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <TrendingUp className="w-16 h-16 mx-auto mb-4" />
                <p>אין נתוני הוצאות עדיין</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Recurring Tab */}
      {activeTab === 'recurring' && (
        <div className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4">עסקאות חוזרות</h2>
          {recurringLoading ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
            </div>
          ) : (recurringData?.recurring_transactions ?? []).length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {(recurringData?.recurring_transactions || []).map((item: RecurringTransaction, index: number) => (
                <div key={index} className="border rounded-lg p-4 hover:shadow-md transition-shadow">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1">
                      <p className="font-medium text-gray-900 truncate">{item.description}</p>
                      <p className="text-sm text-gray-500">
                        {item.occurrences} מופעים
                      </p>
                    </div>
                    <span className={`px-2 py-1 rounded-full text-xs ${
                      item.frequency === 'monthly' ? 'bg-blue-100 text-blue-700' :
                      item.frequency === 'weekly' ? 'bg-green-100 text-green-700' :
                      item.frequency === 'yearly' ? 'bg-purple-100 text-purple-700' :
                      'bg-gray-100 text-gray-700'
                    }`}>
                      {item.frequency === 'monthly' ? 'חודשי' :
                       item.frequency === 'weekly' ? 'שבועי' :
                       item.frequency === 'yearly' ? 'שנתי' : 'לא סדיר'}
                    </span>
                  </div>
                  
                  <div className="mt-3 pt-3 border-t">
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-gray-500">סכום</span>
                      <span className={`font-bold ${
                        item.amount < 0 ? 'text-red-600' : 'text-green-600'
                      }`}>
                        {formatCurrency(Math.abs(item.amount))}
                      </span>
                    </div>
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-sm text-gray-500">מופע אחרון</span>
                      <span className="text-sm">{item.last_occurrence}</span>
                    </div>
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-sm text-gray-500">קטגוריה</span>
                      <span 
                        className="px-2 py-1 rounded-full text-xs"
                        style={{ 
                          backgroundColor: `${CATEGORY_COLORS[item.category] || '#a855f7'}20`,
                          color: CATEGORY_COLORS[item.category] || '#a855f7'
                        }}
                      >
                        {CATEGORY_NAMES[item.category] || item.category}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 text-gray-400">
              <Repeat className="w-16 h-16 mx-auto mb-4" />
              <p>לא נמצאו עסקאות חוזרות</p>
              <p className="text-sm mt-1">ייבא דפי בנק כדי לזהות עסקאות חוזרות</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default BankStatementDashboard;
