#!/usr/bin/env bash
# PreToolUse guard — שכבת 05 (hooks) של ה-control plane.
#
# חוסם דטרמיניסטית שני דברים ששום הנחיה טקסטואלית לא מבטיחה:
#   1. סקריפטים שמבצעים קריאות חיות ל-SUMIT / Open Finance / פרוד (משמעת עלויות API).
#   2. עריכה ידנית של מסמכים מיוצרים (docs/bookkeeper_kb/03-classification-bridge.md).
#
# קלט: JSON של PreToolUse על stdin. פלט: JSON עם permissionDecision=deny כשחוסמים,
# ואחרת יציאה שקטה (exit 0, בלי פלט) כדי לא להוסיף רעש.
#
# היקף: זהו מעקה נגד פעולה אוטומטית בשוגג, לא גבול אבטחה מול יריב. ההתאמה דורשת
# *הרצה* — טוקן מפעיל (python/node/uv run/bash/./) ואחריו שם הסקריפט באותו מקטע פקודה.
# כך נתפסים `cd scripts && python x.py`, `uv run python scripts/x.py`, `bash -c "..."`,
# אך `grep prod_smoke` או קומיט שמזכיר את השם עוברים. מי שרוצה לעקוף — יעקוף; המטרה
# היא שסוכן שמנסה "להריץ את כל הבדיקות" ייעצר.
set -uo pipefail

# fail-closed: תקלה בהוצאת הקלט → חסימה עם הסבר, לא מעבר שקט.
fail_closed() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"guard-costly-and-generated.sh לא הצליח לפענח את קלט ה-hook (%s). חוסם ליתר ביטחון — לבדוק את ה-hook לפני שממשיכים."}}' "$1"
  exit 0
}

command -v jq >/dev/null 2>&1 || fail_closed "jq חסר"

payload="$(cat)" || fail_closed "קריאת stdin נכשלה"
tool="$(printf '%s' "$payload" | jq -r '.tool_name // ""')" || fail_closed "jq נכשל על tool_name"

deny() {
  jq -cn --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

# שמות סקריפטים שאומתו כמבצעי קריאות רשת חיות / כתיבה לפרוד.
COSTLY='(production_readiness_check|prod_smoke|verify_sumit_writeback|pull_sumit_item_names|run_ocr_pipeline|classify_expenses|sumit_daily_file_expenses|fix_prod_schema_drift|migrate_sqlite_to_postgres|apply_[a-z_]+_schema|backfill_vat_split|fix_bills_sign_status|bootstrap_superadmin|grant_superadmin_token|reset_password)\.(py|js)'

case "$tool" in
  Bash)
    cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')" || fail_closed "jq נכשל על command"
    # דורש טוקן מפעיל לפני שם הסקריפט, באותו מקטע (בלי ; | & ביניהם)
    if printf '%s' "$cmd" | grep -Eq "(^|[^A-Za-z0-9_.-])(python[0-9.]*|node|bun|deno|sh|bash|zsh|\./)([^;|&]*[^A-Za-z0-9_.-])?${COSTLY}"; then
      deny "חסום ע\"י .claude/hooks/guard-costly-and-generated.sh: הסקריפט מבצע קריאות חיות ל-SUMIT/Open-Finance או כותב לפרוד. משמעת עלויות API + אפס אוטונומיה בבלתי-הפיך (CLAUDE.md). להרצה — רק באישור מפורש של הבעלים, ידנית."
    fi
    # הפניית שערי הבדיקה המקומיים ל-Neon/פרוד
    if printf '%s' "$cmd" | grep -Eq '(qa_gate|schema_drift_check)\.py' && printf '%s' "$cmd" | grep -q -- '--env-file'; then
      deny "חסום: --env-file מפנה את הבדיקה ל-Neon/פרוד. להרצה מקומית ללא הדגל, או באישור בעלים."
    fi
    ;;
  Write|Edit|NotebookEdit)
    f="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // ""')" || fail_closed "jq נכשל על file_path"
    if printf '%s' "$f" | grep -q '03-classification-bridge\.md'; then
      deny "חסום: 03-classification-bridge.md הוא מסמך מיוצר מ-src/cfo/services/israeli_tax_rules.py. לערוך את הקוד ואז להריץ: python scripts/render_bookkeeper_kb.py"
    fi
    ;;
esac

exit 0
