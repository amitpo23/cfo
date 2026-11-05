# Simplify F: daily skills, summary

- Branch: `feat/simplify-f-daily-skills`, based on `e961c65` (#102)
- Content commit: `0b40ecc` (red test: `991af75`)
- Not merged. No deploy, no migration, no SUMIT/OF calls.

## Skills (`.agents/skills/`, same tree as `rezef-operator`)

| id | path | gate |
|---|---|---|
| `daily-file` | `.agents/skills/daily-file/SKILL.md` | Wraps `sumit-file-expenses`; Amit's GO for every final save; `scripts/sumit_daily_file_expenses.js` named as forbidden |
| `daily-bank-match` | `.agents/skills/daily-bank-match/SKILL.md` | Local only; ends "balanced" (unmatched=0 and gap `undocumented_count`=0) or a blocked list with one fixed reason per row |
| `of-accounts-sync` | `.agents/skills/of-accounts-sync/SKILL.md` | Admin, owner-requested per run, 20h check via `/api/sync/runs`; `allow_implicit_invocation: false`; refresh-all (20 credits) kept out |
| `daily-pnl-cash` | `.agents/skills/daily-pnl-cash/SKILL.md` | One `GET /api/cashflow/period?grain=day` call: today = `periods[-1]`, MTD = `totals`; source + as-of on every figure; חסר instead of 0 |

Routing: `rezef-operator` gets a "Daily loop" table (file → match → optional OF sync → pnl-cash).
`docs/bookkeeper_kb/00-role-and-daily-order.md` gets a short section that links the four ids.

## Tests

`tests/test_repo_financial_skills.py` +6 tests: the four skills exist; frontmatter
`name` matches the directory; the description has Hebrew and English; the body
mentions חסר; rezef-operator and the daily-order doc list the ids in order;
daily-file wraps the runbook; OF sync is not implicit. **Every `/api/...` path
cited in the four skills is checked against `app.openapi()["paths"]`.** A mutation
check (`/api/cashflow/periodx`) made the test fail.

Run (clean env): `pytest tests/test_repo_financial_skills.py` → 8 passed; all kb/skill/
capability/control-plane test files → 240 passed. The full suite was not run (the
change touches no `src/`); the known baseline on main is 45 failures.

## Gaps (found while writing; not fixed here)

1. **`POST /api/sync/run` has no admin gate and no 20h gate.** Only a 15-minute
   cooldown. The 20h interval is enforced in cron and in `connections/refresh-all`.
   The skill enforces both rules, but code does not. A real fix belongs in
   `cfo_sync.trigger_sync` (separate PR).
2. **Loop order versus "no contradictory numbers".** Running the OF sync after
   matching brings in unmatched rows. The skills keep the order Amit asked for and
   add a rule: new bank transactions → run `daily-bank-match` again before the report.
3. **A quiet day is missing (#102 `gap_is_missing`).** At day grain, MTD in `totals`
   mostly comes out "חסר בחלק מהטווח". The skill reports that and does not add a
   `grain=month` call. Waiting on Amit's E decision (#106).
4. **`/api/reconcile-manual/unmatched` has no paging or date filter.** The skill uses
   `limit=1000`, filters locally, and states when the result was truncated.
5. **Two different counts.** The gap report does not filter BOOKED; the period
   payload is BOOKED only. The skill labels each count with its source.
6. **Card/Max (#105) and 1:N (#103) are not on main.** They appear as blocked reasons
   (`card_settlement`, `split_payment_1_to_n`) until those PRs merge.
7. **org 6 (D)** is blocked; the skills forbid inventing credentials.
