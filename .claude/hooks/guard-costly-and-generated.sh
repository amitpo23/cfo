#!/usr/bin/env bash
# PreToolUse guard — שכבת 05 (hooks) של ה-control plane.
#
# חוסם דטרמיניסטית שני דברים ששום הנחיה טקסטואלית לא מבטיחה:
#   1. סקריפטים שמבצעים קריאות חיות ל-SUMIT / Open Finance / פרוד (משמעת עלויות API).
#   2. עריכה ידנית של מסמכים מיוצרים (docs/bookkeeper_kb/03-classification-bridge.md).
#
# קלט: JSON של PreToolUse על stdin. פלט: JSON עם permissionDecision=deny כשחוסמים,
# ואחרת יציאה שקטה (exit 0, בלי פלט) כדי לא להוסיף רעש.
set -uo pipefail

payload="$(cat)"
tool="$(printf '%s' "$payload" | jq -r '.tool_name // ""')"

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

case "$tool" in
  Bash)
    cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')"
    # סקריפטים שנבדקו ומבצעים קריאות רשת חיות / כתיבה לפרוד
    if printf '%s' "$cmd" | grep -Eq 'scripts/(production_readiness_check|prod_smoke|verify_sumit_writeback|pull_sumit_item_names|run_ocr_pipeline|classify_expenses|sumit_daily_file_expenses|fix_prod_schema_drift|migrate_sqlite_to_postgres|apply_[a-z_]*_schema|backfill_vat_split|fix_bills_sign_status|bootstrap_superadmin|grant_superadmin_token|reset_password)\.(py|js)'; then
      deny "חסום ע\"י .claude/hooks/guard-costly-and-generated.sh: הסקריפט מבצע קריאות חיות ל-SUMIT/Open-Finance או כותב לפרוד. משמעת עלויות API + אפס אוטונומיה בבלתי-הפיך (CLAUDE.md). להרצה — רק באישור מפורש של הבעלים, ידנית."
    fi
    # דגלי env של פרוד על סקריפטי בדיקה מקומיים
    if printf '%s' "$cmd" | grep -Eq 'scripts/(qa_gate|schema_drift_check)\.py.*--env-file'; then
      deny "חסום: --env-file מפנה את הבדיקה ל-Neon/פרוד. להרצה מקומית ללא הדגל, או באישור בעלים."
    fi
    ;;
  Write|Edit|NotebookEdit)
    f="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // ""')"
    if printf '%s' "$f" | grep -q 'docs/bookkeeper_kb/03-classification-bridge\.md'; then
      deny "חסום: 03-classification-bridge.md הוא מסמך מיוצר מ-src/cfo/services/israeli_tax_rules.py. לערוך את הקוד ואז להריץ: python scripts/render_bookkeeper_kb.py"
    fi
    ;;
esac

exit 0
