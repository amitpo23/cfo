# SDD Progress — collection-reminders
Plan: docs/superpowers/plans/2026-06-25-collection-reminders.md
Base before Task 1: 56f7d30

Task 1: complete (commit 39140ca..d0da245, review clean)
  Minor (for final review): sent_at DateTime lacks timezone=True (codebase footgun); test asserts 2 fields only — both brief-mandated.
Base before Task 2: d0da245
Task 2: complete (commit d0da245..d2e10ec, review clean)
  Minor (final review): migration omits Create Date docstring/typing header (cosmetic). ⚠️ fresh_org default — confirmed OK by passing test.
Base before Task 3: d2e10ec
Task 3: complete (commit a7483a6..ca96cd6, review clean; Important timezone finding FIXED ca96cd6)
  Minor (final review): _recently_sent ignores injected today (uses wall clock) — intentional, note testability.
Base before Task 4: ca96cd6
Task 4: complete (commit ca96cd6..52fef1d, review clean)
  Minor (final review): duplicate local 'from decimal import Decimal'; test imports mid-file (PEP8). Both brief-mandated.
Base before Task 5: 52fef1d
Task 5: complete (commit 52fef1d..0d0d7ee, review clean)
  Minor (final review): duplicate asyncio import (test); no SMTP timeout (network-hang risk, out of task scope).
Base before Task 6: 0d0d7ee
Task 6: complete (commit 5f246f9..cf6bf16, review clean)
  Minor (final review): no per-org try/except in cron loop (one org error aborts batch — /cron/sync wraps per-org); skipped_no_sumit undercount; import order.
Base before Task 7: cf6bf16
Task 7: complete (commit cf6bf16..069bddc, review clean)
  Minor (final review): mid-file imports (E402, recurring); thin preview-test assertion; run route untested (acceptable).
Base before Task 8: 069bddc
Task 8: complete (commit 069bddc..cb8e464, full suite 383 passed)

=== FINAL REVIEW (opus) + fixes ===
Final review: Needs-fixes -> all resolved.
  Critical (d) SMTP timeout=10: fixed f4b9dd2
  Critical (e) per-org cron try/except+rollback+errors: fixed f4b9dd2
  Important opt-in gate on manual run (user: gate it): fixed 02b2c4e (403 when disabled)
  Minors (a,b,c,f,g): deferred per final-review triage.
FEATURE COMPLETE: 8 tasks + 3 fix commits, full suite 384 passed. HEAD 02b2c4e.

# === SPRINT: completion + test-hardening ===
Plan: docs/superpowers/plans/2026-06-26-completion-sprint.md
Decisions: T-DEC-1 honest-null+flag; T-DEC-2 keep unsupported (Epic 3 skipped)
Base before T1.1: 8fbf3f0
T1.1: complete (commit 8fbf3f0..b0b95bc, review clean) — real AR/AP aging via ARAPAgingService
Base before T1.2: b0b95bc
T1.2: complete (commit b0b95bc..6bcb980; controller-verified, 5 dashboard tests pass) — fabricated COGS removed, honest null+flag
Base before T1.3: 6bcb980
T1.3: complete (commit 6bcb980..a2ff8e8; controller-verified) — honest AI fallback, placeholder removed
Base before T1.4: a2ff8e8
T1.4: complete (commit a2ff8e8..421c734) — real average_days_to_payment + gross_profit null. Epic 1 DONE.
Base before T1.4 review: a2ff8e8
T1.4 review: clean. EPIC 1 COMPLETE (T1.1-T1.4).
T2.1: complete (commit 421c734..80f0938; controller-verified: grep status_code-in empty, 394/394 pass)
  T2.1 SURFACED BUG: revenue_analytics:199 cust['percentage_of_total'] vs 'percentage_of_total_revenue' -> 500 on /opportunities + /ai/executive-summary when customer has >=4 invoices.
Base before T2.1b (bug fix): 0f3136e
