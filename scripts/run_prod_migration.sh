#!/usr/bin/env bash
# הרצת מיגרציית שער 0 בפרוד — פקודה אחת, בעלים בלבד.
#
# למה סקריפט ולא שורות להעתקה: ההעתקה הידנית נכשלה כמה פעמים (ספריית
# עבודה שגויה, טוקן שנחתך ב-tail, קונסול דפדפן במקום bash). כאן כל שלב
# נבדק לפני הבא, וההודעה אומרת בדיוק מה נשבר.
#
# הסקריפט **אינו** מדפיס את הטוקן ואינו מדפיס סודות.
#
#   bash scripts/run_prod_migration.sh
#
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; OFF=$'\033[0m'
ok()   { echo "${GRN}✓${OFF} $*"; }
warn() { echo "${YEL}!${OFF} $*"; }
die()  { echo "${RED}✗${OFF} $*" >&2; exit 1; }

cd "$(dirname "$0")/.." || die "לא הצלחתי להיכנס לשורש הפרויקט"
ok "ספריית עבודה: $(pwd)"

# ב-macOS ה-binary של Docker Desktop אינו ב-PATH של shell לא-אינטראקטיבי.
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:$PATH"

# --- 1. תנאי סף ------------------------------------------------------ #
[ -f .env.prod ] || die ".env.prod חסר. הרץ: vercel env pull .env.prod --environment=production --yes"
[ -x .venv/bin/python ] || die ".venv חסר. הרץ: python3 -m venv .venv && .venv/bin/pip install -e ."
ok "‎.env.prod ו-.venv קיימים"

DB=$(grep -E '^DATABASE_URL=' .env.prod | head -1 | cut -d= -f2- | tr -d '"')
JWT=$(grep -E '^JWT_SECRET_KEY=' .env.prod | head -1 | cut -d= -f2- | tr -d '"')
[ ${#DB}  -gt 20 ] || die "DATABASE_URL ריק ב-.env.prod"
[ ${#JWT} -gt 10 ] || die "JWT_SECRET_KEY ריק ב-.env.prod"
ok "פרטי חיבור נטענו (לא מודפסים)"

# --- 2. גיבוי — הרונבוק דורש נקודת שחזור לפני שינוי סכימה ----------- #
BACKUP="neondb-pre-migrate-$(date +%Y%m%d-%H%M%S).sql"
if command -v docker >/dev/null 2>&1; then
  echo "  מייצר גיבוי טרי (pg_dump — קריאה בלבד)…"
  if docker run --rm -e PGURL="$DB" postgres:17-alpine \
       sh -c 'pg_dump --no-owner --no-privileges "$PGURL"' > "$BACKUP" 2>/dev/null \
     && grep -q "PostgreSQL database dump complete" "$BACKUP"; then
    ok "גיבוי: $BACKUP ($(du -h "$BACKUP" | cut -f1), $(grep -c '^CREATE TABLE' "$BACKUP") טבלאות)"
  else
    rm -f "$BACKUP"
    die "הגיבוי נכשל או נקטע. **אין להמשיך בלי גיבוי.**"
  fi
else
  warn "docker אינו זמין — לא נוצר גיבוי טרי."
  LAST=$(ls -t neondb-pre-migrate-*.sql prod-snapshot.sql 2>/dev/null | head -1)
  [ -n "${LAST:-}" ] || die "אין גם גיבוי קודם. עצור."
  warn "משתמש בגיבוי קיים: $LAST — ודא שהוא עדכני."
fi

# --- 3. revision לפני, לרישום ---------------------------------------- #
BEFORE=$(docker run --rm -e PGURL="$DB" postgres:17-alpine \
  sh -c 'psql -tAc "select version_num from alembic_version" "$PGURL"' 2>/dev/null | tr -d ' ')
ok "revision בפרוד לפני: ${BEFORE:-לא ידוע}"

# --- 4. טוקן SUPER_ADMIN --------------------------------------------- #
echo "  מנפיק טוקן…"
TOKEN=$(DATABASE_URL="$DB" JWT_SECRET_KEY="$JWT" \
  .venv/bin/python scripts/grant_superadmin_token.py amitporat1981@gmail.com 2>/dev/null \
  | grep -oE 'eyJ[A-Za-z0-9._-]+' | head -1)
[ ${#TOKEN} -gt 100 ] || die "הנפקת הטוקן נכשלה (אורך ${#TOKEN}). בדוק שהמשתמש קיים ושה-JWT_SECRET_KEY נכון."
ok "טוקן הונפק (אורך ${#TOKEN}, אינו מודפס)"

# --- 5. המיגרציה ----------------------------------------------------- #
echo
echo "  ${YEL}מריץ מיגרציה בפרוד…${OFF}"
RESP=$(curl -sS -X POST https://cfo-2.vercel.app/api/admin/db/migrate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"confirmation":"I_UNDERSTAND_SCHEMA_MIGRATION_IS_GLOBAL"}' 2>&1)

echo
echo "──────── תשובת ה-endpoint ────────"
echo "$RESP" | .venv/bin/python -m json.tool 2>/dev/null || echo "$RESP"
echo "──────────────────────────────────"

# --- 6. אימות ה-revision אחרי ---------------------------------------- #
AFTER=$(docker run --rm -e PGURL="$DB" postgres:17-alpine \
  sh -c 'psql -tAc "select version_num from alembic_version" "$PGURL"' 2>/dev/null | tr -d ' ')
echo
echo "  לפני:  ${BEFORE:-?}"
echo "  אחרי:  ${AFTER:-?}"
echo "  יעד:   05c6d7e8f9a0"
if [ "$AFTER" = "05c6d7e8f9a0" ]; then
  ok "המיגרציה הושלמה והגיעה ל-head היעד."
else
  warn "ה-revision אינו היעד. **אל תריץ downgrade** — הוא מוחק טבלאות ואינו משחזר נתונים."
  warn "הדבק את התשובה למעלה לצ'אט לאבחון."
fi
echo
echo "  ספירות אחרי (חייבות להיות זהות לפני):"
docker run --rm -e PGURL="$DB" postgres:17-alpine sh -c \
  'psql -tAc "select (select count(*) from journal_entries)||E'"'"' פקודות · '"'"'||(select count(*) from accounts)||E'"'"' כרטיסים · '"'"'||(select count(*) from expenses)||E'"'"' הוצאות'"'"'" "$PGURL"' 2>/dev/null | sed 's/^/    /'
