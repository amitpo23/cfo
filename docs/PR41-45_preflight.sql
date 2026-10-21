-- Rezef/CFO prod preflight for migrations d92e4a10b6c3 .. g15b7d43e9f0 (PR #42–#44)
-- R6 chain: c81e6395fd71 -> d92e4a10b6c3 -> e03f5b21c7d4 -> h26c8e54f1b2 -> i27c9e65a3d4 -> f14a6c32d8e5 -> g15b7d43e9f0
-- i27c9e65a3d4 adds uq_of_class_coverage (one BOUND classification per coverage).
-- R6: 5e/5f/5g kept. ck_membership_role_not_super_admin already exists at c81e6395fd71 and SHOULD be present.
-- READ-ONLY. Every statement is a SELECT inside a READ ONLY transaction. Do not run without Amit's approval.
-- Prepared 2026-10-20; re-validated in R3 (stack tip f43d099, no schema change since R2) against local PG17 at
-- c81e6395fd71 (pass state) and at g15b7d43e9f0 (all section-0 objects reported). Never run against prod.
-- Run: psql "$PROD_URL" -v ON_ERROR_STOP=1 -f PR41-45_preflight.sql
-- Pass criteria: section 0 = c81e6395fd71 and no pre-existing new objects (ck_membership_role_not_super_admin
-- excepted, see note); every count in 1–4 = 0.

BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '2s';

-- 0. Where prod is, and whether schema_sync already created any of the new objects
SELECT version_num AS alembic_current FROM alembic_version;            -- expect c81e6395fd71
SELECT t AS already_exists
FROM unnest(ARRAY[
  'provider_call_log','account_source_coverage','of_account_classifications','client_dashboards','dashboard_entities',
  'dashboard_entity_accounts','dashboard_members','dashboard_share_links','dashboard_plans',
  'dashboard_plan_revisions','published_snapshots','pipeline_runs','dashboard_rate_limits'
]) AS t
WHERE to_regclass('public.' || t) IS NOT NULL;                          -- expect 0 rows
SELECT column_name AS banktx_column_already_exists
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'bank_transactions'
  AND column_name IN ('superseded_by_id','content_fingerprint');        -- expect 0 rows
SELECT conname AS constraint_already_exists FROM pg_constraint
WHERE conname IN ('ck_banktx_source_external_id','ck_membership_role_not_super_admin',
                  'ck_of_class_state','ck_of_class_bound_coverage','ck_of_class_independent_actor');
-- expect: ck_banktx_source_external_id ABSENT (e03f5b21c7d4 adds it).
-- ck_membership_role_not_super_admin comes from an earlier revision; at c81e6395fd71 it SHOULD be present.
-- If prod lacks it, that is pre-existing drift for the Gate-0 repair (allow-listed), not for these migrations.
SELECT indexname AS index_already_exists FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN ('uq_bankconn_source_connection_id','uq_bankconn_one_active_open_finance',
                    'ix_provider_call_org_at','ix_provider_call_office_at',
                    'ix_dashboard_rate_window_start','ix_dashboard_primary_org',
                    'ix_of_class_org','uq_of_class_account','uq_of_class_coverage');

-- 1. e03f5b21c7d4: CHECK ck_banktx_source_external_id  (source = 'manual' OR external_id IS NOT NULL)
SELECT count(*) AS banktx_check_violations
FROM bank_transactions
WHERE source IS DISTINCT FROM 'manual' AND source IS NOT NULL AND external_id IS NULL;
SELECT organization_id, source, count(*) AS rows, min(transaction_date), max(transaction_date)
FROM bank_transactions
WHERE source IS DISTINCT FROM 'manual' AND source IS NOT NULL AND external_id IS NULL
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 50;
-- informational: NULL source passes the CHECK (NULL OR FALSE = NULL) but is not a reviewed import
SELECT count(*) AS banktx_null_source_rows FROM bank_transactions WHERE source IS NULL;

-- 2. e03f5b21c7d4: unique index uq_bankconn_source_connection_id (source, connection_id) WHERE connection_id IS NOT NULL
SELECT source, connection_id, count(*) AS dup_rows, array_agg(id ORDER BY id) AS ids,
       array_agg(DISTINCT organization_id) AS orgs
FROM bank_connections
WHERE connection_id IS NOT NULL
GROUP BY source, connection_id HAVING count(*) > 1;                     -- expect 0 rows

-- 3. e03f5b21c7d4: unique index uq_bankconn_one_active_open_finance (organization_id)
--    WHERE source = 'open_finance' AND status IN ('ACTIVE','CONNECTED','COMPLETED')
SELECT organization_id, count(*) AS active_of_connections,
       array_agg(connection_id || ':' || status ORDER BY id) AS connections
FROM bank_connections
WHERE source = 'open_finance' AND status IN ('ACTIVE','CONNECTED','COMPLETED')
GROUP BY organization_id HAVING count(*) > 1;                           -- expect 0 rows
-- the index is case-sensitive: these would escape it and the bind guard
SELECT status, count(*) FROM bank_connections
WHERE source = 'open_finance' AND upper(status) IN ('ACTIVE','CONNECTED','COMPLETED')
  AND status NOT IN ('ACTIVE','CONNECTED','COMPLETED')
GROUP BY status;                                                        -- expect 0 rows
-- informational: full status distribution of OF consents
SELECT status, count(*) FROM bank_connections WHERE source = 'open_finance' GROUP BY status ORDER BY 2 DESC;

-- 4. CHECK repair allow-list (schema_sync, PR #45 merge): ck_membership_role_not_super_admin (role != 'SUPER_ADMIN')
SELECT count(*) AS membership_super_admin_rows
FROM organization_memberships WHERE role::text = 'SUPER_ADMIN';         -- expect 0

-- 5. Data the new code relies on (informational, not a migration blocker)
-- 5a. office resolution: a file with more than one roster row resolves to the lowest id, active or not
SELECT target_organization_id, count(*) AS roster_rows,
       array_agg(office_organization_id || ':' || coalesce(status,'NULL') ORDER BY id) AS offices
FROM sumit_companies
WHERE target_organization_id IS NOT NULL
GROUP BY target_organization_id HAVING count(*) > 1;
-- 5b. dashboards authorize office access through an ACTIVE roster row
SELECT status, count(*) FROM sumit_companies GROUP BY status;
-- 5c. dashboard access needs a live ADMIN membership; legacy users.role=ADMIN without one lose access
SELECT u.id, u.email, u.organization_id
FROM users u
WHERE u.role::text = 'ADMIN' AND u.is_active
  AND NOT EXISTS (
    SELECT 1 FROM organization_memberships m
    WHERE m.user_id = u.id AND m.organization_id = u.organization_id
      AND m.role::text = 'ADMIN' AND m.status = 'active');
-- 5d. existing provider_request_budgets rows the old public limiter wrote (now unused, safe to purge later)
SELECT count(*) AS old_dashboard_public_budget_rows
FROM provider_request_budgets WHERE provider = 'dashboard_public';

-- 5e. (R3) OF provider accounts that would defeat suffix binding: several Account rows with the same
--     digit tail in one org (e.g. one per consent), and accounts with no digits at all (fail-closed bucket)
SELECT organization_id, regexp_replace(coalesce(provider_account_number,''), '\D', '', 'g') AS digits,
       count(*) AS account_rows, array_agg(id ORDER BY id) AS ids,
       array_agg(DISTINCT open_finance_connection_id) AS connections
FROM accounts
WHERE source = 'open_finance'
GROUP BY 1, 2
HAVING count(*) > 1 OR regexp_replace(coalesce(provider_account_number,''), '\D', '', 'g') = '';

-- 5f. (R5) Reviewed local bank accounts per org: last4 and last local date. covers_from for a bind
--     must be max_local_date + 1 day, and bank_account_suffix must equal last4 (service enforces both).
SELECT a.organization_id, a.id AS local_account_id, a.name, a.external_id,
       right(regexp_replace(coalesce(a.external_id,''), '\D', '', 'g'), 4) AS last4,
       count(t.id) AS local_rows, max(t.transaction_date) AS max_local_date,
       max(t.transaction_date) + 1 AS required_covers_from
FROM accounts a
LEFT JOIN bank_transactions t ON t.account_id = a.id AND t.source = 'reviewed_local_import'
WHERE a.source = 'reviewed_local_import'
GROUP BY 1, 2, 3, 4 ORDER BY 1, 2;
-- 5g. (R5) OF accounts in orgs that have a reviewed local import. Every row here starts UNCLASSIFIED
--     after h26c8e54f1b2 (absence of a classification row); history up to the org's last local date is withheld.
SELECT a.organization_id, a.id AS of_account_id, a.name, a.open_finance_connection_id,
       right(regexp_replace(coalesce(a.provider_account_number,''), '\D', '', 'g'), 4) AS last4_number,
       (a.provider_account_number IS NULL) AS number_missing
FROM accounts a
WHERE a.source = 'open_finance'
  AND EXISTS (SELECT 1 FROM accounts l WHERE l.organization_id = a.organization_id
                AND l.source = 'reviewed_local_import')
ORDER BY 1, 2;

-- 6. Size and lock exposure for the ALTERs on bank_transactions / bank_connections
SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables WHERE relname IN ('bank_transactions','bank_connections','organization_memberships');

ROLLBACK;
