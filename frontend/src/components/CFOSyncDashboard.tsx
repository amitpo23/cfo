import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, CheckCircle, XCircle, Clock, AlertTriangle, Loader2, Database, ShieldCheck } from 'lucide-react';
import apiService from '../services/api';
import { FinanceCard, FinancePageShell, MetricCard } from './finance-ui';

interface Props {
  darkMode: boolean;
}

interface TestConnectionResponse {
  success: boolean;
  message: string;
}

interface SyncRun {
  id: number;
  status: string;
  source: string;
  sync_type: string;
  entity_types?: string;
  started_at?: string;
  finished_at?: string;
  counts?: Record<string, Record<string, number>>;
  error_summary?: string | null;
}

const CFOSyncDashboard: React.FC<Props> = ({ darkMode }) => {
  const queryClient = useQueryClient();

  const { data: runs, isLoading } = useQuery<SyncRun[]>({
    queryKey: ['sync-runs'],
    queryFn: () => apiService.get('/sync/runs?limit=20'),
    refetchInterval: 5000,
  });

  const syncMutation = useMutation({
    mutationFn: (entityTypes?: string) =>
      apiService.post(`/sync/run${entityTypes ? `?entity_types=${entityTypes}` : ''}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-overview'] });
    },
  });

  const testMutation = useMutation<TestConnectionResponse>({
    mutationFn: () => apiService.post('/integration/test'),
  });

  const { data: integrationStatus } = useQuery<{
    configured: Record<string, boolean>;
    connections: Record<string, string>;
  }>({
    queryKey: ['integration-status'],
    queryFn: () => apiService.get('/integration/status'),
  });

  const { data: upayStatus } = useQuery<{ connected: boolean }>({
    queryKey: ['upay-status'],
    queryFn: () => apiService.get('/payments/upay/status'),
    enabled: !!integrationStatus?.configured?.sumit,
  });

  const [upayEmail, setUpayEmail] = React.useState('');
  const [upayPassword, setUpayPassword] = React.useState('');

  const upaySetupMutation = useMutation({
    mutationFn: () =>
      apiService.post('/payments/upay/setup', {
        email: upayEmail,
        password: upayPassword,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['upay-status'] });
      setUpayEmail('');
      setUpayPassword('');
    },
  });

  const [sumitKey, setSumitKey] = React.useState('');
  const [sumitCompany, setSumitCompany] = React.useState('');
  const [ofClientId, setOfClientId] = React.useState('');
  const [ofClientSecret, setOfClientSecret] = React.useState('');
  const [ofUserId, setOfUserId] = React.useState('');

  const sumitConfigMutation = useMutation({
    mutationFn: () =>
      apiService.post('/integration/sumit/configure', {
        api_key: sumitKey,
        company_id: sumitCompany || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-status'] });
      setSumitKey('');
      setSumitCompany('');
    },
  });

  const ofConfigMutation = useMutation({
    mutationFn: () =>
      apiService.post('/integration/open-finance/configure', {
        client_id: ofClientId,
        client_secret: ofClientSecret,
        user_id: ofUserId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integration-status'] });
      setOfClientId('');
      setOfClientSecret('');
      setOfUserId('');
    },
  });

  const inputClass = `w-full px-3 py-2 rounded-xl border text-sm ${
    darkMode
      ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
      : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
  }`;

  const configuredBadge = (ok?: boolean) => (
    <span className={`text-xs px-2 py-0.5 rounded-full ${
      ok ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
    }`}>
      {ok ? 'Configured' : 'Not configured'}
    </span>
  );

  const statusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle size={18} className="text-green-500" />;
      case 'failed': return <XCircle size={18} className="text-red-500" />;
      case 'running': return <Loader2 size={18} className="text-blue-500 animate-spin" />;
      case 'partial': return <AlertTriangle size={18} className="text-yellow-500" />;
      default: return <Clock size={18} className="text-gray-400" />;
    }
  };

  const syncTypes = [
    { label: 'Full Sync', value: undefined },
    { label: 'Invoices Only', value: 'invoices' },
    { label: 'Bills Only', value: 'bills' },
    { label: 'Payments Only', value: 'payments' },
    { label: 'Customers Only', value: 'customers' },
    { label: 'Bank Transactions', value: 'bank_transactions' },
  ];

  return (
    <FinancePageShell
      darkMode={darkMode}
      eyebrow="Data Operations"
      title="סנכרון וחיבורי נתונים"
      description="מרכז הפעלה שמוודא שהמערכת מקבלת נתונים, מריצה סנכרונים, בודקת חיבורים ושומרת היסטוריית ריצות לכל ארגון בנפרד."
      icon={Database}
      metrics={[
        { label: 'הנהלת חשבונות', value: integrationStatus?.configured?.sumit ? 'מחובר' : 'לא מוגדר', tone: integrationStatus?.configured?.sumit ? 'emerald' : 'amber' },
        { label: 'נתוני בנק', value: integrationStatus?.configured?.open_finance ? 'מחובר' : 'לא מוגדר', tone: integrationStatus?.configured?.open_finance ? 'emerald' : 'amber' },
        { label: 'ריצות אחרונות', value: String(runs?.length || 0), tone: 'blue' },
        { label: 'מצב אבטחה', value: integrationStatus?.configured?.security ? 'תקין' : 'לבדיקה', tone: integrationStatus?.configured?.security ? 'emerald' : 'rose' },
      ]}
      actions={
        <button
          type="button"
          onClick={() => testMutation.mutate()}
          disabled={testMutation.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {testMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          בדוק חיבורים
        </button>
      }
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <MetricCard
          darkMode={darkMode}
          icon={Database}
          label="מסמכים"
          value={integrationStatus?.configured?.sumit ? 'מוכן' : 'דורש הגדרה'}
          detail="חשבוניות, קבלות, ספקים ותשלומים"
          tone={integrationStatus?.configured?.sumit ? 'emerald' : 'amber'}
        />
        <MetricCard
          darkMode={darkMode}
          icon={RefreshCw}
          label="תנועות בנק"
          value={integrationStatus?.configured?.open_finance ? 'מוכן' : 'דורש הגדרה'}
          detail="תנועות, התאמות ותובנות בנק"
          tone={integrationStatus?.configured?.open_finance ? 'emerald' : 'amber'}
        />
        <MetricCard
          darkMode={darkMode}
          icon={Clock}
          label="רענון"
          value="5 שניות"
          detail="היסטוריית ריצות מתעדכנת אוטומטית"
          tone="blue"
        />
        <MetricCard
          darkMode={darkMode}
          icon={AlertTriangle}
          label="שגיאות"
          value={String((runs || []).filter((run) => run.status === 'failed').length)}
          detail="ריצות שנכשלו בתצוגה האחרונה"
          tone={(runs || []).some((run) => run.status === 'failed') ? 'rose' : 'emerald'}
        />
      </div>

      {/* Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <FinanceCard darkMode={darkMode} title="בדיקת חיבורים" subtitle="בדיקה מול ה־backend לפי ההרשאות והארגון הנוכחי" icon={ShieldCheck}>
          <button
            type="button"
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending}
            className="w-full px-4 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition font-medium disabled:opacity-50"
          >
            {testMutation.isPending ? 'Testing...' : 'Test Connection'}
          </button>
          {testMutation.data && (
            <div className={`mt-3 p-3 rounded-xl ${
              testMutation.data.success
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`}>
              {testMutation.data.message}
            </div>
          )}
        </FinanceCard>

        <FinanceCard darkMode={darkMode} title="הרצת סנכרון" subtitle="בחר סוג נתונים והריץ רענון יזום" icon={RefreshCw}>
          <div className="grid grid-cols-2 gap-2">
            {syncTypes.map((st) => (
              <button
                key={st.label}
                type="button"
                onClick={() => syncMutation.mutate(st.value)}
                disabled={syncMutation.isPending}
                className={`px-3 py-2 rounded-xl text-sm font-medium transition ${
                  darkMode
                    ? 'bg-gray-700 hover:bg-gray-600 text-white'
                    : 'bg-gray-100 hover:bg-gray-200 text-gray-700'
                } disabled:opacity-50`}
              >
                {st.label}
              </button>
            ))}
          </div>
          {syncMutation.isPending && (
            <div className="mt-3 flex items-center gap-2 text-blue-500">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Syncing...</span>
            </div>
          )}
        </FinanceCard>
      </div>

      {/* Integration Credentials */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <FinanceCard darkMode={darkMode}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">SUMIT Credentials</h2>
            {configuredBadge(integrationStatus?.configured?.sumit)}
          </div>
          <div className="space-y-3">
            <input
              type="password"
              value={sumitKey}
              onChange={(e) => setSumitKey(e.target.value)}
              placeholder="SUMIT API Key"
              className={inputClass}
            />
            <input
              type="text"
              value={sumitCompany}
              onChange={(e) => setSumitCompany(e.target.value)}
              placeholder="Company ID"
              className={inputClass}
            />
            <button
              type="button"
              onClick={() => sumitConfigMutation.mutate()}
              disabled={!sumitKey || sumitConfigMutation.isPending}
              className="w-full px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition font-medium disabled:opacity-50"
            >
              {sumitConfigMutation.isPending ? 'Saving...' : 'Save SUMIT Credentials'}
            </button>
            {sumitConfigMutation.isSuccess && (
              <p className="text-sm text-green-600">Credentials saved for your organization.</p>
            )}
            {sumitConfigMutation.isError && (
              <p className="text-sm text-red-600">Saving failed. Check the values and try again.</p>
            )}
          </div>
        </FinanceCard>

        <FinanceCard darkMode={darkMode}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Open Finance Credentials</h2>
            {configuredBadge(integrationStatus?.configured?.open_finance)}
          </div>
          <p className={`text-sm mb-3 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            שלושת השדות מתקבלים ישירות מ-Open Finance במהלך תהליך ה-onboarding
            העסקי מולם (לא דרך רצף) — פנו אליהם להשלמת ההתקשרות וקבלת הפרטים.
            עיינו ב-<a
              href="https://docs.open-finance.ai/reference"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              התיעוד הרשמי שלהם
            </a> למידע נוסף.
          </p>
          <div className="space-y-3">
            <input
              type="text"
              value={ofClientId}
              onChange={(e) => setOfClientId(e.target.value)}
              placeholder="Client ID"
              className={inputClass}
            />
            <input
              type="password"
              value={ofClientSecret}
              onChange={(e) => setOfClientSecret(e.target.value)}
              placeholder="Client Secret"
              className={inputClass}
            />
            <input
              type="text"
              value={ofUserId}
              onChange={(e) => setOfUserId(e.target.value)}
              placeholder="User ID"
              className={inputClass}
            />
            <button
              type="button"
              onClick={() => ofConfigMutation.mutate()}
              disabled={!ofClientId || !ofClientSecret || !ofUserId || ofConfigMutation.isPending}
              className="w-full px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition font-medium disabled:opacity-50"
            >
              {ofConfigMutation.isPending ? 'Saving...' : 'Save Open Finance Credentials'}
            </button>
            {ofConfigMutation.isSuccess && (
              <p className="text-sm text-green-600">Credentials saved for your organization.</p>
            )}
            {ofConfigMutation.isError && (
              <p className="text-sm text-red-600">Saving failed. Check the values and try again.</p>
            )}
          </div>
        </FinanceCard>
      </div>

      {/* Upay wallet activation — required before payment links can return a real URL */}
      {integrationStatus?.configured?.sumit && (
        <div className="grid grid-cols-1 gap-6">
          <FinanceCard darkMode={darkMode}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">חשבון Upay (סליקת אשראי)</h2>
              {configuredBadge(upayStatus?.connected)}
            </div>
            <p className={`text-sm mb-3 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              קישור חשבון Upay קיים לחברת ה-SUMIT שלכם — נדרש כדי ש"קישור תשלום"
              בעמוד גיול הלקוחות יחזיר עמוד תשלום אמיתי. הסיסמה מועברת ל-SUMIT
              בלבד ואינה נשמרת ברצף.
            </p>
            <div className="space-y-3 max-w-md">
              <input
                type="email"
                value={upayEmail}
                onChange={(e) => setUpayEmail(e.target.value)}
                placeholder="אימייל חשבון Upay"
                className={inputClass}
              />
              <input
                type="password"
                value={upayPassword}
                onChange={(e) => setUpayPassword(e.target.value)}
                placeholder="סיסמת חשבון Upay"
                className={inputClass}
              />
              <button
                type="button"
                onClick={() => upaySetupMutation.mutate()}
                disabled={!upayEmail || !upayPassword || upaySetupMutation.isPending}
                className="w-full px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition font-medium disabled:opacity-50"
              >
                {upaySetupMutation.isPending ? 'מקשר...' : 'קשר חשבון Upay'}
              </button>
              {upaySetupMutation.isSuccess && (
                <p className="text-sm text-green-600">החשבון קושר בהצלחה.</p>
              )}
              {upaySetupMutation.isError && (
                <p className="text-sm text-red-600">הקישור נכשל. בדקו את הפרטים ונסו שוב.</p>
              )}
            </div>
          </FinanceCard>
        </div>
      )}

      {/* Sync Runs */}
      <FinanceCard darkMode={darkMode} title="היסטוריית סנכרון" subtitle="כל ריצה מתועדת עם מקור, סוג, משך ותוצאות" icon={Clock}>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <th className="text-left py-3 px-2 text-sm font-medium">Status</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Source</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Type</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Entities</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Started</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Duration</th>
                <th className="text-left py-3 px-2 text-sm font-medium">Results</th>
              </tr>
            </thead>
            <tbody>
              {(runs || []).map((run) => {
                const started = run.started_at ? new Date(run.started_at) : null;
                const finished = run.finished_at ? new Date(run.finished_at) : null;
                const duration = started && finished
                  ? `${Math.round((finished.getTime() - started.getTime()) / 1000)}s`
                  : '-';

                const counts = run.counts || {};
                const totalCreated = Object.values(counts).reduce((s, c) => s + (c.created || 0), 0);
                const totalUpdated = Object.values(counts).reduce((s, c) => s + (c.updated || 0), 0);

                return (
                  <tr
                    key={run.id}
                    className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}
                  >
                    <td className="py-3 px-2">{statusIcon(run.status)}</td>
                    <td className="py-3 px-2 text-sm">{run.source}</td>
                    <td className="py-3 px-2 text-sm capitalize">{run.sync_type}</td>
                    <td className="py-3 px-2 text-sm text-xs">
                      {run.entity_types?.split(',').join(', ') || 'all'}
                    </td>
                    <td className="py-3 px-2 text-sm">
                      {started ? started.toLocaleString() : '-'}
                    </td>
                    <td className="py-3 px-2 text-sm">{duration}</td>
                    <td className="py-3 px-2 text-sm">
                      {totalCreated > 0 && (
                        <span className="text-green-500 mr-2">+{totalCreated}</span>
                      )}
                      {totalUpdated > 0 && (
                        <span className="text-blue-500 mr-2">~{totalUpdated}</span>
                      )}
                      {run.error_summary && (
                        <span className="text-red-500 text-xs">{String(run.error_summary)}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {isLoading && (
            <div className="text-center py-8">
              <Loader2 size={24} className="animate-spin mx-auto text-blue-500" />
            </div>
          )}
          {!isLoading && (!runs || runs.length === 0) && (
            <div className={`text-center py-12 ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <RefreshCw size={48} className="mx-auto mb-3 opacity-50" />
              <p>No sync runs yet</p>
              <p className="text-sm mt-1">Click "Full Sync" to pull data from your accounting system</p>
            </div>
          )}
        </div>
      </FinanceCard>
    </FinancePageShell>
  );
};

export default CFOSyncDashboard;
