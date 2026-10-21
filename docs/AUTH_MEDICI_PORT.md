# פורט מערכת ההרשאות של Medici לרצף

ענף: `feat/medici-auth-port` · מיגרציה: `h16a2c5e7b9d1` (אחרי `g15b7d43e9f0`, תוספתית)

מטרה: כל אדם נכנס עם המייל שלו (Google או סיסמה) ומגיע **רק** לארגון/לדשבורד
שהוענקו לו. המודל הועתק מ-Medici ולא תוכנן מאפס, כדי ש-Medici יוכל בעתיד לנהל
מי מורשה.

## 1. מפת המקור (קריאה בלבד)

| קובץ ב-Medici (`amitpo23/v0-bookinengine`) | מה הוא עושה |
| --- | --- |
| `lib/auth.ts` | NextAuth `GoogleProvider` (authorization code), callback `/api/auth/callback/google`, סשן JWT, `signIn` שמבצע upsert לטבלת `users` ב-Supabase |
| `lib/rbac/config.ts` | `ROLE_CONFIG` (role → scopes → capabilities → constraints), `ENDPOINT_CAPABILITIES` (endpoint → `required_scopes_any` + `audit`), `SCOPES_CATALOG` |
| `lib/rbac/permissions.ts` | `PermissionChecker` (`hasAnyScope`, `canAccessEndpoint`, allow/deny lists) |
| `lib/rbac/middleware.ts` | `withRBAC` — זיהוי משתמש, בדיקת הרשאה, ביקורת `ACCESS_DENIED`/`ACCESS_GRANTED` |
| `lib/rbac/audit.ts` | `AuditLogger` — action, resource, method, path, status, ip, userAgent |
| `lib/rbac/session.ts` | store סשנים בזיכרון + `authenticateUser` |
| `app/admin/rbac/page.tsx`, `components/auth/{role-guard,login-button}.tsx` | מסך ניהול, שומר תפקיד, כפתור "התחבר עם Google" |

משתני סביבה ב-Medici: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`.

מקור משני לסמנטיקת האישור: `amitpo23/v0-hotelpricemonitormain3`. שם יש
`profiles.is_approved/is_admin`, שורות `hotel_user_access` (`hotel_id`, `user_email`,
`role`, `is_approved`), `app/api/admin/users/approve` ו-`app/auth/pending`.

## 2. מה הועתק 1:1

- נתיבים תואמי NextAuth: `GET /api/auth/signin/google`, `GET /api/auth/callback/google`.
- זרימת authorization code עם state, nonce ו-PKCE (S256), scope `openid email profile`.
- שימוש חוזר ב-OAuth client של Medici (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`).
- מבנה `ROLE_CONFIG`, `ENDPOINT_CAPABILITIES`, `SCOPES_CATALOG` ו-`PermissionChecker`
  (`src/cfo/services/rbac.py`), עם אותם שמות שדות: `scopes`, `capabilities`,
  `constraints.endpoints.{access, allow_list, deny_list}`, `required_scopes_any`, `audit`.
  נשמרו המפתחות `audit:read`, `audit:write`, `tools:list`, `endpoints:*`.
- `withRBAC` → `require_rbac(key)` (`src/cfo/api/rbac.py`), שרושם `ACCESS_DENIED` ו-`ACCESS_GRANTED`.
- שדות הביקורת של Medici (action, resource, method, path, status, error, ip, user_agent).
- סמנטיקת האישור של price-monitor: הענקה למייל → ממתין → פעיל → בוטל.
- כפתור "התחברות עם Google" (פורט של `login-button.tsx`), ומסך ניהול בהשראת `app/admin/rbac`.

## 3. מה הותאם ולמה

