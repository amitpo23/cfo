# Admin User Management & Client Provisioning — Implementation Plan

**Goal:** Let an admin create app login accounts for clients (admin-set password, no self-registration) and manage each user's role/active-state — closing the two gaps the capability map found (data isolation is already complete).

**Architecture:** App-level `User` CRUD in `admin.py` (require_admin), bcrypt-hashed admin-set passwords, org-scoped. Fix the cross-wiring where `POST /admin/users` currently creates a SUMIT user (move that to `/admin/sumit-users`). Wire the existing AdminDashboard buttons to the new endpoints.

**Decision (user):** admin types the initial password in the UI (validated min length; bcrypt server-side; sent over HTTPS).

## Global Constraints
- require_admin (ADMIN/SUPER_ADMIN) on all new endpoints; org-scoping preserved.
- Never store plaintext passwords (use `auth.get_password_hash`). Never log passwords.
- Guards: a user cannot deactivate/delete/demote themselves; cannot remove the last admin of an org.
- TDD; full suite green before commit.

---

### Task 1 — Backend: app-User CRUD (admin.py)
**Files:** `src/cfo/api/routes/admin.py`; tests `tests/test_admin_user_mgmt.py`.

1a. **Move existing SUMIT user creation** off `POST /users`: rename the current `create_user` (which calls `sumit.create_user`) to route `POST /sumit-users` (keep behavior + require_admin). 
1b. **Repurpose `POST /users`** → create an APP `User`: validate email unique (409 if exists), password length ≥ 8 (422), role in `UserRole`, `organization_id` required (the admin provisions into an org); hash with `get_password_hash`; `is_active=True`; return `UserResponse` (no password). require_admin.
1c. **`PATCH /users/{user_id}`** (UserUpdate): update `role` / `is_active` / `full_name` / `phone`. require_admin. Guards: caller cannot set their own `is_active=False` or change their own role (422); if setting a user from ADMIN→lower or is_active False, ensure ≥1 active admin remains in that org (409 otherwise). Return updated `UserResponse`.
1d. **`DELETE /users/{user_id}`** → soft-delete (set `is_active=False`) OR hard delete; choose soft-delete (set is_active False) to preserve audit/FKs. require_admin. Guard: cannot delete self; cannot remove last active admin. Return 204.

TDD tests (each red→green): create app user + login works (verify password hash via `verify_password`); duplicate email → 409; short password → 422; PATCH role change; self-deactivation blocked; last-admin protection; DELETE soft-deactivates; non-admin → 403.

### Task 2 — Frontend: wire AdminDashboard (AdminDashboard.tsx)
**Files:** `frontend/src/components/AdminDashboard.tsx`.
- "Create user" form: email, full_name, role `<select>` (the 6 roles), organization_id, password (type=password, min 8) → `POST /api/admin/users`; on success refresh list + show the created email.
- Edit button (currently no onClick): open inline role `<select>` + is_active toggle → `PATCH /api/admin/users/{id}`.
- Delete button (currently no onClick): confirm → `DELETE /api/admin/users/{id}` → refresh.
- Surface API errors (409/422) to the user.
- Verify `npm run build` passes.

### Task 3 — Verify & docs
- Full backend suite green; `colscan` clean; frontend build green.
- Update `docs/PERMISSIONS.md` "how roles are assigned" → now also via `PATCH /admin/users/{id}`; note admin client-provisioning via `POST /admin/users`.

## Out of scope (note, don't build now)
- Email invite / password-reset flow (needs SMTP).
- Granular per-permission (beyond role) join table.
- The `/users/{id}/permissions` SUMIT-wired endpoints (leave; they manage SUMIT office users) — optionally rename later for clarity.
