/**
 * Settings page — organization profile + a link to the real integrations page.
 *
 * This used to be a fully static mockup: a "Save API Settings" button with
 * no onClick, notification toggles with hardcoded `checked` values, and a
 * "System Information" card that always claimed "API Status: Connected" /
 * "Last Sync: 2 min ago" regardless of reality. SUMIT/Open Finance
 * credentials already have a real, working page at /sync (CFOSyncDashboard)
 * — this page now shows the real connection status (from the same
 * /integration/status endpoint /sync uses) and links there instead of
 * duplicating a broken copy of that form.
 */
import React, { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import apiService from '../services/api';

interface Props {
  darkMode: boolean;
}

interface CurrentUserLite {
  organization_id: number | null;
}

interface IntegrationStatus {
  configured: Record<string, boolean>;
}

interface OrganizationInfo {
  id: number;
  name: string;
  tax_id?: string | null;
}

const SettingsPage: React.FC<Props> = ({ darkMode }) => {
  const queryClient = useQueryClient();

  const { data: currentUser } = useQuery<CurrentUserLite>({
    queryKey: ['auth-me'],
    queryFn: () => apiService.get('/admin/auth/me'),
  });
  const orgId = currentUser?.organization_id ?? null;

  const { data: integrationStatus } = useQuery<IntegrationStatus>({
    queryKey: ['integration-status'],
    queryFn: () => apiService.get('/integration/status'),
  });

  const { data: org } = useQuery<OrganizationInfo>({
    queryKey: ['org-info', orgId],
    queryFn: () => apiService.get(`/admin/organizations/${orgId}`),
    enabled: !!orgId,
  });

  const [name, setName] = useState('');
  const [taxId, setTaxId] = useState('');
  useEffect(() => {
    if (org) {
      setName(org.name || '');
      setTaxId(org.tax_id || '');
    }
  }, [org]);

  const saveOrgMutation = useMutation({
    mutationFn: () =>
      apiService.patch(`/admin/organizations/${orgId}`, {
        name, tax_id: taxId || undefined,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['org-info', orgId] }),
  });

  const cardClass = `p-6 rounded-2xl ${
    darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
  }`;
  const inputClass = `w-full px-4 py-3 rounded-xl border ${
    darkMode
      ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
      : 'bg-white border-gray-300 text-gray-900'
  } focus:outline-none focus:ring-2 focus:ring-blue-500`;
  const labelClass = `block text-sm font-medium mb-2 ${darkMode ? 'text-gray-300' : 'text-gray-700'}`;
  const mutedClass = darkMode ? 'text-gray-400' : 'text-gray-500';

  const statusRow = (label: string, connected?: boolean) => (
    <div className="flex justify-between items-center">
      <span>{label}</span>
      <span className={`font-medium flex items-center gap-2 ${connected ? 'text-green-500' : 'text-amber-500'}`}>
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-amber-500'}`} />
        {connected ? 'מחובר' : 'לא מוגדר'}
      </span>
    </div>
  );

  return (
    <div className={`p-6 ${darkMode ? 'text-white' : 'text-gray-900'}`}>
      <h1 className="text-3xl font-bold mb-8">הגדרות</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Integration status — real data, links to the actual configuration page */}
        <div className={cardClass}>
          <h2 className="text-xl font-semibold mb-2">חיבורי מערכת</h2>
          <p className={`text-sm mb-4 ${mutedClass}`}>
            הגדרת מפתחות SUMIT ו-Open Finance מתבצעת בעמוד הסנכרון הייעודי.
          </p>
          <div className="space-y-3 mb-6">
            {statusRow('SUMIT (הנהלת חשבונות)', integrationStatus?.configured?.sumit)}
            {statusRow('Open Finance (בנק)', integrationStatus?.configured?.open_finance)}
          </div>
          <Link
            to="/sync"
            className="block w-full text-center bg-blue-600 text-white px-4 py-3 rounded-xl hover:bg-blue-700 transition font-medium"
          >
            ניהול חיבורים בעמוד הסנכרון
          </Link>
        </div>

        {/* Company Info — real load + save via PATCH /admin/organizations/{id} */}
        <div className={cardClass}>
          <h2 className="text-xl font-semibold mb-6">פרטי חברה</h2>
          <div className="space-y-4">
            <div>
              <label className={labelClass}>שם חברה</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputClass}
                placeholder="שם החברה בע&quot;מ"
              />
            </div>
            <div>
              <label className={labelClass}>ח.פ.</label>
              <input
                type="text"
                value={taxId}
                onChange={(e) => setTaxId(e.target.value)}
                className={inputClass}
                placeholder="51XXXXXXX"
              />
            </div>
            <button
              type="button"
              onClick={() => saveOrgMutation.mutate()}
              disabled={!orgId || !name || saveOrgMutation.isPending}
              className="w-full bg-blue-600 text-white px-4 py-3 rounded-xl hover:bg-blue-700 transition font-medium disabled:opacity-50"
            >
              {saveOrgMutation.isPending ? 'שומר...' : 'שמור פרטי חברה'}
            </button>
            {saveOrgMutation.isSuccess && <p className="text-sm text-green-600">נשמר בהצלחה.</p>}
            {saveOrgMutation.isError && <p className="text-sm text-red-600">השמירה נכשלה. נסה שוב.</p>}
          </div>
        </div>

        {/* Notifications — honestly not-yet-available, no fake toggles */}
        <div className={cardClass}>
          <h2 className="text-xl font-semibold mb-2">התראות</h2>
          <p className={mutedClass}>ניהול העדפות התראות עדיין לא זמין במערכת.</p>
        </div>

        {/* System Information — real data only */}
        <div className={cardClass}>
          <h2 className="text-xl font-semibold mb-6">מידע מערכת</h2>
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className={mutedClass}>ארגון</span>
              <span className="font-medium">{org?.name || '—'}</span>
            </div>
            {statusRow('SUMIT', integrationStatus?.configured?.sumit)}
            {statusRow('Open Finance', integrationStatus?.configured?.open_finance)}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
