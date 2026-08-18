# רצף (Rezef) — CFO Operating System

FastAPI backend ב-`src/cfo/`, React frontend ב-`frontend/`, פרוד ב-cfo-2.vercel.app (Vercel + Neon). אינטגרציות: SUMIT (הנה"ח ישראלית) + Open Finance (בנקאות פתוחה).

## לפני עבודה חשבונאית/מיסויית — חובה

**טען את `docs/bookkeeper_kb/README.md`** — מרכז הידע של מנהל החשבונות: דיני הכרה בהוצאות, ניכוי תשומות (תקנה 14/18, אירוח, שער-מסמך), סדר היום, ומשמעת הטעינה. הגשר התפעולי לתיוק: `docs/bookkeeper_kb/03-classification-bridge.md` (מיוצר מ-`src/cfo/services/israeli_tax_rules.py` — לערוך בקוד בלבד).

## דוקטרינות מחייבות

- **verify-first**: בדיקה מול מרכז ידע SUMIT (`docs/SUMIT_KNOWLEDGE_BASE.md`) לפני כל פעולה בפורטל/API.
- **אימות משולש**: כל פלט דיווח לרשויות ≥3 בדיקות בלתי-תלויות (`filing_verification`).
- **honest-null**: אין מספרים מומצאים; עמימות = תור הכרעה, לא ניחוש.
- **אפס אוטונומיה בבלתי-הפיך**: סגירת מנה/שידור/תשלום — רק באישור בעלים.
- **משמעת עלויות API**: קריאות SUMIT/OF רק כשחייבים; שערי sync יומיים קשיחים (20h) — לא לעקוף. **חוק קשיח, בכל הארגונים ובכל המערכת** (הנחיית בעלים חוזרת, 17–18/08/2026, אחרי חיוב אמיתי של אלפי שקלים): כל בנייה של `SumitIntegration` בקוד הייצור **חייבת** `request_limiter=SumitRequestLimiter(...)` אמיתי — לא `None`, לא מחלקת-דמה. נאכף מבנית (לא רק בבדיקה) בשתי שכבות בלתי-תלויות:
  1. **רגע הרשת** — `_make_request`/`_post_binary` ב-`sumit_integration.py` מסרבים fail-closed (`SumitRequestBudgetRequired`) אם `request_limiter is None`, גם אם הבנייה עקפה את זה.
  2. **מכסה מהספק** — `assert_paid_action_within_quota` (`sumit_quota.py`) חוסם פעולה בתשלום בלי מדידה טרייה; מדידה לא-ידועה אינה מכסה פנויה.
  שער-נגד-רגרסיה קבוע: `tests/test_sumit_rate_limit_hard_rule.py` סורק את כל `src/cfo/` (AST, לא grep) ונכשל על כל בנייה חשופה או מגביל-דמה. **אין לרכך, לעקוף או למחוק את הטסט הזה** בלי אישור בעלים מפורש.

## תפעול

- טסטים: `python -m pytest tests/ -q` (חובה ירוק לפני commit). TDD.
- חוזה המערכת: `docs/REZEF_OPERATING_SYSTEM.md`; סטטוס יכולת וראיות:
  `docs/rezef_capabilities.json`; לוח הסטטוס היחיד: `docs/MASTER_EXECUTION_PLAN.md`.
- המודל המכונן: `docs/BOOKKEEPER_ARMY_OPERATING_MODEL.md` (workflow + 12 SOP).
- סכימת פרוד: `create_all` לא מוסיף עמודות. לפעול רק לפי
  `docs/GATE0_DEPLOYMENT_RUNBOOK.md`; סקריפט DDL חלקי אינו הוכחת Alembic
  `head` ואינו רשאי לסמן אותו.
