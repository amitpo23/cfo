import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, CheckCircle, XCircle, Clock, AlertTriangle, Loader2 } from 'lucide-react';
import apiService from '../services/api';

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

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  }`;

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
    <div className={`p-6 space-y-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <h1 className="text-3xl font-bold">Data Sync</h1>

      {/* Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className={cardClass}>
          <h2 className="text-lg font-semibold mb-4">Connection</h2>
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
        </div>

        <div className={cardClass}>
          <h2 className="text-lg font-semibold mb-4">Sync Now</h2>
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
        </div>
      </div>

      {/* Sync Runs */}
      <div className={cardClass}>
        <h2 className="text-lg font-semibold mb-4">Sync History</h2>
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
      </div>
    </div>
  );
};

export default CFOSyncDashboard;
