/**
 * API Service for CFO System - Full SUMIT Integration
 * שירות API מלא למערכת CFO עם אינטגרציה ל-SUMIT
 */
import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

class ApiService {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor for adding auth token
    this.client.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('auth_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor for handling errors
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          localStorage.removeItem('auth_token');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  // Generic request methods
  async get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const response = await this.client.get<T>(url, config);
    return response.data;
  }

  async post<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    const response = await this.client.post<T>(url, data, config);
    return response.data;
  }

  async put<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    const response = await this.client.put<T>(url, data, config);
    return response.data;
  }

  async delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const response = await this.client.delete<T>(url, config);
    return response.data;
  }

  // ==================== Accounting - Customers ====================
  
  async createCustomer(customer: any) {
    return this.post('/accounting/customers', customer);
  }

  async updateCustomer(customerId: string, customer: any) {
    return this.put(`/accounting/customers/${customerId}`, customer);
  }

  async getCustomerDebt(customerId: string) {
    return this.get(`/accounting/customers/${customerId}/debt`);
  }

  // ==================== Accounting - Documents ====================

  async createDocument(document: any) {
    return this.post('/accounting/documents', document);
  }

  async getDocument(documentId: string) {
    return this.get(`/accounting/documents/${documentId}`);
  }

  async listDocuments(params?: any) {
    return this.get<any>('/accounting/documents', { params });
  }

  async sendDocument(documentId: string, email: string) {
    return this.post('/accounting/documents/send', {
      document_id: documentId,
      recipient_email: email,
    });
  }

  async downloadDocumentPdf(documentId: string) {
    const response = await this.client.get(
      `/accounting/documents/${documentId}/pdf`,
      { responseType: 'blob' }
    );
    return response.data;
  }

  async cancelDocument(documentId: string) {
    return this.post(`/accounting/documents/${documentId}/cancel`);
  }

  // ==================== Accounting - Income Items ====================

  async createIncomeItem(item: any) {
    return this.post('/accounting/income-items', item);
  }

  async listIncomeItems() {
    return this.get('/accounting/income-items');
  }

  // ==================== Accounting - Reports ====================

  async getDebtReport(params?: any) {
    return this.post('/accounting/reports/debt', params);
  }

  async getBalance() {
    return this.get('/accounting/balance');
  }

  // ==================== Payments ====================

  async chargeCustomer(charge: any) {
    return this.post('/payments/charge', charge);
  }

  async getPayment(paymentId: string) {
    return this.get(`/payments/${paymentId}`);
  }

  async listPayments(params?: any) {
    return this.get('/payments', { params });
  }

  async getPaymentMethods(customerId: string) {
    return this.get(`/payments/methods/${customerId}`);
  }

  // ==================== Payments - Recurring ====================

  async listCustomerRecurring(customerId: string) {
    return this.get(`/payments/recurring/customer/${customerId}`);
  }

  async cancelRecurring(recurringId: string) {
    return this.post(`/payments/recurring/${recurringId}/cancel`);
  }

  // ==================== CRM ====================

  async createEntity(entity: any) {
    return this.post('/crm/entities', entity);
  }

  async getEntity(entityId: string) {
    return this.get(`/crm/entities/${entityId}`);
  }

  async listEntities(folderId: string, params?: any) {
    return this.get('/crm/entities', { params: { folder_id: folderId, ...params } });
  }

  async updateEntity(entityId: string, entity: any) {
    return this.put(`/crm/entities/${entityId}`, entity);
  }

  async deleteEntity(entityId: string) {
    return this.delete(`/crm/entities/${entityId}`);
  }

  async listFolders() {
    return this.get('/crm/folders');
  }

  // ==================== Communications ====================

  async sendSMS(sms: any) {
    return this.post('/communications/sms/send', sms);
  }

  async createTicket(ticket: any) {
    return this.post('/communications/tickets', ticket);
  }

  // ==================== Admin ====================

  async testConnection() {
    return this.get('/admin/test-connection');
  }

  async listStock() {
    return this.get('/admin/stock');
  }

  async listQuotas() {
    return this.get('/admin/quotas');
  }

  // ==================== Financial Operations - Invoices ====================

  async createInvoice(invoice: any) {
    return this.post('/financial/invoices', invoice);
  }

  async getInvoice(invoiceId: string) {
    return this.get(`/financial/invoices/${invoiceId}`);
  }

  async listInvoices(params?: { status?: string; customer_id?: string; start_date?: string; end_date?: string }) {
    return this.get('/financial/invoices', { params });
  }

  async issueInvoiceToSumit(invoiceId: string) {
    return this.post(`/financial/invoices/${invoiceId}/issue`);
  }

  async createCreditNote(creditNote: any) {
    return this.post('/financial/invoices/credit-note', creditNote);
  }

  async receiveSupplierInvoice(supplierInvoice: any) {
    return this.post('/financial/invoices/supplier', supplierInvoice);
  }

  async syncInvoicesFromSumit(params?: { start_date?: string; end_date?: string }) {
    return this.post('/financial/invoices/sync', params);
  }

  async sendPaymentReminder(invoiceId: string, method: 'email' | 'sms' = 'email') {
    return this.post(`/financial/invoices/${invoiceId}/remind`, { method });
  }

  // ==================== Financial Operations - Payment Requests ====================

  async createPaymentRequest(request: any) {
    return this.post('/financial/payments/requests', request);
  }

  async getPaymentRequest(requestId: string) {
    return this.get(`/financial/payments/requests/${requestId}`);
  }

  async listPaymentRequests(params?: { status?: string; customer_id?: string }) {
    return this.get('/financial/payments/requests', { params });
  }

  async sendPaymentRequest(requestId: string, method: 'email' | 'sms' = 'email') {
    return this.post(`/financial/payments/requests/${requestId}/send`, { method });
  }

  async processPaymentCallback(requestId: string, paymentData: any) {
    return this.post(`/financial/payments/requests/${requestId}/callback`, paymentData);
  }

  // ==================== Financial Operations - Standing Orders ====================

  async createStandingOrder(standingOrder: any) {
    return this.post('/financial/payments/standing-orders', standingOrder);
  }

  async getStandingOrder(orderId: string) {
    return this.get(`/financial/payments/standing-orders/${orderId}`);
  }

  async listStandingOrders(params?: { status?: string; customer_id?: string }) {
    return this.get('/financial/payments/standing-orders', { params });
  }

  async chargeStandingOrder(orderId: string) {
    return this.post(`/financial/payments/standing-orders/${orderId}/charge`);
  }

  async pauseStandingOrder(orderId: string) {
    return this.post(`/financial/payments/standing-orders/${orderId}/pause`);
  }

  async resumeStandingOrder(orderId: string) {
    return this.post(`/financial/payments/standing-orders/${orderId}/resume`);
  }

  async cancelStandingOrder(orderId: string) {
    return this.post(`/financial/payments/standing-orders/${orderId}/cancel`);
  }

  // ==================== Financial Operations - Payment Demands ====================

  async createPaymentDemand(demand: any) {
    return this.post('/financial/payments/demands', demand);
  }

  async getPaymentDemand(demandId: string) {
    return this.get(`/financial/payments/demands/${demandId}`);
  }

  async listPaymentDemands(params?: { status?: string; customer_id?: string }) {
    return this.get('/financial/payments/demands', { params });
  }

  async sendPaymentDemand(demandId: string) {
    return this.post(`/financial/payments/demands/${demandId}/send`);
  }

  // ==================== Financial Operations - Agreements ====================

  async createAgreement(agreement: any) {
    return this.post('/financial/agreements', agreement);
  }

  async getAgreement(agreementId: string) {
    return this.get(`/financial/agreements/${agreementId}`);
  }

  async listAgreements(params?: { status?: string; customer_id?: string }) {
    return this.get('/financial/agreements', { params });
  }

  async updateAgreement(agreementId: string, agreement: any) {
    return this.put(`/financial/agreements/${agreementId}`, agreement);
  }

  async activateAgreement(agreementId: string) {
    return this.post(`/financial/agreements/${agreementId}/activate`);
  }

  async suspendAgreement(agreementId: string) {
    return this.post(`/financial/agreements/${agreementId}/suspend`);
  }

  async cancelAgreement(agreementId: string, reason?: string) {
    return this.post(`/financial/agreements/${agreementId}/cancel`, { reason });
  }

  async renewAgreement(agreementId: string, renewalTerms?: any) {
    return this.post(`/financial/agreements/${agreementId}/renew`, renewalTerms);
  }

  async generateAgreementInvoices(agreementId: string, periodMonths?: number) {
    return this.post(`/financial/agreements/${agreementId}/generate-invoices`, { period_months: periodMonths });
  }

  // ==================== Financial Operations - Cash Flow ====================

  async getCashFlowProjection(params?: { months?: number; include_invoices?: boolean; include_agreements?: boolean }) {
    return this.get('/financial/cashflow/projection', { params });
  }

  async getCashFlowForecast(params: { method: 'exponential_smoothing' | 'moving_average' | 'linear_regression'; periods?: number }) {
    return this.get('/financial/cashflow/forecast', { params });
  }

  async getCashFlowAnalysis(params?: { start_date?: string; end_date?: string }) {
    return this.get('/financial/cashflow/analysis', { params });
  }

  async getAgreementCashFlow(agreementId: string, months?: number) {
    return this.get(`/financial/agreements/${agreementId}/cashflow`, { params: { months } });
  }

  // ==================== AI Insights ====================

  async getAIInsights(params?: { focus_area?: string }) {
    return this.get('/ai/insights', { params });
  }

  async getCashFlowPrediction(horizonMonths?: number) {
    return this.get('/ai/cashflow-prediction', { params: { horizon_months: horizonMonths } });
  }

  async getAnomalyDetection() {
    return this.get('/ai/anomaly-detection');
  }

  // ==================== Reports ====================

  async generateReport(reportType: string, params?: any) {
    return this.post('/reports/generate', { report_type: reportType, ...params });
  }

  async downloadReport(reportId: string, format: 'pdf' | 'excel' = 'excel') {
    const response = await this.client.get(`/reports/${reportId}/download`, {
      params: { format },
      responseType: 'blob',
    });
    return response.data;
  }

  async getReportTemplates() {
    return this.get('/reports/templates');
  }

  // ==================== Dashboard & Analytics ====================

  async getDashboardStats() {
    return this.get('/analytics/dashboard');
  }

  async getRevenueAnalytics(params?: { period?: string; granularity?: string }) {
    return this.get('/analytics/revenue', { params });
  }

  async getCustomerAnalytics(params?: { segment?: string }) {
    return this.get('/analytics/customers', { params });
  }

  async getKPIs() {
    return this.get('/analytics/kpis');
  }

  async getARAgingReport() {
    return this.get('/analytics/ar-aging');
  }

  // ==================== Budget ====================

  async getBudget(year?: number, month?: number) {
    return this.get('/budget', { params: { year, month } });
  }

  async createBudget(budget: any) {
    return this.post('/budget', budget);
  }

  async updateBudget(budgetId: string, budget: any) {
    return this.put(`/budget/${budgetId}`, budget);
  }

  async getBudgetVarianceLegacy(budgetId: string) {
    return this.get(`/budget/${budgetId}/variance`);
  }

  // ==================== Bank Statements ====================

  async importBankStatement(file: File, bankId: string) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('bank_id', bankId);
    return this.post('/bank/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  }

  async listBankTransactions(params?: { start_date?: string; end_date?: string; account_id?: string }) {
    return this.get('/bank/transactions', { params });
  }

  async reconcileTransaction(transactionId: string, matchData: any) {
    return this.post(`/bank/transactions/${transactionId}/reconcile`, matchData);
  }

  // ==================== CFO Dashboard ====================

  async getCFOOverview() {
    return this.get('/dashboard/overview');
  }

  async getCFOCashflow(params?: { weeks?: number; scenario?: string }) {
    return this.get('/dashboard/cashflow', { params });
  }

  async getCFOPnl(params?: { months?: number }) {
    return this.get('/dashboard/pnl', { params });
  }

  async getARAging() {
    return this.get('/ar/aging');
  }

  async getARInvoices(params?: { status?: string }) {
    return this.get('/ar/invoices', { params });
  }

  async getAPBills(params?: { days_ahead?: number }) {
    return this.get('/ap/bills', { params });
  }

  async getBudgetVariance(params?: { year?: number; month?: number }) {
    return this.get('/budget/variance', { params });
  }

  // ==================== CFO Sync ====================

  async testIntegrationConnection() {
    return this.post('/integration/test');
  }

  async triggerSync(entityTypes?: string) {
    const params = entityTypes ? `?entity_types=${entityTypes}` : '';
    return this.post(`/sync/run${params}`);
  }

  async getSyncRuns(limit?: number) {
    return this.get('/sync/runs', { params: { limit } });
  }

  async getSyncRun(runId: number) {
    return this.get(`/sync/runs/${runId}`);
  }

  // ==================== CFO Tasks & Alerts ====================

  async createCFOTask(task: { title: string; description?: string; due_date?: string; entity_type?: string; entity_id?: number }) {
    return this.post('/tasks', task);
  }

  async listCFOTasks(status?: string) {
    return this.get('/tasks', { params: status ? { status } : undefined });
  }

  async updateCFOTask(taskId: number, update: { title?: string; status?: string; description?: string }) {
    return this.patch(`/tasks/${taskId}`, update);
  }

  async listCFOAlerts(status?: string) {
    return this.get('/alerts', { params: status ? { status } : undefined });
  }

  async updateCFOAlert(alertId: number, update: { status: string }) {
    return this.patch(`/alerts/${alertId}`, update);
  }

  async evaluateAlerts() {
    return this.post('/alerts/evaluate');
  }

  // ==================== Notes ====================

  async createNote(note: { entity_type: string; entity_id: number; text: string }) {
    return this.post('/notes', note);
  }

  async listNotes(entityType: string, entityId: number) {
    return this.get('/notes', { params: { entity_type: entityType, entity_id: entityId } });
  }

  // ==================== CFO Budgets ====================

  async createCFOBudget(budget: { category_name: string; year: number; month: number; budgeted_amount: number }) {
    return this.post('/budgets', budget);
  }

  async listCFOBudgets(params?: { year?: number; month?: number }) {
    return this.get('/budgets', { params });
  }

  // ==================== Reports Export ====================

  async exportReport(reportType: string) {
    return this.get(`/reports/${reportType}?format=csv`);
  }

  // Helper: PATCH method
  async patch<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    const response = await this.client.patch<T>(url, data, config);
    return response.data;
  }
}

