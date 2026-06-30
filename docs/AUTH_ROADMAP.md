# Rezef Auth Roadmap

## Current Development Mode

For local Docker QA, authentication can be bypassed:

```env
AUTH_BYPASS_ENABLED=true
VITE_AUTH_BYPASS=true
```

When enabled:

- The backend accepts API requests without a Bearer token.
- The request is treated as a deterministic `SUPER_ADMIN` development user.
- The frontend skips the landing/login screen and opens the app directly.
- Super-admin organization switching still works through `X-Active-Org-Id`.

This mode is for local development and QA only. It must not be enabled on a
public production deployment with live financial data.

## Later Production Auth

Use Logto as the external identity and access layer:

- Logto manages sign-in, sign-up, Google login, MFA, invitations, password
  reset, and SSO.
- Logto Organizations map to Rezef `organizations`.
- Logto global role `rezef_super_admin` maps to Rezef `UserRole.SUPER_ADMIN`.
- Logto organization roles map to Rezef roles:
  - `owner`
  - `admin`
  - `accountant`
  - `finance_manager`
  - `viewer`

Rezef remains the source of truth for financial data, client files, SUMIT/Open
Finance credentials, documents, reports, and sync state.

## Migration Tasks

1. Add external identity columns:
   - `users.external_auth_provider`
   - `users.external_subject`
   - `organizations.external_auth_org_id`
2. Add Logto settings:
   - `LOGTO_ISSUER`
   - `LOGTO_AUDIENCE`
   - `LOGTO_APP_ID`
   - `LOGTO_APP_SECRET`
3. Add JWT verification against Logto JWKS.
4. Let `get_current_user` accept both legacy Rezef JWTs and Logto JWTs during
   migration.
5. Add frontend Logto SDK sign-in/sign-out.
6. Map Logto organization context to Rezef `organization_id`.
7. Replace open signup/password handling with Logto invite/signup flows.
8. Disable `AUTH_BYPASS_ENABLED` outside local development.

