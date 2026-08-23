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

// whatsapp_phone_number_id (src/cfo/config.py) is Meta's internal routing
// ID for the Graph API — never a dialable phone number, so it is
// deliberately never rendered here as "the bot's number". Only its
// presence/absence (via /integration/status.configured.whatsapp) drives
// which of the two honest states below is shown.

interface OrganizationInfo {
  id: number;
  name: string;
  tax_id?: string | null;
}

interface LinkCodeResponse {
  code: string;
  expires_at: string;
  instructions: string;
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

  // Channel link-code — the plaintext code is a one-time secret the backend
  // shows exactly once (src/cfo/api/routes/channels.py); kept in memory
  // only, never persisted to localStorage. A 1s ticker drives the
  // countdown and clears the code from screen once expires_at passes.
  const [linkCode, setLinkCode] = useState<string | null>(null);
  const [linkExpiresAt, setLinkExpiresAt] = useState<number | null>(null);
  const [linkInstructions, setLinkInstructions] = useState<string | null>(null);
  const [linkExpired, setLinkExpired] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!linkExpiresAt) return;
    const tick = () => {
      const current = Date.now();
      if (current >= linkExpiresAt) {
        setLinkCode(null);
        setLinkExpiresAt(null);
        setLinkInstructions(null);
        setLinkExpired(true);
      } else {
        setNow(current);
      }
    };
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [linkExpiresAt]);

  const linkCodeMutation = useMutation({
    mutationFn: () => apiService.post<LinkCodeResponse>('/channels/link-code'),
    onSuccess: (data) => {
      setLinkCode(data.code);
      setLinkExpiresAt(new Date(data.expires_at).getTime());
      setLinkInstructions(data.instructions);
      setLinkExpired(false);
      setLinkCopied(false);
    },
  });

  const linkRemainingMs = linkExpiresAt ? Math.max(0, linkExpiresAt - now) : 0;
  const linkRemainingMin = Math.floor(linkRemainingMs / 60000);
  const linkRemainingSec = Math.floor((linkRemainingMs % 60000) / 1000);

  const handleCopyLinkCode = async () => {
    if (!linkCode) return;
    try {
      await navigator.clipboard.writeText(`/start ${linkCode}`);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      // clipboard permission denied/unavailable — code is still visible to copy by hand
    }
  };

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

        {/* Conversational channels — issue a one-time link code to bind Telegram */}
        <div className={cardClass}>
          <h2 className="text-xl font-semibold mb-2">ערוצי שיחה</h2>
          <p className={`text-sm mb-4 ${mutedClass}`}>
            אפשר לדבר עם רצף גם דרך טלגרם. הקישור נעשה באמצעות קוד חד-פעמי שמוצג כאן פעם אחת בלבד.
          </p>

          {!linkCode && (
            <>
              <button
                type="button"
                onClick={() => linkCodeMutation.mutate()}
                disabled={linkCodeMutation.isPending}
                className="w-full bg-blue-600 text-white px-4 py-3 rounded-xl hover:bg-blue-700 transition font-medium disabled:opacity-50"
              >
                {linkCodeMutation.isPending ? 'מנפיק קוד...' : 'הנפק קוד קישור'}
              </button>
              {linkCodeMutation.isError && (
                <p className="text-sm text-red-600 mt-2">הנפקת הקוד נכשלה. נסה שוב.</p>
              )}
              {linkExpired && (
                <p className="text-sm text-amber-600 mt-2">הקוד פג. הנפק קוד חדש.</p>
              )}
            </>
          )}

          {linkCode && (
            <div className="space-y-3">
              <div className={`rounded-xl border-2 border-dashed p-4 text-center ${
                darkMode ? 'border-blue-500 bg-blue-900/10' : 'border-blue-400 bg-blue-50'
              }`}>
                <p className="text-2xl font-bold tracking-widest font-mono" dir="ltr">{linkCode}</p>
              </div>
              {linkInstructions && <p className={`text-sm ${mutedClass}`}>{linkInstructions}</p>}
              <p className="text-sm font-medium text-amber-600">
                הקוד מוצג פעם אחת בלבד — פג תוקף בעוד {linkRemainingMin}:{String(linkRemainingSec).padStart(2, '0')} דקות.
              </p>
              <button
                type="button"
                onClick={handleCopyLinkCode}
                className={`w-full px-4 py-2 rounded-xl border font-medium transition ${
                  darkMode ? 'border-gray-600 hover:bg-gray-700' : 'border-gray-300 hover:bg-gray-100'
                }`}
              >
                {linkCopied ? 'הועתק!' : `העתק "/start ${linkCode}" ללוח`}
              </button>
            </div>
          )}

          {/* WhatsApp — no code to redeem: linking goes through the
              email-verification flow (whatsapp_webhook.py handle_message),
              triggered by messaging the bot, not by anything issued here. */}
          <div className={`mt-6 pt-6 border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
            <h3 className="text-lg font-semibold mb-2">וואטסאפ</h3>
            {integrationStatus?.configured?.whatsapp ? (
              <p className={`text-sm ${mutedClass}`}>
                הערוץ פעיל. כדי לקשר את הוואטסאפ שלך, שלח הודעה למספר הבוט העסקי של רצף
                (לקבלת המספר יש לפנות למנהל המערכת אצלכם) עם כתובת המייל הרשומה שלך ברצף.
                תקבל בחזרה למייל קוד בן 6 ספרות — שלח אותו כהודעה חוזרת באותה שיחה כדי להשלים
                את הקישור, בדיוק כמו בטלגרם.
              </p>
            ) : (
              <p className={`text-sm ${mutedClass}`}>הערוץ טרם הופעל על ידי המשרד.</p>
            )}
          </div>
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