| ב-Medici | ברצף | למה |
| --- | --- | --- |
| `session.ts`/`middleware.ts`: משתמשי דמה, סיסמאות דמה, טוקני bearer קבועים, store בזיכרון | **לא הועבר.** זהות = `users` + bcrypt + JWT עם `token_version`/`jti` (`get_current_user`) | סודות קבועים בקוד; serverless מאבד state. טסט שומר שאף מחרוזת דמה לא נכנסה ל-`src/` |
| `audit.ts`: מערך בזיכרון | שורות `audit_logs` (`services/auth_audit.py`) | ביקורת שנמחקת ב-cold start אינה ביקורת |
| `signIn` יוצר כל משתמש Google | מייל לא מוכר **נדחה** (403 + הודעה בעברית + `GOOGLE_LOGIN_REJECTED`) | Google מאמת אדם, לא הרשאה לעסק |
| `role-guard` מתיר לכל מחובר | בדיקת scope בצד השרת מול התפקיד **בארגון היעד** | ה-guard ב-Medici לא בדק תפקיד |
| תפקיד גלובלי (`admin`/`booker`) | `super_admin` בלבד הוא תפקיד פלטפורמה; כל השאר מ-`OrganizationMembership` (`role_in`) | `User.role=admin` אינו רשאי להקנות ניהול בעסק אחר |
| NextAuth סומך על הספרייה | אימות ID token **מקומי** מול JWKS (cache, רענון על kid לא מוכר): RS256, `aud`, `iss ∈ {accounts.google.com, https://accounts.google.com}`, exp/iat (סטייה 120 שנ'), `email_verified`, nonce בהשוואה בזמן קבוע | אין ספריית OIDC; אין תלות ב-`tokeninfo` |
| סשן = עוגיית NextAuth | ה-SPA שומר JWT ב-localStorage, ולכן ה-callback מנפיק **קוד חד-פעמי של 120 שניות** ב-fragment (`/auth/complete#code=…`). ה-SPA מחליף אותו ב-`POST /api/auth/google/exchange`. הקוד נשמר כ-sha256, **מקושר לדפדפן** (עוגיית HttpOnly `rezef_login_binding`, שה-hash שלה נשמר בשורה) ונצרך ב-UPDATE מותנה אחד | JWT ארוך-חיים לעולם אינו נכנס ל-URL; fragment אינו נשלח לשרתים ואינו נכנס ל-Referer; קישור לדפדפן חוסם login-CSRF (קוד של תוקף שהודבק אצל קורבן) |
| `/api/admin/users/approve` של price-monitor לא בודק שהקורא אדמין | כל הענקה עוברת `assert_can_grant` מול ארגון היעד | פער אבטחה במקור |
| `NEXTAUTH_URL` | `AUTH_URL`, ואם חסר: `VERCEL_BRANCH_URL` (רק כש-`VERCEL_ENV=preview`), ואז `APP_URL`. **לעולם לא Host header** | פריוויו חייב לחזור לאותו host שבו נשמרה עוגיית ה-state |

מיפוי תפקידים (`MEDICI_ROLE_ALIASES`): `admin` של Medici → `super_admin`; `booker` → `viewer`.
תפקידי רצף: `super_admin`, `admin`, `accountant`, `manager`, `user`, `viewer`, ובדשבורד
`client_viewer` / `client_editor`. Scopes חדשים: `org:read`, `org:write`, `org:admin`,
`dashboard:read`, `dashboard:write`, `access:read`, `access:grant`.

### GIS (`POST /api/admin/auth/google`) — הוקשח ומסומן deprecated

- `tokeninfo` הוחלף באותו אימות JWKS מקומי (בלי nonce, כי הכפתור הישן לא שלח).
- מייל לא מוכר נדחה. **שינוי התנהגות:** אין יותר הרשמה עצמית דרך Google, גם לא עם
  `registration_code`/checkout. הרשמה עצמית נשארת בטופס הסיסמה, ותמיד לארגון חדש.
- ה-frontend כבר לא טוען את GIS. `VITE_GOOGLE_CLIENT_ID` לא בשימוש, ואין צורך ב-JavaScript origins.

## 4. מודל נתונים

- **ארגון:** `organization_memberships` (קיים). הזמנה לפי מייל יוצרת חברות `invited`
  דרך `membership_service.invite_checked`. אם אין עדיין משתמש למייל, נוצרת **זהות**
  (`users`) עם סיסמה אקראית ובלי ארגון. כך ה-NOT NULL על `user_id` נשמר, וזו לא הצטרפות
  לפי התאמת מייל: מנהל בחר את המייל במפורש. בהתחברות Google מאומתת הראשונה ההזמנה
  מתקבלת (`accept`) ונעשית `active`.
- **דשבורד:** טבלה חדשה `dashboard_access_grants`: `dashboard_id`, `email` (lowercase),
  `user_id`, `role ∈ {client_viewer, client_editor}`, `status ∈ {invited, active, revoked}`,
  `source`, `granted_by_user_id`, `activated_at`, `revoked_at`, `revoked_by_user_id`.
  יש unique על (`dashboard_id`, `email`).
- **קוד כניסה:** טבלה חדשה `auth_login_codes` עם `code_hash` (unique), `browser_binding` (sha256 של nonce העוגייה), `user_id`, `expires_at`, `used_at`.
- **ייצוא/ייבוא ל-Medici** (`GET /api/admin/access/export`, `POST /api/admin/access/import`):

```json
{"version": 1, "source": "rezef", "grants": [
  {"email": "a@x.com", "target": {"type": "organization", "id": 5}, "role": "viewer", "status": "invited", "source": "rezef"},
  {"email": "b@x.com", "target": {"type": "dashboard", "id": 7, "slug": "foodgroup", "organization_id": 5}, "role": "client_viewer", "status": "active", "source": "medici"}
]}
```

הייבוא שמור ל-`super_admin`. תפקיד `booker` של Medici ממופה ל-`viewer`. `admin` של Medici אינו ממופה (כהרשאת ארגון הוא דו-משמעי), ושאר המפתחות הם מפתחות רצף. `active` בייבוא נשמר כ-`invited`: הפעלה קורית רק
בהתחברות מאומתת. כל שורה רצה ב-savepoint משלה.

## 5. הזרימה

1. ה-SPA מפנה ל-`/api/auth/signin/google?return_to=/d/slug`. השרת יוצר state, nonce ו-PKCE
   ושומר אותם בעוגייה חתומה `rezef_oauth_state`: HttpOnly, Secure, SameSite=Lax,
   `Path=/api/auth`, 10 דקות. אחר כך הוא מפנה ל-Google. `return_to` מתקבל רק כנתיב יחסי.
2. `/api/auth/callback/google` בודק את ה-state, מחליף את ה-code (עם `code_verifier`)
   ומאמת את ה-ID token מקומית. אחר כך הוא ממפה מייל → משתמש:
   משתמש קיים ופעיל, או זהות שהוזמנה, או הרשאת דשבורד ממתינה. כל השאר נדחה.
   הרשאות ממתינות מופעלות, נכתבת ביקורת, ונעשה redirect ל-`/auth/complete#code=…&next=…`.
3. שגיאה: redirect ל-`/login?auth_error=<code>`. ה-SPA מציג הודעה בעברית
   (`unknown_email`, `account_disabled`, `verification_failed`, `not_configured`, `access_denied`).
4. `/d/<slug>`: `public` נשאר ציבורי. `link` נפתח עם עוגיית קישור שיתוף (כמו קודם), **או**
   למשתמש מחובר עם תפקיד. `members` נפתח רק למשתמש מחובר עם תפקיד. תפקיד =
   מנהל-על, ADMIN בארגון, חבר פעיל בארגון, `DashboardMember`, או הרשאת מייל פעילה.
   ביטול מפורש לדשבורד (`DashboardMember`/הרשאת מייל ב-`revoked`) גובר על חברות
   בארגון. סירוב ואנונימי מקבלים 404.
5. ניהול: `/access` ב-SPA, ו-API תחת `/api/admin/access/*`: `organizations`, `grants`,
   `grants/revoke`, `export`, `import`, `rbac`. `super_admin` מנהל כל ארגון; `admin`
   רק ארגון שבו יש לו חברות ADMIN פעילה. אי-אפשר להעניק `super_admin`. ההגנה על
   המנהל האחרון נשמרת.

ביקורת (`audit_logs.action`): `GOOGLE_LOGIN`, `GOOGLE_LOGIN_REJECTED` (שם נשמר דומיין
בלבד), `GOOGLE_TOKEN_REJECTED` (סיבה בלבד, לעולם לא הטוקן), `LOGIN`, `LOGIN_FAILED`,
`ACCESS_GRANT`, `ACCESS_REVOKE`, `ACCESS_IMPORT`, `ACCESS_DENIED`, `ACCESS_GRANTED`,
ובנוסף `MEMBERSHIP_INVITE/GRANT/ACCEPT/REVOKE` הקיימים.

### פשרות מודעות (סקירת אבטחה)

- **קבלה אוטומטית בכניסת Google:** הזמנה לארגון מתקבלת בכניסה המאומתת הראשונה,
  כנדרש. ההשפעה מוגבלת: המוזמן מקבל גישה ואינו חושף דבר. בכניסת סיסמה ההזמנה
  **אינה** מתקבלת.
- **זהות נוצרת בזמן ההזמנה:** למייל חדש נוצרת שורת `users` בלי סיסמה שמישה. לכן
  הרשמה בסיסמה לאותו מייל תיענה "כבר רשום", והאדם נכנס עם Google או מאפס סיסמה.
  החלופה (טבלת הזמנות ארגון לפי מייל) נדחתה כדי לא לפתוח מסלול חברות שני.

## 6. משתני סביבה (שמות בלבד)

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (אותו client כמו ב-Medici), `AUTH_URL`
(מומלץ גם ב-Preview), `APP_URL`, `JWT_SECRET_KEY` (חותם את עוגיית ה-state).
`DASHBOARD_COOKIE_SECRET` נשאר ללא שינוי. `VERCEL_ENV` ו-`VERCEL_BRANCH_URL` הם
משתני מערכת של Vercel.

## 7. Google Cloud Console — להוסיף ל-OAuth client הקיים של Medici

**Authorized redirect URIs:**

```
https://cfo-2.vercel.app/api/auth/callback/google
https://cfo-2-git-feat-medici-auth-port-guyofiror.vercel.app/api/auth/callback/google
```

**Authorized JavaScript origins:** לא נדרש. כפתור GIS הוסר וזרימת השרת אינה משתמשת ב-origins.

`vercel.json` כבר מפנה `/api/:path*` ל-FastAPI, ולכן שני הנתיבים מגיעים ל-`api/index`.
`/auth/complete` נופל ל-`index.html` (SPA).

## 8. ממצאי כניסת סיסמה

1. **חיפוש מייל תלוי-רישיות (תוקן).** `EmailStr` מנרמל רק את הדומיין. מי שנרשם
   כ-`Amit@…` ונכנס כ-`amit@…` קיבל "סיסמה שגויה" (וזה גם צבר נעילה). login, הרשמה
   (בדיקת כפילות), יצירת משתמש באדמין, הזמנת חברות ו-request-password-reset עוברים
   עכשיו דרך `access_grants.find_user`.
2. **כניסה כושלת לא נרשמה (תוקן).** `LOGIN_FAILED` נרשם עם `bad_password`,
   `unknown_email` או `account_disabled`. סיסמה ומייל זר לא נשמרים.
3. **0 חברויות בפרוד.** משתמש שאינו super_admin נכנס בהצלחה, ואז מקבל 403
   `no_organization_membership` בכל מסלול ארגוני. הקוד אוסר במפורש fallback ל-
   `users.organization_id`, ולכן זה לא תוקן בקוד. מסלול השחרור: מנהל-על ב-`/access` ←
   "הפעלה מיידית למשתמש קיים" (`activate_now`), או הזמנה וכניסת Google.
   מנהל-העל עצמו לא ננעל: בוחר ארגון בכותרת `X-Active-Org-Id` (טסט).
4. **הזמנה אינה מתקבלת בכניסת סיסמה (במכוון).** זה עקבי עם
   `test_a_created_user_has_no_access_until_acceptance`: סיסמה שמנהל קבע אינה מוכיחה
   בעלות על המייל.
5. **נעילה ותקרת מקור.** 5 כישלונות נועלים ל-15 דקות. תקרת המקור תלויה בטבלה
   `provider_request_budgets` (מיגרציה `f3a4b5c6d7e8`). אם היא חסרה בפרוד, ה-login
   מחזיר 503 (fail-closed). לבדוק ב-Gate 0.
6. **איפוס סיסמה דורש SMTP.** בלי `SMTP_HOST`/`SMTP_FROM` מתקבל 503 כן. זה לא באג;
   כניסת Google היא חלופה שאינה תלויה ב-SMTP.

## 9. פריסה

לא נפרס ולא הורץ על פרוד. כדי להפעיל צריך: מיגרציה `h16a2c5e7b9d1` לפי
`docs/GATE0_DEPLOYMENT_RUNBOOK.md`, משתני הסביבה בסעיף 6, ו-redirect URIs בסעיף 7.