// Types for better TypeScript support
export interface Invoice {
  id?: string;
  customer_id: string;
  customer_name: string;
  items: InvoiceItem[];
  total_amount: number;
  currency: string;
  status: 'draft' | 'pending' | 'issued' | 'paid' | 'overdue' | 'cancelled';
  due_date: string;
  created_at?: string;
  sumit_document_id?: string;
}

export interface InvoiceItem {
  description: string;
  quantity: number;
  unit_price: number;
  total: number;
  vat_rate?: number;
}

export interface PaymentRequest {
  id?: string;
  customer_id: string;
  customer_name: string;
  amount: number;
  currency: string;
  description: string;
  status: 'pending' | 'sent' | 'viewed' | 'paid' | 'expired' | 'cancelled';
  expiry_date?: string;
  payment_url?: string;
}

export interface StandingOrder {
  id?: string;
  customer_id: string;
  customer_name: string;
  amount: number;
  currency: string;
  frequency: 'weekly' | 'monthly' | 'quarterly' | 'yearly';
  status: 'active' | 'paused' | 'cancelled' | 'completed';
  next_charge_date: string;
  start_date: string;
  end_date?: string;
}

export interface Agreement {
  id?: string;
  customer_id: string;
  customer_name: string;
  title: string;
  description?: string;
  total_value: number;
  currency: string;
  status: 'draft' | 'pending' | 'active' | 'suspended' | 'cancelled' | 'completed';
  start_date: string;
  end_date: string;
  billing_frequency: 'one_time' | 'monthly' | 'quarterly' | 'yearly';
  auto_renew: boolean;
}

export interface CashFlowProjection {
  period: string;
  expected_income: number;
  expected_expenses: number;
  net_cash_flow: number;
  cumulative_balance: number;
  sources: {
    invoices: number;
    agreements: number;
    standing_orders: number;
    other: number;
  };
}

export interface ForecastResult {
  method: string;
  periods: number;
  predictions: Array<{
    period: string;
    predicted_value: number;
    lower_bound?: number;
    upper_bound?: number;
  }>;
  accuracy_metrics?: {
    mape?: number;
    rmse?: number;
    r2?: number;
  };
}

export const apiService = new ApiService();
export default apiService;
