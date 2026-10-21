# נוהל שחזור מסד נתונים — RESTORE RUNBOOK (W6.3)

**עד 21/08/2026 לא היה מסמך כזה** — היה רק גיבוי אד-הוק לפני מיגרציה,
והנחה לא-מאומתת ש-Neon PITR קיים. מהיום: גיבוי יומי מוצפן (GitHub
Actions ‏`db-backup`, ‏02:00 UTC, שמירה 30 יום) + הנוהל הזה.

## Local recovery verification — 2026-09-06

A synthetic PostgreSQL 18.3 drill passed using `scripts/verify_postgres_restore.py`:
68 tables, fresh Alembic migrations, full schema parity, encrypted backup/decryption,
all-table row fingerprints, organization foreign keys, and checkout uniqueness.
The measured fixture drill took 2.92 seconds. This is a small synthetic test,
not a production RTO measurement or evidence that the production backup secrets work.

The script accepts only loopback databases named `rezef_test_*` and refuses
nonempty source/destination databases. CI now runs it against an isolated
PostgreSQL service. Production backup retrieval, key availability, PITR settings,
and a restore of an actual customer backup still require the owner-run drill below.

Evidence: `audits/evidence/2026-09-06-postgres-restore.json`.

## יעדים (עד שהבעלים יקבע אחרת)

- **RPO** (אובדן נתונים מרבי): ‏24 שעות — גיל הגיבוי היומי האחרון.
  ל-RPO קטן יותר: לאמת ולהפעיל Neon PITR (קונסולת Neon → Branches/Restore).
- **RTO** (זמן חזרה לאוויר): ‏≤ שעה, בהינתן שהנוהל תורגל.

## שחזור מגיבוי ה-Actions (התרחיש המרכזי)

1. **לעצור כתיבה**: להשבית זמנית את ה-crons ב-Vercel (או `vercel env` —
   ‏`SUMIT_GLOBAL_REQUESTS_PER_MINUTE=0` עוצר גם sync).
2. **להוריד את הגיבוי**: GitHub → Actions → ‏db-backup → הריצה האחרונה
   הירוקה → Artifact ‏`db-backup-<stamp>`.
3. **לפענח** (עם ה-passphrase ממנהל הסיסמאות):
   ```bash
   openssl enc -d -aes-256-cbc -pbkdf2 -in backup-<stamp>.sql.enc \
     -out backup-<stamp>.sql -pass env:BACKUP_PASSPHRASE
   grep -q "PostgreSQL database dump complete" backup-<stamp>.sql  # אימות
   ```
4. **מסד יעד נקי**: ליצור מסד/branch חדש ב-Neon (לא לדרוס את החי לפני
   שאובחן!). לשחזר:
   ```bash
   psql "<NEW_DATABASE_URL>" < backup-<stamp>.sql
   ```
5. **אימות אחרי שחזור** (חובה, לפי GATE0):
   ```bash
   python scripts/schema_drift_check.py --env-file <OWNER_APPROVED_RESTORE_ENV_FILE>
   # + ספירות שורות מול הצפוי: organizations, invoices, journal_entries
   ```
   ואז `python -m alembic upgrade head` אם הגיבוי ישן מה-head.
6. **החלפה**: לעדכן `DATABASE_URL` ב-Vercel אל המסד המשוחזר, deploy,
   ‏`GET /api/health` חייב להחזיר `database: ok` + revision נכון.
7. **הפעלת crons מחדש** ורישום האירוע (מה קרה, כמה נתונים אבדו, לקחים).

## שחזור נקודתי (Neon PITR) — אם מופעל

קונסולת Neon → Restore/Branch מנקודת זמן → מקבלים DSN חדש → צעדים 5–7.
**פעולת בעלים לביצוע פעם אחת:** לוודא בקונסולה שחלון ה-PITR פעיל ולרשום
כאן את אורכו: ‏`____ ימים` (נכון ל: ‏____).

## תרגול (drill) — חובה רבעונית

לבצע צעדים 2–5 מול מסד זמני, למדוד זמן, ולתעד כאן:

| תאריך | גיבוי | משך | תוצאה | חתימה |
|---|---|---|---|---|
| _טרם בוצע_ | | | | |

## מה הגיבוי לא מכסה

- קבצי env/סודות (מנוהלים ב-Vercel + מנהל סיסמאות — לא ב-DB).
- מסדי per-tenant עתידיים (כשיפוצלו — להרחיב את ה-workflow פר-DSN).
