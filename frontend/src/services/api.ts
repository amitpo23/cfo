/**
 * API Service for SUMIT Integration
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
    return this.get('/accounting/documents', { params });
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
}

export const apiService = new ApiService();
export default apiService;
